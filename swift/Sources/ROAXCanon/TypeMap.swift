import Foundation

/// Resolving a structured path and an observed JSON kind to one ROAX type tag.
///
/// **This is an interface on purpose, and the reason is a corpus defect rather
/// than a taste for abstraction.** Specification section 4.2 makes the operative
/// matcher a structured-path DFA over `schemas/type-map-artifact-1.0.json`, and
/// says a display-pattern table MUST NOT be used to resolve. Every corpus vector
/// that needs a map nevertheless resolves against `corpus/type-maps/<recordType>.json`,
/// which *is* the display-pattern format, and no published artifact for
/// `org.roax.corpus.synthetic` exists at all - so no structured-path DFA can
/// resolve a single corpus record. Under specification section 1.1 that is a
/// release-blocking corpus defect, already reported by the TypeScript build
/// (`docs/typescript-implementation-findings.md`).
///
/// So the seam is explicit: `DisplayPatternTypeMap` is labelled superseded and
/// carries the corpus, and `TypeResolver` is what a structured-artifact
/// resolver will implement without any caller changing.
public protocol TypeResolver {
    /// Resolves, or fails closed.
    ///
    /// Decision D7a: a resolver MUST NOT search another installed map, infer
    /// from JSON syntax or apply a fallback tag.
    func resolve(segments: Path, jsonKind: JSONKind) throws -> TypeTag
}

/// The superseded display-pattern representation of
/// `schemas/type-map-1.0.json`, which is what `corpus/type-maps/` carries.
///
/// The schema itself says this format "MUST NOT be used to publish or resolve a
/// type map". It is implemented here because the committed corpus is expressed
/// in it and for no other reason, and it is named so that no caller can adopt
/// it by accident.
public struct DisplayPatternTypeMap: TypeResolver {

    /// One `(pattern, jsonKind) -> tag` row.
    struct Entry {
        let tokens: [PatternToken]
        let jsonKind: JSONKind?
        let tag: TypeTag
    }

    enum PatternToken: Equatable {
        /// A KEY segment, already NFC-normalized at parse time.
        case key(String)
        /// `[*]`: any single INDEX segment.
        case anyIndex
        /// `**`: any run of segments, including none.
        case anySegments
    }

    public let recordType: String
    public let schemaVersion: String
    let entries: [Entry]

    /// Parses the display-pattern carrier.
    ///
    /// **Both sides of the lookup normalize, under ruled decision D14a.**
    /// A pattern's KEY token is NFC-normalized here, at parse time, and a
    /// segment's key is normalized at match time. Normalizing only the segment
    /// key would leave a decomposed pattern permanently dead rather than
    /// provably redundant (`docs/type-maps.md` section 3.1).
    public init(json: JSONValue) throws {
        guard case .object = json,
              case .string(let recordType)? = json["recordType"],
              case .string(let schemaVersion)? = json["schemaVersion"],
              case .array(let rows)? = json["entries"]
        else {
            throw ROAXError.typeMapInvalid("missing recordType, schemaVersion or entries")
        }
        self.recordType = recordType
        self.schemaVersion = schemaVersion

        var parsed = [Entry]()
        for row in rows {
            guard case .string(let pattern)? = row["pattern"] else {
                throw ROAXError.typeMapInvalid("an entry has no pattern")
            }
            guard case .number(let tagText)? = row["tag"], let raw = UInt8(tagText),
                  let tag = TypeTag(rawValue: raw)
            else {
                throw ROAXError.typeMapInvalid("entry \(pattern) has no usable tag")
            }
            // Specification section 6.5: an implementation MUST reject a type
            // map that binds any path to tag 8 until a profile declares it.
            if tag == .blobRef { throw ROAXError.blobRefNotSelectable }

            var kind: JSONKind? = nil
            if case .string(let kindText)? = row["jsonKind"] {
                guard let k = JSONKind(rawValue: kindText) else {
                    throw ROAXError.typeMapInvalid("entry \(pattern) has unknown jsonKind \(kindText)")
                }
                kind = k
            }
            parsed.append(Entry(tokens: try Self.parsePattern(pattern), jsonKind: kind, tag: tag))
        }
        self.entries = parsed
    }

    public init(jsonText: String) throws {
        try self.init(json: try JSONScanner.parse(jsonText))
    }

    /// Parses one display pattern into tokens.
    ///
    /// **An ambiguous pattern is rejected rather than mis-parsed.**
    /// `corpus/README.md` ambiguity 5 records the limit: the pattern field is
    /// display notation, so it cannot address a key containing `.`, `[` or `]`,
    /// which specification section 5 deliberately admits with no rejection rule.
    /// The refusal is what keeps a pattern from silently addressing a different
    /// path from the one its author meant.
    static func parsePattern(_ pattern: String) throws -> [PatternToken] {
        var tokens = [PatternToken]()
        var current = ""
        var i = pattern.startIndex

        func flushKey() throws {
            if current == "**" {
                tokens.append(.anySegments)
            } else if current.contains("*") {
                throw ROAXError.typeMapInvalid(
                    "pattern \(pattern.debugDescription) mixes '*' into a key token"
                )
            } else {
                tokens.append(.key(NFC.normalize(current)))
            }
            current = ""
        }

        while i < pattern.endIndex {
            let c = pattern[i]
            if c == "." {
                guard !current.isEmpty else {
                    throw ROAXError.typeMapInvalid("pattern \(pattern.debugDescription) has an empty key token")
                }
                try flushKey()
                i = pattern.index(after: i)
            } else if c == "[" {
                if !current.isEmpty { try flushKey() }
                guard let close = pattern[i...].firstIndex(of: "]") else {
                    throw ROAXError.typeMapInvalid("pattern \(pattern.debugDescription) has an unterminated index token")
                }
                let inner = String(pattern[pattern.index(after: i)..<close])
                guard inner == "*" else {
                    throw ROAXError.typeMapInvalid(
                        "pattern \(pattern.debugDescription) carries index token [\(inner)]; only [*] is defined"
                    )
                }
                tokens.append(.anyIndex)
                i = pattern.index(after: close)
                // A '.' may follow an index token; anything else is a run-on.
                if i < pattern.endIndex, pattern[i] == "." { i = pattern.index(after: i) }
                else if i < pattern.endIndex, pattern[i] != "[" {
                    throw ROAXError.typeMapInvalid(
                        "pattern \(pattern.debugDescription) has content directly after an index token"
                    )
                }
            } else if c == "]" {
                throw ROAXError.typeMapInvalid("pattern \(pattern.debugDescription) has an unmatched ']'")
            } else {
                current.append(c)
                i = pattern.index(after: i)
            }
        }
        if !current.isEmpty { try flushKey() }
        return tokens
    }

    public func resolve(segments: Path, jsonKind: JSONKind) throws -> TypeTag {
        for entry in entries {
            guard entry.jsonKind == nil || entry.jsonKind == jsonKind else { continue }
            if Self.matches(tokens: entry.tokens, segments: segments) { return entry.tag }
        }
        // Decision D7a: fail closed, even when the tag seems mechanically
        // obvious from JSON syntax.
        throw ROAXError.typeMapUncoveredPath(
            path: PathEncoding.display(segments),
            jsonKind: jsonKind.rawValue
        )
    }

    /// Matches tokens against decoded segments, never against a rendered string.
    ///
    /// The comparison for a KEY token is `NFC(patternKey) == NFC(segmentKey)`.
    /// That is ruled decision D14a and not a reading: section 11.2's rule is
    /// "check the bytes you commit, not the bytes you received", and an encoded
    /// KEY segment commits `NFC(key)`, so a raw comparison would decide
    /// admissibility on a spelling no root records.
    static func matches(tokens: [PatternToken], segments: Path) -> Bool {
        matches(tokens: tokens[...], segments: segments[...])
    }

    private static func matches(
        tokens: ArraySlice<PatternToken>,
        segments: ArraySlice<PathSegment>
    ) -> Bool {
        guard let token = tokens.first else { return segments.isEmpty }
        switch token {
        case .anySegments:
            // Any run of segments, including none.
            var consumed = segments
            while true {
                if matches(tokens: tokens.dropFirst(), segments: consumed) { return true }
                guard !consumed.isEmpty else { return false }
                consumed = consumed.dropFirst()
            }
        case .key(let normalizedPatternKey):
            guard case .key(let segmentKey)? = segments.first else { return false }
            guard NFC.normalize(segmentKey) == normalizedPatternKey else { return false }
            return matches(tokens: tokens.dropFirst(), segments: segments.dropFirst())
        case .anyIndex:
            guard case .index? = segments.first else { return false }
            return matches(tokens: tokens.dropFirst(), segments: segments.dropFirst())
        }
    }
}

/// A resolver that authorizes nothing, for tests that need the fail-closed path
/// without a map.
public struct FailClosedTypeMap: TypeResolver {
    public init() {}
    public func resolve(segments: Path, jsonKind: JSONKind) throws -> TypeTag {
        throw ROAXError.typeMapUncoveredPath(
            path: PathEncoding.display(segments),
            jsonKind: jsonKind.rawValue
        )
    }
}
