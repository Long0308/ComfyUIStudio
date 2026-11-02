"""Python verified-hash cache: a hit is a stat, a changed size / mtime is a miss, the stated trust boundary is audited by rehash_all."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import pytest

from engine.editorial.segments_hashcache import HashCache


def aged(path: Path, data: bytes, seconds: int = 3600) -> None:
    path.write_bytes(data)
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def ref(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_second_lookup_is_a_hit_and_counts_the_bytes_not_read(tmp_path: Path) -> None:
    file = tmp_path / "clip.bin"
    data = os.urandom(300_000)
    aged(file, data)
    cache = HashCache(tmp_path / "hc.json")
    assert cache.sha256(file) == ref(data)
    assert cache.sha256(file) == ref(data)
    stats = cache.stats()
    assert (stats["hits"], stats["misses"], stats["bytes_not_read"], stats["bytes_read"]) == (1, 1, 300_000, 300_000)


def test_survives_save_reload_and_an_unreadable_cache_is_empty(tmp_path: Path) -> None:
    file = tmp_path / "a.bin"
    aged(file, b"hello cache")
    cache = HashCache(tmp_path / "hc.json")
    cache.sha256(file)
    assert cache.save() is True
    again = HashCache(tmp_path / "hc.json")
    assert again.sha256(file) == ref(b"hello cache") and again.stats()["hits"] == 1
    (tmp_path / "hc.json").write_text("{not json", encoding="utf-8")
    broken = HashCache(tmp_path / "hc.json")
    assert broken.stats()["load_error"] and broken.sha256(file) == ref(b"hello cache") and broken.stats()["hits"] == 0


def test_a_changed_size_or_mtime_is_a_miss(tmp_path: Path) -> None:
    file = tmp_path / "a.bin"
    aged(file, b"first version")
    cache = HashCache(tmp_path / "hc.json")
    cache.sha256(file)
    aged(file, b"second version, longer")
    assert cache.sha256(file) == ref(b"second version, longer")
    aged(file, b"second version, LONGER", 1800)
    assert cache.sha256(file) == ref(b"second version, LONGER")
    assert cache.stats()["hits"] == 0 and cache.stats()["misses"] == 3


def test_trust_boundary_restored_mtime_is_invisible_and_rehash_all_repairs_it(tmp_path: Path) -> None:
    file = tmp_path / "a.bin"
    aged(file, b"AAAAAAAA")
    stat = file.stat()
    cache = HashCache(tmp_path / "hc.json")
    honest = cache.sha256(file)
    file.write_bytes(b"BBBBBBBB")
    os.utime(file, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert cache.sha256(file) == honest  # the declared boundary: stat identity unchanged
    cache.save()
    audit = HashCache(tmp_path / "hc.json", rehash_all=True)
    assert audit.sha256(file) == ref(b"BBBBBBBB") and audit.stats()["hits"] == 0
    audit.save()
    assert HashCache(tmp_path / "hc.json").sha256(file) == ref(b"BBBBBBBB")


def test_a_file_hashed_right_after_its_write_is_racy_and_not_trusted(tmp_path: Path) -> None:
    file = tmp_path / "fresh.bin"
    file.write_bytes(b"just written")
    cache = HashCache(tmp_path / "hc.json")
    cache.sha256(file)
    cache.sha256(file)
    assert cache.stats()["hits"] == 0 and cache.stats()["racy"] == 1


def test_a_missing_file_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="nope.bin"):
        HashCache().sha256(tmp_path / "nope.bin")
