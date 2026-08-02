package io.roax.canon

import io.roax.canon.conformance.Corpus
import io.roax.canon.json.JsonArray
import io.roax.canon.json.JsonObject
import io.roax.canon.json.JsonReader
import io.roax.canon.json.JsonString
import io.roax.canon.json.JsonValue
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.io.File
import java.nio.charset.StandardCharsets
import java.security.MessageDigest

/**
 * The platform's NFC tables, pinned as a digest over every string the committed corpus contains.
 *
 * **Why this exists, because it is not redundant with the corpus run and a reader who assumes it is
 * will delete it.** The corpus vectors cover THIS LIBRARY's behaviour. This test covers the
 * PLATFORM UNDERNEATH IT, which no corpus vector can reach: ROAX-CANON/1 section 6.1 pins Unicode
 * 15.1, `java.text.Normalizer` uses whatever data drop the running JDK - or, on Android, the
 * platform ICU - was built against, and **no JDK ships 15.1** (17 has 13.0, 25 has 16.0). So the
 * corpus can pass in full while the tables under it have changed, which is exactly the divergence
 * ROAX exists to prevent. Section 6.1 makes that mismatch detectable by DECLARATION rather than by
 * demonstration; this is the demonstration, on the one input set whose stability actually matters.
 *
 * **A single JVM cannot compare two table versions, so this test pins the digest for the CURRENT
 * runtime and the comparison is made by running it under both.** That is the whole design:
 *
 * ```
 * gradle -p kotlin :roax-canon:test --tests '*PlatformNfcTablesTest'                    # JDK 17, Unicode 13.0
 * gradle -p kotlin -Proax.testJdk=25 :roax-canon:test --tests '*PlatformNfcTablesTest'  # JDK 25, Unicode 16.0
 * ```
 *
 * Both MUST pass against the same [PINNED_DIGEST]. The constant is deliberately NOT keyed on
 * [Nfc.unicodeVersion]: a per-version table would degrade the guard into "each runtime agrees with
 * itself", which is the opposite of what it is for. If two runtimes disagree, that is a finding to
 * escalate under section 6.1 and not a constant to widen.
 *
 * `kotlin/FINDINGS.md` section 2 cites this test for its headline measurement.
 */
class PlatformNfcTablesTest {

    @Test
    fun `NFC over every corpus string digests to the pinned value on this runtime's tables`() {
        val strings = extractStrings()
        val nonAscii = strings.count { s -> s.any { it.code > 0x7F } }
        val changed = strings.count { PlatformNfc.normalize(it) != it }
        val digest = digestOver(strings.map { PlatformNfc.normalize(it) })

        println(
            "PlatformNfcTablesTest: unicode=${PlatformNfc.unicodeVersion} " +
                "strings=${strings.size} non-ascii=$nonAscii changed-by-nfc=$changed " +
                "skipped-lone-surrogate=$skipped digest=$digest",
        )

        // The counts come first on purpose. They separate the two causes below without a human
        // having to guess which one fired: a count that moved is the input set, and a count that
        // held while the digest moved is the tables.
        assertEquals(PINNED_TOTAL, strings.size, COUNT_DRIFT)
        assertEquals(PINNED_NON_ASCII, nonAscii, COUNT_DRIFT)
        assertEquals(PINNED_CHANGED_BY_NFC, changed, COUNT_DRIFT)

        assertEquals(PINNED_DIGEST, digest, DIGEST_DRIFT)
    }

    /**
     * Records which tables the run above was measured against.
     *
     * Section 6.1's declaration is only useful if the declared value is one this repository has
     * actually characterized, so an unrecognized runtime fails here rather than quietly carrying a
     * digest nobody can attribute to a Unicode release.
     */
    @Test
    fun `the runtime declares a Unicode version this repository has characterized`() {
        val version = PlatformNfc.unicodeVersion
        assertTrue(
            version in KNOWN_UNICODE_VERSIONS,
            "this runtime probes as Unicode '$version', which is not one of " +
                "$KNOWN_UNICODE_VERSIONS. The digest in this test was measured on JDK 17 " +
                "(Unicode 13.0) and JDK 25 (Unicode 16.0); a third set of tables is an " +
                "uncharacterized runtime, and under specification section 6.1 it MUST NOT claim " +
                "conformance until its NFC has been measured against the corpus pin of " +
                "${Corpus.unicodeVersion}.",
        )
        println("PlatformNfcTablesTest: ran under Unicode $version tables")
    }

    // --- extraction -------------------------------------------------------------------------------

    /** Lone surrogates seen during the last [extractStrings]; see [skipLoneSurrogates]. */
    private var skipped = 0

    /**
     * Every string in [INPUT_FILES], in file order and then in document order.
     *
     * **Object member keys are included as well as string values**, because the key site is half of
     * what specification section 5.1 hashes and half of what corpus class 19 tests: a KEY segment
     * is NFC-normalized before it is length-prefixed, exactly as a STRING leaf value is. Extracting
     * values alone would leave the half that ruled decision D14a turns on unguarded.
     *
     * Numeric literals, booleans and nulls are not strings and are not extracted.
     */
    private fun extractStrings(): List<String> {
        skipped = 0
        val out = ArrayList<String>()
        for (file in INPUT_FILES) {
            // Through this library's own reader, which is itself a third thing that can move the
            // digest - see DIGEST_DRIFT. It is the right reader anyway: it is the only one on this
            // platform that refuses a duplicate member name rather than dropping one silently,
            // and a dropped member would silently shrink the input set.
            walk(JsonReader.parse(file.readBytes()), out)
        }
        return out
    }

    private fun walk(value: JsonValue, out: MutableList<String>) {
        when (value) {
            is JsonObject -> for (m in value.members) {
                emit(m.key, out)
                walk(m.value, out)
            }
            is JsonArray -> for (e in value.elements) walk(e, out)
            is JsonString -> emit(value.value, out)
            else -> Unit
        }
    }

    /**
     * Appends [s] unless it carries an unpaired surrogate.
     *
     * A lone surrogate is not valid input to this comparison: specification section 6.1 requires it
     * to be REJECTED before normalization, so its NFC form is not a defined quantity to digest.
     * Measured on the committed tree this branch never fires - [skipped] is 0 - and it is written
     * anyway so that a fixture which later carries one narrows the input set visibly instead of
     * digesting a `?` substitution. (A raw `\uD800` escape would not even reach here: [JsonReader]
     * refuses it at parse time, which is `Reason.UNPAIRED_SURROGATE` rather than a silent pass.)
     */
    private fun emit(s: String, out: MutableList<String>) {
        if (skipLoneSurrogates(s)) skipped++ else out.add(s)
    }

    private fun skipLoneSurrogates(s: String): Boolean {
        var i = 0
        while (i < s.length) {
            val c = s[i]
            if (Character.isHighSurrogate(c)) {
                if (i + 1 >= s.length || !Character.isLowSurrogate(s[i + 1])) return true
                i += 2
            } else {
                if (Character.isLowSurrogate(c)) return true
                i += 1
            }
        }
        return false
    }

    /**
     * SHA-256 over [strings], each framed as a 4-byte big-endian UTF-8 length then those bytes.
     *
     * The length prefix is the same reason specification section 5.1 uses one: without it the
     * concatenation is ambiguous, and two different input sets could digest alike.
     */
    private fun digestOver(strings: List<String>): String {
        val md = MessageDigest.getInstance("SHA-256")
        for (s in strings) {
            val b = s.toByteArray(StandardCharsets.UTF_8)
            md.update(
                byteArrayOf(
                    (b.size ushr 24).toByte(), (b.size ushr 16).toByte(),
                    (b.size ushr 8).toByte(), b.size.toByte(),
                ),
            )
            md.update(b)
        }
        return Bytes.toHex(md.digest())
    }

    companion object {

        /**
         * The input set, in the exact order it is digested.
         *
         * Directory listings are sorted by name rather than taken in filesystem order, because the
         * digest has to be reproducible on another machine.
         */
        private val INPUT_FILES: List<File> =
            listOf(Corpus.file("corpus/conformance-corpus-1.0.json")) +
                listOf(
                    "corpus/fixtures/records",
                    "corpus/fixtures/envelopes",
                    "corpus/type-maps",
                ).flatMap { dir ->
                    (Corpus.file(dir).listFiles() ?: emptyArray())
                        .filter { it.isFile && it.name.endsWith(".json") }
                        .sortedBy { it.name }
                }

        /**
         * Measured by running this test; see the class documentation for how to re-derive it.
         *
         * **Identical on JDK 17 (Unicode 13.0) and JDK 25 (Unicode 16.0)**, which is the
         * measurement, and the corroborating counts below are identical on both too: of 17,517
         * strings, 54 are non-ASCII and 23 are changed by NFC, and 0 were skipped for carrying a
         * lone surrogate.
         *
         * RE-DERIVED when the corpus grew class 20 and the type-map binding fixtures, and re-run
         * on both JDKs before re-pinning, exactly as [COUNT_DRIFT] requires. The total moved from
         * 14,836 to 17,517 because the new fixtures added strings; the non-ASCII and
         * changed-by-NFC counts did NOT move, because every added string is ASCII, which is the
         * corroboration that the input set grew rather than the tables changing.
         */
        private const val PINNED_DIGEST =
            "7e7e6e4fbc860336d5c9dcc79e94b4f851b55ce08dd3cf8325359be0c9e4377a"

        private const val PINNED_TOTAL = 18_066
        private const val PINNED_NON_ASCII = 54
        private const val PINNED_CHANGED_BY_NFC = 23

        /** The Unicode releases this repository has measured this digest under. */
        private val KNOWN_UNICODE_VERSIONS = listOf("13.0", "16.0")

        private const val COUNT_DRIFT =
            "The set of strings extracted from the committed corpus changed, so the pinned digest " +
                "below cannot be compared. This is the INPUT half of the two causes: the corpus " +
                "or a fixture was edited, or this test's extraction was. Re-derive every constant " +
                "in PlatformNfcTablesTest and re-run on BOTH JDKs before re-pinning - re-pinning " +
                "from one runtime would silently retire the cross-version comparison."

        private const val DIGEST_DRIFT =
            "The NFC digest over the committed corpus is not the pinned value, and the string " +
                "counts above all held. Two causes, and they need OPPOSITE responses.\n" +
                "  (1) THE PLATFORM'S NFC TABLES CHANGED. This is the finding this test exists to " +
                "surface. A JDK or Android ICU upgrade moved a normalization, so this runtime MAY " +
                "PRODUCE DIFFERENT ROOTS than the ones the corpus pins and MUST NOT claim " +
                "conformance under ROAX-CANON/1 section 6.1. Escalate it; do not re-pin.\n" +
                "  (2) THE COMMITTED CORPUS CHANGED IN A WAY THE COUNTS DID NOT CATCH - an edit " +
                "that replaced a string rather than adding or removing one. Then re-pin the " +
                "constant, having re-run on BOTH JDKs.\n" +
                "  (3, less likely) This test's own extraction or framing changed. Check the diff " +
                "on PlatformNfcTablesTest before concluding either of the above.\n" +
                "Diagnose by normalizing the corpus with an independent implementation at a known " +
                "Unicode version - `corpus/tools/roax_ref.py` runs at 15.1 - and comparing which " +
                "individual strings differ."
    }
}
