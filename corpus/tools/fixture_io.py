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


def set_mode(mode: str) -> None:
    """`write` writes every fixture; `check` compares and records differences instead."""
    global _mode
    if mode not in ("write", "check"):
        raise ValueError(f"unknown fixture mode {mode!r}")
    _mode = mode
    _differences.clear()


def emit(path: str, text: str) -> str:
    """Emit one fixture. Returns the text, so a caller can verify what it produced."""
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
    """(path, why) for every fixture that did not match, in the order they were emitted."""
    return list(_differences)
