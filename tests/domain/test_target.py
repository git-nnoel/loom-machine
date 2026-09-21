"""Contract C-12 — `TargetFile` and the `TargetRepository` protocol.

Pure, zero I/O. What this suite **cannot** prove is stated once, here: that a real scan of a real
directory produces these values at all. A hand-written fake satisfying the protocol proves the
surface is implementable and substitutable; only `tests/infrastructure/test_target.py`, driven off
the committed fixture, can prove that a symlink on a real disk comes back with `is_symlink=True`.
That division is deliberate and is the shape charter §10 asks for — and it is why the task's
mutation lives in the infrastructure suite and not in this one.
"""

from __future__ import annotations

import pytest

from harness_library.domain.target import TargetFile, TargetRepository

DIGEST = "a" * 64


class FakeTarget:
    """The full surface, as T-15's and T-16's fakes are written.

    **Seven members since ruling R97**, which put `read_link` and `write_link` into C-12 — T-20
    added them to `FilesystemTargetRepository` alone and flagged that the contract wanted them.
    The cost is L24's: a member added to a protocol is a member every hand-written implementation
    has to gain, in every directory, including the ones a task's scope does not name.
    """

    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = dict(files)
        self._links: dict[str, str] = {}

    def scan(self) -> tuple[TargetFile, ...]:
        return tuple(
            TargetFile(path=path, sha256=DIGEST, size=len(data), is_symlink=False)
            for path, data in sorted(self._files.items())
        )

    def read_bytes(self, path: str) -> bytes:
        return self._files[path]

    def write(self, path: str, data: bytes) -> None:
        self._files[path] = data

    def delete(self, path: str) -> None:
        self._files.pop(path, None)
        self._links.pop(path, None)

    def exists(self, path: str) -> bool:
        return path in self._files or path in self._links

    def read_link(self, path: str) -> str:
        return self._links[path]

    def write_link(self, path: str, destination: str) -> None:
        # A link holds no bytes (R6), so it replaces whatever content was there rather than
        # sitting beside it — which is what `os.symlink` over an existing file does.
        self._files.pop(path, None)
        self._links[path] = destination


class ReadOnlyTarget:
    """The surface C-12 refuses: a target that can be scanned and read but not written.

    Named because it is the plausible mistake — the library's `ArtifactRepository` is exactly this
    shape, and a fake copied from it would satisfy nothing apply needs.
    """

    def scan(self) -> tuple[TargetFile, ...]:
        return ()

    def read_bytes(self, path: str) -> bytes:
        return b""

    def exists(self, path: str) -> bool:
        return False


def test_a_full_implementation_satisfies_the_protocol() -> None:
    assert isinstance(FakeTarget({}), TargetRepository)


def test_a_target_that_cannot_be_written_does_not_satisfy_it() -> None:
    """Positive control for the assertion above: without this, a protocol that accepted anything
    would make the previous test pass having checked nothing."""
    assert not isinstance(ReadOnlyTarget(), TargetRepository)


def test_a_fake_round_trips_a_write_through_the_protocol() -> None:
    """The byte members compose: what `write` put there, `exists` sees and `read_bytes` returns,
    and `delete` takes away. Asserted on a fake because that is the substitutability C-12 is
    frozen for — apply must be testable without a disk."""
    target: TargetRepository = FakeTarget({})
    target.write("skills/delivery-lead/SKILL.md", b"---\nname: delivery-lead\n---\n")

    assert target.exists("skills/delivery-lead/SKILL.md")
    assert target.read_bytes("skills/delivery-lead/SKILL.md").startswith(b"---")

    target.delete("skills/delivery-lead/SKILL.md")
    assert not target.exists("skills/delivery-lead/SKILL.md")


def test_a_fake_round_trips_a_link_through_the_protocol() -> None:
    """**Ruling R97's two members, composed the way the byte members are.**

    A link's content is its destination, and the round trip is what makes that usable: what
    `write_link` put there, `exists` sees and `read_link` returns **verbatim**, and `delete`
    unlinks as itself. The destination is deliberately one that climbs out of the target — R6
    never follows it, so a fake that resolved it would be modelling the escape rather than the
    contract.
    """
    target: TargetRepository = FakeTarget({})
    target.write_link("skills/delivery-lead/references/elsewhere.md", "../../../outside/leak.md")

    assert target.exists("skills/delivery-lead/references/elsewhere.md")
    assert (
        target.read_link("skills/delivery-lead/references/elsewhere.md")
        == "../../../outside/leak.md"
    )

    target.delete("skills/delivery-lead/references/elsewhere.md")
    assert not target.exists("skills/delivery-lead/references/elsewhere.md")


# -------------------------------------------------------------------------------------------
# TargetFile's invariants
# -------------------------------------------------------------------------------------------


def test_an_ordinary_entry_carries_its_four_facts() -> None:
    entry = TargetFile(path="settings.json", sha256=DIGEST, size=177, is_symlink=False)

    assert (entry.path, entry.sha256, entry.size, entry.is_symlink) == (
        "settings.json",
        DIGEST,
        177,
        False,
    )


def test_a_symlink_entry_carries_no_content_digest() -> None:
    """Ruling R6: a link is never followed and never hashed, so there is no content to digest.
    Its `size` is still real — the length of the path it names, from `lstat`.

    **Ruling R68** spells that absence `None`. T-14 wrote the empty string, which compares, sorts
    and renders like a digest while being none; `None` is the spelling C-10 and C-11 already use
    for every optional field, and it cannot be mistaken for content.
    """
    entry = TargetFile(path="skills/x/elsewhere.md", sha256=None, size=36, is_symlink=True)

    assert entry.is_symlink
    assert entry.sha256 is None
    assert entry.size == 36


def test_a_symlink_entry_may_not_carry_the_retired_empty_string_either() -> None:
    """R68 leaves one spelling of "no digest", not two. `""` on a link is refused with the same
    message as a real digest is, because a consumer testing `sha256 is None` would otherwise read
    an empty string as content and compare it against the library's."""
    with pytest.raises(ValueError, match="never followed and never hashed"):
        TargetFile(path="skills/x/elsewhere.md", sha256="", size=36, is_symlink=True)


def test_a_symlink_entry_may_not_carry_a_digest() -> None:
    """The one invariant, and the one direction it runs. A digest on a link could only have come
    from reading through it, which is the escape R6 exists to prevent."""
    with pytest.raises(ValueError, match="never followed and never hashed"):
        TargetFile(path="skills/x/elsewhere.md", sha256=DIGEST, size=36, is_symlink=True)


def test_an_entry_that_is_not_a_link_may_be_built_without_a_digest() -> None:
    """The **converse is deliberately not enforced**, and this test pins that choice so nobody
    tightens it by accident.

    A two-way invariant would look stricter and would cost the task its mutation control: the
    required mutation makes `scan()` report `is_symlink=False` for every entry, and under a
    two-way rule the fixture's link would *raise* inside `TargetFile` instead of coming back with
    the wrong flag. Every test that scans the fixture would redden together and the
    must-stay-green control would be buried. The rule worth having is the one about what must
    never be hashed.
    """
    entry = TargetFile(path="skills/x/SKILL.md", sha256=None, size=0, is_symlink=False)

    assert entry.sha256 is None


def test_an_entry_has_a_path() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        TargetFile(path="", sha256=DIGEST, size=1, is_symlink=False)


def test_an_entry_has_a_size_that_is_not_negative() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        TargetFile(path="settings.json", sha256=DIGEST, size=-1, is_symlink=False)
