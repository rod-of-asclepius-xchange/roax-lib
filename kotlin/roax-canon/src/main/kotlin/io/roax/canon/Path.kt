package io.roax.canon

/**
 * One path segment. ROAX-CANON/1 section 5: a path is a sequence of KEY and INDEX segments with
 * **no reserved characters and no escaping**.
 */
sealed interface Segment {

    /** A map member name. May be the empty string, which is distinct from an absent segment. */
    data class Key(val key: String) : Segment

    /**
     * A 0-based array index, which MUST be `< 2^32`.
     *
     * Held as a Long so that `2^32` itself is representable and refused. Section 5 is explicit:
     * "An implementation that cannot represent an index in 32 bits MUST error rather than
     * truncate", and an `Int` field would make the error unreachable by making the state
     * unrepresentable in the wrong direction - `2^32` would wrap to 0 before any check ran.
     */
    data class Index(val index: Long) : Segment {
        init {
            if (index < 0 || index > 0xFFFFFFFFL) {
                fail(
                    Reason.INDEX_OUT_OF_32_BIT_RANGE,
                    "array index $index is outside [0, 2^32)",
                )
            }
        }
    }
}

/** Convenience builders. */
fun key(k: String): Segment.Key = Segment.Key(k)

fun index(i: Long): Segment.Index = Segment.Index(i)

fun path(vararg segments: Segment): List<Segment> = segments.toList()

/**
 * ROAX-CANON/1 section 5.
 *
 * ```
 * encodePath(segments) =
 *     u32be(count(segments))
 *   ‖ for each segment:
 *         KEY(k)   ->  0x01 ‖ u32be(len(utf8(NFC(k)))) ‖ utf8(NFC(k))
 *         INDEX(i) ->  0x02 ‖ u32be(i)
 * ```
 *
 * The key is NFC-normalized here, which is what makes an encoded KEY segment commit `NFC(key)` -
 * the fact ruled decision D14a rests on when it requires the type-map lookup to compare the
 * normalized form (section 4.2).
 */
fun encodePath(segments: List<Segment>, nfc: Nfc = PlatformNfc): ByteArray {
    val sink = ByteSink(16 + segments.size * 12)
    sink.bytes(Bytes.u32be(segments.size.toLong()))
    for (s in segments) {
        when (s) {
            is Segment.Key -> {
                val normalized = nfc.normalize(requirePairedSurrogates(s.key, "path key"))
                sink.byte(0x01).lengthPrefixed32(utf8Strict(normalized, "path key"))
            }

            is Segment.Index -> sink.byte(0x02).bytes(Bytes.u32be(s.index))
        }
    }
    return sink.toByteArray()
}

/**
 * The human-readable form, `a.b[0].c`.
 *
 * ROAX-CANON/1 section 5.2: it is retained for display and for disclosure requests, MUST NOT enter
 * any hash preimage, and MUST NOT be parsed back into an encoded path. Nothing in this library
 * consumes the result - it exists only to be shown to a person.
 *
 * The key is emitted **as received**, not NFC-normalized, because this is not a commitment: the
 * corpus pins that with `path-nfc-key` and `path-nfd-key`, whose display paths differ while their
 * encodings are identical.
 */
fun displayPath(segments: List<Segment>): String {
    val sb = StringBuilder()
    for (s in segments) {
        when (s) {
            is Segment.Key -> {
                if (sb.isNotEmpty()) sb.append('.')
                sb.append(s.key)
            }

            is Segment.Index -> sb.append('[').append(s.index).append(']')
        }
    }
    return sb.toString()
}
