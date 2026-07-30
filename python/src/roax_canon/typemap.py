"""Schema binding: resolving a structured path and an observed JSON kind to a type tag.

**The type tag MUST come from the schema, not from the JSON literal's syntax**
(specification section 4).
**Unknown transitions and missing observed-kind outputs MUST fail closed**
(specification section 4.2, ruled decision D7a).
Nothing in this module infers, defaults or searches a second map.

Two shapes of map exist in this repository and only one of them is implemented here.

:class:`DisplayPatternTypeMap` reads the format of `schemas/type-map-1.0.json`, which
that schema itself marks superseded and non-operative.
It is what `corpus/type-maps/*.json` carries and therefore what the conformance corpus
resolves against, so it is implemented to the letter and no further.

The operative published format is the structured-path DFA of
`schemas/type-map-artifact-1.0.json`, with exact content-ID selection and issuer
extensions (`docs/type-maps.md` sections 3 through 5).
**It is deliberately not implemented here**, because no committed corpus vector exercises
it: the corpus predates the artifact work, its maps are the display-pattern draft, and
building an artifact loader would add a large unexercised surface to a library whose
acceptance criterion is byte-identical agreement on the corpus.
:class:`TypeResolver` is the seam a DFA resolver drops into unchanged.

**Decision D14 is open and this module must not settle it.**
Whether the lookup matches over an NFC-normalized key or over the bytes as received is
unresolved (`docs/decisions.md` part 2a).
Both existing reference implementations compare **raw**, and the corpus's synthetic map
carries the Kelvin key under both spellings precisely so that no vector depends on the
answer.
:meth:`DisplayPatternTypeMap.resolve` therefore compares raw, with no ``nfc()`` on either
side.
Adding one here would rule D14 silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from .errors import ErrorCode, RoaxError, TypeResolutionError
from .path import Index, Key, Segment, display_path

__all__ = [
    "TypeResolver",
    "PatternToken",
    "KeyToken",
    "IndexToken",
    "AnyRunToken",
    "parse_pattern",
    "DisplayPatternTypeMap",
]

JSON_KINDS = ("string", "number", "boolean", "null", "object", "array")
_TOP_LEVEL_FIELDS = frozenset(
    {"typeMapVersion", "recordType", "schemaVersion", "sourceSchemas", "entries"}
)
_REQUIRED_TOP_LEVEL_FIELDS = ("typeMapVersion", "recordType", "schemaVersion", "entries")
_ENTRY_FIELDS = frozenset({"pattern", "jsonKind", "tag", "source"})
_SOURCE_SCHEMA_FIELDS = frozenset({"path", "commit", "note"})
_TYPE_MAP_VERSION = re.compile(r"\A[0-9]+\.[0-9]+\.[0-9]+\Z")
_SOURCE_COMMIT = re.compile(r"\A[0-9a-f]{7,40}\Z")


def _unknown_fields(document: dict[Any, Any], allowed: frozenset[str]) -> list[str]:
    """Return stable diagnostic spellings without assuming every key is a string."""
    return sorted((repr(key) for key in document if key not in allowed))


def _reject_unknown_fields(
    document: dict[Any, Any], allowed: frozenset[str], *, source: str, where: str
) -> None:
    unknown = _unknown_fields(document, allowed)
    if unknown:
        raise RoaxError(
            ErrorCode.TYPE_MAP_REJECTED,
            f"{source}: unknown {where} fields {unknown}",
        )


class TypeResolver(Protocol):
    """The seam every tag lookup goes through.

    An implementation MUST raise :class:`~roax_canon.errors.TypeResolutionError` with
    :data:`~roax_canon.errors.ErrorCode.TYPE_UNRESOLVED` when it has no output, rather
    than returning a default.

    The protocol carries no artifact metadata.
    :func:`roax_canon.record.build_tree` binds
    :class:`DisplayPatternTypeMap`'s declared ``recordType`` and ``schemaVersion``
    automatically, but a custom resolver is a trusted integration seam whose caller MUST
    bind its provenance and scope to the supplied identity before construction
    (specification sections 4.2 and 12.1).
    """

    def resolve(self, segments: Sequence[Segment], kind: str) -> int:  # pragma: no cover
        ...


@dataclass(frozen=True, slots=True)
class KeyToken:
    """One literal map member in a display pattern."""

    name: str


@dataclass(frozen=True, slots=True)
class IndexToken:
    """``[*]``: any single array index."""


@dataclass(frozen=True, slots=True)
class AnyRunToken:
    """``**``: any run of one or more segments.

    One or more rather than zero or more.
    A zero-length run would make ``a.**`` also bind the value at ``a`` itself, which
    would silently widen every map that uses the token.
    No committed vector discriminates; this is the narrower reading and it is stated
    rather than left implicit.
    """


PatternToken = KeyToken | IndexToken | AnyRunToken

# A component is a name followed by zero or more `[*]` groups. The name may not contain
# a bracket: display notation has no escape, so a key containing `[` or `]` is
# unreachable through it and a pattern that appears to contain one is ambiguous rather
# than meaningful (`corpus/README.md`, ambiguity 5).
_COMPONENT = re.compile(r"\A(?P<name>[^\[\]]*)(?P<indices>(?:\[\*\])*)\Z")


def parse_pattern(pattern: str) -> tuple[PatternToken, ...]:
    """Parse a display-notation pattern into tokens.

    Raises rather than guessing when the notation is ambiguous.
    The pattern language cannot address a key containing ``.``, ``[`` or ``]``, which
    specification section 5 deliberately admits with no rejection rule, so ``a.**`` is how
    such a key is reached.
    """
    if not isinstance(pattern, str) or pattern == "":
        raise RoaxError(ErrorCode.TYPE_MAP_REJECTED, "type-map pattern must be a non-empty string")

    tokens: list[PatternToken] = []
    for component in pattern.split("."):
        if component == "**":
            tokens.append(AnyRunToken())
            continue
        m = _COMPONENT.match(component)
        if m is None:
            raise RoaxError(
                ErrorCode.TYPE_MAP_REJECTED,
                f"ambiguous type-map pattern component {component!r} in {pattern!r}",
            )
        name = m.group("name")
        if name == "":
            raise RoaxError(
                ErrorCode.TYPE_MAP_REJECTED,
                f"ambiguous type-map pattern component {component!r} in {pattern!r}",
            )
        if "*" in name:
            raise RoaxError(
                ErrorCode.TYPE_MAP_REJECTED,
                f"ambiguous type-map pattern component {component!r} in {pattern!r}",
            )
        tokens.append(KeyToken(name))
        tokens.extend(IndexToken() for _ in range(len(m.group("indices")) // 3))
    return tuple(tokens)


def _match(tokens: Sequence[PatternToken], segments: Sequence[Segment]) -> bool:
    """Match tokens against decoded segments, never against a rendered string.

    Specification section 5.2 forbids reasoning over display paths; the pattern is
    authored in display notation for readability and is compiled to tokens before it
    touches a path.
    """
    if not tokens:
        return not segments
    head, rest = tokens[0], tokens[1:]

    if isinstance(head, AnyRunToken):
        # One or more segments, tried longest-first so a trailing `**` is greedy without
        # changing which paths match.
        for take in range(len(segments), 0, -1):
            if _match(rest, segments[take:]):
                return True
        return False

    if not segments:
        return False
    seg = segments[0]
    if isinstance(head, KeyToken):
        # RAW comparison. Decision D14 is open; see the module docstring.
        if not isinstance(seg, Key) or seg.value != head.name:
            return False
    else:
        if not isinstance(seg, Index):
            return False
    return _match(rest, segments[1:])


@dataclass(frozen=True, slots=True)
class _Entry:
    tokens: tuple[PatternToken, ...]
    json_kind: str | None
    tag: int
    pattern: str


class DisplayPatternTypeMap:
    """The superseded display-pattern map of `schemas/type-map-1.0.json`.

    First match wins, in the order the ``entries`` array declares, which is that format's
    own order-dependent rule.
    An entry with no ``jsonKind`` matches any observed kind; an entry with one matches
    only that kind.

    A map that binds any path to tag 8 `BLOB_REF` is rejected outright rather than
    resolving, because the content-addressed binding is defined and selected by no
    version-1 profile (specification section 6.5).
    That is a different outcome from failing closed: the path IS covered, by a binding no
    profile has declared, and conflating the two would let an implementation pass by
    treating an undeclared binding as an unknown path.
    """

    def __init__(self, document: Any, *, source: str = "<memory>") -> None:
        from .jsonio import as_int, is_json_string, is_record_type_string

        # This class consumes the closed carrier pinned by `schemas/type-map-1.0.json`.
        # Validate that boundary here rather than relying on a caller to have run a JSON
        # Schema tool: `from_file` is used directly by the standalone corpus runner.
        if not isinstance(document, dict):
            raise RoaxError(
                ErrorCode.TYPE_MAP_REJECTED,
                f"{source}: type map must be an object",
            )
        _reject_unknown_fields(document, _TOP_LEVEL_FIELDS, source=source, where="type-map")

        missing = [field for field in _REQUIRED_TOP_LEVEL_FIELDS if field not in document]
        if missing:
            raise RoaxError(
                ErrorCode.TYPE_MAP_REJECTED,
                f"{source}: type map is missing required fields {missing}",
            )

        type_map_version = document["typeMapVersion"]
        record_type = document["recordType"]
        schema_version = document["schemaVersion"]
        if (
            not is_json_string(type_map_version)
            or _TYPE_MAP_VERSION.match(type_map_version) is None
        ):
            raise RoaxError(
                ErrorCode.TYPE_MAP_REJECTED,
                f"{source}: typeMapVersion must be a three-part numeric version string",
            )
        if not is_record_type_string(record_type):
            raise RoaxError(
                ErrorCode.TYPE_MAP_REJECTED,
                f"{source}: recordType is not a reverse-DNS profile string",
            )
        if not is_json_string(schema_version) or not schema_version:
            raise RoaxError(
                ErrorCode.TYPE_MAP_REJECTED,
                f"{source}: schemaVersion must be a non-empty string",
            )

        self.source = source
        self.record_type = record_type
        self.schema_version = schema_version
        self.type_map_version = type_map_version

        if "sourceSchemas" in document:
            raw_sources = document["sourceSchemas"]
            if not isinstance(raw_sources, list):
                raise RoaxError(
                    ErrorCode.TYPE_MAP_REJECTED,
                    f"{source}: sourceSchemas must be an array",
                )
            for raw_source in raw_sources:
                if not isinstance(raw_source, dict):
                    raise RoaxError(
                        ErrorCode.TYPE_MAP_REJECTED,
                        f"{source}: sourceSchemas entry is not an object: {raw_source!r}",
                    )
                _reject_unknown_fields(
                    raw_source,
                    _SOURCE_SCHEMA_FIELDS,
                    source=source,
                    where="sourceSchemas entry",
                )
                path = raw_source.get("path")
                if not is_json_string(path):
                    raise RoaxError(
                        ErrorCode.TYPE_MAP_REJECTED,
                        f"{source}: sourceSchemas entry carries no `path` string",
                    )
                commit = raw_source.get("commit")
                if "commit" in raw_source and (
                    not is_json_string(commit) or _SOURCE_COMMIT.match(commit) is None
                ):
                    raise RoaxError(
                        ErrorCode.TYPE_MAP_REJECTED,
                        f"{source}: sourceSchemas entry carries a malformed `commit`",
                    )
                if "note" in raw_source and not is_json_string(raw_source["note"]):
                    raise RoaxError(
                        ErrorCode.TYPE_MAP_REJECTED,
                        f"{source}: sourceSchemas entry carries a non-string `note`",
                    )

        raw_entries = document["entries"]
        if not isinstance(raw_entries, list) or not raw_entries:
            raise RoaxError(ErrorCode.TYPE_MAP_REJECTED, f"{source}: type map has no entries")

        entries: list[_Entry] = []
        for raw in raw_entries:
            # This is the fail-closed artifact-loading surface, so every field of an entry
            # is validated and every rejection carries the same stable code. A `pattern`
            # read by a bare subscript would raise `KeyError` out of `from_file` instead,
            # and `is_json_string` rather than `isinstance(pattern, str)` because a
            # `JsonNumber` pattern would bind the key its literal spells.
            if not isinstance(raw, dict):
                raise RoaxError(
                    ErrorCode.TYPE_MAP_REJECTED, f"{source}: entry is not an object: {raw!r}"
                )
            _reject_unknown_fields(raw, _ENTRY_FIELDS, source=source, where="entry")
            pattern = raw.get("pattern")
            if not is_json_string(pattern) or not pattern:
                raise RoaxError(
                    ErrorCode.TYPE_MAP_REJECTED,
                    f"{source}: entry carries no non-empty `pattern` string: {raw!r}",
                )
            try:
                # A tag is an artifact field rather than a record value, so converting it
                # from the literal-preserving reader's carrier is correct here.
                tag = as_int(raw.get("tag"), field="tag")
            except RoaxError:
                raise RoaxError(
                    ErrorCode.TYPE_MAP_REJECTED, f"{source}: bad tag {raw.get('tag')!r}"
                ) from None
            if not 0 <= tag <= 8:
                raise RoaxError(ErrorCode.TYPE_MAP_REJECTED, f"{source}: bad tag {tag!r}")
            if tag == 8:
                raise RoaxError(
                    ErrorCode.TYPE_MAP_REJECTED,
                    f"{source}: binds {pattern!r} to tag 8 BLOB_REF, which no "
                    f"version-1 profile declares (specification section 6.5)",
                )
            kind = raw.get("jsonKind")
            if "jsonKind" in raw and kind not in JSON_KINDS:
                raise RoaxError(ErrorCode.TYPE_MAP_REJECTED, f"{source}: bad jsonKind {kind!r}")
            if "source" in raw and not is_json_string(raw["source"]):
                raise RoaxError(
                    ErrorCode.TYPE_MAP_REJECTED,
                    f"{source}: entry carries a non-string `source`",
                )
            entries.append(_Entry(parse_pattern(pattern), kind, tag, pattern))
        self.entries = tuple(entries)

    @classmethod
    def from_file(cls, path: str) -> "DisplayPatternTypeMap":
        from .jsonio import load_file

        return cls(load_file(path), source=path)

    def resolve(self, segments: Sequence[Segment], kind: str) -> int:
        """Resolve a path and observed kind to a tag, or fail closed.

        Fails closed for an uncovered path AND for a covered path with no output at the
        observed kind, which are the two cases specification section 4.2 names.
        """
        segments = tuple(segments)
        for entry in self.entries:
            if entry.json_kind is not None and entry.json_kind != kind:
                continue
            if _match(entry.tokens, segments):
                return entry.tag
        raise TypeResolutionError(
            ErrorCode.TYPE_UNRESOLVED,
            f"no binding for {display_path(segments)!r} at kind {kind!r} in {self.source} "
            f"(specification section 4.2, ruled decision D7a)",
        )
