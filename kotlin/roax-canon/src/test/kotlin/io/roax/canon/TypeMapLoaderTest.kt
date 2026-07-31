package io.roax.canon

import io.roax.canon.json.JsonReader
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test

/**
 * A malformed type map is refused, and it is refused through the [Reason] taxonomy.
 *
 * Both properties are load-bearing and neither is covered by the corpus, because every committed
 * map is well formed. The first is decision D7: a resolver whose entire contract is to fail closed
 * cannot quietly widen its own path language when the map that defines it is mis-authored. The
 * second is what `Errors.kt` claims - [RoaxException] is the single exception type and [Reason] is
 * total - and an artifact is parsed BEFORE its content ID can authenticate it, so a caller's
 * `catch (RoaxException)` is the only thing standing between malformed bytes and the process.
 */
class TypeMapLoaderTest {

    private val nfc = PlatformNfc

    private fun displayMap(vararg entries: String): DisplayPatternTypeMap =
        DisplayPatternTypeMap.load(
            """
            {"typeMapVersion":"1.0.0","recordType":"org.roax.corpus.synthetic",
             "schemaVersion":"1.0","entries":[${entries.joinToString(",")}]}
            """.trimIndent().toByteArray(),
            nfc,
        )

    private fun entry(pattern: String, tag: String = "2", kind: String = "\"string\"") =
        """{"pattern":"$pattern","jsonKind":$kind,"tag":$tag}"""

    private fun rejects(pattern: String): Reason =
        assertThrows(RoaxException::class.java) { displayMap(entry(pattern)) }.reason

    // ------------------------------------------------ an empty component is refused, not dropped --

    @Test
    fun `a display pattern with an empty component is refused rather than silently compiled`() {
        // Dropping the empty component would compile `a..b` to the two-segment path `a.b`, binding
        // a path the author never wrote. Display notation cannot address an empty key at all -
        // ambiguity 5 in `corpus/README.md` - so rejecting is the only reading that does not
        // invent a binding.
        assertEquals(Reason.JSON_SYNTAX, rejects(".a"))
        assertEquals(Reason.JSON_SYNTAX, rejects("a..b"))
        assertEquals(Reason.JSON_SYNTAX, rejects("a."))
        assertEquals(Reason.JSON_SYNTAX, rejects("a.[0]"))
        assertEquals(Reason.JSON_SYNTAX, rejects("."))
    }

    @Test
    fun `a dot after a closing bracket is a separator, not an empty component`() {
        // The regression guard for the above: in `entry[0].fullUrl` the `.` also arrives with no
        // pending key characters, and 143 committed corpus patterns have that shape. A rejection
        // predicate that cannot tell the two apart takes out every one of them.
        val map = displayMap(
            entry("entry[0].fullUrl"),
            entry("entry[*].resource.id"),
            entry("plain"),
            entry("under.**"),
        )
        assertEquals(
            TypeTag.STRING,
            map.resolve(listOf(Segment.Key("entry"), Segment.Index(0), Segment.Key("fullUrl")), JsonKind.STRING),
        )
        assertEquals(
            TypeTag.STRING,
            map.resolve(
                listOf(Segment.Key("entry"), Segment.Index(7), Segment.Key("resource"), Segment.Key("id")),
                JsonKind.STRING,
            ),
        )
        assertEquals(TypeTag.STRING, map.resolve(listOf(Segment.Key("plain")), JsonKind.STRING))
        assertEquals(
            TypeTag.STRING,
            map.resolve(listOf(Segment.Key("under"), Segment.Key("x")), JsonKind.STRING),
        )
        assertNull(map.resolve(listOf(Segment.Key("entry"), Segment.Key("fullUrl")), JsonKind.STRING))
    }

    // --------------------------------------------------------------- an index body is plain digits --

    @Test
    fun `a display pattern index body must be plain ASCII digits`() {
        // A numeric parse admits both signs. `[-1]` is worse than useless: no record can carry a
        // negative index, so the binding is permanently dead while reading as if it bound
        // something. `[+1]` is the same path as `[1]` under a second spelling.
        assertEquals(Reason.JSON_SYNTAX, rejects("a[+1]"))
        assertEquals(Reason.JSON_SYNTAX, rejects("a[-1]"))
        assertEquals(Reason.JSON_SYNTAX, rejects("a[]"))
        assertEquals(Reason.JSON_SYNTAX, rejects("a[1x]"))
        // U+0661 ARABIC-INDIC DIGIT ONE, which `Char.isDigit` accepts and this must not. Written as
        // an escape so a tool that rewrites this file cannot turn it into an ASCII `1`.
        assertEquals(Reason.JSON_SYNTAX, rejects("a[\u0661]"))
        assertEquals(Reason.JSON_SYNTAX, rejects("a[0"))
        assertEquals(Reason.JSON_SYNTAX, rejects("a]"))

        val map = displayMap(entry("a[0]"), entry("b[*]"))
        assertEquals(TypeTag.STRING, map.resolve(listOf(Segment.Key("a"), Segment.Index(0)), JsonKind.STRING))
        assertNull(map.resolve(listOf(Segment.Key("a"), Segment.Index(1)), JsonKind.STRING))
        assertEquals(TypeTag.STRING, map.resolve(listOf(Segment.Key("b"), Segment.Index(9)), JsonKind.STRING))
    }

    // ------------------------------------------ a malformed tag or kind stays inside the taxonomy --

    @Test
    fun `a display map naming an unknown tag or kind raises a RoaxException`() {
        assertEquals(Reason.JSON_SYNTAX, assertThrows(RoaxException::class.java) {
            displayMap(entry("a", tag = "9"))
        }.reason)
        // Twenty digits: well inside the 1024-digit bound `canonicalInteger` enforces, so the
        // literal reaches the Int conversion intact and the overflow has to be caught there.
        assertEquals(Reason.JSON_SYNTAX, assertThrows(RoaxException::class.java) {
            displayMap(entry("a", tag = "99999999999999999999"))
        }.reason)
        assertEquals(Reason.JSON_SYNTAX, assertThrows(RoaxException::class.java) {
            displayMap(entry("a", kind = "\"objekt\""))
        }.reason)
    }

    @Test
    fun `a DFA artifact naming an unknown tag or kind raises a RoaxException`() {
        fun artifact(tag: String, kind: String) = """
            {"typeMapVersion":"1.0.0","recordType":"org.roax.corpus.synthetic",
             "schemaVersion":"1.0","automaton":{"start":"s0","states":[
               {"id":"s0","keys":[{"key":"a","to":"s1"}]},
               {"id":"s1","bindings":[{"jsonKind":$kind,"tag":$tag}]}]}}
        """.trimIndent().toByteArray()

        val ok = DfaTypeMap.load(artifact("2", "\"string\""), nfc)
        assertEquals(TypeTag.STRING, ok.resolve(listOf(Segment.Key("a")), JsonKind.STRING))

        val malformed = listOf(
            artifact("9", "\"string\""),
            artifact("99999999999999999999", "\"string\""),
            artifact("2", "\"objekt\""),
        )
        for (bad in malformed) {
            val e = assertThrows(RoaxException::class.java) { DfaTypeMap.load(bad, nfc) }
            assertEquals(Reason.JSON_SYNTAX, e.reason)
        }
    }

    // ---------------------------------------------- a third-party resolver cannot smuggle in tag 8 --

    @Test
    fun `a resolver returning BLOB_REF is refused as blob-ref-not-declared, not as a kind mismatch`() {
        // Both loaders reject an artifact that binds tag 8, but `TypeResolver` is public API, so a
        // caller's own resolver reaches the flattener without passing either. Section 6.5 requires
        // rejecting tag 8 specifically, so the reason code is the substance.
        val blobEverywhere = object : TypeResolver {
            override fun resolve(segments: List<Segment>, kind: JsonKind): TypeTag = TypeTag.BLOB_REF
        }
        val options = FlattenOptions(resolver = blobEverywhere, nfc = nfc)

        val records = listOf(
            """{"a":"x"}""",
            """{"a":1}""",
            """{"a":true}""",
            """{"a":null}""",
            """{"a":[]}""",
            """{"a":{}}""",
        )
        for (record in records) {
            val e = assertThrows(RoaxException::class.java) {
                flattenRecord(JsonReader.parse(record), options)
            }
            assertEquals(Reason.BLOB_REF_NOT_DECLARED, e.reason, "record $record")
        }
    }
}
