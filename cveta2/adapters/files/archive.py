"""Deterministic ``sources.tar.gz``: the fetched source tables of a prepared bundle."""

import gzip
import io
import tarfile
import zlib
from collections.abc import Mapping

from cveta2.domain.bundle.models import UploadError
from cveta2.domain.bundle.preparation import SOURCE_NAMES, SOURCES_ARCHIVE


def _broken(reason: str) -> UploadError:
    return UploadError(f"Архив {SOURCES_ARCHIVE} повреждён или неполон: {reason}; запустите cveta2 verify заново.")


def pack_sources(content: Mapping[str, bytes]) -> bytes:
    """Pack the four source tables so the same content always gives the same bytes."""
    if set(content) != set(SOURCE_NAMES):
        raise _broken(f"ожидаются файлы {', '.join(SOURCE_NAMES)}")
    buffer = io.BytesIO()
    with (
        gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0, compresslevel=9) as stream,
        tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive,
    ):
        for name in SOURCE_NAMES:
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(content[name]), 0, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(content[name]))
    return buffer.getvalue()


def unpack_sources(data: bytes) -> dict[str, bytes]:
    """Read the four source tables; never extracts to disk and accepts nothing else."""
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if sorted(names) != sorted(SOURCE_NAMES):
                raise _broken(f"состав файлов {names}, ожидается {list(SOURCE_NAMES)}")
            result: dict[str, bytes] = {}
            for member in members:
                stream = archive.extractfile(member) if member.isreg() else None
                if stream is None:
                    raise _broken(f"{member.name} не обычный файл")
                result[member.name] = stream.read()
    except (tarfile.TarError, OSError, EOFError, zlib.error) as error:
        raise _broken(str(error)) from error
    return {name: result[name] for name in SOURCE_NAMES}
