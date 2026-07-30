import XCTest
@testable import ROAXCanon

/// The traps this language sets, each asserted against the platform behaviour
/// rather than against a belief about it.
///
/// Every test here pairs a measurement of what Foundation actually does with an
/// assertion that this library does something else. That pairing is the point:
/// a test that only checked our own output would still pass if someone later
/// "simplified" the code back onto the Foundation API, because the corpus does
/// not reach most of these cases.
final class SwiftPlatformTrapTests: XCTestCase {

    // MARK: finding 1 - JSONSerialization destroys numeric literals

    /// Specification section 6.4 names Swift as the sharp edge and calls the
    /// failure inconsistent, which is worse than lossy. Both halves are measured
    /// here: Foundation mangles the small literals and preserves a large one.
    func testJSONSerializationDestroysLiteralsAndOursDoesNot() throws {
        let cases: [(literal: String, foundation: String)] = [
            ("0.010", "0.01"),
            ("1.50", "1.5"),
            ("2.0", "2"),
            ("1e2", "100"),
            ("0.1", "0.10000000000000001"),
        ]
        for c in cases {
            let text = "{\"a\":\(c.literal)}"
            let object = try JSONSerialization.jsonObject(with: Data(text.utf8))
            let reserialized = String(
                decoding: try JSONSerialization.data(withJSONObject: object), as: UTF8.self
            )
            XCTAssertEqual(reserialized, "{\"a\":\(c.foundation)}",
                           "Foundation's behaviour for \(c.literal) changed; finding 1 needs re-measuring")

            // The scanner keeps the literal verbatim.
            guard case .object(let members) = try JSONScanner.parse(text),
                  case .number(let kept) = members[0].value
            else { return XCTFail("scanner did not produce a number for \(c.literal)") }
            XCTAssertEqual(kept, c.literal)
        }

        // The inconsistency: a magnitude above the threshold DOES survive, so
        // every small-number test anyone writes passes.
        let large = "{\"a\":1234567890123456789.1}"
        let object = try JSONSerialization.jsonObject(with: Data(large.utf8))
        XCTAssertEqual(
            String(decoding: try JSONSerialization.data(withJSONObject: object), as: UTF8.self),
            large,
            "Foundation no longer preserves the large literal; the inconsistency in finding 1 has changed"
        )
    }

    /// `JSONSerialization` silently accepts a duplicate member, so a parser
    /// built on it cannot raise `duplicate-key` at all - a second, independent
    /// reason the scanner has to be hand-written that specification section 6.4
    /// does not name.
    func testJSONSerializationAcceptsDuplicateKeysAndOursRejects() throws {
        let text = "{\"a\":\"x\",\"a\":\"y\"}"
        XCTAssertNoThrow(try JSONSerialization.jsonObject(with: Data(text.utf8)),
                         "Foundation started rejecting duplicate keys; finding 1 needs re-measuring")
        XCTAssertThrowsError(try JSONScanner.parse(text)) { error in
            XCTAssertEqual((error as? ROAXError)?.reason, "duplicate-key")
        }
    }

    // MARK: finding 2 - Decimal cannot carry a FHIR decimal

    /// `Decimal` is base-10, which makes it look like the right type. It carries
    /// 38 significant digits and drops trailing zeros, so it fails the corpus in
    /// both directions.
    func testDecimalCannotCarryTheCorpusAndOursCan() throws {
        // Class 1 carries a 40-digit integer part with a 40-digit fraction.
        let long = String(repeating: "9", count: 40) + "." + String(repeating: "1", count: 40)
        let viaDecimal = Decimal(string: long).map { "\($0)" }
        XCTAssertNotEqual(viaDecimal, long,
                          "Decimal grew past 38 significant digits; finding 2 needs re-measuring")
        XCTAssertEqual(try CanonicalNumber.canonicalizeDecimal(long), long)

        // FHIR R4 SHALL: 0.010 is not 0.01. Decimal disagrees.
        XCTAssertEqual(Decimal(string: "0.010").map { "\($0)" }, "0.01")
        XCTAssertEqual(try CanonicalNumber.canonicalizeDecimal("0.010"), "0.010")

        // A 50-digit integer is corrupted rather than rejected, which is the
        // dangerous shape: it returns a value.
        let fifty = "12345678901234567890123456789012345678901234567890"
        XCTAssertNotEqual(Decimal(string: fifty).map { "\($0)" }, fifty)
        XCTAssertEqual(try CanonicalNumber.canonicalizeInteger(fifty), fifty)
    }

    // MARK: finding 3 - Foundation's base64 accepts a non-canonical quantum

    /// RFC 4648 section 3.5 identifies the non-zero-unused-bits case, and
    /// specification section 6.3 requires rejecting it by name. Foundation
    /// rejects the other three spellings, so a reader who spot-checks would
    /// conclude `Data(base64Encoded:)` is sufficient.
    func testFoundationBase64AcceptsNonZeroPadBitsAndOursRejects() throws {
        XCTAssertNotNil(Data(base64Encoded: "aGl="),
                        "Foundation started rejecting non-zero pad bits; finding 3 needs re-measuring")
        XCTAssertThrowsError(try CanonicalBase64.decode("aGl=")) { error in
            XCTAssertEqual((error as? ROAXError)?.reason, "base64-not-canonical")
        }

        // The three Foundation does reject, rejected here too and for the same
        // stated reason.
        for spelling in ["SGVsbG8sIFJPQVg", "-_8=", "SGVs\nbG8="] {
            XCTAssertNil(Data(base64Encoded: spelling))
            XCTAssertThrowsError(try CanonicalBase64.decode(spelling))
        }

        // And the canonical form still decodes.
        XCTAssertEqual(
            try CanonicalBase64.decode("SGVsbG8sIFJPQVgh"),
            Array("Hello, ROAX!".utf8)
        )
    }

    // MARK: finding 4 - Swift String substitutes an unpaired surrogate

    /// Specification section 3.2 rejects unpaired surrogates at the input
    /// boundary. On this platform the rejection has to happen before a `String`
    /// exists, because constructing one replaces the surrogate with U+FFFD and
    /// turns an input the specification refuses into one that commits.
    func testUnpairedSurrogateIsRejectedBeforeStringConstruction() throws {
        let units: [UInt16] = [0x0041, 0xD800, 0x0042]
        let viaSwift = String(decoding: units, as: UTF16.self)
        XCTAssertEqual(Array(viaSwift.unicodeScalars).map(\.value), [0x41, 0xFFFD, 0x42],
                       "Swift stopped substituting U+FFFD; finding 4 needs re-measuring")

        XCTAssertThrowsError(try UTF16Input.string(fromCodeUnits: units)) { error in
            XCTAssertEqual((error as? ROAXError)?.reason, "unpaired-surrogate")
        }
        XCTAssertThrowsError(try UTF16Input.string(fromCodeUnits: [0xDC00])) { error in
            XCTAssertEqual((error as? ROAXError)?.reason, "unpaired-surrogate")
        }
        // A well-formed pair is not rejected.
        XCTAssertEqual(try UTF16Input.string(fromCodeUnits: [0xD83D, 0xDE00]), "\u{1F600}")
    }

    /// The same rejection through the JSON escape path, which is where a record
    /// actually carries one.
    func testUnpairedSurrogateEscapeInJSONIsRejected() {
        XCTAssertThrowsError(try JSONScanner.parse("{\"a\":\"\\uD800\"}")) { error in
            XCTAssertEqual((error as? ROAXError)?.reason, "unpaired-surrogate")
        }
        XCTAssertNoThrow(try JSONScanner.parse("{\"a\":\"\\uD83D\\uDE00\"}"))
    }

    // MARK: finding 7 - Swift String equality is canonical equivalence

    /// **The sharpest trap in this language, and the one no other target
    /// language sets.**
    ///
    /// Swift compares `String` by canonical equivalence rather than by bytes,
    /// and `Hashable` agrees. So the obvious spelling of specification section
    /// 3.2's duplicate-key check - a `Set<String>` - silently rejects a record
    /// whose two member names are distinct raw keys that agree under NFC. That
    /// is the shape `corpus/README.md` ambiguity 6 turns on, and the Rust
    /// implementation accepts it, so the language feature would have decided an
    /// open ambiguity in the opposite direction from the rest of the family.
    ///
    /// No committed vector reaches this, in either direction.
    func testStringEqualityIsCanonicalEquivalenceAndDuplicateDetectionIsNot() throws {
        let composed = "\u{00e9}"
        let decomposed = "e\u{0301}"

        // The language's position, measured.
        XCTAssertEqual(composed, decomposed, "Swift String == is canonical equivalence")
        XCTAssertEqual(Set([composed, decomposed]).count, 1, "and Hashable agrees")
        XCTAssertNotEqual(Array(composed.utf8), Array(decomposed.utf8), "while the bytes differ")

        // The duplicate check compares RAW bytes, so this record is accepted.
        let text = "{\"\(composed)\":\"1\",\"\(decomposed)\":\"2\"}"
        guard case .object(let members) = try JSONScanner.parse(text) else {
            return XCTFail("scanner rejected distinct raw keys")
        }
        XCTAssertEqual(members.count, 2)

        // A genuine duplicate - the same bytes twice - is still rejected.
        XCTAssertThrowsError(try JSONScanner.parse("{\"\(composed)\":\"1\",\"\(composed)\":\"2\"}")) {
            XCTAssertEqual(($0 as? ROAXError)?.reason, "duplicate-key")
        }
    }

    /// One layer down, the same language feature is what we want, and the two
    /// readings coincide rather than conflict.
    ///
    /// `PathSegment`'s derived equality is canonical equivalence, and
    /// `encodePath` commits `NFC(key)`, so two canonically equivalent keys
    /// always encode identically. The trap is not that the feature is wrong; it
    /// is that it is right in one place and wrong in the other.
    func testPathSegmentEqualityAgreesWithEncodedPathEquality() {
        let a: PathSegment = .key("\u{00e9}")
        let b: PathSegment = .key("e\u{0301}")
        XCTAssertEqual(a, b)
        XCTAssertEqual(PathEncoding.encode([a]).roaxHex, PathEncoding.encode([b]).roaxHex)
    }

    // MARK: the two SHA-256 implementations agree

    /// CryptoKit and the in-tree block are cross-checked rather than trusted.
    func testReferenceSHA256AgreesWithCryptoKit() {
        // NIST FIPS 180-4 known answers.
        XCTAssertEqual(
            ReferenceSHA256.hash([]).roaxHex,
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
        XCTAssertEqual(
            ReferenceSHA256.hash(Array("abc".utf8)).roaxHex,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )
        // Across every block-boundary length, including multi-block messages.
        for length in [0, 1, 55, 56, 57, 63, 64, 65, 119, 120, 127, 128, 1000] {
            let message = (0..<length).map { UInt8($0 % 251) }
            XCTAssertEqual(
                ReferenceSHA256.hash(message).roaxHex,
                SHA256Hash.hash(message).roaxHex,
                "the two SHA-256 implementations disagree at length \(length)"
            )
        }
    }
}
