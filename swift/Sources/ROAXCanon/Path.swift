import Foundation

/// One segment of a path (specification section 5).
///
/// There are no reserved characters and no escaping. A key MAY be the empty
/// string, and it encodes distinctly from an absent segment because the
/// segment count differs.
///
/// **The derived `Equatable` is canonical equivalence, and here that is
/// correct.** Swift's `String` `==` compares canonical equivalence rather than
/// bytes, so `.key("é")` equals `.key("e\u{0301}")`. That coincides exactly with
/// encoded-path equality, because `encodePath` commits `NFC(key)` - two
/// canonically equivalent keys always encode identically. The same language
/// feature is exactly *wrong* one layer up, where specification section 3.2
/// asks whether two raw map keys are duplicates; `JSONScanner` therefore
/// compares raw UTF-8 bytes there, and `swift/FINDINGS.md` finding 7 records why
/// the distinction has to be made deliberately in this language.
public enum PathSegment: Equatable, Hashable, Sendable {
    case key(String)
    case index(UInt32)

    /// Builds an INDEX segment from an unconstrained integer.
    ///
    /// Specification section 5: array indices MUST be below 2^32, and an
    /// implementation that cannot represent one MUST error rather than
    /// truncate. `PathSegment.index` is typed `UInt32`, so the error has to be
    /// raised where the wider integer is still visible, which is here.
    public static func index<T: BinaryInteger>(checking value: T) throws -> PathSegment {
        guard value >= 0, let narrow = UInt32(exactly: value) else {
            throw ROAXError.indexOutOf32BitRange(UInt64(clamping: value))
        }
        return .index(narrow)
    }
}

public typealias Path = [PathSegment]

public enum PathEncoding {

    /// `encodePath` of specification section 5.
    ///
    /// ```
    /// u32be(count) ‖ for each segment:
    ///     KEY(k)   -> 0x01 ‖ u32be(len(utf8(NFC(k)))) ‖ utf8(NFC(k))
    ///     INDEX(i) -> 0x02 ‖ u32be(i)
    /// ```
    public static func encode(_ segments: Path) -> [UInt8] {
        var out = [UInt8]()
        out.reserveCapacity(4 + segments.count * 8)
        out.appendU32BE(UInt32(segments.count))
        for segment in segments {
            switch segment {
            case .key(let k):
                let bytes = NFC.utf8(k)
                out.append(0x01)
                out.appendU32BE(UInt32(bytes.count))
                out.append(contentsOf: bytes)
            case .index(let i):
                out.append(0x02)
                out.appendU32BE(i)
            }
        }
        return out
    }

    /// The human-readable form `a.b[0].c`.
    ///
    /// Specification section 5.2: this is for display and for disclosure
    /// requests. It MUST NOT enter any hash preimage, and an encoded path MUST
    /// NOT be reconstructed by parsing one. Nothing in this library consumes
    /// the result of this function.
    public static func display(_ segments: Path) -> String {
        var out = ""
        for segment in segments {
            switch segment {
            case .key(let k):
                if out.isEmpty { out = k } else { out += "." + k }
            case .index(let i):
                out += "[\(i)]"
            }
        }
        return out
    }
}

// MARK: - the reserved namespace guard (specification section 11.2)

public enum ReservedNamespace {

    /// The ASCII prefix reserved for the leaves of specification section 11.2.
    public static let prefix = "roax."

    /// Rejects a record-supplied path whose **first** segment is a KEY whose
    /// NFC-normalized key begins with `roax.`.
    ///
    /// Three ways to get this wrong, and each is closed here deliberately:
    ///
    /// - it is not run against a rendered display path, because specification
    ///   section 5.2 forbids reasoning over one;
    /// - it applies to the first segment only, because every reserved path is a
    ///   single segment, so `[KEY("a"), KEY("roax.foo")]` cannot collide with
    ///   one and rejecting it would be over-broad;
    /// - it compares the **NFC-normalized** key, because section 6.1 normalizes
    ///   a key before it is committed and a check on the raw bytes checks a
    ///   different string from the one that gets hashed.
    ///
    /// A key named `roax`, or `roaxX`, has no dot and collides with nothing, so
    /// it is accepted.
    public static func check(_ segments: Path) throws {
        guard case .key(let first)? = segments.first else { return }
        if NFC.normalize(first).hasPrefix(prefix) {
            throw ROAXError.reservedNamespace(first)
        }
    }
}

// MARK: - byte helpers

extension Array where Element == UInt8 {
    @inlinable
    mutating func appendU32BE(_ v: UInt32) {
        append(UInt8(truncatingIfNeeded: v >> 24))
        append(UInt8(truncatingIfNeeded: v >> 16))
        append(UInt8(truncatingIfNeeded: v >> 8))
        append(UInt8(truncatingIfNeeded: v))
    }

    @inlinable
    mutating func appendU64BE(_ v: UInt64) {
        for shift in stride(from: 56, through: 0, by: -8) {
            append(UInt8(truncatingIfNeeded: v >> UInt64(shift)))
        }
    }
}

/// Plain unsigned byte comparison, which is the order specification section 9
/// pins for leaves.
@inlinable
public func roaxByteCompare(_ a: [UInt8], _ b: [UInt8]) -> Int {
    let n = Swift.min(a.count, b.count)
    var i = 0
    while i < n {
        if a[i] != b[i] { return a[i] < b[i] ? -1 : 1 }
        i += 1
    }
    if a.count == b.count { return 0 }
    return a.count < b.count ? -1 : 1
}

extension Array where Element == UInt8 {
    /// Lowercase hex, which is the form every hex field in the envelope and the
    /// corpus uses.
    public var roaxHex: String {
        var s = ""
        s.reserveCapacity(count * 2)
        let digits: [Character] = ["0", "1", "2", "3", "4", "5", "6", "7",
                                   "8", "9", "a", "b", "c", "d", "e", "f"]
        for b in self {
            s.append(digits[Int(b >> 4)])
            s.append(digits[Int(b & 0x0f)])
        }
        return s
    }

    public static func roaxFromHex(_ text: String) -> [UInt8]? {
        let chars = Array(text.utf8)
        guard chars.count % 2 == 0 else { return nil }
        var out = [UInt8]()
        out.reserveCapacity(chars.count / 2)
        var i = 0
        func nibble(_ c: UInt8) -> UInt8? {
            switch c {
            case 0x30...0x39: return c - 0x30
            case 0x61...0x66: return c - 0x61 + 10
            default: return nil
            }
        }
        while i < chars.count {
            guard let hi = nibble(chars[i]), let lo = nibble(chars[i + 1]) else { return nil }
            out.append(hi << 4 | lo)
            i += 2
        }
        return out
    }
}
