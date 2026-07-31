import Foundation

/// The admissible value kinds of specification section 3.2, with numbers held
/// as their **verbatim source literal**.
///
/// `JSONSerialization` cannot carry this model. Measured on this checkout it
/// reserializes `0.010` as `0.01`, `1.50` as `1.5`, `2.0` as `2` and `0.1` as
/// `0.10000000000000001`, while `1234567890123456789.1` survives because
/// Foundation switches to `NSDecimalNumber` above a magnitude threshold. That
/// inconsistency is what makes it dangerous rather than merely lossy: every
/// small-number test anyone writes passes. `swift/FINDINGS.md` finding 1
/// records the measurement, and specification section 6.4 already predicted it
/// as a negative result for Swift.
public indirect enum JSONValue: Equatable {
    /// Members in source order, which the flattener does not depend on
    /// (specification section 3.3) but which keeps a re-serialization readable.
    case object([(key: String, value: JSONValue)])
    case array([JSONValue])
    case string(String)
    /// The number's source text, exactly as written.
    case number(String)
    case bool(Bool)
    case null

    public var jsonKind: JSONKind {
        switch self {
        case .object: return .object
        case .array: return .array
        case .string: return .string
        case .number: return .number
        case .bool: return .boolean
        case .null: return .null
        }
    }

    public static func == (lhs: JSONValue, rhs: JSONValue) -> Bool {
        switch (lhs, rhs) {
        case (.object(let a), .object(let b)):
            return a.count == b.count
                && zip(a, b).allSatisfy { $0.key == $1.key && $0.value == $1.value }
        case (.array(let a), .array(let b)): return a == b
        case (.string(let a), .string(let b)): return a == b
        case (.number(let a), .number(let b)): return a == b
        case (.bool(let a), .bool(let b)): return a == b
        case (.null, .null): return true
        default: return false
        }
    }

    public subscript(key: String) -> JSONValue? {
        guard case .object(let members) = self else { return nil }
        return members.first(where: { $0.key == key })?.value
    }
}

/// A JSON reader that preserves numeric literals and refuses what
/// specification section 3.2 refuses.
///
/// Specification section 6.4 states that nothing in Foundation preserves a raw
/// numeric literal and that a literal-preserving scanner must be hand-written
/// for Swift. This is that scanner. It also has to be hand-written for a second
/// reason the specification does not name: `JSONSerialization` silently accepts
/// a duplicate object member and keeps one of them, so a parser built on it
/// cannot raise `duplicate-key` at all.
///
/// What it rejects at the input boundary, per specification section 3.2:
/// duplicate map keys; `NaN`, `Infinity` and `-Infinity`; and unpaired UTF-16
/// surrogates, including ones written as `\uD800` escapes.
public struct JSONScanner {

    private let bytes: [UInt8]
    private var i = 0

    private init(_ bytes: [UInt8]) { self.bytes = bytes }

    /// Parses one complete JSON document.
    public static func parse(_ text: String) throws -> JSONValue {
        try parse(Array(text.utf8))
    }

    /// Parses one complete JSON document from UTF-8 bytes.
    ///
    /// Taking bytes rather than a `String` matters: a `String` has already been
    /// through UTF-8 validation, so malformed input would have been replaced
    /// before this scanner could refuse it.
    public static func parse(_ bytes: [UInt8]) throws -> JSONValue {
        var scanner = JSONScanner(bytes)
        scanner.skipWhitespace()
        let value = try scanner.parseValue(depth: 0)
        scanner.skipWhitespace()
        guard scanner.i == scanner.bytes.count else {
            throw ROAXError.malformedJSON("trailing content at byte \(scanner.i)")
        }
        return value
    }

    // MARK: scanning

    private static let maxDepth = 512

    private mutating func parseValue(depth: Int) throws -> JSONValue {
        guard depth <= Self.maxDepth else {
            throw ROAXError.malformedJSON("nesting deeper than \(Self.maxDepth)")
        }
        guard i < bytes.count else { throw ROAXError.malformedJSON("unexpected end of input") }
        switch bytes[i] {
        case UInt8(ascii: "{"): return try parseObject(depth: depth)
        case UInt8(ascii: "["): return try parseArray(depth: depth)
        case UInt8(ascii: "\""): return .string(try parseString())
        case UInt8(ascii: "t"):
            try expect("true"); return .bool(true)
        case UInt8(ascii: "f"):
            try expect("false"); return .bool(false)
        case UInt8(ascii: "n"):
            try expect("null"); return .null
        default:
            return try parseNumber()
        }
    }

    private mutating func parseObject(depth: Int) throws -> JSONValue {
        i += 1                                  // '{'
        var members = [(key: String, value: JSONValue)]()
        // **Keyed by the RAW UTF-8 BYTES, and that is not a stylistic choice.**
        //
        // Swift's `String` equality is *canonical equivalence*, not byte
        // equality: `"é" == "e\u{0301}"` is `true`, and `Hashable` agrees, so a
        // `Set<String>` here would report a duplicate for two members whose raw
        // keys are distinct. Specification section 3.2 requires *raw* map keys
        // to be unique, and `corpus/README.md` ambiguity 6 turns on exactly that
        // shape: `{"é":{"a":1},"é":{"b":2}}` written in the two spellings has no
        // duplicate raw key, and the Rust implementation accepts it.
        //
        // So the obvious Swift spelling of this check silently decides an open
        // specification ambiguity, in the opposite direction from the rest of
        // the family, through a language feature rather than a decision.
        // `swift/FINDINGS.md` finding 7 records it.
        var seen = Set<[UInt8]>()
        skipWhitespace()
        if i < bytes.count, bytes[i] == UInt8(ascii: "}") { i += 1; return .object(members) }
        while true {
            skipWhitespace()
            guard i < bytes.count, bytes[i] == UInt8(ascii: "\"") else {
                throw ROAXError.malformedJSON("expected a member name at byte \(i)")
            }
            let key = try parseString()
            // Specification section 3.2: duplicate keys are rejected at the
            // input boundary and before any hashing. The comparison is over the
            // raw key, because that is what "duplicate keys in a map" names;
            // NFC-colliding siblings with disjoint descendants are a separate
            // and unruled question (`corpus/README.md` ambiguity 6).
            guard seen.insert(Array(key.utf8)).inserted else { throw ROAXError.duplicateKey(key) }
            skipWhitespace()
            guard i < bytes.count, bytes[i] == UInt8(ascii: ":") else {
                throw ROAXError.malformedJSON("expected ':' at byte \(i)")
            }
            i += 1
            skipWhitespace()
            let value = try parseValue(depth: depth + 1)
            members.append((key: key, value: value))
            skipWhitespace()
            guard i < bytes.count else { throw ROAXError.malformedJSON("unterminated object") }
            if bytes[i] == UInt8(ascii: ",") { i += 1; continue }
            if bytes[i] == UInt8(ascii: "}") { i += 1; return .object(members) }
            throw ROAXError.malformedJSON("expected ',' or '}' at byte \(i)")
        }
    }

    private mutating func parseArray(depth: Int) throws -> JSONValue {
        i += 1                                  // '['
        var items = [JSONValue]()
        skipWhitespace()
        if i < bytes.count, bytes[i] == UInt8(ascii: "]") { i += 1; return .array(items) }
        while true {
            skipWhitespace()
            items.append(try parseValue(depth: depth + 1))
            skipWhitespace()
            guard i < bytes.count else { throw ROAXError.malformedJSON("unterminated array") }
            if bytes[i] == UInt8(ascii: ",") { i += 1; continue }
            if bytes[i] == UInt8(ascii: "]") { i += 1; return .array(items) }
            throw ROAXError.malformedJSON("expected ',' or ']' at byte \(i)")
        }
    }

    /// Reads a string, decoding escapes and rejecting an unpaired surrogate.
    ///
    /// The surrogate check runs over UTF-16 code units gathered here rather
    /// than over the finished `String`, because a Swift `String` cannot hold an
    /// unpaired surrogate: constructing one substitutes U+FFFD, which turns a
    /// refusable input into a committable one.
    private mutating func parseString() throws -> String {
        i += 1                                  // opening quote
        var units = [UInt16]()
        var literalRun = [UInt8]()

        func flushLiteral() throws {
            guard !literalRun.isEmpty else { return }
            guard let s = String(bytes: literalRun, encoding: .utf8) else {
                throw ROAXError.malformedJSON("string is not valid UTF-8")
            }
            units.append(contentsOf: Array(s.utf16))
            literalRun.removeAll(keepingCapacity: true)
        }

        while true {
            guard i < bytes.count else { throw ROAXError.malformedJSON("unterminated string") }
            let c = bytes[i]
            if c == UInt8(ascii: "\"") {
                i += 1
                try flushLiteral()
                return try UTF16Input.string(fromCodeUnits: units)
            }
            if c == UInt8(ascii: "\\") {
                try flushLiteral()
                i += 1
                guard i < bytes.count else { throw ROAXError.malformedJSON("unterminated escape") }
                let e = bytes[i]
                i += 1
                switch e {
                case UInt8(ascii: "\""): units.append(0x22)
                case UInt8(ascii: "\\"): units.append(0x5C)
                case UInt8(ascii: "/"): units.append(0x2F)
                case UInt8(ascii: "b"): units.append(0x08)
                case UInt8(ascii: "f"): units.append(0x0C)
                case UInt8(ascii: "n"): units.append(0x0A)
                case UInt8(ascii: "r"): units.append(0x0D)
                case UInt8(ascii: "t"): units.append(0x09)
                case UInt8(ascii: "u"):
                    guard i + 3 < bytes.count else {
                        throw ROAXError.malformedJSON("truncated \\u escape")
                    }
                    var value: UInt16 = 0
                    for _ in 0..<4 {
                        guard let n = Self.hexNibble(bytes[i]) else {
                            throw ROAXError.malformedJSON("bad \\u escape")
                        }
                        value = value << 4 | UInt16(n)
                        i += 1
                    }
                    units.append(value)
                default:
                    throw ROAXError.malformedJSON("unknown escape \\\(Character(UnicodeScalar(e)))")
                }
                continue
            }
            if c < 0x20 {
                throw ROAXError.malformedJSON("unescaped control character in string")
            }
            literalRun.append(c)
            i += 1
        }
    }

    /// Reads a number and keeps its source text verbatim.
    ///
    /// The scanner also refuses the three non-finite spellings by name rather
    /// than treating them as unknown tokens, so the reason code says what the
    /// specification says: `NaN`, `Infinity` and `-Infinity` are values
    /// section 3.2 rejects at the input boundary.
    private mutating func parseNumber() throws -> JSONValue {
        if matchesKeyword("NaN") { throw ROAXError.nonFiniteNumber("NaN") }
        if matchesKeyword("Infinity") { throw ROAXError.nonFiniteNumber("Infinity") }
        if matchesKeyword("-Infinity") { throw ROAXError.nonFiniteNumber("-Infinity") }

        let start = i
        if i < bytes.count, bytes[i] == UInt8(ascii: "-") { i += 1 }
        let intStart = i
        while i < bytes.count, isDigit(bytes[i]) { i += 1 }
        guard i > intStart else {
            throw ROAXError.malformedJSON("expected a value at byte \(start)")
        }
        if i < bytes.count, bytes[i] == UInt8(ascii: ".") {
            i += 1
            let fracStart = i
            while i < bytes.count, isDigit(bytes[i]) { i += 1 }
            guard i > fracStart else { throw ROAXError.malformedJSON("empty fraction") }
        }
        if i < bytes.count, bytes[i] == UInt8(ascii: "e") || bytes[i] == UInt8(ascii: "E") {
            i += 1
            if i < bytes.count, bytes[i] == UInt8(ascii: "+") || bytes[i] == UInt8(ascii: "-") {
                i += 1
            }
            let expStart = i
            while i < bytes.count, isDigit(bytes[i]) { i += 1 }
            guard i > expStart else { throw ROAXError.malformedJSON("empty exponent") }
        }
        // Verbatim: the bytes as written, not a reserialization of a parse.
        return .number(String(decoding: bytes[start..<i], as: UTF8.self))
    }

    // MARK: primitives

    private mutating func skipWhitespace() {
        while i < bytes.count {
            switch bytes[i] {
            case 0x20, 0x09, 0x0A, 0x0D: i += 1
            default: return
            }
        }
    }

    private mutating func expect(_ keyword: String) throws {
        let k = Array(keyword.utf8)
        guard i + k.count <= bytes.count, Array(bytes[i..<(i + k.count)]) == k else {
            throw ROAXError.malformedJSON("expected \(keyword) at byte \(i)")
        }
        i += k.count
    }

    private func matchesKeyword(_ keyword: String) -> Bool {
        let k = Array(keyword.utf8)
        guard i + k.count <= bytes.count else { return false }
        return Array(bytes[i..<(i + k.count)]) == k
    }

    @inline(__always)
    private func isDigit(_ c: UInt8) -> Bool {
        c >= UInt8(ascii: "0") && c <= UInt8(ascii: "9")
    }

    private static func hexNibble(_ c: UInt8) -> UInt8? {
        switch c {
        case 0x30...0x39: return c - 0x30
        case 0x61...0x66: return c - 0x61 + 10
        case 0x41...0x46: return c - 0x41 + 10
        default: return nil
        }
    }
}
