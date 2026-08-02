package io.roax.canon

/** One revealed leaf of a disclosed copy, with everything a verifier needs to recompute it. */
class DisclosedLeaf internal constructor(
    val segments: List<Segment>,
    val index: Int,
    val tag: TypeTag,
    val value: RoaxValue,
    val salt: ByteArray,
    val auditPath: List<ByteArray>,
) {
    val displayPath: String get() = displayPath(segments)
}

/** A selective disclosure over a sealed [Commitment]. */
class DisclosedCopy internal constructor(
    val context: IssuanceContext,
    val root: ByteArray,
    val leafCount: Int,
    val leaves: List<DisclosedLeaf>,
)

/**
 * ROAX-CANON/1 section 10: reveal [paths] and nothing else.
 *
 * **The context is not a parameter.** A [Commitment] retains the exact context it was issued under
 * and this function accepts no replacement, because accepting a second caller-supplied context lets
 * safe values from two issuances be mixed into an envelope that its own verifier then rejects at
 * outer-identity binding (sections 10 and 11.3).
 *
 * Each revealed leaf carries **its own salt and no other**. That second half is the load-bearing
 * one: a disclosed copy that shipped every salt would still verify correctly against the root,
 * because salts do not change any leaf hash, while leaking every withheld field in the record to a
 * dictionary search. Nothing about the verification result would indicate a problem.
 */
fun Commitment.disclose(paths: List<List<Segment>>, nfc: Nfc = PlatformNfc): DisclosedCopy {
    val wanted = paths.map { Bytes.toHex(encodePath(it, nfc)) }.toSet()
    val revealed = ArrayList<DisclosedLeaf>(wanted.size)

    leaves.forEachIndexed { i, leaf ->
        if (Bytes.toHex(leaf.encodedPath) !in wanted) return@forEachIndexed
        revealed.add(
            DisclosedLeaf(
                segments = leaf.segments,
                index = i,
                tag = leaf.tag,
                value = leaf.value,
                salt = leaf.salt,
                auditPath = auditPath(i),
            ),
        )
    }

    if (revealed.size != wanted.size) {
        val found = revealed.map { Bytes.toHex(encodePath(it.segments, nfc)) }.toSet()
        val missing = paths.filter { Bytes.toHex(encodePath(it, nfc)) !in found }
        fail(
            Reason.ENVELOPE_SHAPE,
            "cannot disclose ${missing.joinToString { displayPath(it) }}: no such leaf in this commitment",
        )
    }

    return DisclosedCopy(context, root, leafCount, revealed)
}

/**
 * Serializes an envelope.
 *
 * A full copy embeds the record's **original bytes verbatim** rather than reserializing a parsed
 * tree. That is not an optimization: section 7.3 notes that the record body of a full copy carries
 * record numbers in their original JSON form, so the section 6.4 parser requirement applies to the
 * envelope and not only to a bare record. Reserializing through any numeric type would destroy the
 * very literals the root was computed from.
 */
object EnvelopeWriter {

    /**
     * A full copy: the whole record plus the salt of **every** leaf.
     *
     * Without every salt a full copy is not verifiable at all - `leafHash` needs the leaf's salt
     * and the record body carries none, so a verifier would have no route to any leaf hash and
     * therefore none to the root.
     */
    fun fullCopy(commitment: Commitment, recordBytes: ByteArray, nfc: Nfc = PlatformNfc): String {
        val sb = StringBuilder(recordBytes.size + commitment.leafCount * 160)
        sb.append('{')
        header(sb, commitment)
        sb.append(",\"record\":").append(decodeUtf8Strict(recordBytes).trim())
        sb.append(",\"salts\":[")
        commitment.leaves.forEachIndexed { i, leaf ->
            if (i > 0) sb.append(',')
            sb.append("{\"segments\":")
            segments(sb, leaf.segments)
            sb.append(",\"salt\":\"").append(Bytes.toHex(leaf.salt)).append("\"}")
        }
        sb.append("]}")
        return sb.toString()
    }

    /** A disclosed copy: the revealed leaves, their salts and their audit paths, and nothing else. */
    fun disclosedCopy(copy: DisclosedCopy, nfc: Nfc = PlatformNfc): String {
        val sb = StringBuilder(copy.leaves.size * 320)
        sb.append('{')
        header(sb, copy.context, copy.root, copy.leafCount)
        sb.append(",\"disclosure\":{\"mode\":\"selective\",\"leaves\":[")
        copy.leaves.forEachIndexed { i, leaf ->
            if (i > 0) sb.append(',')
            sb.append("{\"segments\":")
            segments(sb, leaf.segments)
            // Display only, and never an input to anything the verifier computes (section 5.2).
            sb.append(",\"displayPath\":")
            string(sb, leaf.displayPath)
            sb.append(",\"index\":").append(leaf.index)
            sb.append(",\"tag\":").append(leaf.tag.code)
            value(sb, leaf.tag, leaf.value)
            sb.append(",\"salt\":\"").append(Bytes.toHex(leaf.salt)).append('"')
            sb.append(",\"auditPath\":[")
            leaf.auditPath.forEachIndexed { j, h ->
                if (j > 0) sb.append(',')
                sb.append('"').append(Bytes.toHex(h)).append('"')
            }
            sb.append("]}")
        }
        // No `salts` array here, deliberately. Its absence makes a withheld leaf's salt
        // UNREPRESENTABLE in a disclosed copy rather than merely prohibited: the per-leaf `salt`
        // above is then the only place a salt can appear, and every entry there belongs by
        // construction to a leaf being revealed. Adding one "for symmetry" reopens the hole.
        sb.append("]}}")
        return sb.toString()
    }

    private fun header(sb: StringBuilder, commitment: Commitment) =
        header(sb, commitment.context, commitment.root, commitment.leafCount)

    private fun header(sb: StringBuilder, ctx: IssuanceContext, root: ByteArray, leafCount: Int) {
        sb.append("\"canon\":").also { string(sb, ctx.canon) }
        sb.append(",\"hashAlg\":").also { string(sb, ctx.hashAlgId) }
        if (ctx.identity.ordering != Ordering.PATH) {
            // SELF-DESCRIPTION, and NOT AUTHORITY. A verifier takes the ordering from the
            // anchoring registry (specification section 9.5, H2); [EnvelopeVerifier] never reads
            // this member, and nothing here reads it back to select an ordering.
            //
            // Emitted only for a NON-DEFAULT ordering, so a path-ordered envelope stays
            // byte-identical to what this library issued before the axis existed - the same
            // ROAX-CANON/1 compatibility rule that gives `path` the empty domain suffix.
            // Omitting it on a `hash`-ordered copy would not be silence: both envelope schemas
            // define the member's ABSENCE as meaning `path`, so such a copy would ASSERT an
            // ordering it was not issued under. A self-description that lies is worse than none
            // even where nothing reads it, which is the reasoning section 7.4 used to reject a
            // `roax.hashAlg` reserved leaf.
            sb.append(",\"ordering\":").also { string(sb, ctx.identity.ordering.id) }
        }
        sb.append(",\"recordType\":").also { string(sb, ctx.identity.recordType) }
        sb.append(",\"schemaVersion\":").also { string(sb, ctx.identity.schemaVersion) }
        sb.append(",\"recordId\":").also { string(sb, ctx.identity.recordId) }
        if (ctx.envelopeProfile.bindsTypeMapId) {
            // BOTH members, and FAIL CLOSED without either. `schemas/envelope-1.0.json` requires
            // `id` and `version` together whenever `typeMap` is present, so emitting the
            // identifier alone produced a schema-invalid envelope - which nothing caught until
            // conformance corpus class 20 asked this library to produce one and compare it
            // against a committed copy. Coercing an absent version to the empty string is the
            // same defect one layer down: `""` fails the schema's `^[0-9]+\.[0-9]+\.[0-9]+$` and
            // no verifier here reads the member, so the library would accept its own invalid
            // output. [Reserved.leavesFor] already refuses an absent `typeMapId` under this
            // profile, and the version is refused on the same terms.
            val id = ctx.identity.typeMapId ?: fail(
                Reason.ENVELOPE_SHAPE,
                "envelope profile ${ctx.envelopeProfile} requires typeMap.id, which selects and " +
                    "authenticates the exact artifact (specification section 4.2)",
            )
            val version = ctx.identity.typeMapVersion ?: fail(
                Reason.ENVELOPE_SHAPE,
                "envelope profile ${ctx.envelopeProfile} emits the `typeMap` member, which " +
                    "carries `id` and `version` together, so RecordIdentity.typeMapVersion is " +
                    "required (schemas/envelope-1.0.json)",
            )
            sb.append(",\"typeMap\":{\"id\":")
            string(sb, id)
            sb.append(",\"version\":")
            string(sb, version)
            sb.append('}')
        }
        sb.append(",\"root\":\"").append(Bytes.toHex(root)).append('"')
        sb.append(",\"leafCount\":").append(leafCount)
        sb.append(",\"issuer\":{\"id\":")
        string(sb, ctx.identity.issuerId)
        ctx.identity.issuerKeyId?.let {
            sb.append(",\"keyId\":")
            string(sb, it)
        }
        sb.append('}')
    }

    private fun segments(sb: StringBuilder, segments: List<Segment>) {
        sb.append('[')
        segments.forEachIndexed { i, s ->
            if (i > 0) sb.append(',')
            when (s) {
                is Segment.Key -> {
                    sb.append("{\"key\":")
                    string(sb, s.key)
                    sb.append('}')
                }

                is Segment.Index -> sb.append("{\"index\":").append(s.index).append('}')
            }
        }
        sb.append(']')
    }

    private fun value(sb: StringBuilder, tag: TypeTag, v: RoaxValue) {
        when (tag) {
            // A valueless tag carries no `value` member at all. Emitting one as null would make a
            // NULL leaf and an EMPTY_OBJECT leaf indistinguishable on the wire.
            TypeTag.NULL, TypeTag.EMPTY_ARRAY, TypeTag.EMPTY_OBJECT -> return
            TypeTag.BOOL -> sb.append(",\"value\":").append((v as RoaxValue.Bool).value)
            TypeTag.STRING -> {
                sb.append(",\"value\":")
                string(sb, (v as RoaxValue.Text).value)
            }
            // Carried as a STRING, which is what the corpus does and for the same reason: a JSON
            // number here would be destroyed by a reader that parses it through a float.
            TypeTag.INTEGER -> {
                sb.append(",\"value\":")
                string(sb, Numbers.canonicalInteger((v as RoaxValue.Integer).literal))
            }

            TypeTag.DECIMAL -> {
                sb.append(",\"value\":")
                string(sb, Numbers.canonicalDecimal((v as RoaxValue.Decimal).literal))
            }

            // LOWERCASE HEX, not base64, and this used to be base64.
            //
            // The disclosure carrier is per tag and is NOT the record's own spelling: a record
            // spells `base64Binary` in RFC 4648 form, the leaf commits the DECODED OCTETS, and
            // `schemas/envelope-1.0.json` pins the carrier to "lowercase hex of even length".
            // Emitting base64 here produced a copy this library's own verifier rejected, and no
            // vector could see it because until conformance corpus class 20 nothing asked this
            // library to PRODUCE a disclosed copy. The pinned base64 form is an
            // input-admissibility condition on the record, not the committed value (section 6.3).
            TypeTag.BYTES -> {
                sb.append(",\"value\":")
                string(sb, Bytes.toHex((v as RoaxValue.Bytes).value))
            }

            TypeTag.BLOB_REF -> fail(
                Reason.BLOB_REF_NOT_DECLARED,
                "no version-1 profile declares tag 8 (specification section 6.5)",
            )
        }
    }

    /** RFC 8259 string escaping. Refuses an unpaired surrogate rather than emitting one. */
    private fun string(sb: StringBuilder, s: String) {
        requirePairedSurrogates(s, "envelope string")
        sb.append('"')
        for (c in s) {
            when {
                c == '"' -> sb.append("\\\"")
                c == '\\' -> sb.append("\\\\")
                c == '\n' -> sb.append("\\n")
                c == '\r' -> sb.append("\\r")
                c == '\t' -> sb.append("\\t")
                c == '\b' -> sb.append("\\b")
                c == '\u000C' -> sb.append("\\f")
                c.code < 0x20 -> sb.append("\\u").append("%04x".format(c.code))
                else -> sb.append(c)
            }
        }
        sb.append('"')
    }
}
