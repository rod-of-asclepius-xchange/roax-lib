import Foundation

/// The canonical base64 form pinned by specification section 6.3: RFC 4648
/// section 4, standard alphabet, with padding, no line wrapping.
///
/// **Foundation's decoder is not this decoder, and the gap is not theoretical.**
/// Measured on this checkout, `Data(base64Encoded: "aGl=")` returns two bytes.
/// That input's final quantum carries non-zero unused bits, which RFC 4648
/// section 3.5 identifies as the non-canonical case and specification section
/// 6.3 requires rejecting by name, and it is a committed corpus vector
/// (`reject-bytes-base64-nonzero-pad-bits`). `Data(base64Encoded:)` does reject
/// the unpadded, URL-safe and line-wrapped spellings, so a reader who spot-checks
/// three of the four rejections would conclude Foundation is sufficient.
/// `swift/FINDINGS.md` finding 3 records it.
public enum CanonicalBase64 {

    private static let alphabet: [UInt8] = Array(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/".utf8
    )

    private static let decodeTable: [Int8] = {
        var table = [Int8](repeating: -1, count: 256)
        for (i, c) in alphabet.enumerated() { table[Int(c)] = Int8(i) }
        return table
    }()

    /// Decodes, rejecting every spelling outside the pinned form.
    ///
    /// Under the ruled FHIR `base64Binary` binding this is an
    /// **input-admissibility** condition and never the committed value: the
    /// octets are what gets hashed, and a spelling outside the pinned form is
    /// rejected before it is decoded (`docs/type-maps.md` section 1.3).
    public static func decode(_ text: String) throws -> [UInt8] {
        let chars = Array(text.utf8)

        // A line break is outside the alphabet, so it is caught by the alphabet
        // scan below; it is named here because it is the spelling a permissive
        // decoder is most likely to accept.
        guard chars.count % 4 == 0 else {
            throw ROAXError.base64NotCanonical("length \(chars.count) is not a multiple of 4")
        }
        if chars.isEmpty { return [] }

        var padding = 0
        while padding < 2, chars.count - 1 - padding >= 0,
              chars[chars.count - 1 - padding] == UInt8(ascii: "=") {
            padding += 1
        }
        // Excess padding: a third '=' is not a quantum this form admits.
        if chars.count >= 3, chars[chars.count - 1 - padding] == UInt8(ascii: "=") {
            throw ROAXError.base64NotCanonical("more than two padding characters")
        }

        var values = [UInt8]()
        values.reserveCapacity(chars.count - padding)
        for (i, c) in chars.enumerated() {
            if i >= chars.count - padding {
                continue                       // already established to be '='
            }
            let v = decodeTable[Int(c)]
            guard v >= 0 else {
                throw ROAXError.base64NotCanonical(
                    "character \(String(UnicodeScalar(c)).debugDescription) is outside the RFC 4648 section 4 alphabet"
                )
            }
            values.append(UInt8(v))
        }

        // RFC 4648 section 3.5: the unused bits of the final quantum MUST be
        // zero, or several spellings decode to the same octets.
        if padding == 1 {
            guard values[values.count - 1] & 0x03 == 0 else {
                throw ROAXError.base64NotCanonical("final quantum carries non-zero unused bits")
            }
        } else if padding == 2 {
            guard values[values.count - 1] & 0x0f == 0 else {
                throw ROAXError.base64NotCanonical("final quantum carries non-zero unused bits")
            }
        }

        var out = [UInt8]()
        out.reserveCapacity(chars.count / 4 * 3)
        var i = 0
        while i + 3 < values.count {
            let n = UInt32(values[i]) << 18 | UInt32(values[i + 1]) << 12
                | UInt32(values[i + 2]) << 6 | UInt32(values[i + 3])
            out.append(UInt8(truncatingIfNeeded: n >> 16))
            out.append(UInt8(truncatingIfNeeded: n >> 8))
            out.append(UInt8(truncatingIfNeeded: n))
            i += 4
        }
        let remaining = values.count - i
        if remaining == 3 {
            let n = UInt32(values[i]) << 18 | UInt32(values[i + 1]) << 12 | UInt32(values[i + 2]) << 6
            out.append(UInt8(truncatingIfNeeded: n >> 16))
            out.append(UInt8(truncatingIfNeeded: n >> 8))
        } else if remaining == 2 {
            let n = UInt32(values[i]) << 18 | UInt32(values[i + 1]) << 12
            out.append(UInt8(truncatingIfNeeded: n >> 16))
        } else if remaining == 1 {
            throw ROAXError.base64NotCanonical("a one-character final quantum encodes nothing")
        }
        return out
    }

    /// Encodes in the pinned form. Used for round-trip tests, never in a digest.
    public static func encode(_ bytes: [UInt8]) -> String {
        var out = [UInt8]()
        var i = 0
        while i + 2 < bytes.count {
            let n = UInt32(bytes[i]) << 16 | UInt32(bytes[i + 1]) << 8 | UInt32(bytes[i + 2])
            out.append(alphabet[Int(n >> 18 & 63)])
            out.append(alphabet[Int(n >> 12 & 63)])
            out.append(alphabet[Int(n >> 6 & 63)])
            out.append(alphabet[Int(n & 63)])
            i += 3
        }
        let remaining = bytes.count - i
        if remaining == 2 {
            let n = UInt32(bytes[i]) << 16 | UInt32(bytes[i + 1]) << 8
            out.append(alphabet[Int(n >> 18 & 63)])
            out.append(alphabet[Int(n >> 12 & 63)])
            out.append(alphabet[Int(n >> 6 & 63)])
            out.append(UInt8(ascii: "="))
        } else if remaining == 1 {
            let n = UInt32(bytes[i]) << 16
            out.append(alphabet[Int(n >> 18 & 63)])
            out.append(alphabet[Int(n >> 12 & 63)])
            out.append(UInt8(ascii: "="))
            out.append(UInt8(ascii: "="))
        }
        return String(decoding: out, as: UTF8.self)
    }
}
