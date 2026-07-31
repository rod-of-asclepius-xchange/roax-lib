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

    /// **A disclosure this library produces must verify through this library's
    /// own verifier**, and nothing in the corpus can check that.
    ///
    /// Every committed envelope fixture was built by something else, so the
    /// corpus only ever exercises the verifier against a third party's bytes.
    /// The producing side is therefore completely uncovered: an implementation
    /// whose `disclose` emitted a leaf without its carrier value, or with the
    /// wrong carrier for its tag, would pass all 488 vectors and be unable to
    /// verify a single envelope it had itself issued.
    ///
    /// This test drives the real `EnvelopeVerifier`, including the outer-identity
    /// binding and the minimum-disclosure floor, over an envelope assembled from
    /// `Commitment.disclose`.
    func testADisclosureThisLibraryProducesVerifiesThroughItsOwnVerifier() throws {
        let committer = try syntheticCommitter()
        // One leaf per carrier form the envelope pins, so a wrong carrier for
        // any tag fails here rather than only for STRING.
        let record = try JSONScanner.parse("""
        {"marker":"m","flag":true,
         "counts":{"integer":5,"decimal":0.010,"text":"5"},
         "blob":{"bytes":"SGVsbG8sIFJPQVgh","text":"t"}}
        """)
        let commitment = try committer.commit(
            record: record, context: CommitmentContext(identity: syntheticIdentity)
        )

        let paths: [Path] = [
            [.key("roax.recordType")], [.key("roax.schemaVersion")],
            [.key("roax.recordId")], [.key("roax.issuer.id")],
            [.key("marker")], [.key("flag")],
            [.key("counts"), .key("integer")], [.key("counts"), .key("decimal")],
            [.key("blob"), .key("bytes")],
        ]
        let disclosed = try commitment.disclose(paths: paths, hash: SHA256Hash.self)

        // Every carrier is populated; a nil value on a tag that requires one is
        // precisely the bug this test exists for.
        for leaf in disclosed where ![.null, .emptyArray, .emptyObject].contains(leaf.tag) {
            XCTAssertNotNil(leaf.value, "leaf \(PathEncoding.display(leaf.segments)) carries no value")
        }
        // And the carriers are the tag's, not the record's: BYTES is hex here
        // even though the record spelled it base64.
        let bytesLeaf = disclosed.first { $0.tag == .bytes }!
        XCTAssertEqual(bytesLeaf.value, .string("48656c6c6f2c20524f415821"))
        // DECIMAL keeps its trailing zero through the round trip.
        let decimalLeaf = disclosed.first { $0.tag == .decimal }!
        XCTAssertEqual(decimalLeaf.value, .string("0.010"))

        let envelope = Envelope(
            recordType: syntheticIdentity.recordType,
            schemaVersion: syntheticIdentity.schemaVersion,
            recordId: syntheticIdentity.recordId,
            issuerId: syntheticIdentity.issuerId,
            root: commitment.root,
            leafCount: commitment.leafCount,
            disclosedLeaves: disclosed
        )
        let verifier = EnvelopeVerifier<SHA256Hash>()
        XCTAssertNoThrow(try verifier.verify(envelope),
                         "this library cannot verify an envelope it issued itself")

        // And the verifier is not simply accepting everything: dropping a
        // floor path is refused, and so is a tampered value.
        let short = Envelope(
            recordType: syntheticIdentity.recordType,
            schemaVersion: syntheticIdentity.schemaVersion,
            recordId: syntheticIdentity.recordId,
            issuerId: syntheticIdentity.issuerId,
            root: commitment.root, leafCount: commitment.leafCount,
            disclosedLeaves: disclosed.filter {
                $0.segments != [.key("roax.recordId")]
            }
        )
        XCTAssertThrowsError(try verifier.verify(short)) {
            XCTAssertEqual(($0 as? ROAXError)?.reason, "outer-identity-mismatch")
        }

        let tampered = disclosed.map { leaf -> DisclosedLeaf in
            guard leaf.segments == [.key("marker")] else { return leaf }
            return DisclosedLeaf(
                segments: leaf.segments, index: leaf.index, tag: leaf.tag,
                value: .string("tampered"), salt: leaf.salt, auditPath: leaf.auditPath
            )
        }
        XCTAssertThrowsError(try verifier.verify(Envelope(
            recordType: syntheticIdentity.recordType,
            schemaVersion: syntheticIdentity.schemaVersion,
            recordId: syntheticIdentity.recordId,
            issuerId: syntheticIdentity.issuerId,
            root: commitment.root, leafCount: commitment.leafCount,
            disclosedLeaves: tampered
        ))) {
            XCTAssertEqual(($0 as? ROAXError)?.reason, "inclusion-proof-failed")
        }
    }

    // MARK: the type-map binding, which no committed vector can reach

    /// **The presenter must not be able to decide whether a check runs.**
    ///
    /// Every committed envelope fixture is `schemas/envelope-1.0.json` and none
    /// carries a `typeMap` member, so the corpus cannot reach any of this. The
    /// hazard is specific: `roax.typeMap.id` is mandatory to disclose *by
    /// arithmetic* (`docs/profiles/*.md` section 4) because it selects and
    /// authenticates the exact map, and type-map selection is what decides how
    /// a field is typed and canonicalized. A binding gated on the outer,
    /// holder-supplied `typeMap` member is switched off by the party it
    /// constrains.
    func testTypeMapIdBindingIsDrivenByTheCommittedLeafNotTheOuterMember() throws {
        let committer = try syntheticCommitter()
        let identity = RecordIdentity(
            recordType: syntheticIdentity.recordType,
            schemaVersion: syntheticIdentity.schemaVersion,
            recordId: syntheticIdentity.recordId,
            issuerId: syntheticIdentity.issuerId,
            typeMapId: "urn:roax:type-map:org.roax.corpus.synthetic:1.0.0"
        )
        let record = try JSONScanner.parse("{\"marker\":\"m\",\"flag\":true}")
        let commitment = try committer.commit(
            record: record, context: CommitmentContext(identity: identity)
        )
        XCTAssertEqual(commitment.leafCount, 7, "5 reserved leaves plus 2 record leaves")

        let reserved: [Path] = [
            [.key("roax.recordType")], [.key("roax.schemaVersion")],
            [.key("roax.recordId")], [.key("roax.issuer.id")],
            [.key("roax.typeMap.id")],
        ]
        let full = try commitment.disclose(paths: reserved + [[.key("marker")]], hash: SHA256Hash.self)

        func envelope(_ leaves: [DisclosedLeaf], typeMapId: String?) -> Envelope {
            Envelope(
                recordType: identity.recordType, schemaVersion: identity.schemaVersion,
                recordId: identity.recordId, issuerId: identity.issuerId,
                typeMapId: typeMapId,
                root: commitment.root, leafCount: commitment.leafCount,
                disclosedLeaves: leaves
            )
        }
        let verifier = EnvelopeVerifier<SHA256Hash>()
        let withoutLeaf = full.filter { $0.segments != [.key("roax.typeMap.id")] }

        // A matched pair verifies, so the tightening did not simply close the
        // door on every 2.0-shaped copy.
        XCTAssertNoThrow(try verifier.verify(envelope(full, typeMapId: identity.typeMapId)))

        // The attack the outer gate allowed: the leaf is committed and
        // disclosed, and deleting the outer member used to skip the binding
        // entirely. Absence is now the same failure as disagreement.
        XCTAssertThrowsError(try verifier.verify(envelope(full, typeMapId: nil))) {
            XCTAssertEqual(($0 as? ROAXError)?.reason, "outer-identity-mismatch")
        }
        // The other direction, which was already refused and must stay so.
        XCTAssertThrowsError(try verifier.verify(envelope(withoutLeaf, typeMapId: identity.typeMapId))) {
            XCTAssertEqual(($0 as? ROAXError)?.reason, "outer-identity-mismatch")
        }
        XCTAssertThrowsError(try verifier.verify(envelope(full, typeMapId: "urn:roax:type-map:other:9.9.9"))) {
            XCTAssertEqual(($0 as? ROAXError)?.reason, "outer-identity-mismatch")
        }

        // **The limit, stated rather than hidden.** Dropping BOTH leaves an
        // envelope byte-indistinguishable from a legitimate 1.0 copy: the only
        // signal a fifth reserved leaf was committed is `leafCount`, which
        // specification section 11.1 measured is not authenticated in a
        // disclosed copy. A default verifier accepts it.
        XCTAssertNoThrow(try verifier.verify(envelope(withoutLeaf, typeMapId: nil)))

        // So the last case is the VERIFIER's decision, never the presenter's.
        let requiring = EnvelopeVerifier<SHA256Hash>(typeMapBinding: .required)
        XCTAssertThrowsError(try requiring.verify(envelope(withoutLeaf, typeMapId: nil))) {
            XCTAssertEqual(($0 as? ROAXError)?.reason, "outer-identity-mismatch")
        }
        XCTAssertNoThrow(try requiring.verify(envelope(full, typeMapId: identity.typeMapId)))
    }

    // MARK: a known member with the wrong JSON shape

    /// A present-but-wrong-typed known member is `malformed-json`, never a
    /// silent absence.
    ///
    /// `Envelope.parse` enforces the `additionalProperties: false` closure of
    /// `schemas/envelope-*.json` itself rather than deferring to a validator
    /// this package does not ship, so it owns the shapes too. Reading a
    /// wrong-typed member as absent turned off the guards keyed on presence:
    /// `"salts": {}` beside a `disclosure` parsed with `salts == nil`, so the
    /// section 10.1 salt-leak prohibition never fired and a copy carrying salts
    /// for withheld leaves verified. No committed fixture carries a wrong-typed
    /// member, so nothing in the corpus notices either way.
    func testWrongTypedKnownEnvelopeMemberIsMalformedRatherThanAbsent() throws {
        func text(_ extra: String) -> String {
            """
            {"canon":"ROAX-CANON/1","hashAlg":"SHA-256",
             "recordType":"org.roax.corpus.synthetic","schemaVersion":"1.0",
             "recordId":"urn:uuid:11111111-1111-4111-8111-111111111111",
             "issuer":{"id":"did:web:corpus.roax.invalid"},
             "root":"\(String(repeating: "0", count: 64))","leafCount":6\(extra)}
            """
        }

        // The control: the same envelope with every known member well-typed.
        XCTAssertNoThrow(try Envelope.parse(jsonText: text(",\"record\":{\"a\":\"1\"}")))

        for extra in [
            ",\"record\":{\"a\":\"1\"},\"salts\":{}",              // the load-bearing one
            ",\"record\":{\"a\":\"1\"},\"salts\":\"deadbeef\"",
            ",\"record\":{\"a\":\"1\"},\"disclosure\":[]",
            ",\"record\":{\"a\":\"1\"},\"typeMap\":\"urn:roax:type-map:x:1.0.0\"",
            ",\"record\":{\"a\":\"1\"},\"typeMap\":{\"id\":5}",
            ",\"record\":{\"a\":\"1\"},\"typeMap\":{\"id\":\"x\",\"version\":[]}",
            // `record` is the last known member, and its schema types it as an
            // object. Without this a scalar record surfaces as a fail-closed
            // type-map lookup at the empty path rather than as a malformed
            // envelope.
            ",\"record\":\"not-an-object\"",
            ",\"record\":[]",
        ] {
            XCTAssertThrowsError(try Envelope.parse(jsonText: text(extra)), extra) {
                XCTAssertEqual(($0 as? ROAXError)?.reason, "malformed-json", extra)
            }
        }
        // `issuer.keyId` is the conditional leaf, and a wrong-typed one must not
        // read as the absence that means "no leaf".
        XCTAssertThrowsError(try Envelope.parse(jsonText: """
        {"canon":"ROAX-CANON/1","hashAlg":"SHA-256",
         "recordType":"org.roax.corpus.synthetic","schemaVersion":"1.0",
         "recordId":"urn:uuid:11111111-1111-4111-8111-111111111111",
         "issuer":{"id":"did:web:corpus.roax.invalid","keyId":7},
         "root":"\(String(repeating: "0", count: 64))","leafCount":6,"record":{"a":"1"}}
        """)) {
            XCTAssertEqual(($0 as? ROAXError)?.reason, "malformed-json")
        }

        // And a WELL-typed `salts` beside a disclosure still reaches the
        // section 10.1 rejection, which is the reason code the corpus pins.
        let leaking = try Envelope.parse(jsonText: text(",\"salts\":[],\"disclosure\":{\"leaves\":[]}"))
        XCTAssertThrowsError(try EnvelopeVerifier<SHA256Hash>().verify(leaking)) {
            XCTAssertEqual(($0 as? ROAXError)?.reason, "disclosed-copy-carries-salts")
        }
    }

    // MARK: the two carriers of the hash algorithm

    /// `DOMAIN` is `"ROAX-CANON/1/" ‖ hashAlg` (specification sections 7 and 8),
    /// so the declared name and the digest function are two carriers of one
    /// fact and nothing used to check they agreed. Every corpus vector declares
    /// SHA-256, so no vector can tell.
    func testDeclaredHashAlgMustBeTheHashBeingComputed() throws {
        let committer = try syntheticCommitter()
        let record = try JSONScanner.parse("{\"marker\":\"m\"}")

        // Issuance: leaves domained `ROAX-CANON/1/Poseidon-BN254` while hashed
        // with SHA-256 is the record section 7.4 says MUST NOT be issued.
        XCTAssertThrowsError(try committer.commit(
            record: record,
            context: CommitmentContext(identity: syntheticIdentity, hashAlg: "Poseidon-BN254")
        )) {
            XCTAssertEqual(($0 as? ROAXError)?.reason, "hash-alg-mismatch")
        }
        XCTAssertNoThrow(try committer.commit(
            record: record, context: CommitmentContext(identity: syntheticIdentity)
        ))

        // Verification: the allow-list settles which names this verifier runs,
        // and the check settles that the name it accepted is what it computes.
        let envelope = Envelope(
            hashAlg: "Poseidon-BN254",
            recordType: syntheticIdentity.recordType,
            schemaVersion: syntheticIdentity.schemaVersion,
            recordId: syntheticIdentity.recordId,
            issuerId: syntheticIdentity.issuerId,
            root: [UInt8](repeating: 0, count: 32), leafCount: 6,
            disclosedLeaves: []
        )
        // The default allow-list refuses it first, and that ordering is kept.
        XCTAssertThrowsError(try EnvelopeVerifier<SHA256Hash>().verify(envelope)) {
            XCTAssertEqual(($0 as? ROAXError)?.reason, "hash-alg-not-allowed")
        }
        let widened = EnvelopeVerifier<SHA256Hash>(
            allowList: HashAlgorithmAllowList(allowed: ["SHA-256", "Poseidon-BN254"])
        )
        XCTAssertThrowsError(try widened.verify(envelope)) {
            XCTAssertEqual(($0 as? ROAXError)?.reason, "hash-alg-mismatch")
        }
    }

    /// A disclosure naming a path the commitment has no leaf for is its own
    /// condition, not a missing salt.
    ///
    /// `salt-missing-for-leaf` names a salt carrier that failed to supply a salt
    /// for a leaf the record produced, and the corpus uses it for exactly that
    /// envelope case; `SaltAssignment` still throws it there. Keeping the two
    /// one-to-one is what `ReasonEquivalence` depends on.
    func testDiscloseNamesAnUnknownPathRatherThanAMissingSalt() throws {
        let committer = try syntheticCommitter()
        let commitment = try committer.commit(
            record: try JSONScanner.parse("{\"marker\":\"m\"}"),
            context: CommitmentContext(identity: syntheticIdentity)
        )
        XCTAssertThrowsError(
            try commitment.disclose(paths: [[.key("nosuchfield")]], hash: SHA256Hash.self)
        ) {
            XCTAssertEqual(($0 as? ROAXError)?.reason, "unknown-disclosure-path")
        }
        // The salt carrier's own condition keeps its code.
        XCTAssertThrowsError(try committer.commit(
            record: try JSONScanner.parse("{\"marker\":\"m\"}"),
            salts: try SaltAssignment.byPath([([.key("marker")], [UInt8](repeating: 3, count: 16))]),
            context: CommitmentContext(identity: syntheticIdentity)
        )) {
            XCTAssertEqual(($0 as? ROAXError)?.reason, "salt-missing-for-leaf")
        }
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
