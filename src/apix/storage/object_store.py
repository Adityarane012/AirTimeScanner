"""Immutable, content-hashed raw-payload store.

Local-filesystem implementation of the "raw landing" layer described in
docs/03-architecture.md. Stands in for MinIO/S3 in the no-Docker prototype
environment: same guarantee (content-addressed, immutable, never overwritten),
same interface shape, so swapping in a real S3-compatible backend later is a
one-file change — nothing that calls `ObjectStore` needs to know.

Layout: <raw_store_path>/<hash[:2]>/<hash[2:4]>/<hash>.raw
(two-level fan-out so a single directory never gets huge at scale)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PutResult:
    content_hash: str
    path: Path
    already_existed: bool


class ObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, content_hash: str) -> Path:
        return self.root / content_hash[:2] / content_hash[2:4] / f"{content_hash}.raw"

    def put(self, payload: bytes) -> PutResult:
        """Store a raw payload immutably, keyed by its own SHA-256 hash.

        Idempotent: storing the same bytes twice is a no-op the second time
        and returns already_existed=True. Never overwrites — that's the point.
        """
        content_hash = hashlib.sha256(payload).hexdigest()
        path = self._path_for(content_hash)
        if path.exists():
            return PutResult(content_hash, path, already_existed=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(payload)
        tmp.replace(path)  # atomic on both POSIX and Windows (same volume)
        return PutResult(content_hash, path, already_existed=False)

    def get(self, content_hash: str) -> bytes:
        path = self._path_for(content_hash)
        if not path.exists():
            raise FileNotFoundError(f"No raw payload for hash {content_hash}")
        return path.read_bytes()

    def exists(self, content_hash: str) -> bool:
        return self._path_for(content_hash).exists()
