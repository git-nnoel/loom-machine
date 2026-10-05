"""Content hashing. Charter §7.

`content_hash` covers the sorted sequence of `(relative path, bytes)`. It **excludes** file mode
(ruling R9 — every file in the real library is `-rwxrw-rw-`, an accident of how it was copied, and
initiative 02 normalises mode on install), mtime, and any skipped path.

There is exactly **one** implementation, `content_hash_of_digests`. The two convenience entry points
delegate to it. Two hashing routines over the same rule agree until they don't, and initiative 02
compares hashes computed by this module against hashes computed on an installed tree — a drift there
would read as a spurious "changed" verdict on every artifact.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from loom.domain.artifact import ArtifactFile

_ENCODING = "utf-8"


def hash_bytes(data: bytes) -> str:
    """The SHA-256 of one file's bytes, lowercase hex. This is `ArtifactFile.sha256`."""
    return hashlib.sha256(data).hexdigest()


def content_hash_of_digests(entries: Iterable[tuple[str, str]]) -> str:
    """Hash `(relative path, sha256 hex)` pairs. The single definition of the content hash.

    Entries are sorted by path, then by digest, so the result does not depend on the order the
    scanner happened to walk the tree in. Each field is length-prefixed before it is fed to the
    digest, so no combination of path and content can be reframed into another — which is what
    makes the hash rename-sensitive rather than merely content-sensitive.

    Raises:
        ValueError: on a duplicate path, which would otherwise silently hash as two files.
    """
    ordered = sorted(entries)
    seen: set[str] = set()
    digest = hashlib.sha256()
    for path, sha256 in ordered:
        if path in seen:
            raise ValueError(f"duplicate path in content hash input: {path!r}")
        seen.add(path)
        for field in (path, sha256):
            encoded = field.encode(_ENCODING)
            digest.update(str(len(encoded)).encode(_ENCODING))
            digest.update(b":")
            digest.update(encoded)
    return digest.hexdigest()


def content_hash(entries: Iterable[tuple[str, bytes]]) -> str:
    """Hash `(relative path, bytes)` pairs — charter §7's rule, stated in its own terms."""
    return content_hash_of_digests((path, hash_bytes(data)) for path, data in entries)


def content_hash_of_files(files: Iterable[ArtifactFile]) -> str:
    """Hash an already-scanned file list, reusing the per-file digests.

    The scanner has read every file once already; re-reading them to recompute the same digests
    would double the I/O of every scan for no additional guarantee.
    """
    return content_hash_of_digests((file.path, file.sha256) for file in files)
