package io.roax.canon

import java.security.MessageDigest

/**
 * The hash `H` of ROAX-CANON/1 sections 8 and 9.
 *
 * The construction is written over `H` rather than over SHA-256 because this is a hash-agile
 * specification; `ROAX-CANON/1` **defines** `H` for `SHA-256` only.
 */
interface HashAlgorithm {
    /** The `hashAlg` identifier, which is also the tail of `DOMAIN`. */
    val id: String

    fun digest(input: ByteArray): ByteArray
}

object Sha256 : HashAlgorithm {
    override val id: String = "SHA-256"

    override fun digest(input: ByteArray): ByteArray =
        MessageDigest.getInstance("SHA-256").digest(input)
}

/**
 * `Poseidon-BN254` is **registered and unparameterized**.
 *
 * Section 7.4 is normative: a record MUST NOT be issued with this algorithm until a revision pins
 * the field, the rate and capacity, the round constants and - the part the byte layouts of
 * sections 5 through 8 do not survive without - the encoding from a length-prefixed byte string to
 * field elements. It exists here so that the identifier resolves to a *refusal* with a stated
 * reason rather than to "unknown algorithm", which is the behaviour
 * `algorithm-poseidon-fails-closed` asserts.
 */
object PoseidonBn254Unparameterized : HashAlgorithm {
    override val id: String = "Poseidon-BN254"

    override fun digest(input: ByteArray): ByteArray = fail(
        Reason.HASH_ALG_NOT_ALLOWED,
        "Poseidon-BN254 is registered but its parameterization is not pinned by ROAX-CANON/1, " +
            "so a record MUST NOT be issued against it (specification section 7.4)",
    )
}

/**
 * A verifier's own allow-list of hash algorithms.
 *
 * This is mechanism H3 of section 7.4, and it closes the case H2 does not: an algorithm that was
 * legitimately registered and has since been retired. Without it a verifier that has retired an
 * algorithm still runs it because the envelope asked it to.
 *
 * Note what this is **not**. Section 7.4 H2 requires a verifier to take `hashAlg` from the
 * anchoring registry rather than from the envelope, and section 2.2 leaves that registry
 * undesigned, so this library cannot supply it. [VerifierConfig.anchorHashAlg] is where a
 * deployment hands in the registry's answer; when it is absent the envelope's own value is used and
 * that is a *hint* being trusted, which [VerifierConfig] says in its own documentation rather than
 * pretending the binding is closed.
 */
class HashAlgorithmAllowList(private val allowed: Map<String, HashAlgorithm>) {

    fun resolve(id: String): HashAlgorithm = allowed[id] ?: fail(
        Reason.HASH_ALG_NOT_ALLOWED,
        "hashAlg '$id' is not on this verifier's allow-list",
    )

    fun contains(id: String): Boolean = allowed.containsKey(id)

    companion object {
        /**
         * The only algorithm `ROAX-CANON/1` defines a construction for.
         *
         * `Poseidon-BN254` is deliberately absent: it is registered by the envelope schema but has
         * no defined construction, so a v1 verifier's allow-list excludes it and it fails closed.
         */
        val DEFAULT: HashAlgorithmAllowList = HashAlgorithmAllowList(mapOf(Sha256.id to Sha256))
    }
}

/** ROAX-CANON/1 section 7: exactly 16 bytes, the 128-bit entropy floor. */
const val SALT_LENGTH_BYTES: Int = 16

/**
 * `DOMAIN = "ROAX-CANON/1/" ‖ hashAlg`.
 *
 * Algorithm-qualified, per sections 7, 7.4 and 8. `hashAlg` is deliberately **not** a leaf: a leaf
 * is hashed under the algorithm it names, so it cannot bind it (section 7.4).
 */
fun domain(canon: String, hashAlg: String, ordering: Ordering = Ordering.PATH): ByteArray =
    "$canon/$hashAlg${ordering.domainSuffix}".toByteArray(Charsets.US_ASCII)

/**
 * Leaf ordering, selected per record (specification section 9).
 *
 * Two first-class options, exactly as decision B makes ZK-friendly and non-ZK hashes both
 * first-class and selectable per record; the amended decision D5 rules ordering the same kind of
 * axis. [PATH] is the DEFAULT, and it is the same default in all five libraries because section 9
 * makes that normative: a default differing between implementations would be the silent divergence
 * this project exists to prevent.
 *
 * The two differ in exactly one pair of properties and neither dominates. [PATH] admits absence
 * proofs and leaks gap counts; [HASH] leaks nothing about position and forecloses absence proofs
 * permanently for records issued under it. Section 9.4 states the trade at the point of choice.
 */
enum class Ordering(val id: String, val domainSuffix: String) {
    /** Ascending `encodePath` bytes. */
    PATH("path", ""),

    /**
     * Ascending `leafHash` bytes.
     *
     * The suffix asymmetry is a stated compatibility rule rather than an accident, and section 9.5
     * argues it: [PATH] contributes the EMPTY string so that a path-ordered record's domain string
     * is byte-identical to what `ROAX-CANON/1` specified before this axis existed. Read the suffix
     * from this table; never derive it from the name.
     */
    HASH("hash", "/hash"),
    ;

    companion object {
        /**
         * Fail closed on an ordering this version does not define.
         *
         * H3 of specification section 9.5 at its narrowest: an unregistered ordering is refused
         * rather than approximated by the default.
         */
        fun parse(id: String): Ordering = entries.firstOrNull { it.id == id } ?: fail(
            Reason.ORDERING_NOT_DEFINED,
            "ROAX-CANON/1 defines no leaf ordering named $id",
        )
    }
}

/** The canonicalization version this library implements. Bound into every leaf preimage. */
const val CANON: String = "ROAX-CANON/1"

/**
 * ROAX-CANON/1 section 8.
 *
 * ```
 * leafHash(path, tag, value, salt) = H(
 *       0x00                              // RFC 9162 leaf domain byte
 *     ‖ u32be(len(DOMAIN)) ‖ DOMAIN       // DOMAIN = "ROAX-CANON/1/" ‖ hashAlg
 *     ‖ u32be(len(P))      ‖ P            // P = encodePath(path)
 *     ‖ tag                               // one byte
 *     ‖ u32be(len(salt))   ‖ salt         // 16 bytes
 *     ‖ u64be(len(V))      ‖ V            // V = encoded value bytes
 * )
 * ```
 *
 * **This is the only preimage builder in this library**, which is the shape section 8 recommends
 * on dogtag's evidence that "a second preimage builder is the drift". Salts have no preimage
 * since decision D4 was ruled D4b, so there is nothing else to build.
 */
fun leafHash(
    segments: List<Segment>,
    tag: TypeTag,
    value: RoaxValue,
    salt: ByteArray,
    hash: HashAlgorithm = Sha256,
    canon: String = CANON,
    nfc: Nfc = PlatformNfc,
    allowBlobRef: Boolean = false,
    ordering: Ordering = Ordering.PATH,
): ByteArray {
    if (salt.size != SALT_LENGTH_BYTES) {
        fail(
            Reason.SALT_LENGTH,
            "salt is ${salt.size} bytes; ROAX-CANON/1 pins exactly $SALT_LENGTH_BYTES",
        )
    }
    val encodedPath = encodePath(segments, nfc)
    val encodedValue = encodeValue(tag, value, nfc, allowBlobRef)
    val preimage = ByteSink(96 + encodedPath.size + encodedValue.size)
        .byte(0x00)
        .lengthPrefixed32(domain(canon, hash.id, ordering))
        .lengthPrefixed32(encodedPath)
        .byte(tag.code)
        .lengthPrefixed32(salt)
        .lengthPrefixed64(encodedValue)
        .toByteArray()
    return hash.digest(preimage)
}
