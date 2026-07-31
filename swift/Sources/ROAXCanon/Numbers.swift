import Foundation

/// Canonical numbers, specification section 6.2.
///
/// **Nothing here goes through a numeric type.** Not `Double`, not `Decimal`,
/// not `Int`. Every operation is over the ASCII digits of the literal, because
/// a number that has passed through a floating-point type is a number the
/// specification refuses (section 6.4) and because `Decimal` is not a way out:
/// it carries 38 significant digits, so a 40-digit integer is corrupted and
/// `0.010` loses the trailing zero FHIR R4 says SHALL be preserved.
/// `swift/FINDINGS.md` findings 1 and 2 record both measurements.
///
/// The grammars are matched by a hand-written scanner rather than by
/// `NSRegularExpression`. That is a deliberate response to the divergence
/// `corpus/README.md` records: Python's `$` also matches before a trailing
/// newline where JavaScript's does not, and `reject-decimal-trailing-newline`
/// exists because one reference implementation accepted `"1.0\n"`. A scanner
/// that consumes to the end of the input has no anchor to get wrong.
public enum CanonicalNumber {

    /// The bound of specification section 6.2, a fixed constant of
    /// `ROAX-CANON/1` that MUST NOT be implementation-chosen.
    public static let digitBound = 1024

    // MARK: integer

    /// Canonical INTEGER: grammar `-?(0|[1-9][0-9]*)`, `-0` normalizes to `0`.
    ///
    /// **The digit bound is applied to INTEGER as well as DECIMAL.**
    /// `corpus/README.md` ambiguity 1 records that specification section 6.2
    /// states the bound under *Canonical decimal* while its own justification
    /// counts "class 2's 40-digit integer" against it, and that both reference
    /// implementations and the Rust library apply it to both. No vector
    /// discriminates. This implementation makes the same choice, so that four
    /// libraries agree on an ambiguity rather than three.
    public static func canonicalizeInteger(_ text: String) throws -> String {
        let s = Array(text.utf8)
        var i = 0
        let negative = i < s.count && s[i] == UInt8(ascii: "-")
        if negative { i += 1 }
        guard i < s.count else { throw ROAXError.integerGrammar(text) }
        let digitsStart = i
        if s[i] == UInt8(ascii: "0") {
            i += 1
        } else if s[i] >= UInt8(ascii: "1") && s[i] <= UInt8(ascii: "9") {
            while i < s.count, isDigit(s[i]) { i += 1 }
        } else {
            throw ROAXError.integerGrammar(text)
        }
        // Consuming to the end is what anchors the grammar: a trailing newline,
        // a space or any other byte leaves i < s.count and fails here.
        guard i == s.count else { throw ROAXError.integerGrammar(text) }

        let digits = String(decoding: s[digitsStart..<i], as: UTF8.self)
        guard digits.count <= digitBound else { throw ROAXError.digitBoundExceeded(text) }
        if digits == "0" { return "0" }              // -0 normalizes to 0
        return negative ? "-" + digits : digits
    }

    // MARK: decimal

    /// Canonical DECIMAL, specification section 6.2.
    ///
    /// Input grammar `-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?`, which is
    /// exactly the FHIR R4 `decimal` pattern. Canonicalization does only two
    /// things: it expands exponent notation into positional notation, and it
    /// drops the sign of a zero-valued magnitude. The digit sequence is never
    /// rounded, extended or truncated to a target precision, so trailing zeros
    /// of the fraction survive and `0.010` is not `0.01`.
    public static func canonicalizeDecimal(_ text: String) throws -> String {
        let s = Array(text.utf8)
        var i = 0

        let negative = i < s.count && s[i] == UInt8(ascii: "-")
        if negative { i += 1 }

        // integer part: 0 | [1-9][0-9]*
        guard i < s.count else { throw ROAXError.decimalGrammar(text) }
        let intStart = i
        if s[i] == UInt8(ascii: "0") {
            i += 1
        } else if s[i] >= UInt8(ascii: "1") && s[i] <= UInt8(ascii: "9") {
            while i < s.count, isDigit(s[i]) { i += 1 }
        } else {
            throw ROAXError.decimalGrammar(text)
        }
        let intDigits = Array(s[intStart..<i])

        // fraction: (\.[0-9]+)?
        var fracDigits = [UInt8]()
        if i < s.count, s[i] == UInt8(ascii: ".") {
            i += 1
            let fracStart = i
            while i < s.count, isDigit(s[i]) { i += 1 }
            guard i > fracStart else { throw ROAXError.decimalGrammar(text) }
            fracDigits = Array(s[fracStart..<i])
        }

        // exponent: ([eE][+-]?[0-9]+)?
        var exponentNegative = false
        var exponentDigits = [UInt8]()
        if i < s.count, s[i] == UInt8(ascii: "e") || s[i] == UInt8(ascii: "E") {
            i += 1
            if i < s.count, s[i] == UInt8(ascii: "+") || s[i] == UInt8(ascii: "-") {
                exponentNegative = s[i] == UInt8(ascii: "-")
                i += 1
            }
            let expStart = i
            while i < s.count, isDigit(s[i]) { i += 1 }
            guard i > expStart else { throw ROAXError.decimalGrammar(text) }
            exponentDigits = Array(s[expStart..<i])
        }

        guard i == s.count else { throw ROAXError.decimalGrammar(text) }

        // The exponent is grammar-unbounded, so it is range-checked before it
        // is used to size anything. Any |e| larger than the digit bound plus
        // the mantissa length necessarily blows the bound, in both directions:
        // a positive exponent grows the integer part and a negative one grows
        // the fraction. Deciding that arithmetically is what keeps `1e999999999`
        // from asking for a gigabyte of zeros before it is rejected.
        let mantissaLength = intDigits.count + fracDigits.count
        var exponent = 0
        if !exponentDigits.isEmpty {
            let significant = exponentDigits.drop(while: { $0 == UInt8(ascii: "0") })
            if significant.count > 10 {
                throw ROAXError.digitBoundExceeded(text)
            }
            for d in significant { exponent = exponent * 10 + Int(d - UInt8(ascii: "0")) }
            if exponent > digitBound + mantissaLength {
                throw ROAXError.digitBoundExceeded(text)
            }
            if exponentNegative { exponent = -exponent }
        }

        // Expansion: shift the point right by `exponent` places.
        var digits = intDigits + fracDigits
        var pointPosition = intDigits.count + exponent

        if pointPosition <= 0 {
            let pad = -pointPosition
            guard pad + digits.count <= digitBound else {
                throw ROAXError.digitBoundExceeded(text)
            }
            digits = [UInt8](repeating: UInt8(ascii: "0"), count: pad) + digits
            pointPosition = 0
        } else if pointPosition >= digits.count {
            guard pointPosition <= digitBound else {
                throw ROAXError.digitBoundExceeded(text)
            }
            digits += [UInt8](repeating: UInt8(ascii: "0"), count: pointPosition - digits.count)
        } else {
            guard digits.count <= digitBound else {
                throw ROAXError.digitBoundExceeded(text)
            }
        }

        // The bound counts the expanded positional form BEFORE the output
        // grammar normalizes it. `corpus/README.md` ambiguity 2 records this
        // choice: it is the literal reading of "the expanded positional form"
        // and the memory-safe one, and under the other reading `0e99999`
        // canonicalizes to `0` where here it is rejected. No vector carries it.
        guard digits.count <= digitBound else { throw ROAXError.digitBoundExceeded(text) }

        var integerPart = Array(digits[0..<pointPosition])
        let fractionPart = Array(digits[pointPosition...])

        // Output grammar `-?(0|[1-9][0-9]*)(\.[0-9]+)?`.
        var stripped = 0
        while stripped < integerPart.count - 1 && integerPart[stripped] == UInt8(ascii: "0") {
            stripped += 1
        }
        integerPart = Array(integerPart[stripped...])
        if integerPart.isEmpty { integerPart = [UInt8(ascii: "0")] }

        var out = String(decoding: integerPart, as: UTF8.self)
        if !fractionPart.isEmpty {
            out += "." + String(decoding: fractionPart, as: UTF8.self)
        }

        // A zero-valued magnitude keeps its fraction digits and loses its sign.
        let isZero = !digits.contains { $0 != UInt8(ascii: "0") }
        if negative && !isZero { out = "-" + out }
        return out
    }

    @inline(__always)
    private static func isDigit(_ c: UInt8) -> Bool {
        c >= UInt8(ascii: "0") && c <= UInt8(ascii: "9")
    }
}
