import Foundation

/// One entry of a full copy's `salts` array.
public struct SaltEntry {
    public let segments: Path
    public let salt: [UInt8]
}

/// One revealed leaf of a disclosed copy.
public struct DisclosedLeaf {
    public let segments: Path
    public let index: Int
    public let tag: TypeTag
    /// The value in its envelope carrier form, absent for tags 0, 6 and 7.
    public let value: JSONValue?
    public let salt: [UInt8]
    public let auditPath: [[UInt8]]
}

/// A parsed envelope, in either copy kind.
public struct Envelope {
    public let canon: String
    public let hashAlg: String
    public let recordType: String
    public let schemaVersion: String
    public let recordId: String
    public let issuerId: String
    public let issuerKeyId: String?
    public let typeMapId: String?
    public let typeMapVersion: String?
    public let root: [UInt8]
    public let leafCount: Int
    public let record: JSONValue?
    public let salts: [SaltEntry]?
    public let disclosedLeaves: [DisclosedLeaf]?

    public init(
        canon: String = ROAXCanon.version,
        hashAlg: String = SHA256Hash.identifier,
        recordType: String,
        schemaVersion: String,
        recordId: String,
        issuerId: String,
        issuerKeyId: String? = nil,
        typeMapId: String? = nil,
        typeMapVersion: String? = nil,
        root: [UInt8],
        leafCount: Int,
        record: JSONValue? = nil,
        salts: [SaltEntry]? = nil,
        disclosedLeaves: [DisclosedLeaf]? = nil
    ) {
        self.canon = canon
        self.hashAlg = hashAlg
        self.recordType = recordType
        self.schemaVersion = schemaVersion
        self.recordId = recordId
        self.issuerId = issuerId
        self.issuerKeyId = issuerKeyId
        self.typeMapId = typeMapId
        self.typeMapVersion = typeMapVersion
        self.root = root
        self.leafCount = leafCount
        self.record = record
        self.salts = salts
        self.disclosedLeaves = disclosedLeaves
    }

    public var identity: RecordIdentity {
        RecordIdentity(
            recordType: recordType,
            schemaVersion: schemaVersion,
            recordId: recordId,
            issuerId: issuerId,
            issuerKeyId: issuerKeyId,
            typeMapId: typeMapId
        )
    }
}

// MARK: - parsing

public extension Envelope {

    /// Parses an envelope through the literal-preserving scanner.
    ///
    /// **The parser requirement of specification section 6.4 applies to the
    /// envelope, not only to a bare record.** A full copy's `record` member
    /// carries record numbers in their original JSON form, so reading an
    /// envelope through a float-based JSON parser destroys the very literals the
    /// verifier is about to recompute the root from, and it fails to reproduce a
    /// root it should have matched. `JSONSerialization` is never used here.
    static func parse(jsonText: String) throws -> Envelope {
        try parse(json: try JSONScanner.parse(jsonText))
    }

    static func parse(json: JSONValue) throws -> Envelope {
        guard case .object(let members) = json else {
            throw ROAXError.malformedJSON("envelope is not an object")
        }

        // `schemas/envelope-*.json` closes the object with
        // `additionalProperties: false` so that no seed field can be added by an
        // issuer (specification section 7.3, rule 3). That closure is enforced
        // here rather than left to a schema validator this package does not ship.
        let known: Set<String> = [
            "canon", "hashAlg", "recordType", "schemaVersion", "recordId",
            "typeMap", "root", "leafCount", "issuer", "anchor",
            "disclosure", "record", "salts",
        ]
        for member in members where !known.contains(member.key) {
            if member.key == "masterSalt" || member.key == "masterSaltHex" || member.key == "seed" {
                throw ROAXError.masterSaltInEnvelope
            }
            throw ROAXError.malformedJSON("envelope carries unknown member \(member.key.debugDescription)")
        }

        func requiredString(_ key: String) throws -> String {
            guard case .string(let s)? = json[key] else {
                throw ROAXError.malformedJSON("envelope member \(key) is missing or not a string")
            }
            return s
        }

        let canon = try requiredString("canon")
        let hashAlg = try requiredString("hashAlg")
        let recordType = try requiredString("recordType")
        let schemaVersion = try requiredString("schemaVersion")
        let recordId = try requiredString("recordId")

        guard case .object? = json["issuer"], case .string(let issuerId)? = json["issuer"]?["id"] else {
            throw ROAXError.malformedJSON("envelope issuer.id is missing")
        }
        var issuerKeyId: String? = nil
        if case .string(let k)? = json["issuer"]?["keyId"] { issuerKeyId = k }

        var typeMapId: String? = nil
        var typeMapVersion: String? = nil
        if case .string(let id)? = json["typeMap"]?["id"] { typeMapId = id }
        if case .string(let v)? = json["typeMap"]?["version"] { typeMapVersion = v }

        let rootHex = try requiredString("root")
        guard let root = [UInt8].roaxFromHex(rootHex), root.count == 32 else {
            throw ROAXError.malformedJSON("envelope root is not 32 lowercase hex bytes")
        }
        guard case .number(let leafCountText)? = json["leafCount"], let leafCount = Int(leafCountText) else {
            throw ROAXError.malformedJSON("envelope leafCount is missing or not an integer")
        }

        var salts: [SaltEntry]? = nil
        if case .array(let rows)? = json["salts"] {
            salts = try rows.map { row in
                guard case .array(let segs)? = row["segments"],
                      case .string(let saltHex)? = row["salt"],
                      let salt = [UInt8].roaxFromHex(saltHex)
                else {
                    throw ROAXError.malformedJSON("a salts entry is malformed")
                }
                guard salt.count == 16 else { throw ROAXError.saltLength(salt.count) }
                return SaltEntry(segments: try parseSegments(segs), salt: salt)
            }
        }

        var disclosedLeaves: [DisclosedLeaf]? = nil
        if case .object? = json["disclosure"] {
            guard case .array(let rows)? = json["disclosure"]?["leaves"] else {
                throw ROAXError.malformedJSON("disclosure carries no leaves array")
            }
            disclosedLeaves = try rows.map { row in
                guard case .array(let segs)? = row["segments"],
                      case .number(let indexText)? = row["index"], let index = Int(indexText),
                      case .number(let tagText)? = row["tag"], let rawTag = UInt8(tagText),
                      let tag = TypeTag(rawValue: rawTag),
                      case .string(let saltHex)? = row["salt"],
                      let salt = [UInt8].roaxFromHex(saltHex),
                      case .array(let auditRows)? = row["auditPath"]
                else {
                    throw ROAXError.malformedJSON("a disclosed leaf is malformed")
                }
                guard salt.count == 16 else { throw ROAXError.saltLength(salt.count) }
                let auditPath: [[UInt8]] = try auditRows.map {
                    guard case .string(let hex) = $0, let bytes = [UInt8].roaxFromHex(hex), bytes.count == 32
                    else { throw ROAXError.malformedJSON("an audit path entry is not a 32-byte hex hash") }
                    return bytes
                }
                return DisclosedLeaf(
                    segments: try parseSegments(segs),
                    index: index,
                    tag: tag,
                    value: row["value"],
                    salt: salt,
                    auditPath: auditPath
                )
            }
        }

        return Envelope(
            canon: canon, hashAlg: hashAlg, recordType: recordType,
            schemaVersion: schemaVersion, recordId: recordId,
            issuerId: issuerId, issuerKeyId: issuerKeyId,
            typeMapId: typeMapId, typeMapVersion: typeMapVersion,
            root: root, leafCount: leafCount,
            record: json["record"], salts: salts, disclosedLeaves: disclosedLeaves
        )
    }

    /// Parses structured path segments. Never parses a display path
    /// (specification section 5.2).
    static func parseSegments(_ rows: [JSONValue]) throws -> Path {
        try rows.map { row in
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
}

// MARK: - verification

/// Verifying an envelope of either copy kind.
///
/// The order of the disclosed-copy steps is a **derived requirement, not a
/// preference**. Specification section 11.3 says a field outside the root is
/// never authority; it follows that authority is established before an outer
/// field selects anything. Choosing the floor from the envelope's `recordType`
/// and validating it afterwards is trust-then-verify, which is the shape of the
/// dogtag scar section 11.3 records.
///
/// 1. every disclosed leaf is recomputed and its inclusion proof checked;
/// 2. the outer `recordType`, `schemaVersion`, `recordId` and `issuer.id` are
///    bound to the reserved leaves the root commits;
/// 3. the floor is selected from the **committed** `roax.recordType` leaf and
///    enforced.
///
/// The consequence is load-bearing and observable: because a missing reserved
/// leaf trips the binding at step 2, the floor loop can only ever reject on a
/// profile-specific path, so every `floor-<profile>-omits-roax-*` vector
/// asserts `outer-identity-mismatch` rather than `minimum-disclosure-floor`.
/// An implementation that enforces the floor first fails exactly those 16.
public struct EnvelopeVerifier<H: ROAXHash> {

    public let registry: ProfileRegistry
    public let allowList: HashAlgorithmAllowList
    public let resolver: TypeResolver?
    public let emptyContainerPolicy: EmptyContainerPolicy

    public init(
        registry: ProfileRegistry = .versionOne,
        allowList: HashAlgorithmAllowList = .versionOneDefault,
        resolver: TypeResolver? = nil,
        emptyContainerPolicy: EmptyContainerPolicy = .mapAuthorized
    ) {
        self.registry = registry
        self.allowList = allowList
        self.resolver = resolver
        self.emptyContainerPolicy = emptyContainerPolicy
    }

    public func verify(_ envelope: Envelope) throws {
        // The verifier's own allow-lists come first. `profile-unknown` and
        // `hash-alg-not-allowed` settle whether this verifier can proceed at
        // all, rather than which policy to apply; they are the same shape as the
        // `hashAlg` allow-list of section 7.4 H3.
        guard envelope.canon == ROAXCanon.version else {
            throw ROAXError.canonUnknown(envelope.canon)
        }
        try allowList.check(envelope.hashAlg)
        _ = try registry.profile(for: envelope.recordType)

        // Exactly one of `record` and `disclosure` MUST be present.
        switch (envelope.record, envelope.disclosedLeaves) {
        case (nil, nil):
            throw ROAXError.envelopeCopyKind("neither record nor disclosure is present")
        case (.some, .some):
            throw ROAXError.envelopeCopyKind("both record and disclosure are present")
        case (.some(let record), nil):
            try verifyFullCopy(envelope, record: record)
        case (nil, .some(let leaves)):
            try verifyDisclosedCopy(envelope, leaves: leaves)
        }
    }

    // MARK: full copy

    private func verifyFullCopy(_ envelope: Envelope, record: JSONValue) throws {
        guard let salts = envelope.salts else {
            throw ROAXError.envelopeCopyKind("a full copy carries no salts array")
        }
        // `salts` carries one entry per leaf of the union, so its length equals
        // `leafCount` (specification sections 7.3 and 11.1).
        guard salts.count == envelope.leafCount else {
            throw ROAXError.saltsLengthNotLeafCount(expected: envelope.leafCount, actual: salts.count)
        }

        var table = [[UInt8]: [UInt8]]()
        for entry in salts {
            let encoded = PathEncoding.encode(entry.segments)
            guard table.updateValue(entry.salt, forKey: encoded) == nil else {
                throw ROAXError.saltsDuplicatePath(PathEncoding.display(entry.segments))
            }
        }

        guard let resolver else {
            throw ROAXError.typeMapInvalid("a full copy needs a type map to flatten its record")
        }
        let committer = Committer<H>(resolver: resolver, emptyContainerPolicy: emptyContainerPolicy)
        let commitment = try committer.commit(
            record: record,
            salts: .byEncodedPath(table),
            context: CommitmentContext(identity: envelope.identity, hashAlg: envelope.hashAlg)
        )

        // Specification section 11.1: in a full copy the verifier derives the
        // leaf count itself, and a derived count that disagrees with the
        // `leafCount` field MUST be a rejection - not a warning and not a silent
        // preference for either value.
        guard commitment.leafCount == envelope.leafCount else {
            throw ROAXError.saltsLengthNotLeafCount(
                expected: envelope.leafCount, actual: commitment.leafCount
            )
        }
        guard commitment.root == envelope.root else { throw ROAXError.rootMismatch }
    }

    // MARK: disclosed copy

    private func verifyDisclosedCopy(_ envelope: Envelope, leaves: [DisclosedLeaf]) throws {
        // A disclosed copy MUST NOT carry a `salts` array. With that array
        // absent, the per-leaf `salt` inside `disclosure.leaves` is the only
        // place a salt can appear, and every entry there belongs by construction
        // to a leaf being revealed - which is what makes a withheld leaf's salt
        // unrepresentable rather than merely prohibited (section 10.1).
        if envelope.salts != nil { throw ROAXError.disclosedCopyCarriesSalts }

        // Step 1: recompute every leaf and check its proof.
        var committed = [String: String]()      // reserved key -> committed value
        for leaf in leaves {
            let encodedValue = try Self.encodeDisclosedValue(leaf: leaf)
            let hash = try LeafConstruction.leafHash(
                segments: leaf.segments,
                tag: leaf.tag,
                encodedValue: encodedValue,
                salt: leaf.salt,
                hash: H.self
            )
            // Never accept a caller-supplied leaf hash. Section 11.1 measured
            // that an attacker who controls both a leaf hash and `leafCount` can
            // walk an internal node to the genuine root, so this recomputation
            // is the defence rather than a convenience.
            let ok = MerkleTree.verifyInclusion(
                leafHash: hash,
                index: leaf.index,
                treeSize: envelope.leafCount,
                auditPath: leaf.auditPath,
                root: envelope.root,
                hash: H.self
            )
            guard ok else {
                throw ROAXError.inclusionProofFailed(PathEncoding.display(leaf.segments))
            }
            if case .key(let k) = leaf.segments.first, leaf.segments.count == 1,
               k.hasPrefix(ReservedNamespace.prefix), case .string(let v)? = leaf.value {
                committed[k] = v
            }
        }

        // Step 2: bind the outer identity to the reserved leaves the root
        // commits. The outer `recordType` is what SELECTS the profile floor, and
        // PDT's floor is a strict subset of recovery's, so an unbound one lets a
        // holder relabel a recovery copy as PDT, withhold `validUntil`, and have
        // every inclusion proof still verify against the genuine root.
        //
        // Both sides are compared under NFC, because a STRING leaf commits its
        // normalized form.
        try bind("recordType", outer: envelope.recordType, committed: committed["roax.recordType"])
        try bind("schemaVersion", outer: envelope.schemaVersion, committed: committed["roax.schemaVersion"])
        try bind("recordId", outer: envelope.recordId, committed: committed["roax.recordId"])
        try bind("issuer.id", outer: envelope.issuerId, committed: committed["roax.issuer.id"])
        if envelope.typeMapId != nil {
            try bind("typeMap.id", outer: envelope.typeMapId!, committed: committed["roax.typeMap.id"])
        }
        // `roax.issuer.keyId` is deliberately NOT bound: it is the one
        // conditional leaf and the one reserved leaf that is OPTIONAL to
        // disclose, because requiring it would break key rotation on an
        // already-anchored record (section 11.2).

        // Step 3: select the floor from the COMMITTED recordType leaf.
        //
        // Sourcing it from the leaf rather than the outer field is a clarity
        // convention rather than a corpus-enforced requirement, and
        // `corpus/README.md` measures why: step 2 has just proved the two
        // NFC-equal, so both sources yield the same floor table and no vector
        // can tell them apart. It puts the structural claim where a reader of
        // the code can see it.
        let committedRecordType = committed["roax.recordType"] ?? envelope.recordType
        let identity = RecordIdentity(
            recordType: committedRecordType,
            schemaVersion: envelope.schemaVersion,
            recordId: envelope.recordId,
            issuerId: envelope.issuerId,
            issuerKeyId: envelope.issuerKeyId,
            typeMapId: envelope.typeMapId
        )
        let disclosedPaths = Set(leaves.map { PathEncoding.encode($0.segments) })
        for required in try registry.floor(for: identity) {
            guard disclosedPaths.contains(PathEncoding.encode(required)) else {
                throw ROAXError.minimumDisclosureFloor(PathEncoding.display(required))
            }
        }
    }

    private func bind(_ field: String, outer: String, committed: String?) throws {
        guard let committed, NFC.normalize(committed) == NFC.normalize(outer) else {
            throw ROAXError.outerIdentityMismatch(field)
        }
    }

    /// Turns a disclosed leaf's envelope carrier into encoded value bytes.
    ///
    /// The carriers are the ones `schemas/envelope-1.0.json` pins per tag:
    /// tags 0, 6 and 7 carry no value; BOOL carries a JSON boolean; STRING,
    /// INTEGER and DECIMAL carry strings, the numeric two already in canonical
    /// output form; BYTES carries lowercase hex, not base64.
    static func encodeDisclosedValue(leaf: DisclosedLeaf) throws -> [UInt8] {
        switch leaf.tag {
        case .null, .emptyArray, .emptyObject:
            guard leaf.value == nil else {
                throw ROAXError.valueKindMismatch(tag: leaf.tag, detail: "\(leaf.tag.name) carries no value")
            }
            return []
        case .blobRef:
            throw ROAXError.blobRefNotSelectable
        default:
            guard let value = leaf.value else {
                throw ROAXError.disclosedLeafNamedWithoutValue(PathEncoding.display(leaf.segments))
            }
            switch (leaf.tag, value) {
            case (.bool, .bool(let b)):
                return [b ? 0x01 : 0x00]
            case (.string, .string(let s)):
                return NFC.utf8(s)
            case (.integer, .string(let s)):
                return Array(try CanonicalNumber.canonicalizeInteger(s).utf8)
            case (.decimal, .string(let s)):
                return Array(try CanonicalNumber.canonicalizeDecimal(s).utf8)
            case (.bytes, .string(let hex)):
                guard let bytes = [UInt8].roaxFromHex(hex) else {
                    throw ROAXError.valueKindMismatch(tag: .bytes, detail: "value is not lowercase hex")
                }
                return bytes
            default:
                throw ROAXError.valueKindMismatch(
                    tag: leaf.tag, detail: "carrier is \(value.jsonKind.rawValue)"
                )
            }
        }
    }
}

// MARK: - producing a disclosure

public extension Commitment {

    /// Builds a disclosed copy from a sealed commitment.
    ///
    /// **The context is the one this commitment was sealed with, and this method
    /// accepts no replacement.** Accepting a second caller-supplied context
    /// would let safe values from two issuances be mixed into an envelope that
    /// its own verifier rejects at outer-identity binding.
    func disclose<H: ROAXHash>(paths: [Path], hash: H.Type) throws -> [DisclosedLeaf] {
        let hashes = leaves.map(\.hash)
        return try paths.map { path in
            guard let index = index(of: path) else {
                throw ROAXError.saltMissingForLeaf(PathEncoding.display(path))
            }
            let leaf = leaves[index]
            return DisclosedLeaf(
                segments: leaf.segments,
                index: index,
                tag: leaf.tag,
                // The carrier form its tag pins, so this disclosure verifies
                // through `EnvelopeVerifier` rather than being rejected for
                // `disclosed-leaf-named-without-value`. The salt is the
                // load-bearing part: a disclosed copy carries the salt of every
                // leaf it reveals and the salt of no other leaf.
                value: leaf.carrierValue,
                salt: leaf.salt,
                auditPath: try MerkleTree.inclusionProof(leaves: hashes, index: index, hash: H.self)
            )
        }
    }
}
