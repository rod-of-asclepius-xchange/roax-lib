package io.roax.canon.json

import io.roax.canon.Reason
import io.roax.canon.decodeUtf8Strict
import io.roax.canon.fail
import io.roax.canon.requirePairedSurrogates

/**
 * A JSON document, in the only shape ROAX-CANON/1 can be computed from.
 *
 * Two properties matter and neither is offered by any JSON library on this platform:
 *
 * 1. **A number is its verbatim source text.** Section 6.4 is normative - implementations MUST NOT
 *    parse record numbers through any floating-point type - and section 6.2 requires
 *    `0.010` to stay distinct from `0.01`, which no numeric type on the JVM preserves through a
 *    round trip. [JsonNumber] therefore carries the literal and nothing else.
 * 2. **Duplicate member names are visible.** Section 3.2 requires them to be *rejected* at the
 *    input boundary, and a `Map`-shaped parse result has already silently dropped one by the time
 *    a caller could look.
 *
 * `docs/spec/roax-canon-1.md` section 6.4 lists Kotlin/JVM as the one target language with no
 * confirmed literal-preserving mechanism. [JsonReader] is that mechanism: a hand-written scanner,
 * which is the same answer section 6.4 records for Swift.
 */
sealed interface JsonValue

data class JsonMember(val key: String, val value: JsonValue)

/** Members in document order. Order is irrelevant to the root (section 3.3) but is preserved. */
data class JsonObject(val members: List<JsonMember>) : JsonValue {
    val isEmpty: Boolean get() = members.isEmpty()

    operator fun get(key: String): JsonValue? = members.firstOrNull { it.key == key }?.value
}

data class JsonArray(val elements: List<JsonValue>) : JsonValue {
    val isEmpty: Boolean get() = elements.isEmpty()
}

data class JsonString(val value: String) : JsonValue

/** The numeric literal exactly as it appeared in the source text. Never parsed. */
data class JsonNumber(val literal: String) : JsonValue

data class JsonBoolean(val value: Boolean) : JsonValue

data object JsonNull : JsonValue

/**
 * A strict RFC 8259 reader that preserves numeric literals and refuses duplicate member names.
 *
 * Deliberately refuses, beyond plain syntax errors:
 * - `NaN`, `Infinity` and `-Infinity`, which are not JSON and which section 3.2 lists explicitly;
 * - duplicate member names in one object (section 3.2);
 * - unpaired UTF-16 surrogates arriving through `\uXXXX` escapes (sections 3.2 and 6.1);
 * - malformed UTF-8 in the input bytes, which `String(bytes, UTF_8)` would replace silently;
 * - trailing content after the top-level value.
 */
object JsonReader {

    /** Nesting limit, so a pathological document is refused rather than overflowing the stack. */
    private const val MAX_DEPTH = 512

    fun parse(bytes: ByteArray): JsonValue = parse(decodeUtf8Strict(bytes))

    fun parse(text: String): JsonValue {
        val p = Parser(text)
        p.skipWhitespace()
        val v = p.readValue(0)
        p.skipWhitespace()
        if (!p.atEnd()) p.syntax("trailing content after the top-level value")
        return v
    }

    private class Parser(private val s: String) {
        private var i = 0

        fun atEnd(): Boolean = i >= s.length

        fun skipWhitespace() {
            while (i < s.length) {
                when (s[i]) {
                    ' ', '\t', '\n', '\r' -> i++
                    else -> return
                }
            }
        }

        fun syntax(detail: String): Nothing =
            fail(Reason.JSON_SYNTAX, "at offset $i: $detail")

        fun readValue(depth: Int): JsonValue {
            if (depth > MAX_DEPTH) syntax("nesting deeper than $MAX_DEPTH")
            if (atEnd()) syntax("unexpected end of input")
            return when (val c = s[i]) {
                '{' -> readObject(depth)
                '[' -> readArray(depth)
                '"' -> JsonString(readString())
                't' -> { literal("true"); JsonBoolean(true) }
                'f' -> { literal("false"); JsonBoolean(false) }
                'n' -> { literal("null"); JsonNull }
                'N' -> nonFinite("NaN")
                'I' -> nonFinite("Infinity")
                '-' -> if (s.startsWith("-Infinity", i)) nonFinite("-Infinity") else readNumber()
                else -> if (c in '0'..'9') readNumber() else syntax("unexpected character '$c'")
            }
        }

        private fun nonFinite(token: String): Nothing = fail(
            Reason.NON_FINITE_NUMBER,
            "$token is not JSON and is refused at the input boundary " +
                "(specification section 3.2)",
        )

        private fun literal(word: String) {
            if (!s.startsWith(word, i)) syntax("expected '$word'")
            i += word.length
        }

        private fun readObject(depth: Int): JsonObject {
            i++ // '{'
            val members = ArrayList<JsonMember>()
            val seen = HashSet<String>()
            skipWhitespace()
            if (i < s.length && s[i] == '}') { i++; return JsonObject(members) }
            while (true) {
                skipWhitespace()
                if (i >= s.length || s[i] != '"') syntax("expected a member name")
                val key = readString()
                if (!seen.add(key)) {
                    // Compared on the RAW decoded key, not its NFC form. Section 3.2 requires raw
                    // map keys to be unique; whether NFC-COLLIDING sibling keys with disjoint
                    // descendants must also be refused is not ruled by the specification, and is
                    // the sixth ambiguity `corpus/README.md` records. This library accepts that
                    // shape, matching the Rust implementation, and refuses a genuine duplicate.
                    fail(Reason.DUPLICATE_KEY, "duplicate member name \"$key\"")
                }
                skipWhitespace()
                if (i >= s.length || s[i] != ':') syntax("expected ':'")
                i++
                skipWhitespace()
                members.add(JsonMember(key, readValue(depth + 1)))
                skipWhitespace()
                if (i >= s.length) syntax("unterminated object")
                when (s[i]) {
                    ',' -> { i++; continue }
                    '}' -> { i++; return JsonObject(members) }
                    else -> syntax("expected ',' or '}'")
                }
            }
        }

        private fun readArray(depth: Int): JsonArray {
            i++ // '['
            val elements = ArrayList<JsonValue>()
            skipWhitespace()
            if (i < s.length && s[i] == ']') { i++; return JsonArray(elements) }
            while (true) {
                skipWhitespace()
                elements.add(readValue(depth + 1))
                skipWhitespace()
                if (i >= s.length) syntax("unterminated array")
                when (s[i]) {
                    ',' -> { i++; continue }
                    ']' -> { i++; return JsonArray(elements) }
                    else -> syntax("expected ',' or ']'")
                }
            }
        }

        private fun readString(): String {
            i++ // opening quote
            val sb = StringBuilder()
            while (true) {
                if (i >= s.length) syntax("unterminated string")
                when (val c = s[i]) {
                    '"' -> {
                        i++
                        // An escape sequence can introduce a lone surrogate that no UTF-8 input
                        // could have carried, so the check belongs here rather than only at the
                        // byte boundary. Section 6.1 requires it BEFORE normalization.
                        return requirePairedSurrogates(sb.toString(), "JSON string")
                    }

                    '\\' -> {
                        i++
                        if (i >= s.length) syntax("unterminated escape")
                        when (val e = s[i]) {
                            '"' -> { sb.append('"'); i++ }
                            '\\' -> { sb.append('\\'); i++ }
                            '/' -> { sb.append('/'); i++ }
                            'b' -> { sb.append('\b'); i++ }
                            'f' -> { sb.append('\u000C'); i++ }
                            'n' -> { sb.append('\n'); i++ }
                            'r' -> { sb.append('\r'); i++ }
                            't' -> { sb.append('\t'); i++ }
                            'u' -> {
                                i++
                                if (i + 4 > s.length) syntax("truncated \\u escape")
                                var code = 0
                                for (k in 0 until 4) {
                                    val h = s[i + k]
                                    val d = when (h) {
                                        in '0'..'9' -> h - '0'
                                        in 'a'..'f' -> h - 'a' + 10
                                        in 'A'..'F' -> h - 'A' + 10
                                        else -> syntax("'\\u' escape carries a non-hex digit '$h'")
                                    }
                                    code = (code shl 4) or d
                                }
                                i += 4
                                sb.append(code.toChar())
                            }

                            else -> syntax("unknown escape '\\$e'")
                        }
                    }

                    else -> {
                        if (c.code < 0x20) syntax("unescaped control character U+%04X".format(c.code))
                        sb.append(c)
                        i++
                    }
                }
            }
        }

        /**
         * Reads a JSON number and returns its **source text unchanged**.
         *
         * The grammar accepted here is RFC 8259's, which is exactly the DECIMAL input grammar of
         * section 6.2. Nothing is converted: whether the literal is admissible under the tag the
         * type map selects is decided later, by [io.roax.canon.Numbers].
         */
        private fun readNumber(): JsonNumber {
            val start = i
            if (i < s.length && s[i] == '-') i++
            if (i >= s.length) syntax("truncated number")
            if (s[i] == '0') {
                i++
            } else {
                if (s[i] !in '1'..'9') syntax("number has no integer part")
                while (i < s.length && s[i] in '0'..'9') i++
            }
            if (i < s.length && s[i] == '.') {
                i++
                val fracStart = i
                while (i < s.length && s[i] in '0'..'9') i++
                if (i == fracStart) syntax("number has an empty fraction")
            }
            if (i < s.length && (s[i] == 'e' || s[i] == 'E')) {
                i++
                if (i < s.length && (s[i] == '+' || s[i] == '-')) i++
                val expStart = i
                while (i < s.length && s[i] in '0'..'9') i++
                if (i == expStart) syntax("number has an empty exponent")
            }
            return JsonNumber(s.substring(start, i))
        }
    }
}
