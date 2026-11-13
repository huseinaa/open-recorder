"""Where generated helpers (thumbnail strips, waveforms, silences) are kept: one file per source
file and kind, named from the source's path, size and date so an edited file is redone."""
from __future__ import annotations

import hashlib
from pathlib import Path


def cache_path(cache_dir: Path, source: Path, kind: str, ext: str) -> Path:
    try:
        st = source.stat()
        stamp = f"{source.resolve()}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        stamp = str(source)
    digest = hashlib.sha1(stamp.encode("utf-8")).hexdigest()[:16]
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{source.stem[:40]}-{digest}.{kind}.{ext}"
