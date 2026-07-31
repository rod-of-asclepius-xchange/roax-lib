package io.roax.canon

/**
 * Byte-level primitives from ROAX-CANON/1 section 1.
 *
 * Hex is hand-rolled rather than taken from `java.util.HexFormat`, which is JDK 17+ and absent on
 * Android; the same reasoning keeps `java.util.Base64` out of [Base64Strict].
 */
object Bytes {

    private const val HEX = "0123456789abcdef"

    /**
     * `u32be(n)`. [n] is a Long so an out-of-range value is representable and can be refused
     * rather than silently truncated, which ROAX-CANON/1 section 5 requires of array indices.
     * Range is enforced here as a programming error; [Segment.Index] performs the *input*
     * validation that carries [Reason.INDEX_OUT_OF_32_BIT_RANGE].
     */
    fun u32be(n: Long): ByteArray {
        require(n in 0..0xFFFFFFFFL) { "$n does not fit in an unsigned 32-bit integer" }
        return byteArrayOf(
            ((n ushr 24) and 0xFF).toByte(),
            ((n ushr 16) and 0xFF).toByte(),
            ((n ushr 8) and 0xFF).toByte(),
            (n and 0xFF).toByte(),
        )
    }

    /** `u64be(n)`. */
    fun u64be(n: Long): ByteArray {
        require(n >= 0) { "u64be is unsigned" }
        val out = ByteArray(8)
        for (i in 0 until 8) out[i] = ((n ushr ((7 - i) * 8)) and 0xFF).toByte()
        return out
    }

    fun toHex(b: ByteArray): String {
        val sb = StringBuilder(b.size * 2)
        for (x in b) {
            val v = x.toInt() and 0xFF
            sb.append(HEX[v ushr 4]).append(HEX[v and 0x0F])
        }
        return sb.toString()
    }

    /** Parses lowercase or uppercase hex. Rejects an odd length or any non-hex character. */
    fun fromHex(s: String): ByteArray {
        if (s.length % 2 != 0) throw IllegalArgumentException("hex string has odd length: ${s.length}")
        val out = ByteArray(s.length / 2)
        for (i in out.indices) {
            val hi = digit(s[i * 2])
            val lo = digit(s[i * 2 + 1])
            out[i] = ((hi shl 4) or lo).toByte()
        }
        return out
    }

    private fun digit(c: Char): Int = when (c) {
        in '0'..'9' -> c - '0'
        in 'a'..'f' -> c - 'a' + 10
        in 'A'..'F' -> c - 'A' + 10
        else -> throw IllegalArgumentException("not a hex digit: '$c'")
    }

    /** Unsigned lexicographic comparison, which is what ROAX-CANON/1 section 9 orders leaves by. */
    fun compareUnsigned(a: ByteArray, b: ByteArray): Int {
        val n = minOf(a.size, b.size)
        for (i in 0 until n) {
            val d = (a[i].toInt() and 0xFF) - (b[i].toInt() and 0xFF)
            if (d != 0) return d
        }
        return a.size - b.size
    }

    /** Constant-time equality, used wherever a digest is compared against a supplied one. */
    fun constantTimeEquals(a: ByteArray, b: ByteArray): Boolean {
        if (a.size != b.size) return false
        var diff = 0
        for (i in a.indices) diff = diff or (a[i].toInt() xor b[i].toInt())
        return diff == 0
    }
}

/** Append-only byte buffer, so a preimage is built in one place and never re-parsed. */
internal class ByteSink(initial: Int = 64) {
    private var buf = ByteArray(initial)
    private var len = 0

    fun byte(b: Int): ByteSink {
        ensure(1); buf[len++] = b.toByte(); return this
    }

    fun bytes(b: ByteArray): ByteSink {
        ensure(b.size); System.arraycopy(b, 0, buf, len, b.size); len += b.size; return this
    }

    /** `u32be(len(b)) ‖ b`, the length-prefixed form every variable-length component uses. */
    fun lengthPrefixed32(b: ByteArray): ByteSink = bytes(Bytes.u32be(b.size.toLong())).bytes(b)

    /** `u64be(len(b)) ‖ b`. */
    fun lengthPrefixed64(b: ByteArray): ByteSink = bytes(Bytes.u64be(b.size.toLong())).bytes(b)

    fun toByteArray(): ByteArray = buf.copyOf(len)

    private fun ensure(extra: Int) {
        if (len + extra <= buf.size) return
        var cap = buf.size * 2
        while (cap < len + extra) cap *= 2
        buf = buf.copyOf(cap)
    }
}
