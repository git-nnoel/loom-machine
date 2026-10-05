"""The content hash — charter §7, ruling R9.

The golden digest in `test_content_hash_is_stable_across_insertion_order` is load-bearing and is not
a coverage flourish. Reversing the sort inside `content_hash_of_digests` still produces a
deterministic, still order-independent digest, so an equality-only test sails straight through that
mutation. The literal is what makes the ordering rule observable.
"""

from __future__ import annotations

import pytest

from loom.domain.artifact import ArtifactFile
from loom.domain.hashing import (
    content_hash,
    content_hash_of_digests,
    content_hash_of_files,
    hash_bytes,
)

FILE_SET = [
    ("SKILL.md", b"# Delivery lead\n"),
    ("references/contracts.md", b"one decision, one object\n"),
    ("assets/diagram.png", b"\x89PNG\r\n\x1a\n binary"),
]
REVERSED_FILE_SET = list(reversed(FILE_SET))

GOLDEN_CONTENT_HASH = "6c5f73f7366f0944663fb25db2687a42d07f848233eb8cf1ea3c37b536ec3501"


def test_hash_bytes_is_sha256_hex() -> None:
    assert hash_bytes(b"") == ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
    assert len(hash_bytes(b"anything")) == 64


def test_content_hash_is_stable_across_insertion_order() -> None:
    """The same file set hashes identically however it was collected — and to the same value it
    hashed to yesterday. Both halves are the one claim: the hash does not move."""
    assert content_hash(FILE_SET) == content_hash(REVERSED_FILE_SET)
    assert content_hash(FILE_SET) == GOLDEN_CONTENT_HASH


def test_content_hash_is_rename_sensitive() -> None:
    """Same bytes, different path — a different artifact. Initiative 02 judges install per path."""
    original = content_hash([("SKILL.md", b"body")])
    renamed = content_hash([("GUIDE.md", b"body")])
    assert original != renamed


def test_content_hash_is_content_sensitive() -> None:
    assert content_hash([("SKILL.md", b"body")]) != content_hash([("SKILL.md", b"other")])


def test_path_and_content_cannot_be_reframed_into_each_other() -> None:
    """Length-prefixed framing: concatenating a path onto its neighbour's content must not
    collide with the split the other way round."""
    left = content_hash([("a", b"bc")])
    right = content_hash([("ab", b"c")])
    assert left != right


def test_empty_file_set_has_a_defined_hash() -> None:
    """An artifact whose every file was skipped still has a content hash, not a crash."""
    assert content_hash([]) == content_hash_of_digests([])


def test_content_hash_of_files_agrees_with_content_hash() -> None:
    """One rule, one implementation. These two entry points delegate to the same core, so this
    test cannot drift into rubber-stamping two independent routines."""
    files = tuple(
        ArtifactFile(path=path, sha256=hash_bytes(data), size=len(data), is_text=True)
        for path, data in FILE_SET
    )
    assert content_hash_of_files(files) == content_hash(FILE_SET)


def test_a_duplicate_path_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate path"):
        content_hash([("SKILL.md", b"a"), ("SKILL.md", b"b")])
