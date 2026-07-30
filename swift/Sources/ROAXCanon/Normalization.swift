import Foundation

/// Unicode Normalization Form C, pinned by specification section 6.1 at
/// Unicode 15.1.
///
/// **What this implementation can and cannot assert about the pin.**
/// Foundation's `precomposedStringWithCanonicalMapping` is the only NFC on
/// Apple platforms, and neither Foundation nor the Swift standard library
/// exposes the Unicode version of the tables behind it. Measured on this
/// checkout, the standard library's own property tables answer for characters
/// assigned in Unicode 16.0 - U+10D40 GARAY DIGIT ZERO reports
/// `decimalNumber` rather than unassigned - so the tables are at least 16.0
/// and are not the pinned 15.1.
///
/// That is the same position `corpus/README.md` records for reference
/// implementation B, which generated agreeing vectors under Node's 16.0 tables
/// against a corpus pinned at 15.1, and it is the limit
/// `docs/conformance-corpus.md` class 16 states about itself: a version
/// mismatch is detected by declaration rather than by demonstration, because no
/// character whose NFC form changed across the boundary has been identified.
/// `ROAXCanon.unicodeVersion` is therefore the *declared* pin this library
/// claims conformance to, not a reading of the tables, and
/// `swift/FINDINGS.md` finding 5 states why no reading is available.
public enum NFC {

    /// The Unicode version `ROAX-CANON/1` pins, as a declaration.
    public static let declaredUnicodeVersion = "15.1"

    /// `NFC(s)` of specification section 6.1.
    @inlinable
    public static func normalize(_ s: String) -> String {
        s.precomposedStringWithCanonicalMapping
    }

    /// `utf8(NFC(s))`, which is what a STRING leaf and a KEY segment commit.
    @inlinable
    public static func utf8(_ s: String) -> [UInt8] {
        Array(normalize(s).utf8)
    }
}

/// Building a Swift `String` from UTF-16 code units, rejecting an unpaired
/// surrogate rather than replacing it.
///
/// Specification section 3.2 requires unpaired surrogates to be rejected at the
/// input boundary, and section 6.1 requires the rejection to happen *before*
/// normalization. On this platform the rejection has to happen before the
/// `String` exists at all: `String(decoding:as: UTF16.self)` over
/// `[0x0041, 0xD800, 0x0042]` yields `A\u{FFFD}B` rather than failing, which
/// silently turns an input the specification refuses into one that commits.
/// `swift/FINDINGS.md` finding 4 records the measurement.
public enum UTF16Input {

    /// Decodes UTF-16 code units, throwing `ROAXError.unpairedSurrogate`
    /// rather than substituting U+FFFD.
    public static func string(fromCodeUnits units: [UInt16]) throws -> String {
        var scalars = String.UnicodeScalarView()
        var i = 0
        while i < units.count {
            let u = units[i]
            if u >= 0xD800 && u <= 0xDBFF {
                guard i + 1 < units.count else { throw ROAXError.unpairedSurrogate }
                let low = units[i + 1]
                guard low >= 0xDC00 && low <= 0xDFFF else { throw ROAXError.unpairedSurrogate }
                let value = 0x10000
                    + (UInt32(u - 0xD800) << 10)
                    + UInt32(low - 0xDC00)
                scalars.append(Unicode.Scalar(value)!)
                i += 2
            } else if u >= 0xDC00 && u <= 0xDFFF {
                throw ROAXError.unpairedSurrogate
            } else {
                scalars.append(Unicode.Scalar(u)!)
                i += 1
            }
        }
        return String(scalars)
    }
}
