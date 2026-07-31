package io.roax.canon

import io.roax.canon.json.JsonArray
import io.roax.canon.json.JsonBoolean
import io.roax.canon.json.JsonNull
import io.roax.canon.json.JsonNumber
import io.roax.canon.json.JsonObject
import io.roax.canon.json.JsonReader
import io.roax.canon.json.JsonString
import io.roax.canon.json.JsonValue

/** The observed JSON kind of a value, which is the second half of a type-map lookup key. */
enum class JsonKind(val label: String) {
    STRING("string"),
    NUMBER("number"),
    BOOLEAN("boolean"),
    NULL("null"),
    OBJECT("object"),
    ARRAY("array"),
    ;

    companion object {
        private val BY_LABEL = entries.associateBy { it.label }

        fun ofLabel(label: String): JsonKind =
            BY_LABEL[label] ?: throw IllegalArgumentException("unknown JSON kind '$label'")

        fun of(value: JsonValue): JsonKind = when (value) {
            is JsonString -> STRING
            is JsonNumber -> NUMBER
            is JsonBoolean -> BOOLEAN
            is JsonNull -> NULL
            is JsonObject -> OBJECT
            is JsonArray -> ARRAY
        }
    }
}

/**
 * Resolves a structured path and an observed JSON kind to a ROAX type tag.
 *
 * **Fail-closed is the contract**: `null` means no binding, and a caller MUST refuse the record
 * rather than searching another installed map, inferring from JSON syntax or applying a fallback
 * tag (ROAX-CANON/1 section 4.2, ruled decision D7).
 *
 * This is an interface for a reason recorded in `docs/typescript-implementation-findings.md`:
 * the operative format is the structured-path DFA of `schemas/type-map-artifact-1.0.json`, while
 * every committed corpus vector resolves against `corpus/type-maps/<recordType>.json`, which is
 * the display-pattern format `schemas/type-map-1.0.json` itself calls superseded and says MUST NOT
 * be used to resolve. Both implementations live behind this interface so that the operative one is
 * not quietly replaced by the corpus one.
 */
interface TypeResolver {
    fun resolve(segments: List<Segment>, kind: JsonKind): TypeTag?
}

/**
 * The **operative** resolver: the structured-path DFA of `schemas/type-map-artifact-1.0.json`,
 * as defined by `docs/type-maps.md` section 3.
 */
class DfaTypeMap private constructor(
    val recordType: String,
    val schemaVersion: String,
    val typeMapVersion: String,
    /** `sha256:<64 lowercase hex>` over `utf8("ROAX-TYPE-MAP/1") ‖ 0x00 ‖ exactArtifactBytes`. */
    val contentId: String,
    private val start: String,
    private val states: Map<String, State>,
    private val nfc: Nfc,
) : TypeResolver {

    private class State(
        val keys: Map<String, String>,
        val anyIndex: String?,
        val bindings: Map<JsonKind, TypeTag>,
    )

    override fun resolve(segments: List<Segment>, kind: JsonKind): TypeTag? {
        var current = states[start] ?: return null
        for (segment in segments) {
            val next = when (segment) {
                // Step 2: NFC-normalize the key under the section 6.1 pin and take the one
                // transition whose key equals it. Ruled decision D14a; comparing the bytes as
                // received would decide admissibility on a spelling no root ever records.
                is Segment.Key -> current.keys[nfc.normalize(segment.key)]
                is Segment.Index -> current.anyIndex
            } ?: return null // step 4: fail closed immediately
            current = states[next] ?: return null
        }
        // Steps 5 and 6: exactly one binding per observed kind, or fail closed - even when the tag
        // seems mechanically obvious from JSON syntax.
        return current.bindings[kind]
    }

    companion object {

        /**
         * `utf8("ROAX-TYPE-MAP/1")` followed by a NUL byte, written as an explicit escape
         * so the separator is visible in the source rather than an invisible byte.
         */
        private val CONTENT_ID_PREFIX =
            "ROAX-TYPE-MAP/1\u0000".toByteArray(Charsets.UTF_8)

        /** `docs/type-maps.md` section 2.1: SHA-256 over `utf8("ROAX-TYPE-MAP/1\0") ‖ bytes`. */
        fun contentIdOf(artifactBytes: ByteArray): String {
            val sink = ByteSink(CONTENT_ID_PREFIX.size + artifactBytes.size)
                .bytes(CONTENT_ID_PREFIX)
                .bytes(artifactBytes)
            return "sha256:" + Bytes.toHex(Sha256.digest(sink.toByteArray()))
        }

        /**
         * Loads an artifact from its **exact bytes**, so the content ID is computed over what was
         * fetched rather than over a reserialization.
         *
         * The bytes MUST decode as strict UTF-8 and MUST contain neither duplicate JSON object
         * member names nor unpaired surrogate escapes (section 4.2 and `docs/type-maps.md`
         * section 2.1), which [JsonReader] enforces. A content ID authenticates bytes but cannot
         * make two permissive parsers agree about malformed input, which is why that requirement
         * exists at all.
         */
        fun load(artifactBytes: ByteArray, nfc: Nfc = PlatformNfc): DfaTypeMap {
            val root = JsonReader.parse(artifactBytes) as? JsonObject
                ?: fail(Reason.JSON_SYNTAX, "type-map artifact is not a JSON object")

            fun text(name: String): String = (root[name] as? JsonString)?.value
                ?: fail(Reason.JSON_SYNTAX, "type-map artifact has no string member '$name'")

            val automaton = root["automaton"] as? JsonObject
                ?: fail(Reason.JSON_SYNTAX, "type-map artifact has no 'automaton'")
            val start = (automaton["start"] as? JsonString)?.value
                ?: fail(Reason.JSON_SYNTAX, "automaton has no 'start'")
            val stateList = (automaton["states"] as? JsonArray)?.elements
                ?: fail(Reason.JSON_SYNTAX, "automaton has no 'states'")

            val states = LinkedHashMap<String, State>(stateList.size * 2)
            for (element in stateList) {
                val s = element as? JsonObject
                    ?: fail(Reason.JSON_SYNTAX, "automaton state is not an object")
                val id = (s["id"] as? JsonString)?.value
                    ?: fail(Reason.JSON_SYNTAX, "automaton state has no 'id'")

                val keys = LinkedHashMap<String, String>()
                (s["keys"] as? JsonArray)?.elements?.forEach { k ->
                    val t = k as? JsonObject
                        ?: fail(Reason.JSON_SYNTAX, "key transition is not an object")
                    val raw = (t["key"] as? JsonString)?.value
                        ?: fail(Reason.JSON_SYNTAX, "key transition has no 'key'")
                    val to = (t["to"] as? JsonString)?.value
                        ?: fail(Reason.JSON_SYNTAX, "key transition has no 'to'")
                    // Both sides of the D14a comparison normalize. A conforming artifact's
                    // transition keys are already NFC, so this is validation rather than repair:
                    // a non-NFC transition key would be permanently dead under a normalizing
                    // lookup, and silently accepting one would hide that.
                    val normalized = nfc.normalize(requirePairedSurrogates(raw, "transition key"))
                    if (normalized != raw) {
                        fail(
                            Reason.TYPE_MAP_FAIL_CLOSED,
                            "transition key \"$raw\" in state $id is not NFC, so a normalizing " +
                                "lookup could never reach it (docs/type-maps.md section 3.1)",
                        )
                    }
                    keys[normalized] = to
                }

                val bindings = LinkedHashMap<JsonKind, TypeTag>()
                (s["bindings"] as? JsonArray)?.elements?.forEach { b ->
                    val binding = b as? JsonObject
                        ?: fail(Reason.JSON_SYNTAX, "binding is not an object")
                    val kindLabel = (binding["jsonKind"] as? JsonString)?.value
                        ?: fail(Reason.JSON_SYNTAX, "binding has no 'jsonKind'")
                    val tagLiteral = (binding["tag"] as? JsonNumber)?.literal
                        ?: fail(Reason.JSON_SYNTAX, "binding has no 'tag'")
                    val tag = TypeTag.ofCode(Numbers.canonicalInteger(tagLiteral).toInt())
                    if (tag == TypeTag.BLOB_REF) {
                        fail(
                            Reason.BLOB_REF_NOT_DECLARED,
                            "state $id binds tag 8 BLOB_REF, which no version-1 profile declares " +
                                "(specification section 6.5)",
                        )
                    }
                    val kind = JsonKind.ofLabel(kindLabel)
                    if (bindings.put(kind, tag) != null) {
                        // The DFA intentionally carries no first-match rule.
                        fail(
                            Reason.TYPE_MAP_FAIL_CLOSED,
                            "state $id has two outputs for observed kind '$kindLabel'",
                        )
                    }
                }

                // `unresolved` rows and `structurallyUntypedObject` markers are read but never
                // consulted for a tag: `docs/type-maps.md` section 3 says a resolver MUST read
                // outputs only from `bindings`, and a path represented only by that metadata
                // remains unknown and fails closed. They are operative for the extension
                // lifecycle, which this library does not implement.
                states[id] = State(keys, (s["anyIndex"] as? JsonString)?.value, bindings)
            }

            return DfaTypeMap(
                recordType = text("recordType"),
                schemaVersion = text("schemaVersion"),
                typeMapVersion = text("typeMapVersion"),
                contentId = contentIdOf(artifactBytes),
                start = start,
                states = states,
                nfc = nfc,
            )
        }
    }
}

/**
 * The **superseded** display-pattern format of `schemas/type-map-1.0.json`, which
 * `corpus/type-maps/<recordType>.json` is written in.
 *
 * This exists because of a corpus defect, and naming it here is the point. That schema's own
 * description says it "MUST NOT be used to publish or resolve a type map", and ROAX-CANON/1
 * section 4.2 requires the operative matcher to be a structured-path DFA which "MUST NOT parse or
 * match a display path". Yet every committed vector that needs a map resolves against this format,
 * and no published artifact exists for `org.roax.corpus.synthetic` at all, so no
 * [DfaTypeMap] can resolve a single corpus record. Under section 1.1 that is a release-blocking
 * corpus defect rather than something to work around silently, and it is recorded identically in
 * `docs/typescript-implementation-findings.md`.
 *
 * The matching is still performed on **decoded segments**, never on a rendered display string, so
 * section 5.2's prohibition is respected even though the pattern is authored in display notation.
 */
class DisplayPatternTypeMap private constructor(
    val recordType: String,
    val schemaVersion: String,
    val typeMapVersion: String,
    private val entries: List<Entry>,
    private val nfc: Nfc,
) : TypeResolver {

    private sealed interface Token {
        /** Already NFC-normalized at parse time - both sides of the D14a comparison normalize. */
        data class Key(val key: String) : Token

        data class LiteralIndex(val index: Long) : Token

        data object AnyIndex : Token

        /** `**`, a run of one or more segments. */
        data object AnySegments : Token
    }

    private class Entry(val tokens: List<Token>, val kind: JsonKind?, val tag: TypeTag, val pattern: String)

    override fun resolve(segments: List<Segment>, kind: JsonKind): TypeTag? {
        var found: TypeTag? = null
        for (entry in entries) {
            if (entry.kind != null && entry.kind != kind) continue
            if (!matches(entry.tokens, 0, segments, 0)) continue
            if (found != null && found != entry.tag) {
                // Two outputs for one path language and observed kind. `docs/type-maps.md`
                // section 5.1 requires rejecting such an artifact rather than picking one, and the
                // DFA "intentionally carries no first-match rule" (section 3), so the superseded
                // format's ordering is deliberately not used to break the tie.
                fail(
                    Reason.TYPE_MAP_FAIL_CLOSED,
                    "two conflicting outputs for ${displayPath(segments)} at kind ${kind.label}",
                )
            }
            found = entry.tag
        }
        return found
    }

    private fun matches(tokens: List<Token>, ti: Int, segments: List<Segment>, si: Int): Boolean {
        if (ti == tokens.size) return si == segments.size
        return when (val t = tokens[ti]) {
            is Token.AnySegments -> {
                // A run of ONE OR MORE segments. Whether `**` may match zero segments is not
                // stated by any document here, and no committed vector discriminates it: the only
                // `**` pattern is `a.**`, and no fixture carries a scalar at `a`. Recorded as a
                // finding rather than resolved silently.
                var take = si + 1
                while (take <= segments.size) {
                    if (matches(tokens, ti + 1, segments, take)) return true
                    take++
                }
                false
            }

            else -> {
                if (si >= segments.size) return false
                val segment = segments[si]
                val ok = when (t) {
                    is Token.Key -> segment is Segment.Key && nfc.normalize(segment.key) == t.key
                    is Token.AnyIndex -> segment is Segment.Index
                    is Token.LiteralIndex -> segment is Segment.Index && segment.index == t.index
                    is Token.AnySegments -> false // unreachable
                }
                ok && matches(tokens, ti + 1, segments, si + 1)
            }
        }
    }

    companion object {

        fun load(artifactBytes: ByteArray, nfc: Nfc = PlatformNfc): DisplayPatternTypeMap {
            val root = JsonReader.parse(artifactBytes) as? JsonObject
                ?: fail(Reason.JSON_SYNTAX, "type map is not a JSON object")

            fun text(name: String): String = (root[name] as? JsonString)?.value
                ?: fail(Reason.JSON_SYNTAX, "type map has no string member '$name'")

            val entryList = (root["entries"] as? JsonArray)?.elements
                ?: fail(Reason.JSON_SYNTAX, "type map has no 'entries'")

            val entries = entryList.map { e ->
                val entry = e as? JsonObject ?: fail(Reason.JSON_SYNTAX, "entry is not an object")
                val pattern = (entry["pattern"] as? JsonString)?.value
                    ?: fail(Reason.JSON_SYNTAX, "entry has no 'pattern'")
                val tagLiteral = (entry["tag"] as? JsonNumber)?.literal
                    ?: fail(Reason.JSON_SYNTAX, "entry has no 'tag'")
                val tag = TypeTag.ofCode(Numbers.canonicalInteger(tagLiteral).toInt())
                if (tag == TypeTag.BLOB_REF) {
                    fail(
                        Reason.BLOB_REF_NOT_DECLARED,
                        "pattern '$pattern' binds tag 8 BLOB_REF, which no version-1 profile " +
                            "declares (specification section 6.5)",
                    )
                }
                val kind = (entry["jsonKind"] as? JsonString)?.value?.let { JsonKind.ofLabel(it) }
                Entry(tokenize(pattern, nfc), kind, tag, pattern)
            }

            return DisplayPatternTypeMap(
                recordType = text("recordType"),
                schemaVersion = text("schemaVersion"),
                typeMapVersion = text("typeMapVersion"),
                entries = entries,
                nfc = nfc,
            )
        }

        /**
         * Splits a display pattern into structured tokens.
         *
         * The notation cannot address a key containing `.`, `[` or `]` - keys section 5
         * deliberately admits with no rejection rule - which is the fifth ambiguity
         * `corpus/README.md` records. An ambiguous pattern is **rejected** rather than mis-parsed.
         */
        private fun tokenize(pattern: String, nfc: Nfc): List<Token> {
            val tokens = ArrayList<Token>()
            val current = StringBuilder()
            var i = 0
            var sawKeyChar = false

            fun flushKey() {
                val raw = current.toString()
                current.setLength(0)
                if (raw == "**") {
                    tokens.add(Token.AnySegments)
                } else {
                    tokens.add(Token.Key(nfc.normalize(requirePairedSurrogates(raw, "pattern key"))))
                }
                sawKeyChar = false
            }

            while (i < pattern.length) {
                when (val c = pattern[i]) {
                    '.' -> {
                        if (!sawKeyChar && current.isEmpty() && tokens.isEmpty()) {
                            fail(Reason.JSON_SYNTAX, "pattern '$pattern' starts with '.'")
                        }
                        if (sawKeyChar || current.isNotEmpty()) flushKey()
                        i++
                    }

                    '[' -> {
                        if (sawKeyChar || current.isNotEmpty()) flushKey()
                        val close = pattern.indexOf(']', i)
                        if (close < 0) fail(Reason.JSON_SYNTAX, "pattern '$pattern' has an unclosed '['")
                        val inner = pattern.substring(i + 1, close)
                        tokens.add(
                            if (inner == "*") {
                                Token.AnyIndex
                            } else {
                                val n = inner.toLongOrNull()
                                    ?: fail(
                                        Reason.JSON_SYNTAX,
                                        "pattern '$pattern' has a non-numeric index '[$inner]'",
                                    )
                                Token.LiteralIndex(n)
                            },
                        )
                        i = close + 1
                    }

                    ']' -> fail(Reason.JSON_SYNTAX, "pattern '$pattern' has an unmatched ']'")

                    else -> {
                        current.append(c)
                        sawKeyChar = true
                        i++
                    }
                }
            }
            if (sawKeyChar || current.isNotEmpty()) flushKey()
            return tokens
        }
    }
}
