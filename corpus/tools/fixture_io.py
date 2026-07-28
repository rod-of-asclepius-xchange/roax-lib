"""Fixture output for implementation A's generator: one write mode, one check mode.

`build_corpus.py --check` could not fail before. Every fixture was written to disk while the
corpus was being assembled, so the check erased the hand edit it existed to catch, and every
later step then read the file the generator had just rewritten. A check that cannot fail counts
as one that passed.

So the bytes are produced once, held, and either written or compared. A generator never reads a
fixture back from disk: what it verifies is the bytes it just built, which is the only reading
under which a difference against the committed file means anything.
"""

from __future__ import annotations

import os

_mode = "write"
_differences = []
_emitted = set()
_owned = []


def set_mode(mode: str) -> None:
    """`write` writes every fixture; `check` compares and records differences instead."""
    global _mode
    if mode not in ("write", "check"):
        raise ValueError(f"unknown fixture mode {mode!r}")
    _mode = mode
    _differences.clear()
    _emitted.clear()
    _owned.clear()


def owns(directory: str) -> None:
    """Declare a directory whose every `.json` file this generator produces.

    Only a fully owned directory can be compared as a SET, which is the only way an EXTRA file
    is detectable. `corpus/type-maps/` is deliberately NOT one: the generator writes the
    synthetic map there while `build_type_maps.py` writes the three derived MOH maps, so
    scanning it would report those three as orphans.
    """
    path = os.path.abspath(directory)
    if path not in _owned:
        _owned.append(path)


def emit(path: str, text: str) -> str:
    """Emit one fixture. Returns the text, so a caller can verify what it produced."""
    _emitted.add(os.path.abspath(path))
    if _mode == "check":
        try:
            with open(path, "r", encoding="utf-8") as handle:
                committed = handle.read()
        except FileNotFoundError:
            _differences.append((path, "not committed"))
            return text
        if committed != text:
            _differences.append((path, "differs from a fresh build"))
        return text

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return text


def differences():
    """Every fixture that did not match, as (path, why), plus every orphan in an owned directory.

    `emit` catches a fixture that was MODIFIED or is missing. It cannot catch an EXTRA one: a
    rename leaves the old file behind, referenced by no vector and reported by nothing, while
    the check still passes. So an owned directory is also compared as a set against what this
    build produced.

    `.json` only, and deliberately: a gitignored `.DS_Store` is not a fixture, and failing the
    check on one would be a macOS-only failure with no visible cause.
    """
    out = list(_differences)
    for directory in _owned:
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            if name.endswith(".json") and os.path.isfile(path) and path not in _emitted:
                out.append((path, "not produced by this build - an orphan no vector references"))
    return out
