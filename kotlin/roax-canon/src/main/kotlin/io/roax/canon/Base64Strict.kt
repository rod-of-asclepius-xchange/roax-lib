package io.roax.canon

/**
 * The base64 form ROAX-CANON/1 section 6.3 pins: **RFC 4648 section 4 - the standard alphabet,
 * with padding, and no line wrapping.**
 *
 * `java.util.Base64` cannot be used for this, and the reason is measured rather than assumed.
 * `Base64.getDecoder()` on JDK 17 accepts the unpadded `SGVsbG8`, and it accepts `SGVsbG9=`,
 * whose final quantum carries non-zero unused bits and which decodes to the same octets as the
 * canonical `SGVsbG8=`. Section 6.3 requires both to be rejected, and RFC 4648 section 3.5 is
 * where the second one is identified as the non-canonical case. Three of the four base64
 * rejection vectors in the corpus decode to the accepted fixture's octets under a permissive
 * decoder, which is that hazard exhibited rather than described.
 *
 * `java.util.Base64` is also API 26+ on Android, so hand-rolling costs nothing this library was
 * not already paying.
 *
 * Under the ruled FHIR `base64Binary` binding (grade Strong, `docs/type-maps.md` section 1.3) the
 * canonical form is an **input-admissibility condition and never the committed value**: the
 * decoded octets are what gets hashed, and a spelling outside the pinned form is refused before it
 * is decoded.
 */
object Base64Strict {

    private const val ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

    private val DECODE = IntArray(128) { -1 }.also { table ->
        for (i in ALPHABET.indices) table[ALPHABET[i].code] = i
    }

    /**
     * Decodes canonical RFC 4648 section 4 base64, or raises
     * [Reason.BASE64_NOT_CANONICAL].
     */
    fun decode(text: String): ByteArray {
        if (text.isEmpty()) return ByteArray(0)

        if (text.length % 4 != 0) {
            fail(
                Reason.BASE64_NOT_CANONICAL,
                "length ${text.length} is not a multiple of 4, so padding is absent or excess",
            )
        }

        var padding = 0
        while (padding < 2 && text[text.length - 1 - padding] == '=') padding++
        if (padding == 2 && text.length >= 3 && text[text.length - 3] == '=') {
            fail(Reason.BASE64_NOT_CANONICAL, "more than two '=' padding characters")
        }

        val dataLength = text.length - padding
        val values = IntArray(dataLength)
        for (i in 0 until dataLength) {
            val c = text[i]
            val v = if (c.code < 128) DECODE[c.code] else -1
            if (v < 0) {
                val what = when {
                    c == '-' || c == '_' -> "URL-safe alphabet character"
                    c == '=' -> "interior padding character"
                    c == '\n' || c == '\r' -> "line break"
                    else -> "character outside the RFC 4648 section 4 alphabet"
                }
                fail(Reason.BASE64_NOT_CANONICAL, "$what '${escape(c)}' at index $i")
            }
            values[i] = v
        }

        // RFC 4648 section 3.5: the unused bits of the final quantum MUST be zero.
        when (padding) {
            1 -> if (values[dataLength - 1] and 0x03 != 0) {
                fail(Reason.BASE64_NOT_CANONICAL, "final quantum carries non-zero unused bits")
            }

            2 -> if (values[dataLength - 1] and 0x0F != 0) {
                fail(Reason.BASE64_NOT_CANONICAL, "final quantum carries non-zero unused bits")
            }
        }

        val outLength = (text.length / 4) * 3 - padding
        val out = ByteArray(outLength)
        var oi = 0
        var i = 0
        while (i + 4 <= dataLength) {
            val n = (values[i] shl 18) or (values[i + 1] shl 12) or
                (values[i + 2] shl 6) or values[i + 3]
            out[oi++] = ((n ushr 16) and 0xFF).toByte()
            out[oi++] = ((n ushr 8) and 0xFF).toByte()
            out[oi++] = (n and 0xFF).toByte()
            i += 4
        }
        when (dataLength - i) {
            2 -> {
                val n = (values[i] shl 18) or (values[i + 1] shl 12)
                out[oi++] = ((n ushr 16) and 0xFF).toByte()
            }

            3 -> {
                val n = (values[i] shl 18) or (values[i + 1] shl 12) or (values[i + 2] shl 6)
                out[oi++] = ((n ushr 16) and 0xFF).toByte()
                out[oi] = ((n ushr 8) and 0xFF).toByte()
            }
        }
        return out
    }

    /** Encodes in the pinned canonical form, so `decode(encode(b))` is the identity on bytes. */
    fun encode(data: ByteArray): String {
        if (data.isEmpty()) return ""
        val sb = StringBuilder(((data.size + 2) / 3) * 4)
        var i = 0
        while (i + 3 <= data.size) {
            val n = ((data[i].toInt() and 0xFF) shl 16) or
                ((data[i + 1].toInt() and 0xFF) shl 8) or (data[i + 2].toInt() and 0xFF)
            sb.append(ALPHABET[(n ushr 18) and 0x3F]).append(ALPHABET[(n ushr 12) and 0x3F])
                .append(ALPHABET[(n ushr 6) and 0x3F]).append(ALPHABET[n and 0x3F])
            i += 3
        }
        when (data.size - i) {
            1 -> {
                val n = (data[i].toInt() and 0xFF) shl 16
                sb.append(ALPHABET[(n ushr 18) and 0x3F]).append(ALPHABET[(n ushr 12) and 0x3F])
                    .append("==")
            }

            2 -> {
                val n = ((data[i].toInt() and 0xFF) shl 16) or ((data[i + 1].toInt() and 0xFF) shl 8)
                sb.append(ALPHABET[(n ushr 18) and 0x3F]).append(ALPHABET[(n ushr 12) and 0x3F])
                    .append(ALPHABET[(n ushr 6) and 0x3F]).append('=')
            }
        }
        return sb.toString()
    }

    private fun escape(c: Char): String =
        if (c.code in 0x20..0x7E) c.toString() else "\\u%04x".format(c.code)
}
