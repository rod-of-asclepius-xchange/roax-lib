import Foundation
import ROAXCanon

/// The result of one assertion.
public enum Outcome {
    case pass
    case fail(String)
    case notRun(String)
}

/// Per-class tallies, so the report says which class is short and why.
public final class Report {
    public private(set) var passed = 0
    public private(set) var failed = 0
    public private(set) var notRun = 0
    private var perClass = [Int: (pass: Int, fail: Int, notRun: Int)]()
    public private(set) var failures = [String]()
    public private(set) var notRunReasons = [String]()

    public func record(_ outcome: Outcome, class cls: Int, name: String) {
        var entry = perClass[cls] ?? (0, 0, 0)
        switch outcome {
        case .pass:
            passed += 1; entry.pass += 1
        case .fail(let detail):
            failed += 1; entry.fail += 1
            failures.append("class \(cls) \(name): \(detail)")
        case .notRun(let reason):
            notRun += 1; entry.notRun += 1
            notRunReasons.append("class \(cls) \(name): \(reason)")
        }
        perClass[cls] = entry
    }

    public func print() {
        Swift.print("")
        Swift.print("  class   pass   fail  notrun")
        for cls in perClass.keys.sorted() {
            let e = perClass[cls]!
            let flag = e.fail > 0 ? "  FAIL" : (e.notRun > 0 ? "  NOT RUN" : "")
            Swift.print(String(format: "  %5d  %5d  %5d  %6d%@", cls, e.pass, e.fail, e.notRun, flag))
        }
        Swift.print(String(format: "  total  %5d  %5d  %6d", passed, failed, notRun))

        if !failures.isEmpty {
            Swift.print("\nFAILURES")
            for f in failures.prefix(60) { Swift.print("  - \(f)") }
            if failures.count > 60 { Swift.print("  ... and \(failures.count - 60) more") }
        }
        if !notRunReasons.isEmpty {
            Swift.print("\nNOT RUN - each names the input that would enable it")
            var seen = Set<String>()
            for r in notRunReasons where seen.insert(String(r.split(separator: ":").dropFirst().joined())).inserted {
                Swift.print("  - \(r)")
            }
        }
    }

    /// 0 all ran and passed, 1 something ran and failed, 2 nothing failed but
    /// something did not run. A bare run must not read as a pass.
    public var exitCode: Int32 { failed > 0 ? 1 : (notRun > 0 ? 2 : 0) }
}

/// The runner's parsed type maps, keyed by `recordType`.
final class TypeMapCache {
    private var maps = [String: DisplayPatternTypeMap]()

    func map(for recordType: String) -> DisplayPatternTypeMap? { maps[recordType] }

    func store(_ map: DisplayPatternTypeMap, for recordType: String) { maps[recordType] = map }
}

/// Mapping a corpus `reason` to this library's own code.
///
/// `corpus/README.md` measured that four implementations name the fail-closed
/// condition four different ways and non-canonical base64 two ways, and records
/// that a corpus `reason` is the reference implementations' spelling rather than
/// a normative code. The response it prescribes is a **declared** equivalence
/// table beside that measurement rather than a loosened comparison: one
/// reference code maps to the one local code naming the same condition, and a
/// rejection for a different reason still fails.
public enum ReasonEquivalence {
    public static let table: [String: String] = [
        // The reference implementations' spelling of decision D7a fail-closed.
        "type-map-uncovered-path": "type-map-fail-closed",
    ]

    /// The same claim for ONE VECTOR rather than for a code everywhere it appears.
    ///
    /// Keyed `<vector name>::<reference reason>`, because a code-keyed entry would be too wide.
    /// `salt-leak-disclosed-copy-with-wrong-typed-salts` carries `"salts": {}` beside a
    /// `disclosure`: the reference implementations ask whether the member is PRESENT, so they
    /// answer `disclosed-copy-carries-salts`, while this package types every known member as it
    /// parses and refuses a present-but-wrong-typed one as `malformed-json` before the copy kind
    /// is settled. That refusal is deliberate and is what the vector is about - reading a
    /// wrong-typed member as ABSENT would switch the salt-leak guard off from outside.
    /// Aliasing the CODE globally would also excuse `salt-leak-disclosed-copy-with-salts-array`,
    /// where this package agrees exactly and where a parse-level refusal would mean it never
    /// reached the salt-leak guard at all.
    public static let perVector: [String: String] = [
        "salt-leak-disclosed-copy-with-wrong-typed-salts::disclosed-copy-carries-salts":
            "malformed-json",
    ]

    public static func matches(corpusReason: String, thrown: ROAXError) -> Bool {
        matches(vector: nil, corpusReason: corpusReason, thrown: thrown)
    }

    public static func matches(vector: String?, corpusReason: String, thrown: ROAXError) -> Bool {
        let expected = vector.flatMap { perVector["\($0)::\(corpusReason)"] }
            ?? table[corpusReason]
            ?? corpusReason
        return thrown.reason == expected
    }
}

/// Reads a corpus `input` escape form.
///
/// Three values cannot appear literally in a JSON file, so `input` may carry
/// one of these instead of a plain JSON value (`corpus/README.md`).
public enum InputForm {
    case literal(JSONValue)
    case utf16([UInt16])
    case segments([JSONValue])
    case jsonText(String)

    public static func classify(_ value: JSONValue?) -> InputForm {
        guard let value else { return .literal(.null) }
        if case .array(let units)? = value["$utf16"] {
            let codeUnits: [UInt16] = units.compactMap {
                guard case .string(let hex) = $0 else { return nil }
                return UInt16(hex, radix: 16)
            }
            return .utf16(codeUnits)
        }
        if case .array(let segs)? = value["$segments"] { return .segments(segs) }
        if case .string(let text)? = value["$jsonText"] { return .jsonText(text) }
        return .literal(value)
    }
}

/// Parses corpus path segments, including the escape form a segment key may
/// itself carry.
///
/// `corpus/README.md`: "A segment's `key` may itself be a `$utf16` object."
/// That is how `reject-unpaired-surrogate-key` carries a key no conforming JSON
/// writer can emit as well-formed UTF-8, and decoding it here is what lets the
/// vector reach the rejection it is about rather than dying as malformed JSON.
/// The decoding lives in the runner because `$utf16` is a corpus carrier and
/// not part of the envelope format.
public func parseCorpusSegments(_ rows: [JSONValue]) throws -> Path {
    try rows.map { row in
        if case .array(let units)? = row["key"]?["$utf16"] {
            let codeUnits: [UInt16] = units.compactMap {
                guard case .string(let hex) = $0 else { return nil }
                return UInt16(hex, radix: 16)
            }
            return .key(try UTF16Input.string(fromCodeUnits: codeUnits))
        }
        if case .string(let k)? = row["key"] { return .key(k) }
        if case .number(let i)? = row["index"] {
            guard let n = UInt64(i) else {
                throw ROAXError.malformedJSON("path index \(i) is not a non-negative integer")
            }
            return try PathSegment.index(checking: n)
        }
        throw ROAXError.malformedJSON("a path segment is neither a key nor an index")
    }
}

public func loadJSON(_ path: String) throws -> JSONValue {
    let data = try Data(contentsOf: URL(fileURLWithPath: path))
    return try JSONScanner.parse([UInt8](data))
}

func hexBytes(_ value: JSONValue?) -> [UInt8]? {
    guard case .string(let hex)? = value else { return nil }
    return [UInt8].roaxFromHex(hex)
}

func intValue(_ value: JSONValue?) -> Int? {
    guard case .number(let text)? = value else { return nil }
    return Int(text)
}

func stringValue(_ value: JSONValue?) -> String? {
    guard case .string(let s)? = value else { return nil }
    return s
}

func boolValue(_ value: JSONValue?) -> Bool? {
    guard case .bool(let b)? = value else { return nil }
    return b
}

func arrayValue(_ value: JSONValue?) -> [JSONValue]? {
    guard case .array(let a)? = value else { return nil }
    return a
}
/// The first field on which a produced envelope differs from a committed one, or nil.
///
/// Field by field rather than by bytes, because this package emits no JSON and because JSON
/// member order, `displayPath` and the order of `disclosure.leaves` are not fixed by the
/// specification anyway. A whole envelope printed twice is not a readable failure, and the
/// defect class 20 exists for is one missing member on one leaf.
func firstEnvelopeDifference(produced: Envelope, expected: Envelope) -> String? {
    func compare<T: Equatable>(_ label: String, _ got: T, _ want: T) -> String? {
        got == want ? nil : "\(label): \(got) != \(want)"
    }
    let scalars: [String?] = [
        compare("canon", produced.canon, expected.canon),
        compare("hashAlg", produced.hashAlg, expected.hashAlg),
        compare("recordType", produced.recordType, expected.recordType),
        compare("schemaVersion", produced.schemaVersion, expected.schemaVersion),
        compare("recordId", produced.recordId, expected.recordId),
        compare("issuerId", produced.issuerId, expected.issuerId),
        compare("issuer.keyId", produced.issuerKeyId, expected.issuerKeyId),
        compare("typeMap.id", produced.typeMapId, expected.typeMapId),
        compare("typeMap.version", produced.typeMapVersion, expected.typeMapVersion),
        compare("root", produced.root.roaxHex, expected.root.roaxHex),
        compare("leafCount", produced.leafCount, expected.leafCount),
    ]
    if let first = scalars.compactMap({ $0 }).first { return first }

    // A full copy's salts, addressed by path so the array order carries nothing.
    switch (produced.salts, expected.salts) {
    case (nil, nil):
        break
    case (let got?, let want?):
        let key = { (entry: SaltEntry) in PathEncoding.encode(entry.segments).roaxHex }
        let gotTable = Dictionary(uniqueKeysWithValues: got.map { (key($0), $0.salt.roaxHex) })
        let wantTable = Dictionary(uniqueKeysWithValues: want.map { (key($0), $0.salt.roaxHex) })
        if gotTable != wantTable {
            let missing = Set(wantTable.keys).subtracting(gotTable.keys).sorted()
            let extra = Set(gotTable.keys).subtracting(wantTable.keys).sorted()
            return "salts differ: \(missing.count) missing, \(extra.count) unexpected"
        }
    default:
        return "salts: one copy carries the array and the other does not"
    }

    switch (produced.disclosedLeaves, expected.disclosedLeaves) {
    case (nil, nil):
        return nil
    case (let got?, let want?):
        // Sorted by leaf index on both sides: the array order is not specified.
        let gotSorted = got.sorted { $0.index < $1.index }
        let wantSorted = want.sorted { $0.index < $1.index }
        if let difference = compare("disclosure.leaves.count", gotSorted.count, wantSorted.count) {
            return difference
        }
        for (g, w) in zip(gotSorted, wantSorted) {
            let at = PathEncoding.display(w.segments)
            let perLeaf: [String?] = [
                compare("\(at).segments", PathEncoding.encode(g.segments).roaxHex,
                        PathEncoding.encode(w.segments).roaxHex),
                compare("\(at).index", g.index, w.index),
                compare("\(at).tag", g.tag.rawValue, w.tag.rawValue),
                compare("\(at).value", describeCarrier(g.value), describeCarrier(w.value)),
                compare("\(at).salt", g.salt.roaxHex, w.salt.roaxHex),
                compare("\(at).auditPath", g.auditPath.map(\.roaxHex), w.auditPath.map(\.roaxHex)),
            ]
            if let first = perLeaf.compactMap({ $0 }).first { return first }
        }
        return nil
    default:
        return "disclosure: one copy carries revealed leaves and the other does not"
    }
}

/// A comparable rendering of a disclosed leaf's carrier. `nil` is ABSENT and is what tags 0, 6
/// and 7 carry; anything else renders its kind and content, so a BOOL `true` and the string
/// `"true"` never compare equal.
private func describeCarrier(_ value: JSONValue?) -> String {
    guard let value else { return "ABSENT" }
    switch value {
    case .string(let s): return "string:\(s)"
    case .bool(let b): return "bool:\(b)"
    case .number(let n): return "number:\(n)"
    case .null: return "null"
    case .array: return "array"
    case .object: return "object"
    }
}
