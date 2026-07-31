package io.roax.canon

import org.junit.jupiter.api.Assertions.assertArrayEquals
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.math.BigDecimal
import java.nio.charset.StandardCharsets
import java.text.Normalizer

/**
 * The platform hazards this library was written around, pinned as executable evidence.
 *
 * `docs/spec/roax-canon-1.md` section 6.4 lists Kotlin/JVM as the one target language whose
 * literal-preserving mechanism is "Not established", and section 2.2 says to treat that row as an
 * open engineering question rather than a solved one. These tests are what closes it: each one
 * demonstrates the platform behaviour that would have destroyed a requirement, and shows the
 * library not doing it.
 *
 * They are deliberately assertions about the JDK rather than about ROAX, so a future JDK that
 * changes one of them fails here loudly instead of silently moving a root.
 */
class JvmPlatformTrapTest {

    // ---------------------------------------------------------------------- BigDecimal ----------

    @Test
    fun `BigDecimal toString emits scientific notation the output grammar does not admit`() {
        // The canonical decimal output grammar is ^-?(0|[1-9][0-9]*)(\.[0-9]+)?$ (section 6.2).
        // None of these renderings is in it.
        assertEquals("1E+2", BigDecimal("1e2").toString())
        assertEquals("0E+5", BigDecimal("0e5").toString())
        assertEquals("1E-7", BigDecimal("1e-7").toString())
        assertEquals("1E+7", BigDecimal("1e7").toString())

        // And the library's answers, which are.
        assertEquals("100", Numbers.canonicalDecimal("1e2"))
        assertEquals("0", Numbers.canonicalDecimal("0e5"))
        assertEquals("0.0000001", Numbers.canonicalDecimal("1e-7"))
        assertEquals("10000000", Numbers.canonicalDecimal("1e7"))
    }

    @Test
    fun `BigDecimal toPlainString agrees on the worked examples, which is what makes it dangerous`() {
        // Every worked example in section 6.2 round-trips through toPlainString. An implementer who
        // checked only these would conclude BigDecimal is safe.
        val worked = mapOf(
            "1e2" to "100", "1.0e2" to "100", "1.00e1" to "10.0", "1.5e-2" to "0.015",
            "1e-3" to "0.001", "0e5" to "0", "0.010" to "0.010",
        )
        for ((input, expected) in worked) {
            assertEquals(expected, BigDecimal(input).toPlainString(), "toPlainString($input)")
            assertEquals(expected, Numbers.canonicalDecimal(input), "canonicalDecimal($input)")
        }
    }

    @Test
    fun `BigDecimal accepts input both ROAX grammars reject`() {
        // This is why the agreement above does not transfer: validation is a different question,
        // and BigDecimal's parser is not either ROAX grammar.
        for (input in listOf("+1", "007", ".5", "5.")) {
            // BigDecimal takes it.
            BigDecimal(input)
            // Both ROAX grammars refuse it.
            assertThrows(RoaxException::class.java, { Numbers.canonicalDecimal(input) }, "decimal $input")
            assertThrows(RoaxException::class.java, { Numbers.canonicalInteger(input) }, "integer $input")
        }
        // `-0` parses as zero under BigDecimal and is a grammar-valid ROAX INTEGER that normalizes
        // to `0`, so it is the one case that differs by normalization rather than by admissibility.
        assertEquals(0, BigDecimal("-0").signum())
        assertEquals("0", Numbers.canonicalInteger("-0"))
        // Exponent notation is valid DECIMAL and invalid INTEGER, in both letter cases. No single
        // numeric type expresses that split, which is the deeper reason the tag has to come from
        // the schema rather than from the literal's syntax (section 4).
        assertEquals("100", Numbers.canonicalDecimal("1e2"))
        assertEquals("100", Numbers.canonicalDecimal("1E2"))
        assertThrows(RoaxException::class.java) { Numbers.canonicalInteger("1e2") }
        assertThrows(RoaxException::class.java) { Numbers.canonicalInteger("1E2") }
    }

    @Test
    fun `BigDecimal equals compares scale, which is the wrong question for a leaf`() {
        val a = BigDecimal("0.010")
        val b = BigDecimal("0.01")
        assertFalse(a == b)
        assertEquals(0, a.compareTo(b))
        // Trailing zeros of the fraction are significant, so these are different leaves. FHIR R4
        // says implementations SHALL preserve that precision.
        assertNotEquals(
            Bytes.toHex(encodeValue(TypeTag.DECIMAL, RoaxValue.Decimal("0.010"))),
            Bytes.toHex(encodeValue(TypeTag.DECIMAL, RoaxValue.Decimal("0.01"))),
        )
        // stripTrailingZeros is the footgun that would erase it, and it also reintroduces
        // scientific notation on the way.
        assertEquals("2", BigDecimal("2.0").stripTrailingZeros().toString())
        assertEquals("1E+2", BigDecimal("100").stripTrailingZeros().toString())
        assertEquals("2.0", Numbers.canonicalDecimal("2.0"))
        assertEquals("100", Numbers.canonicalDecimal("100"))
    }

    @Test
    fun `the digit bound is decided arithmetically, before anything is materialized`() {
        // BigDecimal would have to expand ten thousand digits before its length could be measured,
        // and `1.4e+999999999` is a memory-exhaustion input under that approach.
        assertThrows(RoaxException::class.java) { Numbers.canonicalDecimal("1.4e+9999") }
        assertThrows(RoaxException::class.java) { Numbers.canonicalDecimal("1e1024") }
        assertThrows(RoaxException::class.java) { Numbers.canonicalDecimal("1.4e+999999999") }
        assertThrows(RoaxException::class.java) { Numbers.canonicalDecimal("1e-999999999") }
        // 1024 clears every vector the corpus requires to succeed: a 40-digit integer part with a
        // 40-digit fraction is 80 digits.
        val long = "1".repeat(40) + "." + "5".repeat(40)
        assertEquals(long, Numbers.canonicalDecimal(long))
    }

    @Test
    fun `no value ever passes through a double`() {
        // Section 6.4, stated normatively. These are the literals a float destroys.
        assertEquals("0.010", Numbers.canonicalDecimal("0.010"))
        assertEquals("9223372036854775807", Numbers.canonicalInteger("9223372036854775807"))
        assertEquals(
            "1234567890123456789.1",
            Numbers.canonicalDecimal("1234567890123456789.1"),
        )
        // What a double would have made of them.
        assertEquals("0.01", java.lang.Double.toString(0.010))
        assertEquals("9.223372036854776E18", java.lang.Double.toString(9223372036854775807.0))
    }

    // --------------------------------------------------------------- exponent expansion ----------

    @Test
    fun `exponent expansion reproduces every worked example in section 6-2`() {
        assertEquals("100", Numbers.canonicalDecimal("1e2"))
        assertEquals("100", Numbers.canonicalDecimal("1.0e2"))
        assertEquals("10.0", Numbers.canonicalDecimal("1.00e1"))
        assertEquals("0.015", Numbers.canonicalDecimal("1.5e-2"))
        assertEquals("0.001", Numbers.canonicalDecimal("1e-3"))
        assertEquals("0", Numbers.canonicalDecimal("0e5"))
        assertEquals("0.010", Numbers.canonicalDecimal("0.010"))
        // And the trailing-zero table.
        assertEquals("0.010", Numbers.canonicalDecimal("0.010"))
        assertEquals("1.50", Numbers.canonicalDecimal("1.50"))
        assertEquals("2.0", Numbers.canonicalDecimal("2.0"))
        assertEquals("0.00", Numbers.canonicalDecimal("-0.00"))
        // 1e2, 1.0e2 and 100 are the SAME leaf; 100.0 is a different one.
        assertEquals(Numbers.canonicalDecimal("1e2"), Numbers.canonicalDecimal("100"))
        assertEquals(Numbers.canonicalDecimal("1.0e2"), Numbers.canonicalDecimal("100"))
        assertNotEquals(Numbers.canonicalDecimal("100.0"), Numbers.canonicalDecimal("100"))
    }

    // ------------------------------------------------------------------ the regex `$` trap -------

    @Test
    fun `a trailing newline is refused, which a Java or Python regex anchor would have admitted`() {
        // `corpus/README.md` records this as the divergence the two reference implementations
        // caught: Python's `$` also matches immediately before a trailing newline, and Java's
        // behaves the same way under find(). The grammars here are hand-written scanners, so the
        // bug is not expressible.
        assertThrows(RoaxException::class.java) { Numbers.canonicalDecimal("1.0\n") }
        assertThrows(RoaxException::class.java) { Numbers.canonicalInteger("1\n") }
        assertThrows(RoaxException::class.java) { Numbers.canonicalDecimal("1.0 ") }

        // The trap itself, demonstrated on this platform so the claim is checkable.
        val javaAnchored = Regex("^-?(0|[1-9][0-9]*)$")
        assertTrue(javaAnchored.containsMatchIn("1\n"), "Java's \$ matches before a trailing newline")
        assertFalse(javaAnchored.matches("1\n"), "matches() requires the whole input, so it is safe")
    }

    // ------------------------------------------------------------------------- Unicode -----------

    @Test
    fun `an unpaired surrogate is rejected, because both platform operations are silent`() {
        val lone = "A\uD800"
        // getBytes substitutes an ASCII '?' rather than failing.
        assertArrayEquals(byteArrayOf(0x41, 0x3F), lone.toByteArray(StandardCharsets.UTF_8))
        // Normalizer passes it straight through.
        assertEquals(lone, Normalizer.normalize(lone, Normalizer.Form.NFC))
        // So the rejection has to be explicit, and it is - before normalization, per section 6.1.
        assertThrows(RoaxException::class.java) { utf8Strict(lone) }
        assertThrows(RoaxException::class.java) {
            encodeValue(TypeTag.STRING, RoaxValue.Text(lone))
        }
        assertThrows(RoaxException::class.java) { encodePath(listOf(Segment.Key(lone))) }
        // A properly paired surrogate is fine.
        assertEquals("f09f9880", Bytes.toHex(utf8Strict("😀")))
    }

    @Test
    fun `strict UTF-8 decoding refuses what String would have replaced silently`() {
        val malformed = byteArrayOf(0x7B, 0x22.toByte(), 0xC3.toByte(), 0x28, 0x22.toByte(), 0x7D)
        // The lenient path substitutes U+FFFD and reports nothing.
        assertTrue(String(malformed, StandardCharsets.UTF_8).contains('�'))
        assertThrows(RoaxException::class.java) { decodeUtf8Strict(malformed) }
    }

    @Test
    fun `the platform NFC tables are reported, because ROAX-CANON-1 pins a version this JDK may not have`() {
        // Section 6.1 pins Unicode 15.1 and makes a mismatch detectable BY DECLARATION rather than
        // by demonstration. No JDK ships 15.1 tables: 17 has 13.0 and 25 has 16.0. The version is a
        // property of the runtime, so the library reports it rather than claiming conformance.
        assertTrue(
            PlatformNfc.unicodeVersion in setOf("13.0", "14.0", "15.0", "15.1", "16.0"),
            "unexpected probed Unicode version ${PlatformNfc.unicodeVersion}",
        )
        // NFC itself works, and U+212A KELVIN SIGN normalizing to ASCII 'K' is the demonstration
        // section 11.2 uses to show that normalization can cross into ASCII.
        assertEquals("é", PlatformNfc.normalize("é"))
        assertEquals("K", PlatformNfc.normalize("K"))
    }

    // ------------------------------------------------------------------------- base64 ------------

    @Test
    fun `java util Base64 accepts spellings section 6-3 requires rejecting`() {
        val permissive = java.util.Base64.getDecoder()
        val canonical = "SGVsbG8="

        // Unpadded: accepted by the JDK, and it decodes to the same octets.
        assertArrayEquals(permissive.decode(canonical), permissive.decode("SGVsbG8"))
        assertThrows(RoaxException::class.java) { Base64Strict.decode("SGVsbG8") }

        // Non-zero unused bits in the final quantum, which RFC 4648 section 3.5 identifies as the
        // non-canonical case: also accepted, also the same octets.
        assertArrayEquals(permissive.decode(canonical), permissive.decode("SGVsbG9="))
        assertThrows(RoaxException::class.java) { Base64Strict.decode("SGVsbG9=") }

        // The URL-safe alphabet and a line break are refused by both, but for the record.
        assertThrows(RoaxException::class.java) { Base64Strict.decode("-_8=") }
        assertThrows(RoaxException::class.java) { Base64Strict.decode("SGVs\nbG8=") }
        assertThrows(RoaxException::class.java) { Base64Strict.decode("SGVsbG8==") }

        // The canonical form decodes, and round-trips.
        assertArrayEquals("Hello".toByteArray(), Base64Strict.decode(canonical))
        assertEquals(canonical, Base64Strict.encode("Hello".toByteArray()))
        assertArrayEquals(ByteArray(0), Base64Strict.decode(""))
    }
}
