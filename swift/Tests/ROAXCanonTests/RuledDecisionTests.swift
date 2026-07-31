import XCTest
@testable import ROAXCanon

/// The rulings this library implements, each with a test that fails if the
/// pre-ruling behaviour comes back.
final class RuledDecisionTests: XCTestCase {

    // MARK: D14a - the type-map lookup NORMALIZES

    /// A map declaring only the composed spelling.
    private func kelvinMap() throws -> DisplayPatternTypeMap {
        try DisplayPatternTypeMap(jsonText: """
        {"typeMapVersion":"1.0.0","recordType":"org.roax.corpus.synthetic",
         "schemaVersion":"1.0","entries":[
           {"pattern":"Kelvin","jsonKind":"string","tag":2},
           {"pattern":"é","jsonKind":"string","tag":2},
           {"pattern":"marker","jsonKind":"string","tag":2}]}
        """)
    }

    /// **The discriminating case, both halves.**
    ///
    /// Decision D14 was ruled D14a, NORMALIZE, on 2026-07-30. The reasoning is
    /// what makes it right rather than merely chosen: section 11.2's rule is
    /// "check the bytes you commit, not the bytes you received", and an encoded
    /// KEY segment commits `NFC(key)` under section 5.1, so a raw comparison
    /// decides admissibility on a spelling no root records.
    ///
    /// The test asserts (a) the alternative spelling resolves, and (b) its raw
    /// UTF-8 bytes differ from the declared pattern's - so **any** byte-comparing
    /// matcher must fail closed on it. Together those pin the ruling without
    /// needing a second production resolver to compare against.
    func testTypeMapLookupNormalizesTheKey() throws {
        let map = try kelvinMap()

        // U+212A KELVIN SIGN normalizes to ASCII "K".
        let kelvinSign = "\u{212A}elvin"
        XCTAssertNotEqual(Array(kelvinSign.utf8), Array("Kelvin".utf8),
                          "the two spellings must differ as bytes, or the test proves nothing")
        XCTAssertEqual(NFC.normalize(kelvinSign), "Kelvin")
        XCTAssertEqual(
            try map.resolve(segments: [.key(kelvinSign)], jsonKind: .string), .string,
            "under raw matching this fails closed; under D14a it resolves"
        )

        // The decomposed é, which is the class-19 key site.
        let decomposed = "e\u{0301}"
        XCTAssertNotEqual(Array(decomposed.utf8), Array("é".utf8))
        XCTAssertEqual(try map.resolve(segments: [.key(decomposed)], jsonKind: .string), .string)

        // Normalizing does NOT widen the map: a key whose NFC form is still not
        // a declared transition fails closed.
        XCTAssertThrowsError(try map.resolve(segments: [.key("Kelvinn")], jsonKind: .string))
    }

    /// **Both sides of the comparison normalize, not only the segment key.**
    ///
    /// A published artifact's transition keys are validated NFC at load and a
    /// display-pattern matcher normalizes its pattern token at parse time.
    /// Normalizing only the segment key would leave a decomposed pattern
    /// permanently dead rather than provably redundant.
    func testTypeMapNormalizesThePatternTokenToo() throws {
        let map = try DisplayPatternTypeMap(jsonText: """
        {"typeMapVersion":"1.0.0","recordType":"org.roax.corpus.synthetic",
         "schemaVersion":"1.0","entries":[
           {"pattern":"e\u{0301}","jsonKind":"string","tag":2}]}
        """)
        // The pattern was authored decomposed; a composed segment key still
        // resolves, which is only true if the pattern was normalized at parse.
        XCTAssertEqual(try map.resolve(segments: [.key("é")], jsonKind: .string), .string)
    }

    /// D14a end to end: two records differing only in spelling give ONE root.
    func testNFCKeySpellingsProduceOneRoot() throws {
        let map = try kelvinMap()
        let committer = Committer<SHA256Hash>(resolver: map)
        let identity = RecordIdentity(
            recordType: "org.roax.corpus.synthetic", schemaVersion: "1.0",
            recordId: "urn:uuid:11111111-1111-4111-8111-111111111111",
            issuerId: "did:web:corpus.roax.invalid"
        )
        let context = CommitmentContext(identity: identity)
        let salts = SaltSource.draw(count: 6)

        let composed = try JSONScanner.parse("{\"é\":\"v\",\"marker\":\"m\"}")
        let decomposed = try JSONScanner.parse("{\"e\u{0301}\":\"v\",\"marker\":\"m\"}")

        let a = try committer.commit(record: composed, salts: .positional(salts), context: context)
        let b = try committer.commit(record: decomposed, salts: .positional(salts), context: context)
        XCTAssertEqual(a.root.roaxHex, b.root.roaxHex,
                       "two records that render identically must give one root")
        XCTAssertEqual(a.leafCount, 6)
    }

    // MARK: the five ruled type bindings

    /// The corpus-side synthetic map, which carries the ruled tag semantics.
    private func syntheticMap() throws -> DisplayPatternTypeMap {
        guard let root = CorpusConformanceTests.repoRoot() else {
            throw XCTSkip("no repository root")
        }
        let file = root.appendingPathComponent("corpus/type-maps/org.roax.corpus.synthetic.json")
        let data = try Data(contentsOf: file)
        return try DisplayPatternTypeMap(json: try JSONScanner.parse([UInt8](data)))
    }

    /// Ruling 1: vaccination `dose` is INTEGER, grade Strong.
    ///
    /// The tag half is asserted here through the corpus-side vaccination map,
    /// which is where the ruling is operative. The positive-integer NARROWING
    /// that ruling also carries is deliberately **not** tested here: ruled
    /// decision D13a keeps value-domain validation in a separate, independently
    /// versioned layer, so putting it in this library would merge two layers a
    /// ruling separated. The discriminating values are `0` and the negatives,
    /// and `corpus/tools/run.sh` step 5 owns them.
    func testRuledDoseIsIntegerAndTheNarrowingIsNotThisLayer() throws {
        guard let root = CorpusConformanceTests.repoRoot() else { throw XCTSkip("no repo root") }
        let file = root.appendingPathComponent("corpus/type-maps/sg.gov.moh.vaccination-healthcert.json")
        let map = try DisplayPatternTypeMap(json: try JSONScanner.parse([UInt8](try Data(contentsOf: file))))

        let dose: Path = [
            .key("notarisationMetadata"), .key("signedEuHealthCerts"), .index(0), .key("dose"),
        ]
        XCTAssertEqual(try map.resolve(segments: dose, jsonKind: .number), .integer,
                       "dose is ruled INTEGER (docs/type-maps.md section 1.1, grade Strong)")

        // Ruling 2 of the same section: expiryDateTime is STRING, grade Moderate.
        let expiry: Path = [
            .key("notarisationMetadata"), .key("signedEuHealthCerts"), .index(0), .key("expiryDateTime"),
        ]
        XCTAssertEqual(try map.resolve(segments: expiry, jsonKind: .string), .string)

        // The canonicalization layer accepts `0` and the negatives, because the
        // narrowing lives one layer up. This is the layering being demonstrated,
        // not a gap.
        XCTAssertEqual(try CanonicalNumber.canonicalizeInteger("0"), "0")
        XCTAssertEqual(try CanonicalNumber.canonicalizeInteger("-3"), "-3")
        // A fractional value is refused one layer DOWN, by the section 6.2 grammar.
        XCTAssertThrowsError(try CanonicalNumber.canonicalizeInteger("1.5"))
    }

    /// Ruling 3: FHIR `base64Binary` is BYTES over the **decoded octets**,
    /// grade Strong, with canonical RFC 4648 as an input-admissibility
    /// condition that never becomes the committed value.
    func testRuledBase64BinaryCommitsDecodedOctets() throws {
        let map = try syntheticMap()

        // The same base64 characters at two paths: one bound BYTES, one STRING.
        let bytesPath: Path = [.key("blob"), .key("bytes")]
        let textPath: Path = [.key("blob"), .key("text")]
        XCTAssertEqual(try map.resolve(segments: bytesPath, jsonKind: .string), .bytes)
        XCTAssertEqual(try map.resolve(segments: textPath, jsonKind: .string), .string)

        let base64 = "SGVsbG8sIFJPQVgh"
        let asBytes = try ValueEncoding.encodeRecordValue(tag: .bytes, value: .string(base64))
        let asString = try ValueEncoding.encodeRecordValue(tag: .string, value: .string(base64))
        XCTAssertEqual(asBytes, Array("Hello, ROAX!".utf8), "BYTES commits the value")
        XCTAssertEqual(asString, Array(base64.utf8), "STRING commits the transport spelling")
        XCTAssertNotEqual(asBytes, asString, "the two readings must be separable")

        // Input admissibility: three of these decode to the accepted fixture's
        // octets under a permissive decoder, which is the RFC 4648 section 3.5
        // hazard exhibited rather than described.
        for spelling in ["SGVsbG8sIFJPQVg", "-_8=", "aGl=", "SGVs\nbG8="] {
            XCTAssertThrowsError(
                try ValueEncoding.encodeRecordValue(tag: .bytes, value: .string(spelling)),
                "non-canonical base64 \(spelling.debugDescription) must be refused before decoding"
            ) { error in
                XCTAssertEqual((error as? ROAXError)?.reason, "base64-not-canonical")
            }
        }

        // An observed kind the path has no binding for still fails closed.
        XCTAssertThrowsError(try map.resolve(segments: bytesPath, jsonKind: .number))
    }

    /// Ruling 4: FHIR `Narrative.div` is STRING over the escaped XHTML text,
    /// grade Decisive, **without parsing or reserializing it**.
    func testRuledNarrativeDivIsUnparsedString() throws {
        let map = try syntheticMap()
        let div: Path = [.key("narrative"), .key("div")]
        XCTAssertEqual(try map.resolve(segments: div, jsonKind: .string), .string)

        let xhtml = "<div xmlns=\"http://www.w3.org/1999/xhtml\">a &amp; b &lt;ok&gt;</div>"
        let encoded = try ValueEncoding.encodeRecordValue(tag: .string, value: .string(xhtml))
        XCTAssertEqual(encoded, Array(xhtml.utf8),
                       "the escaped text is committed as written; entities are not resolved")
        XCTAssertTrue(String(decoding: encoded, as: UTF8.self).contains("&amp;"),
                      "resolving &amp; to & would be reserializing the markup")
    }

    /// Ruling 5: FHIR primitive-array null placeholders get **no NULL binding**
    /// and the record is **rejected**, grade Decisive.
    ///
    /// The ruling is expressed as an absence, and an absence needs a vector or
    /// it is unfalsifiable: the map binds `name[*].given[*]` for `string` and
    /// declares nothing for `null`.
    func testRuledPrimitiveArrayNullPlaceholderIsRejected() throws {
        let map = try syntheticMap()
        let given: Path = [.key("name"), .index(0), .key("given"), .index(1)]

        XCTAssertEqual(try map.resolve(segments: given, jsonKind: .string), .string)
        XCTAssertThrowsError(try map.resolve(segments: given, jsonKind: .null)) { error in
            XCTAssertEqual((error as? ROAXError)?.reason, "type-map-fail-closed")
        }

        // And the whole record is refused, which is what the ruling says.
        let committer = Committer<SHA256Hash>(resolver: map)
        let record = try JSONScanner.parse("{\"name\":[{\"given\":[\"Ada\",null]}],\"marker\":\"m\"}")
        XCTAssertThrowsError(try committer.flatten(record))
    }

    // MARK: tags that are registered and selected by nothing

    /// Specification section 6.5: an implementation MUST reject a type map that
    /// binds any path to tag 8 until a profile declares the binding.
    func testBlobRefIsRejectedInAMapAndInAValue() {
        XCTAssertThrowsError(try DisplayPatternTypeMap(jsonText: """
        {"typeMapVersion":"1.0.0","recordType":"org.roax.corpus.synthetic",
         "schemaVersion":"1.0","entries":[{"pattern":"b","jsonKind":"string","tag":8}]}
        """)) { error in
            XCTAssertEqual((error as? ROAXError)?.reason, "blob-ref-not-selectable")
        }
        XCTAssertThrowsError(
            try ValueEncoding.encodeRecordValue(tag: .blobRef, value: .string("x"))
        )
    }

    /// Specification section 7.4: `Poseidon-BN254` is registered and its
    /// parameterization is not pinned, so a v1 verifier's allow-list excludes it
    /// and it fails closed with a stated reason (H3).
    func testPoseidonFailsClosedOnTheAllowList() {
        XCTAssertThrowsError(try HashAlgorithmAllowList.versionOneDefault.check("Poseidon-BN254")) {
            XCTAssertEqual(($0 as? ROAXError)?.reason, "hash-alg-not-allowed")
        }
        XCTAssertNoThrow(try HashAlgorithmAllowList.versionOneDefault.check("SHA-256"))
    }
}
