package io.roax.canon

import io.roax.canon.json.JsonValue

/** A leaf that has been salted and hashed, in the tree's own order. */
class CommittedLeaf internal constructor(
    val segments: List<Segment>,
    val tag: TypeTag,
    val value: RoaxValue,
    val salt: ByteArray,
    val leafHash: ByteArray,
    internal val encodedPath: ByteArray,
) {
    val displayPath: String get() = displayPath(segments)
}

/**
 * The context a root was issued under.
 *
 * A [Commitment] retains this and [disclose] accepts no replacement, which is deliberate: letting
 * a caller supply a second context at disclosure time would let safe values from two issuances be
 * mixed into an envelope that its own verifier then rejects at outer-identity binding
 * (sections 10 and 11.3).
 */
data class IssuanceContext(
    val identity: RecordIdentity,
    val envelopeProfile: EnvelopeProfile,
    val canon: String = CANON,
    val hashAlgId: String = Sha256.id,
)

/**
 * A record turned into leaves and a root.
 *
 * The whole of ROAX-CANON/1 steps (A) through (D): schema binding, flatten, leaf hash, tree.
 */
class Commitment internal constructor(
    val context: IssuanceContext,
    val leaves: List<CommittedLeaf>,
    val root: ByteArray,
    private val hash: HashAlgorithm,
) {
    /** The UNION of record leaves and reserved leaves, which is what `leafCount` counts. */
    val leafCount: Int get() = leaves.size

    val rootHex: String get() = Bytes.toHex(root)

    /** RFC 9162 audit path for the leaf at [index]. */
    fun auditPath(index: Int): List<ByteArray> =
        Merkle.inclusionPath(leaves.map { it.leafHash }, index, hash)

    /** Index of the leaf at [segments], or -1. Compared on the ENCODED path, never a display one. */
    fun indexOf(segments: List<Segment>, nfc: Nfc = PlatformNfc): Int {
        val target = encodePath(segments, nfc)
        return leaves.indexOfFirst { Bytes.compareUnsigned(it.encodedPath, target) == 0 }
    }
}

/**
 * ROAX-CANON/1 sections 3.3, 7, 8 and 9: record plus envelope identity in, root out.
 *
 * The leaf set is the **union** of the reserved leaves and the record leaves, and the union is
 * formed **before** the sort, so reserved and record leaves are ordered together by encoded path
 * and are indistinguishable to the tree function. An implementation that flattens the record only
 * produces a different root, so this is not an optional step.
 */
fun commit(
    record: JsonValue,
    context: IssuanceContext,
    resolver: TypeResolver,
    saltSource: SaltSource,
    nfc: Nfc = PlatformNfc,
    hash: HashAlgorithm = Sha256,
    emptyContainers: EmptyContainerAuthorization = EmptyContainerAuthorization.REQUIRED,
): Commitment {
    val recordLeaves = flattenRecord(record, FlattenOptions(resolver, nfc, emptyContainers))

    // "A record that contributes zero leaves of its own MUST be rejected at issuance rather than
    // anchored." The rejection is on the record's OWN contribution, because the union always
    // carries the reserved leaves, so the tree itself is never empty.
    //
    // FINDING, reported rather than worked around: this MUST can never fire. Section 3.3's own
    // flattener emits a leaf for an empty map, so `{}` yields one leaf rather than zero, and no
    // JSON document produces an empty leaf set. The check is kept because it is normative and
    // because a future flattener change could make it reachable.
    if (recordLeaves.isEmpty()) {
        fail(Reason.EMPTY_RECORD, "the record contributes zero leaves of its own (section 3.3)")
    }

    val reserved = Reserved.leavesFor(context.identity, context.envelopeProfile)
        .map { (segments, value) -> FlatLeaf(segments, TypeTag.STRING, RoaxValue.Text(value)) }

    val union = reserved + recordLeaves

    // Sorted by ascending encodePath bytes, plain unsigned byte comparison (section 9). The order
    // is NOT alphabetical: the length prefix precedes the key bytes, so it sorts by segment count,
    // then segment kind, then key length, then key bytes. A plain memcmp over the encoding is the
    // easiest thing to get identical in five languages, which is what decision D5a bought.
    // This is SALT-ASSIGNMENT order and it is encodePath order under BOTH leaf orderings
    // (section 9). It cannot be tree order under `hash`, because a leaf hash is computed over its
    // salt, so pairing salts in tree order would be circular and unimplementable.
    val encoded = union.map { encodePath(it.segments, nfc) to it }
    val sorted = encoded.sortedWith { a, b -> Bytes.compareUnsigned(a.first, b.first) }

    for (i in 1 until sorted.size) {
        if (Bytes.compareUnsigned(sorted[i - 1].first, sorted[i].first) == 0) {
            fail(
                Reason.DUPLICATE_LEAF_PATH,
                "two leaves share the encoded path ${displayPath(sorted[i].second.segments)}",
            )
        }
    }

    val committed = sorted.map { (encodedPath, leaf) ->
        val salt = saltSource.next()
        CommittedLeaf(
            segments = leaf.segments,
            tag = leaf.tag,
            value = leaf.value,
            salt = salt,
            leafHash = leafHash(
                leaf.segments, leaf.tag, leaf.value, salt, hash, context.canon, nfc,
                ordering = context.identity.ordering,
            ),
            encodedPath = encodedPath,
        )
    }

    val placed = treeOrder(context.identity.ordering, committed)
    return Commitment(
        context = context,
        leaves = placed,
        root = Merkle.merkleTreeHash(placed.map { it.leafHash }, hash),
        hash = hash,
    )
}

/**
 * Reorders committed leaves from salt-assignment order into TREE order (section 9).
 *
 * [Ordering.PATH] is the identity, because salt-assignment order already is `encodePath` order.
 * [Ordering.HASH] sorts by ascending leaf-hash bytes.
 *
 * Equal leaf hashes are REJECTED rather than tie-broken. Paths are unique already and every
 * variable component of the section 8 preimage is length-prefixed, so two equal hashes over
 * distinct paths are a collision; breaking the tie by path would absorb evidence of a broken hash
 * into a well-defined tree and hand back a root, which section 9 forbids by name.
 */
internal fun treeOrder(ordering: Ordering, leaves: List<CommittedLeaf>): List<CommittedLeaf> {
    if (ordering == Ordering.PATH) return leaves
    val seen = HashSet<String>(leaves.size)
    for (leaf in leaves) {
        if (!seen.add(Bytes.toHex(leaf.leafHash))) {
            fail(
                Reason.LEAF_HASH_COLLISION,
                "two leaves share a leaf hash at ${displayPath(leaf.segments)}; paths are unique, " +
                    "so this is a hash collision rather than a tie to break",
            )
        }
    }
    return leaves.sortedWith { a, b -> Bytes.compareUnsigned(a.leafHash, b.leafHash) }
}

/**
 * Commits [record] reusing salts addressed by path, which is how a full copy is re-verified.
 *
 * Verification never regenerates a salt: it reads the salt from the envelope and recomputes
 * `leafHash` (section 7.3).
 */
fun commitWithSaltsByPath(
    record: JsonValue,
    context: IssuanceContext,
    resolver: TypeResolver,
    saltsByEncodedPath: Map<String, ByteArray>,
    nfc: Nfc = PlatformNfc,
    hash: HashAlgorithm = Sha256,
    emptyContainers: EmptyContainerAuthorization = EmptyContainerAuthorization.REQUIRED,
): Commitment {
    var cursor = 0
    val ordered = ArrayList<ByteArray>()
    // Two passes: the first establishes the sorted order with placeholder salts so each real salt
    // can be looked up by the path it belongs to, which is what makes the pairing independent of
    // this implementation reproducing the sort - the property section 7.2 says the explicit
    // segments in the `salts` array are worth their bytes for.
    val placeholder = ByteArray(SALT_LENGTH_BYTES)
    val shape = commit(record, context, resolver, { placeholder }, nfc, hash, emptyContainers)
    // Re-sort the shape pass back into SALT-ASSIGNMENT order, which is encodePath order under both
    // leaf orderings (section 9). `commit` returns leaves in TREE order, and under `hash` ordering
    // that is a different order computed over PLACEHOLDER salts, so consuming it positionally would
    // pair every real salt with the wrong leaf and yield a plausible wrong root rather than an
    // error. Under `path` this sort is the identity, which is why the bug was invisible until
    // ordering became selectable.
    val assignmentOrder = shape.leaves.sortedWith { a, b ->
        Bytes.compareUnsigned(a.encodedPath, b.encodedPath)
    }
    for (leaf in assignmentOrder) {
        val hex = Bytes.toHex(leaf.encodedPath)
        ordered.add(
            saltsByEncodedPath[hex] ?: fail(
                Reason.SALT_MISSING_FOR_LEAF,
                "no salt for leaf ${leaf.displayPath}",
            ),
        )
    }
    cursor = 0
    return commit(record, context, resolver, { ordered[cursor++] }, nfc, hash, emptyContainers)
}
