"""Ruling R24 as one function: the repository's builtins become the project's taxonomy here.

The repository raises plain `KeyError`, `FileNotFoundError`, `ValueError` and `UnicodeDecodeError`,
deliberately — charter §9 forbids emitting a code that is not yet in the contract, and
`domain/errors.py` was out of bounds for the task that wrote it. This module is where those become
codes, once, so that T-7's exit codes and initiative 03's HTTP statuses read one taxonomy instead of
each re-deriving it from a builtin.

**`UnicodeDecodeError` is a subclass of `ValueError`, and the ordering of the handlers below is
therefore load-bearing.** Catching `ValueError` first would report every binary file as a malformed
path — the wrong code, the wrong HTTP status, and a diagnosis pointing at the caller's request
instead of at the file. Reordering the two `except` clauses is a silent behaviour change that no
type checker will catch, which is why it is stated here rather than left to be rediscovered.
"""

from __future__ import annotations

from harness_library.domain.artifact import Artifact
from harness_library.domain.errors import (
    ArtifactFileNotFoundError,
    ArtifactNotFoundError,
    FileNotTextError,
    InvalidFilePathError,
)
from harness_library.domain.registry import spec_for
from harness_library.domain.repository import ArtifactRepository


def require_artifact(repository: ArtifactRepository, artifact_id: str) -> Artifact:
    """The artifact, or `ArtifactNotFoundError`.

    An **invalid** artifact is returned like any other — feature F-2 requires `hl show` on a skill
    with no `SKILL.md` to render its V1 finding rather than raise. Only a *missing* id raises.
    """
    artifact = repository.get(artifact_id)
    if artifact is None:
        raise ArtifactNotFoundError(artifact_id)
    return artifact


def entry_path_of(artifact: Artifact) -> str:
    """Where this artifact's entry document lives, relative to its root.

    From the type registry, never re-derived: a second place that knows an agent's entry is its own
    basename is a second place to forget it.
    """
    return spec_for(artifact.type).entry_path(artifact.name)


def read_file_text(repository: ArtifactRepository, artifact_id: str, path: str) -> str:
    """Decoded text of one file, with every repository failure translated.

    Raises:
        ArtifactNotFoundError: no artifact with this id.
        ArtifactFileNotFoundError: the artifact contains no file at this path.
        InvalidFilePathError: the path is absolute, empty, climbs out of the root, or is a symlink
            that ruling R6 never follows.
        FileNotTextError: the file does not decode as UTF-8.
    """
    try:
        return repository.read_text(artifact_id, path)
    except KeyError as error:
        raise ArtifactNotFoundError(artifact_id) from error
    except FileNotFoundError as error:
        raise ArtifactFileNotFoundError(artifact_id, path) from error
    except UnicodeDecodeError as error:
        # Before `ValueError`, of which this is a subclass. See the module docstring.
        raise FileNotTextError(artifact_id, path) from error
    except ValueError as error:
        raise InvalidFilePathError(artifact_id, path, str(error)) from error


__all__ = ["entry_path_of", "read_file_text", "require_artifact"]
