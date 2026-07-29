"""Committed salt sets: the input side that replaced salt derivation.

Decision D4 is ruled D4b, so a salt is 16 bytes drawn independently from a CSPRNG and nothing
can re-derive one (`docs/spec/roax-canon-1.md` section 7). A fixed vector file therefore cannot
compute its salts at build time: they have to be DRAWN ONCE and COMMITTED, and every later build
reads them back.

That is why these files are not `fixture_io` fixtures. A fixture is regenerated on every build
and compared, which is exactly what a random value cannot survive - a fresh draw would differ
every run and `--check` would fail forever. A salt set is a committed INPUT, like the type maps.

Drawing is therefore an explicit, separate act: `build_corpus.py --draw-salts`. It is not part
of a normal build, and a normal build that finds a salt set missing FAILS rather than drawing
one, because a drawn-on-demand salt would give this machine a root no other machine could
reproduce.

Two carriers, named by `pairing`, and the difference is not stylistic:

  "path"        one entry per leaf carrying explicit segments, exactly the `salts` array of
                `schemas/envelope-1.0.json`. Self-describing. Everything hand-authored uses it.

  "positional"  a bare array of salts in encodePath order. CORPUS-ONLY, and it MUST NEVER
                become an envelope shape. Specification section 7.2 rejects it for an envelope
                because it makes pairing depend on reproducing the section 9 sort before the
                salts can be read at all; in a corpus vector reproducing that sort is the thing
                under test, so a mispairing fails the vector instead of yielding a silently
                wrong root. Class 10 needs it because its records are the genuine third-party
                MOH reference samples at 69 and 70 leaves, and a path-keyed set would enumerate
                every path of a shipped reference sample into this PUBLIC repository, which
                AGENTS.md forbids - not even a fragment. A positional array discloses only the
                leaf count, and the vector already publishes that as `leafCount`.

See `docs/conformance-corpus.md` class 10, which states the same reasoning and warns that if the
two are ever harmonized, the dangerous direction is making envelopes positional.
"""

from __future__ import annotations

import json
import os
import secrets

SALT_BYTES = 16

_HERE = os.path.dirname(os.path.abspath(__file__))
_DIR = os.path.join(os.path.dirname(_HERE), "fixtures", "salts")

# Corpus-relative, for the `saltsFile` a vector records.
REPO_PREFIX = "corpus/fixtures/salts/"


_drawing = False


def set_drawing(flag: bool) -> None:
    """Enable draw mode. Set once, by build_corpus.py --draw-salts, and never during a build."""
    global _drawing
    _drawing = bool(flag)


def drawing() -> bool:
    return _drawing


def path_for(name: str) -> str:
    return os.path.join(_DIR, name + ".json")


def reference_for(name: str) -> str:
    """What a vector's `saltsFile` says, which is repository-relative and not machine-relative."""
    return REPO_PREFIX + name + ".json"


def _render(doc) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def draw(name: str, ordered, pairing: str) -> dict:
    """Draw a fresh salt set for `ordered` and write it. Only ever called under --draw-salts.

    `secrets.token_bytes` and not `random`: the entropy floor is normative (spec section 7), and
    a corpus whose salts came from a seeded PRNG would model the very defect class 12 exists to
    catch.
    """
    if pairing == "path":
        doc = {
            "pairing": "path",
            "salts": [
                {"segments": leaf.segments, "salt": secrets.token_bytes(SALT_BYTES).hex()}
                for leaf in ordered
            ],
        }
    elif pairing == "positional":
        doc = {
            "pairing": "positional",
            "leafCount": len(ordered),
            "salts": [secrets.token_bytes(SALT_BYTES).hex() for _ in ordered],
        }
    else:
        raise SystemExit(f"unknown salt pairing {pairing!r}")

    os.makedirs(_DIR, exist_ok=True)
    with open(path_for(name), "w", encoding="utf-8") as handle:
        handle.write(_render(doc))
    return doc


def load(name: str) -> dict:
    """Read a committed salt set. A missing one is a build failure, never a fresh draw."""
    try:
        with open(path_for(name), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise SystemExit(
            f"corpus defect: salt set {name!r} is not committed at {reference_for(name)}.\n"
            f"Salts are independent random draws under decision D4b and cannot be recomputed, so "
            f"a build never draws one on demand - that would produce a root no other machine "
            f"could reproduce. Run `build_corpus.py --draw-salts` once and commit the result."
        )


def committed_names():
    """Every committed salt set, so a build can report one that no vector references."""
    if not os.path.isdir(_DIR):
        return []
    return sorted(n[:-5] for n in os.listdir(_DIR) if n.endswith(".json"))
