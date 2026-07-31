package io.roax.canon

import io.roax.canon.json.JsonArray
import io.roax.canon.json.JsonBoolean
import io.roax.canon.json.JsonNull
import io.roax.canon.json.JsonNumber
import io.roax.canon.json.JsonObject
import io.roax.canon.json.JsonString
import io.roax.canon.json.JsonValue

/** One `(path, typeTag, value)` triple, before a salt is attached. */
data class FlatLeaf(val segments: List<Segment>, val tag: TypeTag, val value: RoaxValue)

/**
 * How the flattener treats an empty container whose `(path, observed kind)` the selected map does
 * not bind.
 *
 * **This is a switch because the specification and the committed corpus disagree, and
 * `docs/typescript-implementation-findings.md` asks an implementer to expose both readings rather
 * than pick one silently.**
 *
 * ROAX-CANON/1 section 3.3 is unambiguous: an empty container gets tag 6 or 7 "only when the exact
 * selected map authorizes that structured path and observed kind under section 4.2", because
 * assigning the tag first would let an unknown empty issuer extension bypass decision D7's
 * fail-closed rule. But `corpus/type-maps/org.roax.corpus.synthetic.json` declares `a.b` for
 * `jsonKind: "null"` alone, while two class-5 fixtures carry an empty array and an empty object
 * there - so under the specification's own rule both records fail closed and have no root, and the
 * corpus asserts one.
 *
 * Under section 1.1 that is a release-blocking corpus defect, and the narrow fix is a corpus edit
 * rather than an implementation default.
 */
enum class EmptyContainerAuthorization {

    /** ROAX-CANON/1 section 3.3 as written. The default, because the specification governs. */
    REQUIRED,

    /**
     * The reading the committed corpus was built under: an empty container is tagged 6 or 7 from
     * its observed kind without consulting the map.
     *
     * Selecting this makes those two class-5 vectors pass and **weakens decision D7 exactly where
     * section 3.3 warns**, so it is named for the artifact it exists to reproduce rather than
     * offered as a general option.
     */
    CORPUS_1_0_COMPATIBILITY,
}

/** Everything the flattener needs that is not the record itself. */
data class FlattenOptions(
    val resolver: TypeResolver,
    val nfc: Nfc = PlatformNfc,
    val emptyContainers: EmptyContainerAuthorization = EmptyContainerAuthorization.REQUIRED,
)

/**
 * ROAX-CANON/1 section 3.3.
 *
 * ```
 * flatten(node, path):
 *   if node is a map and is empty:        emit (path, typeTag(path, "object"), -)
 *   if node is a map and is non-empty:    for each key k: flatten(node[k], path ‖ KEY(k))
 *   if node is an array and is empty:     emit (path, typeTag(path, "array"), -)
 *   if node is an array and is non-empty: for each index i: flatten(node[i], path ‖ INDEX(i))
 *   otherwise:                            emit (path, typeTag(path, jsonKind(node)), node)
 * ```
 *
 * Map iteration order is irrelevant, because leaves are sorted by encoded path in section 9. That
 * is deliberate: it removes the class of bug OpenAttestation inherits from JavaScript key
 * enumeration, and it is why a Go implementation works despite Go randomising map iteration.
 *
 * This produces the record's leaves **only**. The leaf set is the union of these and the reserved
 * leaves of section 11.2, and the union is formed before the sort - see [commit].
 */
fun flattenRecord(record: JsonValue, options: FlattenOptions): List<FlatLeaf> {
    val out = ArrayList<FlatLeaf>()
    flatten(record, emptyList(), options, out)
    return out
}

private fun flatten(
    node: JsonValue,
    segments: List<Segment>,
    options: FlattenOptions,
    out: MutableList<FlatLeaf>,
) {
    when (node) {
        is JsonObject -> {
            if (node.isEmpty) {
                out.add(FlatLeaf(segments, emptyContainerTag(segments, JsonKind.OBJECT, options), RoaxValue.EmptyObject))
                return
            }
            for (member in node.members) {
                // The guard checks the FIRST segment only, because every reserved path is a single
                // segment (section 11.2).
                if (segments.isEmpty()) Reserved.guardFirstSegment(member.key, options.nfc)
                flatten(member.value, segments + Segment.Key(member.key), options, out)
            }
        }

        is JsonArray -> {
            if (node.isEmpty) {
                out.add(FlatLeaf(segments, emptyContainerTag(segments, JsonKind.ARRAY, options), RoaxValue.EmptyArray))
                return
            }
            node.elements.forEachIndexed { i, element ->
                flatten(element, segments + Segment.Index(i.toLong()), options, out)
            }
        }

        else -> out.add(scalarLeaf(node, segments, options))
    }
}

private fun emptyContainerTag(
    segments: List<Segment>,
    kind: JsonKind,
    options: FlattenOptions,
): TypeTag {
    val fallback = if (kind == JsonKind.ARRAY) TypeTag.EMPTY_ARRAY else TypeTag.EMPTY_OBJECT
    val resolved = options.resolver.resolve(segments, kind)
    if (resolved != null) {
        if (resolved != fallback) {
            fail(
                Reason.TYPE_TAG_KIND_MISMATCH,
                "${displayPath(segments)} is an empty ${kind.label} but the map binds " +
                    "tag ${resolved.code} ${resolved.name} there",
            )
        }
        return resolved
    }
    return when (options.emptyContainers) {
        EmptyContainerAuthorization.REQUIRED -> failClosed(segments, kind)
        EmptyContainerAuthorization.CORPUS_1_0_COMPATIBILITY -> fallback
    }
}

private fun scalarLeaf(node: JsonValue, segments: List<Segment>, options: FlattenOptions): FlatLeaf {
    val kind = JsonKind.of(node)
    val tag = options.resolver.resolve(segments, kind) ?: failClosed(segments, kind)

    // The tag comes from the schema, not from the JSON literal's syntax (section 4). What is
    // checked here is only that the tag can CARRY the observed kind: a map that bound a string
    // path to INTEGER would otherwise silently reinterpret the value.
    val value: RoaxValue = when (node) {
        is JsonString -> when (tag) {
            TypeTag.STRING -> RoaxValue.Text(node.value)
            // The ruled FHIR `base64Binary` binding (grade Strong): BYTES over the DECODED octets,
            // with canonical RFC 4648 base64 as an input-admissibility condition. The octets are
            // what gets hashed; a spelling outside the pinned form is refused before it is decoded.
            TypeTag.BYTES -> RoaxValue.Bytes(Base64Strict.decode(node.value))
            else -> tagKindMismatch(segments, tag, kind)
        }

        is JsonNumber -> when (tag) {
            TypeTag.INTEGER -> RoaxValue.Integer(node.literal)
            TypeTag.DECIMAL -> RoaxValue.Decimal(node.literal)
            else -> tagKindMismatch(segments, tag, kind)
        }

        is JsonBoolean -> when (tag) {
            TypeTag.BOOL -> RoaxValue.Bool(node.value)
            else -> tagKindMismatch(segments, tag, kind)
        }

        is JsonNull -> when (tag) {
            TypeTag.NULL -> RoaxValue.Null
            else -> tagKindMismatch(segments, tag, kind)
        }

        else -> throw IllegalStateException("container reached the scalar path")
    }

    if (tag == TypeTag.BLOB_REF) {
        fail(
            Reason.BLOB_REF_NOT_DECLARED,
            "${displayPath(segments)} resolves to tag 8 BLOB_REF, which no version-1 profile " +
                "declares (specification section 6.5)",
        )
    }
    return FlatLeaf(segments, tag, value)
}

private fun failClosed(segments: List<Segment>, kind: JsonKind): Nothing = fail(
    Reason.TYPE_MAP_FAIL_CLOSED,
    "the selected type map has no binding for ${displayPath(segments)} at observed kind " +
        "'${kind.label}' (specification section 4.2, ruled decision D7)",
)

private fun tagKindMismatch(segments: List<Segment>, tag: TypeTag, kind: JsonKind): Nothing = fail(
    Reason.TYPE_TAG_KIND_MISMATCH,
    "the map binds ${displayPath(segments)} to tag ${tag.code} ${tag.name}, which cannot carry " +
        "an observed ${kind.label}",
)
