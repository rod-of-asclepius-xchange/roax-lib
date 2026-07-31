package io.roax.canon.conformance

import io.roax.canon.Bytes
import io.roax.canon.DisplayPatternTypeMap
import io.roax.canon.Nfc
import io.roax.canon.PlatformNfc
import io.roax.canon.Profile
import io.roax.canon.ProfileRegistry
import io.roax.canon.Reason
import io.roax.canon.RoaxValue
import io.roax.canon.SALT_LENGTH_BYTES
import io.roax.canon.Segment
import io.roax.canon.TypeResolver
import io.roax.canon.TypeTag
import io.roax.canon.json.JsonArray
import io.roax.canon.json.JsonBoolean
import io.roax.canon.json.JsonNumber
import io.roax.canon.json.JsonObject
import io.roax.canon.json.JsonReader
import io.roax.canon.json.JsonString
import io.roax.canon.json.JsonValue
import java.io.File

/**
 * The committed conformance corpus, loaded from the repository tree.
 *
 * `corpus/README.md` is explicit about what this directory is: if ROAX ships five independent
 * libraries it is the whole enforcement mechanism for cross-language agreement, not a safety net.
 * This library was written from `docs/spec/roax-canon-1.md` alone and validated against the corpus
 * afterwards, which is what makes a pass evidence of anything.
 */
object Corpus {

    /** The repository root, found by walking up until `corpus/conformance-corpus-1.0.json` exists. */
    val root: File by lazy {
        var dir: File? = File(".").absoluteFile
        while (dir != null) {
            if (File(dir, "corpus/conformance-corpus-1.0.json").isFile) return@lazy dir
            dir = dir.parentFile
        }
        throw IllegalStateException(
            "could not find the repository root from ${File(".").absolutePath}",
        )
    }

    fun file(relative: String): File = File(root, relative)

    fun bytes(relative: String): ByteArray = file(relative).readBytes()

    val document: JsonObject by lazy {
        JsonReader.parse(bytes("corpus/conformance-corpus-1.0.json")) as JsonObject
    }

    val corpusVersion: String get() = str(document, "corpusVersion")

    val canon: String get() = str(document, "canon")

    val hashAlg: String get() = str(document, "hashAlg")

    /** The Unicode version the corpus was generated under. Section 6.1 pins it; see [unicodeGate]. */
    val unicodeVersion: String get() = str(document, "unicodeVersion")

    fun vectors(name: String): List<JsonObject> {
        val all = document["vectors"] as JsonObject
        return ((all[name] as? JsonArray)?.elements ?: emptyList()).map { it as JsonObject }
    }

    /**
     * The type maps class 10 and class 11 assert against.
     *
     * These are `schemas/type-map-1.0.json` display-pattern files, which that schema itself calls
     * superseded and says MUST NOT be used to resolve. Every vector needing a map resolves against
     * one, and no published structured-path artifact exists for `org.roax.corpus.synthetic` at all,
     * so no conforming DFA resolver can reach a single corpus record. That is a release-blocking
     * corpus defect under specification section 1.1, recorded identically in
     * `docs/typescript-implementation-findings.md`, and it is the reason
     * [io.roax.canon.TypeResolver] is an interface.
     */
    // Keyed on the [Nfc] INSTANCE as well as the record type. Two normalizers can report the same
    // Unicode version and still disagree - `RawNfc` reports one and normalizes nothing - so a cache
    // hit that ignored the requested one would hand a D14a test the opposite matcher and pass.
    private val typeMaps = HashMap<Pair<String, Nfc>, TypeResolver>()

    fun typeMap(recordType: String, nfc: Nfc = PlatformNfc): TypeResolver =
        typeMaps.getOrPut(recordType to nfc) {
            DisplayPatternTypeMap.load(bytes("corpus/type-maps/$recordType.json"), nfc)
        }

    /**
     * The verifier's profile allow-list for corpus runs.
     *
     * `org.roax.corpus.synthetic` is added here and **only** here. It is a corpus-only
     * `recordType`, deliberately absent from the `docs/profiles/` registry so that structural
     * vectors do not borrow a real health authority's identifier, and a record MUST NOT be issued
     * under it. Its floor is the reserved paths alone, because it declares no profile-specific
     * non-redactable path.
     */
    val profiles: ProfileRegistry =
        ProfileRegistry.DEFAULT.with(Profile("org.roax.corpus.synthetic", emptyList()))

    // --- salt sets ------------------------------------------------------------------------------

    sealed interface SaltSet {
        /** Paired by structured path, which is `schemas/envelope-1.0.json`'s `$defs.leafSalt` shape. */
        class ByPath(val byEncodedPath: Map<String, ByteArray>) : SaltSet

        /** The corpus-only positional carrier defined by `docs/conformance-corpus.md` class 10. */
        class Positional(val salts: List<ByteArray>, val leafCount: Int) : SaltSet
    }

    fun saltSet(relative: String, nfc: Nfc = PlatformNfc): SaltSet {
        val o = JsonReader.parse(bytes(relative)) as JsonObject
        val entries = (o["salts"] as JsonArray).elements
        return when (val pairing = str(o, "pairing")) {
            "path" -> SaltSet.ByPath(
                entries.associate { e ->
                    val entry = e as JsonObject
                    val segments = readSegments(entry["segments"]!!)
                    Bytes.toHex(io.roax.canon.encodePath(segments, nfc)) to hex(str(entry, "salt"))
                },
            )

            "positional" -> SaltSet.Positional(
                entries.map { hex((it as JsonString).value) },
                (o["leafCount"] as JsonNumber).literal.toInt(),
            )

            else -> throw IllegalArgumentException("unknown salt pairing '$pairing'")
        }
    }

    // --- input escape forms ---------------------------------------------------------------------

    /**
     * `corpus/README.md`, "Input escape forms": three values cannot appear literally in a JSON file.
     *
     * `{"$utf16": ["0041", "d800"]}` is how an unpaired surrogate is carried, because a conforming
     * JSON writer cannot emit one as well-formed UTF-8.
     */
    fun utf16(v: JsonValue): String? {
        val o = v as? JsonObject ?: return null
        val units = (o["\$utf16"] as? JsonArray)?.elements ?: return null
        val sb = StringBuilder(units.size)
        for (u in units) sb.append(((u as JsonString).value).toInt(16).toChar())
        return sb.toString()
    }

    fun jsonText(v: JsonValue): String? =
        ((v as? JsonObject)?.get("\$jsonText") as? JsonString)?.value

    fun segmentsEscape(v: JsonValue): JsonValue? = (v as? JsonObject)?.get("\$segments")

    /** A string carried either literally or as `$utf16`. */
    fun text(v: JsonValue): String = utf16(v) ?: (v as JsonString).value

    fun readSegments(v: JsonValue): List<Segment> {
        val array = v as? JsonArray ?: throw IllegalArgumentException("segments is not an array")
        return array.elements.map { element ->
            val o = element as JsonObject
            val k = o["key"]
            val i = o["index"]
            when {
                k != null -> Segment.Key(utf16(k) ?: (k as JsonString).value)
                i != null -> Segment.Index((i as JsonNumber).literal.toLong())
                else -> throw IllegalArgumentException("segment carries neither 'key' nor 'index'")
            }
        }
    }

    /** The value carrier a [TypeTag] uses in `leaf` and `encodeValue` vectors. */
    fun value(tag: TypeTag, raw: JsonValue?): RoaxValue = when (tag) {
        TypeTag.NULL -> RoaxValue.Null
        TypeTag.EMPTY_ARRAY -> RoaxValue.EmptyArray
        TypeTag.EMPTY_OBJECT -> RoaxValue.EmptyObject
        TypeTag.BOOL -> RoaxValue.Bool((raw as JsonBoolean).value)
        TypeTag.STRING -> RoaxValue.Text(text(raw!!))
        TypeTag.INTEGER -> RoaxValue.Integer(text(raw!!))
        TypeTag.DECIMAL -> RoaxValue.Decimal(text(raw!!))
        // The corpus carries BYTES as HEX, not as base64: base64 admissibility is a separate
        // question with its own rejection vectors, and a hex carrier keeps the two apart.
        TypeTag.BYTES -> RoaxValue.Bytes(hex((raw as JsonString).value))
        TypeTag.BLOB_REF -> throw IllegalArgumentException("no corpus vector carries tag 8")
    }

    // --- small readers --------------------------------------------------------------------------

    fun str(o: JsonObject, name: String): String = (o[name] as JsonString).value

    fun strOrNull(o: JsonObject, name: String): String? = (o[name] as? JsonString)?.value

    fun int(o: JsonObject, name: String): Int = (o[name] as JsonNumber).literal.toInt()

    fun bool(o: JsonObject, name: String): Boolean = (o[name] as JsonBoolean).value

    fun boolOrNull(o: JsonObject, name: String): Boolean? = (o[name] as? JsonBoolean)?.value

    fun hex(s: String): ByteArray = Bytes.fromHex(s)

    fun hexList(o: JsonObject, name: String): List<ByteArray> =
        ((o[name] as? JsonArray)?.elements ?: emptyList()).map { hex((it as JsonString).value) }

    /**
     * Whether this runtime's NFC tables are the version the corpus pins.
     *
     * Specification section 6.1 makes a Unicode version mismatch detectable **by declaration**
     * rather than by demonstration, and this is that declaration. It is reported rather than
     * enforced, because no JDK ships the pinned 15.1: JDK 17 has Unicode 13.0 and JDK 25 has 16.0.
     * `RoaxLibraryTest.nfc tables agree across the two available JDK Unicode versions` measures
     * what that costs on this input set.
     */
    fun unicodeGate(nfc: Nfc = PlatformNfc): String =
        if (nfc.unicodeVersion == unicodeVersion) {
            "pinned ${nfc.unicodeVersion}"
        } else {
            "runtime ${nfc.unicodeVersion} against corpus pin $unicodeVersion"
        }

    fun requireSaltLength(salt: ByteArray) {
        require(salt.size == SALT_LENGTH_BYTES) { "salt is ${salt.size} bytes" }
    }
}

/**
 * The DECLARED equivalence between a corpus `reason` and this library's [Reason].
 *
 * `corpus/README.md` measures that four implementations name the fail-closed condition four
 * different ways and non-canonical base64 two ways, and states the consequence: a corpus `reason`
 * is the reference implementations' spelling and is not a normative code, so each library carries a
 * declared table beside that measurement rather than a loosened comparison.
 *
 * This is that table. It maps one reference code to the one local code naming the same condition,
 * and **a rejection for a different reason still fails**.
 */
object ReasonEquivalence {

    private val TABLE: Map<String, Reason> = buildMap {
        // Identical spellings, listed so the whole taxonomy is visible in one place.
        for (r in Reason.entries) put(r.code, r)

        // The two measured divergences.
        //
        // `roax_ref.py` and `roax_ref.mjs` say `type-map-uncovered-path`; the Python library says
        // `type-unresolved`; the TypeScript and Rust libraries say `type-map-fail-closed`, which is
        // the spelling this library adopted.
        put("type-map-uncovered-path", Reason.TYPE_MAP_FAIL_CLOSED)
        put("type-unresolved", Reason.TYPE_MAP_FAIL_CLOSED)
        // Rust says `invalid-base64` where everyone else says `base64-not-canonical`.
        put("invalid-base64", Reason.BASE64_NOT_CANONICAL)
    }

    fun expect(corpusReason: String): Reason = TABLE[corpusReason]
        ?: throw IllegalArgumentException(
            "no declared local equivalent for corpus reason '$corpusReason' - add one to " +
                "ReasonEquivalence rather than loosening the comparison",
        )
}
