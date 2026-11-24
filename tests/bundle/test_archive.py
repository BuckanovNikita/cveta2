"""The prepared-bundle sources archive is byte-for-byte reproducible and strictly read."""

import gzip
import io
import tarfile
from collections.abc import Callable

import pytest

from cveta2.adapters.files.archive import pack_sources, unpack_sources
from cveta2.domain.bundle.models import UploadError
from cveta2.domain.bundle.preparation import SOURCE_NAMES

CONTENT = {name: f"{name}\n1,2\n".encode() for name in SOURCE_NAMES}


def _gzip_tar(members: list[tuple[str, bytes, bytes | None]]) -> bytes:
    """Build a gzip tar from (name, payload, tar type) triples; a None type is a regular file."""
    buffer = io.BytesIO()
    with (
        gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as stream,
        tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive,
    ):
        for name, payload, kind in members:
            info = tarfile.TarInfo(name)
            if kind is not None:
                info.type = kind
                info.linkname = "dataset.csv"
                archive.addfile(info)
                continue
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _regular(name: str) -> tuple[str, bytes, None]:
    return (name, CONTENT[name], None)


def _with_last_as(kind: bytes) -> bytes:
    members: list[tuple[str, bytes, bytes | None]] = [_regular(name) for name in SOURCE_NAMES[:-1]]
    members.append((SOURCE_NAMES[-1], b"", kind))
    return _gzip_tar(members)


def test_same_sources_give_identical_archive_bytes() -> None:
    first = pack_sources(CONTENT)
    second = pack_sources(dict(reversed(list(CONTENT.items()))))
    assert first == second


def test_archive_has_fixed_order_and_zeroed_metadata() -> None:
    data = pack_sources(CONTENT)
    assert data[4:8] == b"\0\0\0\0"
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = archive.getmembers()
    assert [member.name for member in members] == list(SOURCE_NAMES)
    for member in members:
        assert member.mtime == 0
        assert member.uid == member.gid == 0
        assert member.uname == member.gname == ""
        assert member.mode == 0o644
        assert member.isreg()


def test_unpack_round_trips() -> None:
    assert unpack_sources(pack_sources(CONTENT)) == CONTENT


def test_pack_requires_exactly_the_source_names() -> None:
    with pytest.raises(UploadError, match=r"sources\.tar\.gz"):
        pack_sources({"dataset.csv": b""})


_BAD: dict[str, Callable[[], bytes]] = {
    "missing": lambda: _gzip_tar([_regular(name) for name in SOURCE_NAMES[:-1]]),
    "extra": lambda: _gzip_tar([*(_regular(name) for name in SOURCE_NAMES), ("notes.txt", b"x", None)]),
    "duplicate": lambda: _gzip_tar([*(_regular(name) for name in SOURCE_NAMES), _regular(SOURCE_NAMES[0])]),
    "directory": lambda: _with_last_as(tarfile.DIRTYPE),
    "symlink": lambda: _with_last_as(tarfile.SYMTYPE),
    "traversal": lambda: _gzip_tar([*(_regular(name) for name in SOURCE_NAMES[1:]), ("../dataset.csv", b"x", None)]),
    "not-gzip": lambda: b"not a gzip archive",
}


@pytest.mark.parametrize("make", _BAD.values(), ids=_BAD.keys())
def test_unpack_rejects_bad_archives(make: Callable[[], bytes]) -> None:
    with pytest.raises(UploadError, match=r"sources\.tar\.gz"):
        unpack_sources(make())
