package io.roax.canon

import java.nio.charset.CharsetDecoder
import java.nio.charset.CodingErrorAction
import java.nio.charset.StandardCharsets
import java.text.Normalizer

/**
 * Normalization Form C, with the Unicode version the tables come from.
 *
 * This is an interface rather than a direct call to [java.text.Normalizer] because
 * ROAX-CANON/1 section 6.1 pins Unicode 15.1 and **no JVM lets a caller choose its tables**:
 * `java.text.Normalizer` uses whatever version the running JDK - or, on Android, the platform
 * ICU - was built against. That version is a property of the runtime, not of this library.
 *
 * Measured while this library was written:
 *
 * | Runtime | NFC tables |
 * |---|---|
 * | JDK 17.0.19 | Unicode 13.0 |
 * | JDK 25.0.2 | Unicode 16.0 |
 * | Python 3.13.5 (corpus implementation A) | Unicode 15.1 |
 * | Node 22 / ICU 77 (corpus implementation B) | Unicode 16.0 |
 *
 * Neither installed JDK is the pinned 15.1. Section 6.1 says an implementation whose tables are
 * from a different version MAY produce a different root and MUST NOT claim conformance, and it
 * makes the mismatch detectable **by declaration** rather than by demonstration. So this library
 * declares [unicodeVersion] and lets a deployment inject tables it can pin - every entry point
 * takes an [Nfc] - rather than claiming a conformance it cannot verify. `kotlin/FINDINGS.md`
 * records what that costs, measured: JDK 17 and JDK 25 produce byte-identical NFC over every
 * string in the committed corpus and its fixtures, so the version gap is real but is not currently
 * observable on this input set.
 */
interface Nfc {
    /** Unicode version these tables implement, in the canonical form the corpus uses, e.g. `15.1`. */
    val unicodeVersion: String

    /** NFC of [s]. The caller has already rejected unpaired surrogates. */
    fun normalize(s: String): String
}

/**
 * NFC from the running platform's [java.text.Normalizer].
 *
 * The Unicode version is not exposed by any public API, so it is **probed**: [Character.isDefined]
 * tracks the JDK's Unicode support level, and one code point first assigned in each release
 * identifies the highest release this runtime knows. The probe is evidence about the
 * `Character` tables; `Normalizer` is built from the same Unicode data drop in every JDK and in
 * Android's ICU, so it is the best available signal and is reported as a probe rather than as a
 * declaration by the platform.
 */
object PlatformNfc : Nfc {

    /** (code point first assigned in that release, release label), ascending. */
    private val PROBES = listOf(
        0x08BE to "13.0",
        0x061D to "14.0",
        0x0CF3 to "15.0",
        0x11F00 to "15.1",
        0x105C0 to "16.0",
    )

    override val unicodeVersion: String by lazy {
        var highest = "unknown"
        for ((cp, label) in PROBES) if (Character.isDefined(cp)) highest = label
        highest
    }

    override fun normalize(s: String): String = Normalizer.normalize(s, Normalizer.Form.NFC)
}

/**
 * Rejects unpaired UTF-16 surrogates, then returns the string unchanged.
 *
 * ROAX-CANON/1 section 6.1 requires this **before** normalization, and section 3.2 lists it as an
 * input-boundary rejection. It has to be explicit on this platform because both of the operations
 * that would otherwise catch it are silent, which was measured while writing this library:
 * `"A\uD800".toByteArray(UTF_8)` yields `41 3f` - the surrogate becomes an ASCII `?` - and
 * `Normalizer.normalize` passes a lone surrogate straight through. Neither raises anything.
 */
fun requirePairedSurrogates(s: String, what: String): String {
    var i = 0
    while (i < s.length) {
        val c = s[i]
        if (Character.isHighSurrogate(c)) {
            if (i + 1 >= s.length || !Character.isLowSurrogate(s[i + 1])) {
                fail(Reason.UNPAIRED_SURROGATE, "$what carries an unpaired high surrogate at index $i")
            }
            i += 2
        } else {
            if (Character.isLowSurrogate(c)) {
                fail(Reason.UNPAIRED_SURROGATE, "$what carries an unpaired low surrogate at index $i")
            }
            i += 1
        }
    }
    return s
}

/**
 * UTF-8 of [s], having first rejected unpaired surrogates.
 *
 * `String.toByteArray(UTF_8)` on its own substitutes `?` for a lone surrogate rather than failing,
 * so this wrapper is the only encoder this library uses for anything that reaches a hash preimage.
 */
fun utf8Strict(s: String, what: String = "string"): ByteArray =
    requirePairedSurrogates(s, what).toByteArray(StandardCharsets.UTF_8)

/**
 * Decodes [bytes] as strict UTF-8, refusing malformed and unmappable sequences.
 *
 * `String(bytes, UTF_8)` substitutes U+FFFD silently, which would let a malformed record through
 * the input boundary of section 3.2 and change what gets hashed.
 */
fun decodeUtf8Strict(bytes: ByteArray): String {
    val decoder: CharsetDecoder = StandardCharsets.UTF_8.newDecoder()
        .onMalformedInput(CodingErrorAction.REPORT)
        .onUnmappableCharacter(CodingErrorAction.REPORT)
    return try {
        decoder.decode(java.nio.ByteBuffer.wrap(bytes)).toString()
    } catch (e: java.nio.charset.CharacterCodingException) {
        fail(Reason.MALFORMED_UTF8, "input is not well-formed UTF-8: ${e.message}")
    }
}
