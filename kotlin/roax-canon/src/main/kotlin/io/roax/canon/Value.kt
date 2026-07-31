package io.roax.canon

/** ROAX-CANON/1 section 6.1. */
enum class TypeTag(val code: Int) {
    NULL(0),
    BOOL(1),
    STRING(2),
    INTEGER(3),
    DECIMAL(4),
    BYTES(5),
    EMPTY_ARRAY(6),
    EMPTY_OBJECT(7),

    /**
     * REGISTERED and selected by no version-1 profile.
     *
     * Section 6.5 is normative: an implementation MUST reject a record whose type map binds any
     * path to tag 8, and MUST reject an envelope carrying a tag-8 leaf, until a profile document
     * under `docs/profiles/` declares the binding. The construction is implemented in
     * [RoaxValue.BlobRef] so it does not have to be retrofitted after five independent
     * implementations exist, and it is refused at every issuance and verification entry point.
     */
    BLOB_REF(8),
    ;

    companion object {
        private val BY_CODE = entries.associateBy { it.code }

        fun ofCode(code: Int): TypeTag =
            ofCodeOrNull(code) ?: throw IllegalArgumentException("no ROAX type tag with code $code")

        /** The total form, for a caller that must report an unknown code through a [Reason]. */
        fun ofCodeOrNull(code: Int): TypeTag? = BY_CODE[code]
    }
}

/**
 * A leaf's value, in the form the tag selects.
 *
 * Numbers are carried as their **verbatim literal text**, never as a machine number, per
 * section 6.4's normative prohibition on parsing record numbers through any floating-point type.
 */
sealed interface RoaxValue {
    data object Null : RoaxValue

    data class Bool(val value: Boolean) : RoaxValue

    data class Text(val value: String) : RoaxValue

    /** The literal as written in the record, canonicalized by [Numbers.canonicalInteger]. */
    data class Integer(val literal: String) : RoaxValue

    /** The literal as written in the record, canonicalized by [Numbers.canonicalDecimal]. */
    data class Decimal(val literal: String) : RoaxValue

    data class Bytes(val value: ByteArray) : RoaxValue {
        override fun equals(other: Any?): Boolean =
            this === other || (other is Bytes && value.contentEquals(other.value))

        override fun hashCode(): Int = value.contentHashCode()
    }

    data object EmptyArray : RoaxValue

    data object EmptyObject : RoaxValue

    /** Section 6.5. Constructible so the form is pinned; refused by every v1 code path. */
    data class BlobRef(val blobByteLength: Long, val blobDigest: ByteArray) : RoaxValue {
        override fun equals(other: Any?): Boolean = this === other ||
            (other is BlobRef && blobByteLength == other.blobByteLength &&
                blobDigest.contentEquals(other.blobDigest))

        override fun hashCode(): Int = 31 * blobByteLength.hashCode() + blobDigest.contentHashCode()
    }
}

/**
 * ROAX-CANON/1 section 6.1, the encoded value bytes for a tag.
 *
 * [allowBlobRef] exists only so the tag-8 construction can be exercised by a test that asserts the
 * byte layout of section 6.5. It defaults to false, and every issuance and verification path in
 * this library leaves it false, which is what section 6.5 requires of a v1 implementation.
 */
fun encodeValue(
    tag: TypeTag,
    value: RoaxValue,
    nfc: Nfc = PlatformNfc,
    allowBlobRef: Boolean = false,
): ByteArray = when (tag) {
    TypeTag.NULL -> {
        expect(value is RoaxValue.Null, tag, value)
        ByteArray(0)
    }

    TypeTag.BOOL -> {
        expect(value is RoaxValue.Bool, tag, value)
        byteArrayOf(if ((value as RoaxValue.Bool).value) 0x01 else 0x00)
    }

    TypeTag.STRING -> {
        expect(value is RoaxValue.Text, tag, value)
        val raw = (value as RoaxValue.Text).value
        utf8Strict(nfc.normalize(requirePairedSurrogates(raw, "string value")), "string value")
    }

    TypeTag.INTEGER -> {
        expect(value is RoaxValue.Integer, tag, value)
        Numbers.canonicalInteger((value as RoaxValue.Integer).literal).toByteArray(Charsets.US_ASCII)
    }

    TypeTag.DECIMAL -> {
        expect(value is RoaxValue.Decimal, tag, value)
        Numbers.canonicalDecimal((value as RoaxValue.Decimal).literal).toByteArray(Charsets.US_ASCII)
    }

    TypeTag.BYTES -> {
        expect(value is RoaxValue.Bytes, tag, value)
        (value as RoaxValue.Bytes).value.copyOf()
    }

    TypeTag.EMPTY_ARRAY -> {
        expect(value is RoaxValue.EmptyArray, tag, value)
        ByteArray(0)
    }

    TypeTag.EMPTY_OBJECT -> {
        expect(value is RoaxValue.EmptyObject, tag, value)
        ByteArray(0)
    }

    TypeTag.BLOB_REF -> {
        if (!allowBlobRef) {
            fail(
                Reason.BLOB_REF_NOT_DECLARED,
                "tag 8 BLOB_REF is registered and selected by no version-1 profile " +
                    "(specification section 6.5)",
            )
        }
        expect(value is RoaxValue.BlobRef, tag, value)
        val v = value as RoaxValue.BlobRef
        ByteSink(16 + v.blobDigest.size)
            .bytes(Bytes.u64be(v.blobByteLength))
            .lengthPrefixed32(v.blobDigest)
            .toByteArray()
    }
}

private fun expect(condition: Boolean, tag: TypeTag, value: RoaxValue) {
    if (!condition) {
        fail(
            Reason.TYPE_TAG_KIND_MISMATCH,
            "tag ${tag.code} ${tag.name} cannot encode a ${value::class.simpleName}",
        )
    }
}
