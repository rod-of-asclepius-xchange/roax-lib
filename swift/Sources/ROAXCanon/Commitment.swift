import Foundation

/// How the flattener obtains a tag for an **empty container**.
///
/// Specification section 3.3 is unambiguous: `typeTag` is consulted for every
/// emitted record leaf, empty containers included, and tags 6 and 7 are
/// assigned "only when the exact selected map authorizes that structured path
/// and observed kind under section 4.2", because assigning them earlier lets an
/// unknown empty issuer extension bypass decision D7's fail-closed rule.
///
/// **The committed corpus does not implement that rule, and this implementation
/// refuses to pick a side silently.** `corpus/fixtures/records/structure-empty-array.json`
/// and `structure-empty-object.json` both carry an empty container at `a.b`,
/// while `corpus/type-maps/org.roax.corpus.synthetic.json` declares `a.b` for
/// `jsonKind: "null"` alone. Under the specification both records fail closed
/// and have no root; the corpus asserts a root for each. That is exactly 2
/// vectors of class 5, and under specification section 1.1 it is a
/// release-blocking corpus defect rather than a variance to tolerate. The same
/// finding was reported by the TypeScript and Python builds before this one.
public enum EmptyContainerPolicy: Sendable {
    /// Specification section 3.3 as written: the map must authorize the path
    /// and the observed kind, or the record fails closed.
    case mapAuthorized
    /// What the committed corpus requires: EMPTY_ARRAY and EMPTY_OBJECT are
    /// assigned from the observed shape without consulting the map.
    ///
    /// Selecting this is selecting the corpus over the specification. It exists
    /// so the divergence is visible at the call site and in a stack trace,
    /// never as a default.
    case assignedWithoutMapAuthorization
}

/// Everything an issuance needs beyond the record itself.
public struct CommitmentContext {
    public let identity: RecordIdentity
    public let hashAlg: String
    public let canon: String

    public init(
        identity: RecordIdentity,
        hashAlg: String = SHA256Hash.identifier,
        canon: String = ROAXCanon.version
    ) {
        self.identity = identity
        self.hashAlg = hashAlg
        self.canon = canon
    }
}

public enum ROAXCanon {
    public static let version = "ROAX-CANON/1"
}

/// A sealed commitment: the leaves, their order and the root.
public struct Commitment {
    /// Every leaf of the union, in encoded-path order.
    public let leaves: [Leaf]
    public let root: [UInt8]
    /// The exact context this was issued under.
    ///
    /// It is retained rather than re-supplied at disclosure time. Accepting a
    /// second caller-supplied context would let safe values from two issuances
    /// be mixed into an envelope that its own verifier rejects at outer-identity
    /// binding, so `disclose` accepts no replacement.
    public let context: CommitmentContext

    public var leafCount: Int { leaves.count }

    /// The index of a leaf by its encoded path, for building a disclosure.
    public func index(of segments: Path) -> Int? {
        let encoded = PathEncoding.encode(segments)
        return leaves.firstIndex { $0.encodedPath == encoded }
    }
}

/// Flattening a record and committing it (specification sections 3.3, 8 and 9).
public struct Committer<H: ROAXHash> {

    public let resolver: TypeResolver
    public let emptyContainerPolicy: EmptyContainerPolicy

    public init(
        resolver: TypeResolver,
        emptyContainerPolicy: EmptyContainerPolicy = .mapAuthorized
    ) {
        self.resolver = resolver
        self.emptyContainerPolicy = emptyContainerPolicy
    }

    /// One flattened record leaf, before a salt is attached.
    public struct FlattenedLeaf {
        public let segments: Path
        public let tag: TypeTag
        public let encodedValue: [UInt8]
    }

    /// `flatten(record, [])` of specification section 3.3.
    ///
    /// A leaf is produced for every scalar and for every **empty** container.
    /// An empty container is a leaf so that removing it changes the root, which
    /// is where this design departs from dogtag's collapse of empty array,
    /// empty object and null to one leaf.
    ///
    /// Map iteration order is irrelevant because leaves are sorted by encoded
    /// path in section 9; this walks members in source order only so that a
    /// diagnostic reads in the order a human wrote the record.
    public func flatten(_ record: JSONValue) throws -> [FlattenedLeaf] {
        var out = [FlattenedLeaf]()
        try walk(record, path: [], into: &out)
        return out
    }

    private func walk(_ node: JSONValue, path: Path, into out: inout [FlattenedLeaf]) throws {
        switch node {
        case .object(let members):
            if members.isEmpty {
                out.append(try emptyContainerLeaf(path: path, tag: .emptyObject, kind: .object))
                return
            }
            for member in members {
                let child = path + [.key(member.key)]
                // The reserved-namespace guard runs at the input boundary, on
                // the decoded and NFC-normalized key of the FIRST segment only.
                try ReservedNamespace.check(child)
                try walk(member.value, path: child, into: &out)
            }

        case .array(let items):
            if items.isEmpty {
                out.append(try emptyContainerLeaf(path: path, tag: .emptyArray, kind: .array))
                return
            }
            for (i, item) in items.enumerated() {
                // Specification section 5: an implementation that cannot
                // represent an index in 32 bits MUST error rather than truncate.
                let child = path + [try PathSegment.index(checking: i)]
                try walk(item, path: child, into: &out)
            }

        default:
            let tag = try resolver.resolve(segments: path, jsonKind: node.jsonKind)
            let encoded = try ValueEncoding.encodeRecordValue(tag: tag, value: node)
            out.append(FlattenedLeaf(segments: path, tag: tag, encodedValue: encoded))
        }
    }

    private func emptyContainerLeaf(
        path: Path,
        tag: TypeTag,
        kind: JSONKind
    ) throws -> FlattenedLeaf {
        switch emptyContainerPolicy {
        case .mapAuthorized:
            // Path authorization happens BEFORE the flattener assigns the tag,
            // so an unknown issuer extension containing only an empty container
            // cannot bypass the fail-closed allowlist.
            let authorized = try resolver.resolve(segments: path, jsonKind: kind)
            guard authorized == tag else {
                throw ROAXError.typeMapUncoveredPath(
                    path: PathEncoding.display(path),
                    jsonKind: kind.rawValue
                )
            }
            return FlattenedLeaf(segments: path, tag: tag, encodedValue: [])
        case .assignedWithoutMapAuthorization:
            return FlattenedLeaf(segments: path, tag: tag, encodedValue: [])
        }
    }

    /// The leaf set of specification section 3.3: the union of the reserved
    /// leaves and the record leaves, formed **before** the sort of section 9.
    ///
    /// An implementation that flattens the record only produces a different
    /// root, so this is not an optional step.
    public func unionedLeaves(
        record: JSONValue,
        identity: RecordIdentity
    ) throws -> [FlattenedLeaf] {
        let recordLeaves = try flatten(record)
        // A record that contributes zero leaves of its own MUST be rejected at
        // issuance rather than anchored.
        guard !recordLeaves.isEmpty else { throw ROAXError.emptyRecord }

        var out = [FlattenedLeaf]()
        for reserved in identity.reservedLeaves {
            out.append(FlattenedLeaf(
                segments: reserved.segments,
                tag: reserved.tag,
                encodedValue: NFC.utf8(reserved.value)
            ))
        }
        out.append(contentsOf: recordLeaves)
        return out
    }

    /// Issues a commitment, drawing a fresh independent salt for every leaf.
    public func commit(
        record: JSONValue,
        context: CommitmentContext
    ) throws -> Commitment {
        let flattened = try unionedLeaves(record: record, identity: context.identity)
        let salts = SaltSource.draw(count: flattened.count)
        return try commit(flattened: flattened, salts: SaltAssignment.positional(salts), context: context)
    }

    /// Issues a commitment against a supplied salt set.
    ///
    /// Used by the corpus runner and by any caller reproducing an issuance:
    /// under ruled decision D4b nothing can re-derive a salt, so a vector has to
    /// name the set its root was computed under.
    public func commit(
        record: JSONValue,
        salts: SaltAssignment,
        context: CommitmentContext
    ) throws -> Commitment {
        let flattened = try unionedLeaves(record: record, identity: context.identity)
        return try commit(flattened: flattened, salts: salts, context: context)
    }

    func commit(
        flattened: [FlattenedLeaf],
        salts: SaltAssignment,
        context: CommitmentContext
    ) throws -> Commitment {
        // The algorithm is carried twice - `H` supplies the digest function and
        // `context.hashAlg` supplies the `DOMAIN` tail of sections 7 and 8 - and
        // this is what stops the two disagreeing. Without it a caller can issue
        // leaves domained `ROAX-CANON/1/Poseidon-BN254` while hashing with
        // SHA-256, which is the record specification section 7.4 says MUST NOT
        // be issued. Every issuance funnels through here, so one guard covers
        // both public `commit` overloads.
        guard context.hashAlg == H.identifier else {
            throw ROAXError.hashAlgMismatch(declared: context.hashAlg, computing: H.identifier)
        }

        // SALT-ASSIGNMENT order: ascending encodePath bytes under BOTH leaf
        // orderings (specification section 9), plain unsigned byte comparison.
        // It cannot be tree order under `hash`, because a leaf hash is computed
        // over its salt and pairing in tree order would be circular. Paths are
        // unique by construction, so this order is total and tie-free.
        var sortable = flattened.map { leaf -> (encoded: [UInt8], leaf: FlattenedLeaf) in
            (PathEncoding.encode(leaf.segments), leaf)
        }
        sortable.sort { roaxByteCompare($0.encoded, $1.encoded) < 0 }

        // Section 9 says paths are unique by construction. Checking it here is
        // what makes that a property rather than an assumption: a duplicate
        // complete encoded leaf path would make the order ambiguous and the
        // salt pairing wrong.
        for i in 1..<max(sortable.count, 1) where sortable[i].encoded == sortable[i - 1].encoded {
            throw ROAXError.duplicateLeafPath(PathEncoding.display(sortable[i].leaf.segments))
        }

        var leaves = [Leaf]()
        leaves.reserveCapacity(sortable.count)
        for (position, entry) in sortable.enumerated() {
            let salt = try salts.salt(
                forEncodedPath: entry.encoded,
                displayPath: PathEncoding.display(entry.leaf.segments),
                position: position
            )
            let preimage = try LeafConstruction.preimage(
                encodedPath: entry.encoded,
                tag: entry.leaf.tag,
                encodedValue: entry.leaf.encodedValue,
                salt: salt,
                hashAlg: context.hashAlg,
                ordering: context.identity.ordering
            )
            leaves.append(Leaf(
                segments: entry.leaf.segments,
                tag: entry.leaf.tag,
                encodedValue: entry.leaf.encodedValue,
                salt: salt,
                encodedPath: entry.encoded,
                hash: H.hash(preimage)
            ))
        }

        // TREE order. `path` is the identity, because salt-assignment order
        // already is encodePath order. `hash` sorts by ascending leaf-hash bytes.
        //
        // Equal leaf hashes are REJECTED rather than tie-broken. Paths are
        // unique already and every variable component of the section 8 preimage
        // is length-prefixed, so two equal hashes over distinct paths are a
        // collision; breaking the tie by path would absorb evidence of a broken
        // hash into a well-defined tree and hand back a root, which section 9
        // forbids by name.
        if context.identity.ordering == .hash {
            var seen = Set<[UInt8]>()
            for leaf in leaves where !seen.insert(leaf.hash).inserted {
                throw ROAXError.leafHashCollision(leaf.displayPath)
            }
            leaves.sort { roaxByteCompare($0.hash, $1.hash) < 0 }
        }

        let root = MerkleTree.root(leaves.map(\.hash), hash: H.self)
        return Commitment(leaves: leaves, root: root, context: context)
    }
}

/// How a supplied salt set pairs to leaves.
///
/// The corpus carries both shapes and `docs/conformance-corpus.md` class 10
/// says why: everything but class 10 pairs by path, and class 10's sets pair
/// positionally. Path pairing is the safe direction, because a positional set
/// makes the pairing depend on each implementation reproducing the section 9
/// sort before it can even read the salts.
public enum SaltAssignment {
    case byEncodedPath([[UInt8]: [UInt8]])
    case positional([[UInt8]])

    public static func byPath(_ pairs: [(Path, [UInt8])]) throws -> SaltAssignment {
        var table = [[UInt8]: [UInt8]]()
        for (segments, salt) in pairs {
            let encoded = PathEncoding.encode(segments)
            guard table.updateValue(salt, forKey: encoded) == nil else {
                throw ROAXError.saltsDuplicatePath(PathEncoding.display(segments))
            }
        }
        return .byEncodedPath(table)
    }

    func salt(forEncodedPath encoded: [UInt8], displayPath: String, position: Int) throws -> [UInt8] {
        switch self {
        case .byEncodedPath(let table):
            guard let salt = table[encoded] else {
                throw ROAXError.saltMissingForLeaf(displayPath)
            }
            guard salt.count == 16 else { throw ROAXError.saltLength(salt.count) }
            return salt
        case .positional(let list):
            guard position < list.count else {
                throw ROAXError.saltsLengthNotLeafCount(expected: position + 1, actual: list.count)
            }
            guard list[position].count == 16 else { throw ROAXError.saltLength(list[position].count) }
            return list[position]
        }
    }

    var declaredCount: Int? {
        switch self {
        case .byEncodedPath(let table): return table.count
        case .positional(let list): return list.count
        }
    }
}
