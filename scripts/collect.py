"""
Simple Lucid Vision multi-camera image collector using Arena SDK.

Usage:
    # Single camera at 30 fps
    python collect.py --ip 192.168.1.100 --output ./frames --fps 30

    # Multiple specific cameras
    python collect.py --ip 192.168.1.100 192.168.1.101 --output ./frames --fps 15

    # All cameras on the network
    python collect.py --all --output ./frames --fps 10
"""

import argparse
import ctypes
import os
import sys
import time
import logging
import signal
import threading
import queue
from datetime import datetime, timezone

import cv2
import numpy as np

try:
    from arena_api.system import system
    from arena_api.enums import PixelFormat
except ImportError:
    print("ERROR: arena_api not found. Install the Arena SDK Python package.")
    print("  pip install arena-api")
    sys.exit(1)


logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("lucid-collector")
log.setLevel(logging.INFO)

_running = True


def _sigint_handler(sig, frame):
    global _running
    log.info("SIGINT received, stopping...")
    _running = False


signal.signal(signal.SIGINT, _sigint_handler)

# ---------------------------------------------------------------------------
# Writer pool – shared across all cameras
# ---------------------------------------------------------------------------
# Throughput budget for 8 cams × 60 fps = 480 writes/sec:
#   cv2.imwrite ~8-15 ms per frame (releases GIL) → 1 thread ≈ 70-120 writes/sec
#   16 threads → ~1100-1900 writes/sec headroom
#   Queue 1024 → ~2 s buffer at 480 fps before back-pressure
WRITER_THREADS = 16
WRITER_QUEUE_MAX = 1024
JPEG_QUALITY = 85  # lower than 92 for faster encoding at high throughput

_write_q: queue.Queue = queue.Queue(maxsize=WRITER_QUEUE_MAX)
_write_errors = 0
_write_errors_lock = threading.Lock()

# Pre-allocate the JPEG params list once (avoid per-frame allocation)
_JPEG_PARAMS = [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]


def _writer_worker():
    """Background thread: pull (numpy_bgr, filepath) from queue, encode & save."""
    global _write_errors
    while True:
        item = _write_q.get()
        if item is None:  # poison pill
            _write_q.task_done()
            break
        img_bgr, filepath = item
        try:
            cv2.imwrite(filepath, img_bgr, _JPEG_PARAMS)
        except Exception as exc:
            with _write_errors_lock:
                _write_errors += 1
            log.error(
                f"Writer failed {filepath}: {type(exc).__name__}: {exc}", exc_info=True
            )
        finally:
            _write_q.task_done()


# ---------------------------------------------------------------------------
# Camera helpers
# ---------------------------------------------------------------------------


def discover_cameras():
    """Scan network and return all device_infos."""
    log.info("Scanning network for Lucid cameras ...")
    device_infos = system.device_infos
    log.info(f"Found {len(device_infos)} device(s) on the network")
    for i, info in enumerate(device_infos):
        log.info(
            f"  [{i}] ip={info.get('ip', '?')}  "
            f"serial={info.get('serial', '?')}  "
            f"model={info.get('model', '?')}"
        )
    return device_infos


def connect_cameras(ips: list[str] | None):
    """
    Connect to cameras.
    If ips is None  -> connect to ALL discovered cameras.
    If ips is given -> connect only to those IPs.
    Returns list of (camera_no, device, ip) sorted by IP.
    """
    system.destroy_device()
    device_infos = discover_cameras()

    if not device_infos:
        raise RuntimeError("No Lucid cameras found on the network")

    if ips is not None:
        available_ips = {d.get("ip") for d in device_infos}
        missing = [ip for ip in ips if ip not in available_ips]
        if missing:
            raise RuntimeError(
                f"Cameras not found: {missing}. Available: {sorted(available_ips)}"
            )
        selected = [d for d in device_infos if d.get("ip") in ips]
    else:
        selected = device_infos

    # Sort by IP for deterministic camera_no assignment
    selected.sort(key=lambda d: d.get("ip", ""))

    devices = system.create_device(device_infos=selected)
    if not devices:
        raise RuntimeError("create_device returned empty")

    result = []
    for cam_no, device in enumerate(devices):
        nm = device.nodemap
        ip = selected[cam_no].get("ip", "?")
        log.info(
            f"cam{cam_no}: ip={ip}  "
            f"model={nm['DeviceModelName'].value}  "
            f"serial={nm['DeviceSerialNumber'].value}  "
            f"firmware={nm['DeviceFirmwareVersion'].value}"
        )
        result.append((cam_no, device, ip))

    return result


# Pixel formats to try, in preference order: 1 byte/pixel only (Bayer, Mono).
# 3 bpp formats (RGB8, BGR8) are excluded — they cap at ~13 fps on GigE.
# Each entry: (arena PixelFormat enum, OpenCV cvtColor code, bpp on wire)
_FORMAT_PREFERENCE = [
    (PixelFormat.BayerGR8, cv2.COLOR_BayerGR2BGR, 1),
    (PixelFormat.BayerRG8, cv2.COLOR_BayerRG2BGR, 1),
    (PixelFormat.BayerGB8, cv2.COLOR_BayerGB2BGR, 1),
    (PixelFormat.BayerBG8, cv2.COLOR_BayerBG2BGR, 1),
    (PixelFormat.Mono8, cv2.COLOR_GRAY2BGR, 1),
]


def _negotiate_pixel_format(nodemap, prefix: str):
    """Pick the best supported pixel format. Returns (PixelFormat, cvt_code, bpp)."""
    for fmt, cvt_code, bpp in _FORMAT_PREFERENCE:
        try:
            nodemap["PixelFormat"].value = fmt
            log.info(
                f"{prefix}: PixelFormat = {fmt.name} "
                f"({bpp} byte/px on wire, "
                f"{'debayer on host' if cvt_code is not None else 'native BGR'})"
            )
            return fmt, cvt_code, bpp
        except Exception:
            continue

    # Nothing worked — report current value for debugging
    cur = nodemap["PixelFormat"].value
    raise RuntimeError(
        f"{prefix}: No usable pixel format found (current: {cur}). "
        f"Check camera documentation for supported formats."
    )


def configure_camera(cam_no: int, device, target_fps: float):
    """
    Apply capture settings to one camera.
    Sets the requested frame rate, then maximises exposure to fill the frame period.
    Returns (pixel_format, cvt_code) for the grab loop.
    """
    nodemap = device.nodemap
    prefix = f"cam{cam_no}"

    # Pixel format — negotiate best available
    pixel_fmt, cvt_code, bpp = _negotiate_pixel_format(nodemap, prefix)

    # Continuous acquisition
    nodemap["AcquisitionMode"].value = "Continuous"

    # ---- Frame rate (set AFTER pixel format so max reflects actual bandwidth) ----
    nodemap["AcquisitionFrameRateEnable"].value = True
    fr_node = nodemap["AcquisitionFrameRate"]
    actual_fps = min(target_fps, fr_node.max)
    if actual_fps < target_fps:
        log.warning(
            f"{prefix}: Requested {target_fps} fps but camera max is {fr_node.max:.2f} fps "
            f"(resolution {nodemap['Width'].value}x{nodemap['Height'].value}, {pixel_fmt.name})"
        )
    fr_node.value = actual_fps
    log.info(
        f"{prefix}: AcquisitionFrameRate = {fr_node.value:.2f} (max {fr_node.max:.2f})"
    )

    # ---- Exposure: maximise within the frame period ----
    #  frame_period = 1_000_000 / fps  (in µs)
    #  Leave a small margin (~500 µs) for readout overhead.
    nodemap["ExposureAuto"].value = "Off"
    exposure_node = nodemap["ExposureTime"]
    frame_period_us = 1_000_000.0 / fr_node.value
    max_exposure = frame_period_us - 500.0
    desired = max(exposure_node.min, min(max_exposure, exposure_node.max))
    exposure_node.value = desired
    log.info(
        f"{prefix}: ExposureTime = {exposure_node.value:.0f} us "
        f"(frame period {frame_period_us:.0f} us, "
        f"cam range [{exposure_node.min:.0f}, {exposure_node.max:.0f}])"
    )

    # ---- Stream tuning ----
    tl_stream = device.tl_stream_nodemap
    tl_stream["StreamBufferHandlingMode"].value = "NewestOnly"
    tl_stream["StreamAutoNegotiatePacketSize"].value = True
    tl_stream["StreamPacketResendEnable"].value = True

    # Increase driver buffer count — at 60 fps we need headroom for GIL contention
    for node_name in ("StreamInputBufferCount", "StreamBufferCountManual"):
        try:
            tl_stream[node_name].value = 50
            log.info(f"{prefix}: {node_name} = {tl_stream[node_name].value}")
            break
        except Exception:
            continue

    return cvt_code, bpp


# ---------------------------------------------------------------------------
# Per-camera grab loop (runs in its own thread)
# ---------------------------------------------------------------------------


def _grab_loop(
    cam_no: int,
    device,
    ip: str,
    output_dir: str,
    stats: dict,
    cvt_code: int | None,
    bpp: int,
):
    """Acquisition loop for a single camera. Runs in a dedicated thread."""
    prefix = f"cam{cam_no}"
    cam_dir = os.path.join(output_dir, f"cam{cam_no}")
    os.makedirs(cam_dir, exist_ok=True)

    seq = 0
    last_frame_id = -1
    grab_errors = 0
    write_drops = 0

    device.start_stream()
    log.info(f"{prefix} ({ip}): Acquisition started.")

    try:
        while _running:
            # ---- grab ----
            try:
                buffer = device.get_buffer(timeout=2000)
            except Exception as exc:
                grab_errors += 1
                log.error(
                    f"{prefix}: Frame grab failed (seq={seq}, grab_errors={grab_errors}): "
                    f"{type(exc).__name__}: {exc}"
                )
                continue

            if buffer.is_incomplete:
                grab_errors += 1
                log.error(
                    f"{prefix}: Incomplete frame seq={seq}: "
                    f"expected={buffer.width}x{buffer.height}, "
                    f"pixel_format={buffer.pixel_format.name}, "
                    f"error={getattr(buffer, 'error_code', 'N/A')}"
                )
                device.requeue_buffer(buffer)
                continue

            # ---- skip duplicate frames ----
            frame_id = buffer.frame_id
            if frame_id == last_frame_id:
                device.requeue_buffer(buffer)
                time.sleep(0.001)
                continue
            last_frame_id = frame_id

            # ---- fast copy: convert + numpy memcpy, then requeue immediately ----
            accept_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
            filename = f"cam{cam_no}_{seq:06d}_{accept_ts}.jpg"
            filepath = os.path.join(cam_dir, filename)

            try:
                nbytes = buffer.width * buffer.height * bpp
                data_ptr = ctypes.cast(
                    buffer.pdata, ctypes.POINTER(ctypes.c_uint8 * nbytes)
                )
                if bpp == 1:
                    raw = (
                        np.frombuffer(data_ptr.contents, dtype=np.uint8)
                        .reshape(buffer.height, buffer.width)
                        .copy()
                    )
                else:
                    raw = (
                        np.frombuffer(data_ptr.contents, dtype=np.uint8)
                        .reshape(buffer.height, buffer.width, 3)
                        .copy()
                    )

                # Convert to BGR for cv2.imwrite (None means already BGR)
                np_img = cv2.cvtColor(raw, cvt_code) if cvt_code is not None else raw
            except Exception as exc:
                grab_errors += 1
                log.error(
                    f"{prefix}: Convert failed seq={seq}: {type(exc).__name__}: {exc}",
                    exc_info=True,
                )
                continue
            finally:
                device.requeue_buffer(buffer)

            # ---- hand off to shared writer pool ----
            try:
                _write_q.put((np_img, filepath), timeout=0.5)
            except queue.Full:
                write_drops += 1
                log.error(f"{prefix}: Writer queue full, dropping frame seq={seq}")

            seq += 1

            # ---- update shared stats for summary logger ----
            stats["frames"] = seq
            stats["grab_errors"] = grab_errors
            stats["write_drops"] = write_drops

    except Exception as exc:
        log.error(
            f"{prefix}: Grab loop crashed: {type(exc).__name__}: {exc}", exc_info=True
        )
    finally:
        device.stop_stream()
        log.info(f"{prefix} ({ip}): Stream stopped after {seq} frames.")


# ---------------------------------------------------------------------------
# Summary logger (one thread, prints all cameras once per minute)
# ---------------------------------------------------------------------------
LOG_INTERVAL = 60  # seconds


def _summary_logger(cam_stats: list[dict]):
    """Prints a per-camera FPS summary every LOG_INTERVAL seconds."""
    global _write_errors
    # Each entry in cam_stats: {cam_no, ip, frames, grab_errors, write_drops}
    # We snapshot "frames" at the start of each interval to compute mean FPS.

    prev_frames = {s["cam_no"]: 0 for s in cam_stats}
    prev_errors = {s["cam_no"]: 0 for s in cam_stats}
    prev_drops = {s["cam_no"]: 0 for s in cam_stats}
    t0 = time.monotonic()

    while _running:
        time.sleep(1)
        elapsed = time.monotonic() - t0
        if elapsed < LOG_INTERVAL:
            continue

        # ---- build summary ----
        lines = [f"--- Summary (last {int(elapsed)}s) ---"]
        total_frames = 0
        total_errors = 0

        for s in cam_stats:
            cn = s["cam_no"]
            cur_frames = s["frames"]
            cur_errors = s["grab_errors"]
            cur_drops = s["write_drops"]

            delta_f = cur_frames - prev_frames[cn]
            delta_e = cur_errors - prev_errors[cn]
            delta_d = cur_drops - prev_drops[cn]
            mean_fps = delta_f / elapsed if elapsed > 0 else 0

            with _write_errors_lock:
                we = _write_errors  # global, shared across cams

            lines.append(
                f"  cam{cn} ({s['ip']}): "
                f"mean_fps={mean_fps:.2f}  "
                f"frames={delta_f} (total {cur_frames})  "
                f"grab_errors={delta_e}  "
                f"write_drops={delta_d}  "
                f"write_queue={_write_q.qsize()}/{WRITER_QUEUE_MAX}"
            )
            total_frames += delta_f
            total_errors += delta_e + delta_d

            prev_frames[cn] = cur_frames
            prev_errors[cn] = cur_errors
            prev_drops[cn] = cur_drops

        with _write_errors_lock:
            we = _write_errors
            _write_errors = 0
        if we:
            lines.append(f"  write_errors (all cams): {we}")

        lines.append(
            f"  TOTAL: {total_frames} frames, "
            f"{total_frames / elapsed if elapsed > 0 else 0:.2f} fps aggregate, "
            f"{total_errors} errors"
        )

        log.info("\n".join(lines))
        t0 = time.monotonic()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run(ips: list[str] | None, output_dir: str, target_fps: float):
    global _write_errors

    os.makedirs(output_dir, exist_ok=True)

    cameras = connect_cameras(ips)
    log.info(f"Configuring {len(cameras)} camera(s) ...")

    cam_formats = {}  # cam_no -> (cvt_code, bpp)
    for cam_no, device, ip in cameras:
        cvt_code, bpp = configure_camera(cam_no, device, target_fps)
        cam_formats[cam_no] = (cvt_code, bpp)

    # Start shared writer threads
    writers = []
    for _ in range(WRITER_THREADS):
        t = threading.Thread(target=_writer_worker, daemon=True)
        t.start()
        writers.append(t)
    log.info(f"Started {WRITER_THREADS} writer threads (queue max={WRITER_QUEUE_MAX})")

    # Shared stats dicts — one per camera, updated by grab threads, read by summary logger
    cam_stats = []
    for cam_no, device, ip in cameras:
        cam_stats.append(
            {
                "cam_no": cam_no,
                "ip": ip,
                "frames": 0,
                "grab_errors": 0,
                "write_drops": 0,
            }
        )

    # Start per-camera grab threads
    grab_threads = []
    for i, (cam_no, device, ip) in enumerate(cameras):
        cvt_code, bpp = cam_formats[cam_no]
        t = threading.Thread(
            target=_grab_loop,
            args=(cam_no, device, ip, output_dir, cam_stats[i], cvt_code, bpp),
            name=f"grab-cam{cam_no}",
            daemon=True,
        )
        t.start()
        grab_threads.append(t)

    # Start summary logger thread
    summary_t = threading.Thread(
        target=_summary_logger,
        args=(cam_stats,),
        name="summary-logger",
        daemon=True,
    )
    summary_t.start()

    log.info(
        f"All {len(cameras)} camera(s) streaming. "
        f"Summary logged every {LOG_INTERVAL}s. Press Ctrl+C to stop."
    )

    # Wait for Ctrl+C
    try:
        while _running:
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass

    log.info("Shutting down ...")

    # Wait for grab threads to finish
    for t in grab_threads:
        t.join(timeout=5)

    # Drain writer queue
    log.info(f"Flushing writer queue ({_write_q.qsize()} items) ...")
    for _ in writers:
        _write_q.put(None)
    for t in writers:
        t.join(timeout=10)

    remaining = _write_q.qsize()
    if remaining:
        log.warning(f"{remaining} frames still in write queue (lost)")

    system.destroy_device()
    log.info("All devices released. Done.")


def main():
    parser = argparse.ArgumentParser(
        description="Lucid camera multi-camera collector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s --ip 192.168.1.100                --output ./frames --fps 30
  %(prog)s --ip 192.168.1.100 192.168.1.101  --output ./frames --fps 15
  %(prog)s --all                              --output ./frames --fps 10
        """,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ip", nargs="+", help="One or more camera IP addresses")
    group.add_argument(
        "--all", action="store_true", help="Connect to ALL cameras on the network"
    )
    parser.add_argument("--output", required=True, help="Output root directory")
    parser.add_argument(
        "--fps",
        type=float,
        required=True,
        help="Target frame rate. Exposure is auto-maximised to fill the frame period.",
    )
    args = parser.parse_args()

    ips = None if args.all else args.ip
    run(ips, args.output, args.fps)


if __name__ == "__main__":
    main()
