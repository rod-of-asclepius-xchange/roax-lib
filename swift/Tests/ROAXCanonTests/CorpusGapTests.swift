import XCTest
@testable import ROAXCanon

/// Behaviours the committed corpus does **not** discriminate, pinned here.
///
/// Every case below is a place where two conforming-looking implementations
/// could diverge and no committed vector would notice. With five independent
/// libraries and the corpus as the only enforcement mechanism, that gap is the
/// divergence risk the whole design is built around, so each of these names the
/// gap it fills and says whether closing it needs a corpus change.
final class CorpusGapTests: XCTestCase {

    private func syntheticCommitter() throws -> Committer<SHA256Hash> {
        guard let root = CorpusConformanceTests.repoRoot() else { throw XCTSkip("no repo root") }
        let file = root.appendingPathComponent("corpus/type-maps/org.roax.corpus.synthetic.json")
        let map = try DisplayPatternTypeMap(json: try JSONScanner.parse([UInt8](try Data(contentsOf: file))))
        return Committer<SHA256Hash>(resolver: map, emptyContainerPolicy: .assignedWithoutMapAuthorization)
    }

    private var syntheticIdentity: RecordIdentity {
        RecordIdentity(
            recordType: "org.roax.corpus.synthetic", schemaVersion: "1.0",
            recordId: "urn:uuid:11111111-1111-4111-8111-111111111111",
            issuerId: "did:web:corpus.roax.invalid"
        )
    }

    // MARK: the exact 1024-digit boundary

    /// The corpus rejects `1e1024` and accepts a 40-digit fraction. **Neither
    /// side of the exact boundary is carried**, so an implementation that put
    /// the comparison at `<` instead of `<=`, or that counted the mantissa
    /// rather than the expanded form, would pass the corpus.
    func testDigitBoundIsExactlyAtOneThousandAndTwentyFour() throws {
        // 1e1023 expands to 1 followed by 1023 zeros: exactly 1024 digits.
        let atBound = try CanonicalNumber.canonicalizeDecimal("1e1023")
        XCTAssertEqual(atBound.count, 1024)
        XCTAssertEqual(atBound.first, "1")

        // One more digit is refused, which is the corpus's `1e1024` row.
        XCTAssertThrowsError(try CanonicalNumber.canonicalizeDecimal("1e1024")) {
            XCTAssertEqual(($0 as? ROAXError)?.reason, "digit-bound-exceeded")
        }

        // The bound counts integer and fraction digits TOGETHER, so a value
        // split across the point is measured the same way.
        let split = String(repeating: "9", count: 512) + "." + String(repeating: "9", count: 512)
        XCTAssertEqual(try CanonicalNumber.canonicalizeDecimal(split).count, 1025)  // includes the '.'
        let overSplit = String(repeating: "9", count: 513) + "." + String(repeating: "9", count: 512)
        XCTAssertThrowsError(try CanonicalNumber.canonicalizeDecimal(overSplit))
    }

    /// `corpus/README.md` ambiguity 1: specification section 6.2 states the
    /// bound under *Canonical decimal* while its own justification counts a
    /// 40-digit INTEGER against it. Both reference implementations and the Rust
    /// library apply it to INTEGER too, and no vector discriminates. This
    /// records that this library makes the same choice, so a future reader can
    /// see four libraries agreeing rather than three.
    func testDigitBoundAppliesToIntegerAsWell() {
        XCTAssertNoThrow(try CanonicalNumber.canonicalizeInteger(String(repeating: "9", count: 1024)))
        XCTAssertThrowsError(try CanonicalNumber.canonicalizeInteger(String(repeating: "9", count: 1025))) {
            XCTAssertEqual(($0 as? ROAXError)?.reason, "digit-bound-exceeded")
        }
    }

    /// `corpus/README.md` ambiguity 2: what the bound counts. "The expanded
    /// positional form" is read here as the padded form *before* the output
    /// grammar normalizes it, which is the literal reading and the memory-safe
    /// one. Under the other reading `0e99999` canonicalizes to `0`; under this
    /// one it is rejected. **No vector carries `0e99999`.**
    func testAmbiguityTwoIsResolvedTowardsTheLiteralReading() {
        XCTAssertThrowsError(try CanonicalNumber.canonicalizeDecimal("0e99999")) {
            XCTAssertEqual(($0 as? ROAXError)?.reason, "digit-bound-exceeded")
        }
        // Small zero exponents still normalize, so the reading does not
        // over-reject: `0e5` is a committed vector and stays `0`.
        XCTAssertEqual(try CanonicalNumber.canonicalizeDecimal("0e5"), "0")
    }

    /// **A grammar-legal exponent must be rejected without being materialized.**
    ///
    /// The input grammar admits `1e999999999`, whose expansion is a gigabyte of
    /// zeros. An implementation that expands first and measures afterwards is
    /// correct by the specification and trivially denial-of-serviceable. No
    /// corpus vector goes past `1.4e+9999`, which expands to only ten thousand
    /// digits, so the corpus cannot tell the two apart.
    func testEnormousExponentIsRejectedArithmeticallyNotByExpanding() {
        let started = Date()
        for input in ["1e999999999", "1e-999999999", "1.5e99999999999999999999", "-2e2000000000"] {
            XCTAssertThrowsError(try CanonicalNumber.canonicalizeDecimal(input)) {
                XCTAssertEqual(($0 as? ROAXError)?.reason, "digit-bound-exceeded")
            }
        }
        XCTAssertLessThan(Date().timeIntervalSince(started), 1.0,
                          "these rejections must be arithmetic, not the result of building the digits")
    }

    // MARK: NFC-colliding siblings, ambiguity 6

    /// `corpus/README.md` ambiguity 6, recorded rather than decided: sibling
    /// keys that differ raw but agree under NFC, whose descendant leaf paths
    /// stay distinct. Specification sections 3.2 and 3.3 require raw map keys to
    /// be unique and section 5 normalizes each KEY segment, so this shape has
    /// neither a duplicate raw key nor a duplicate complete encoded leaf path.
    ///
    /// **This library accepts it, which is what the Rust implementation does.**
    /// No committed vector distinguishes acceptance from rejecting every
    /// intermediate-key collision, so this test exists to make the reading
    /// visible and to keep four libraries aligned on it.
    func testNFCCollidingSiblingsWithDisjointDescendantsAreAccepted() throws {
        let committer = try syntheticCommitter()
        // "a" composed-é and "a" decomposed-é, with disjoint children.
        let text = "{\"\u{00e9}\":{\"a\":\"1\"},\"e\u{0301}\":{\"b\":\"2\"},\"marker\":\"m\"}"
        let record = try JSONScanner.parse(text)

        // Distinct raw keys, so the section 3.2 duplicate rule does not fire.
        guard case .object(let members) = record else { return XCTFail("not an object") }
        XCTAssertEqual(members.count, 3)

        let map = try DisplayPatternTypeMap(jsonText: """
        {"typeMapVersion":"1.0.0","recordType":"org.roax.corpus.synthetic","schemaVersion":"1.0",
         "entries":[{"pattern":"é.**","jsonKind":"string","tag":2},
                    {"pattern":"marker","jsonKind":"string","tag":2}]}
        """)
        let c = Committer<SHA256Hash>(resolver: map)
        let leaves = try c.flatten(record)
        XCTAssertEqual(leaves.count, 3)

        // The two intermediate paths encode identically, but the complete leaf
        // paths do not, which is exactly why the shape is not a duplicate.
        let encoded = Set(leaves.map { PathEncoding.encode($0.segments).roaxHex })
        XCTAssertEqual(encoded.count, 3)
        _ = committer
    }

    /// The other side of the same rule: when the collision reaches a **complete**
    /// leaf path, the record is rejected. Nothing in the corpus carries this
    /// either, and without it the section 9 claim that "paths are unique by
    /// construction" would be an assumption rather than a property.
    func testNFCCollidingCompleteLeafPathIsRejected() throws {
        let map = try DisplayPatternTypeMap(jsonText: """
        {"typeMapVersion":"1.0.0","recordType":"org.roax.corpus.synthetic","schemaVersion":"1.0",
         "entries":[{"pattern":"é.**","jsonKind":"string","tag":2},
                    {"pattern":"marker","jsonKind":"string","tag":2}]}
        """)
        let c = Committer<SHA256Hash>(resolver: map)
        let record = try JSONScanner.parse(
            "{\"\u{00e9}\":{\"x\":\"1\"},\"e\u{0301}\":{\"x\":\"2\"},\"marker\":\"m\"}"
        )
        XCTAssertThrowsError(
            try c.commit(record: record, salts: .positional(SaltSource.draw(count: 8)),
                         context: CommitmentContext(identity: syntheticIdentity))
        ) { error in
            XCTAssertEqual((error as? ROAXError)?.reason, "duplicate-leaf-path")
        }
    }

    // MARK: the display path is never hashed

    /// Specification section 5.2 forbids reconstructing an encoded path by
    /// parsing a display one. The corpus pins the nested-versus-dotted pair;
    /// **this pins the index case**, which is the one a display-parsing
    /// implementation would collapse.
    func testDistinctPathsThatShareADisplayStringEncodeDifferently() {
        let structured: Path = [.key("a"), .index(0)]
        let literal: Path = [.key("a[0]")]
        XCTAssertEqual(PathEncoding.display(structured), "a[0]")
        XCTAssertEqual(PathEncoding.display(literal), "a[0]")
        XCTAssertNotEqual(
            PathEncoding.encode(structured).roaxHex,
            PathEncoding.encode(literal).roaxHex,
            "an implementation that hashed the display path would collapse these two"
        )

        // And the empty key is a real segment, distinct from an absent one,
        // because the segment count differs (specification section 5).
        XCTAssertEqual(PathEncoding.encode([.key("")]).roaxHex, "0000000101" + "00000000")
        XCTAssertNotEqual(
            PathEncoding.encode([.key("")]).roaxHex,
            PathEncoding.encode([]).roaxHex
        )
    }

    /// Specification section 5: an index at or beyond 2^32 MUST error rather
    /// than truncate. The corpus carries the rejection through the path encoder;
    /// this also pins that `UInt32.max` itself is accepted, which is the
    /// off-by-one a `<` versus `<=` slip would break.
    func testIndexBoundIsExclusiveAtTwoToTheThirtyTwo() throws {
        XCTAssertNoThrow(try PathSegment.index(checking: UInt64(UInt32.max)))
        for bad: UInt64 in [4_294_967_296, 4_294_967_300] {
            XCTAssertThrowsError(try PathSegment.index(checking: bad)) {
                XCTAssertEqual(($0 as? ROAXError)?.reason, "index-out-of-32-bit-range")
            }
        }
    }

    // MARK: the class-9 gap - a forged tree size through full verification

    /// **The stale class-9 row, demonstrated as a library-local regression.**
    ///
    /// `corpus/README.md` records that no committed `negativeProof` row has
    /// attack `forged-tree-size`, and that the carrier cannot express one:
    /// those rows carry only a supplied `leafHash`, not the path, tag, value and
    /// salt needed to drive the full disclosed-copy verification specification
    /// section 10 step 2 requires. So this reproduces both halves of the
    /// section 11.1 measurement.
    ///
    /// This does **not** close the corpus gap. `corpus/README.md` says plainly
    /// that an implementation-specific regression may demonstrate the defence
    /// and does not make the missing release gate complete. It is recorded in
    /// `swift/FINDINGS.md` finding 6 as a corpus item, not as a library item.
    func testForgedTreeSizeVerifiesBareButIsRefusedByFullVerification() throws {
        // An 8-leaf tree of arbitrary leaf hashes.
        let leaves = (0..<8).map { i in SHA256Hash.hash(Array("leaf-\(i)".utf8)) }
        let root = MerkleTree.root(leaves, hash: SHA256Hash.self)

        // The internal node MTH(L[0:4]).
        let internalNode = MerkleTree.root(Array(leaves[0..<4]), hash: SHA256Hash.self)
        let rightHalf = MerkleTree.root(Array(leaves[4..<8]), hash: SHA256Hash.self)

        // Half one: with a FORGED tree size of 2, the bare RFC 9162 fold
        // accepts the internal node as the leaf at index 0.
        XCTAssertTrue(
            MerkleTree.verifyInclusion(
                leafHash: internalNode, index: 0, treeSize: 2,
                auditPath: [rightHalf], root: root, hash: SHA256Hash.self
            ),
            "specification section 11.1's measurement no longer reproduces"
        )

        // Half two: with the honest tree size it fails, which is why a RANDOM
        // wrong leafCount is usually caught and a CHOSEN one is not.
        XCTAssertFalse(
            MerkleTree.verifyInclusion(
                leafHash: internalNode, index: 0, treeSize: 8,
                auditPath: [rightHalf], root: root, hash: SHA256Hash.self
            )
        )

        // Half three, the defence: a conforming verifier never ACCEPTS a leaf
        // hash, it recomputes one, and every recomputed leaf hash is
        // 0x00-domained by construction. So no (path, tag, value, salt) the
        // verifier will build can equal an internal node except by defeating
        // second-preimage resistance.
        let recomputed = try LeafConstruction.leafHash(
            segments: [.key("anything")], tag: .string,
            encodedValue: Array("anything".utf8),
            salt: [UInt8](repeating: 7, count: 16), hash: SHA256Hash.self
        )
        XCTAssertNotEqual(recomputed, internalNode)
        // The domain bytes are what separate them: 0x00 for a leaf, 0x01 for a node.
        let leafPreimage = try LeafConstruction.preimage(
            encodedPath: PathEncoding.encode([.key("anything")]), tag: .string,
            encodedValue: Array("anything".utf8),
            salt: [UInt8](repeating: 7, count: 16), hashAlg: "SHA-256"
        )
        XCTAssertEqual(leafPreimage.first, 0x00)
    }

    // MARK: the library's own round trip

    /// Issue, disclose and verify through this library's API.
    ///
    /// The corpus only ever verifies envelopes someone else built, so nothing in
    /// it exercises the issuance side end to end. This does, including that a
    /// disclosed copy carries the salt of every leaf it reveals and of no other.
    func testIssueDiscloseVerifyRoundTrip() throws {
        let committer = try syntheticCommitter()
        let record = try JSONScanner.parse("{\"marker\":\"m\",\"flag\":true}")
        let commitment = try committer.commit(
            record: record, context: CommitmentContext(identity: syntheticIdentity)
        )
        XCTAssertEqual(commitment.leafCount, 6, "4 reserved leaves plus 2 record leaves")

        // Every salt is distinct: independent draws, not a derivation.
        XCTAssertEqual(Set(commitment.leaves.map { $0.salt.roaxHex }).count, 6)

        // A disclosure of the floor plus one field.
        let disclosed = try commitment.disclose(
            paths: [
                [.key("roax.recordType")], [.key("roax.schemaVersion")],
                [.key("roax.recordId")], [.key("roax.issuer.id")],
                [.key("marker")],
            ],
            hash: SHA256Hash.self
        )
        XCTAssertEqual(disclosed.count, 5)

        // Every proof verifies against the genuine root, with the leaf hash
        // recomputed rather than trusted.
        for leaf in disclosed {
            let source = commitment.leaves[leaf.index]
            XCTAssertTrue(MerkleTree.verifyInclusion(
                leafHash: source.hash, index: leaf.index, treeSize: commitment.leafCount,
                auditPath: leaf.auditPath, root: commitment.root, hash: SHA256Hash.self
            ), "the proof for \(source.displayPath) does not verify")
        }

        // The withheld leaf's salt appears nowhere in the disclosure, which is
        // the property section 10.1 says is the whole ballgame.
        let withheld = commitment.leaves.first { $0.displayPath == "flag" }!
        XCTAssertFalse(disclosed.map { $0.salt.roaxHex }.contains(withheld.salt.roaxHex))
    }

    /// A record contributing zero leaves of its own is rejected at issuance
    /// rather than anchored (specification sections 3.3 and 9.1).
    ///
    /// **This is the one MUST in the specification that can never fire from a
    /// JSON record**, and the reason is worth pinning: `{}` is an empty map, so
    /// section 3.3's flattener emits one EMPTY_OBJECT leaf for it. Three
    /// independent implementations reported the same thing before this one. The
    /// check is kept because a caller reaching it has a defect worth failing on.
    func testZeroLeafRecordIsRejectedButIsUnreachableFromJSON() throws {
        let map = try DisplayPatternTypeMap(jsonText: """
        {"typeMapVersion":"1.0.0","recordType":"org.roax.corpus.synthetic","schemaVersion":"1.0",
         "entries":[{"pattern":"","jsonKind":"object","tag":7}]}
        """)
        let c = Committer<SHA256Hash>(resolver: map, emptyContainerPolicy: .assignedWithoutMapAuthorization)
        // `{}` yields ONE leaf, not zero, so the MUST cannot fire here.
        XCTAssertEqual(try c.flatten(try JSONScanner.parse("{}")).count, 1)
        XCTAssertEqual(try c.flatten(try JSONScanner.parse("[]")).count, 1)
    }

    // MARK: the reserved-namespace guard

    /// All four cases of specification section 11.2, including the two an
    /// earlier draft got wrong.
    func testReservedNamespaceGuardCoversTheFourCases() {
        // Rejected: the exact reserved name, and any `roax.` prefix squat.
        for key in ["roax.recordType", "roax.anythingElse", "roax.recordIdX"] {
            XCTAssertThrowsError(try ReservedNamespace.check([.key(key)])) {
                XCTAssertEqual(($0 as? ROAXError)?.reason, "reserved-namespace")
            }
        }
        // Accepted: no dot, so it collides with nothing. Both reverse an
        // earlier draft written against a string-path model.
        XCTAssertNoThrow(try ReservedNamespace.check([.key("roax")]))
        XCTAssertNoThrow(try ReservedNamespace.check([.key("roaxX")]))

        // The guard checks the FIRST segment only: a nested `roax.foo` differs
        // from every reserved path in segment count, so rejecting it would be
        // over-broad. Applying the check to every segment is the most likely
        // over-implementation.
        XCTAssertNoThrow(try ReservedNamespace.check([.key("a"), .key("roax.foo")]))
        XCTAssertNoThrow(try ReservedNamespace.check([.index(0), .key("roax.foo")]))
    }
}
