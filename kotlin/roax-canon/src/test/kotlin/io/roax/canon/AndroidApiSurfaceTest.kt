package io.roax.canon

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.io.DataInputStream
import java.io.File
import java.util.TreeSet

/**
 * Proves the compiled library is consumable from Android **without needing an Android SDK to
 * check**.
 *
 * The library is destined for the dogtag Android app, and the usual evidence for that - "we applied
 * the Android Gradle Plugin and it compiled" - needs an SDK, a licence acceptance and a network,
 * none of which this repository has in CI (there is no CI at all). So the check is done directly on
 * the bytecode: every JDK type the class files reference is compared against an allow-list of types
 * that exist in the Android runtime, and the class-file version is asserted to be the Java 11 floor.
 *
 * This is what actually catches the two mistakes that would break the Android build:
 * `java.util.Base64` (API 26+) and `java.util.HexFormat` (absent entirely), both of which are easy
 * to reach for and both of which this library hand-rolls for exactly this reason.
 */
class AndroidApiSurfaceTest {

    /**
     * JDK packages and types this library may reference, all present on Android API 21+.
     *
     * Kept as a deliberately short list rather than a broad package allowance: the point is that
     * the surface is small enough to enumerate, and a new entry should be a decision rather than an
     * accident.
     */
    private val allowedPrefixes = listOf(
        "java/lang/",
        "java/io/IOException",
        "java/nio/ByteBuffer",
        "java/nio/CharBuffer",
        "java/nio/charset/",
        "java/security/MessageDigest",
        "java/security/SecureRandom",
        "java/security/NoSuchAlgorithmException",
        "java/text/Normalizer",
        "java/util/List",
        "java/util/Map",
        "java/util/Set",
        "java/util/Collection",
        "java/util/Iterator",
        "java/util/ArrayList",
        "java/util/HashMap",
        "java/util/HashSet",
        "java/util/LinkedHashMap",
        "java/util/LinkedHashSet",
        "java/util/Arrays",
        "java/util/Objects",
        "java/util/NoSuchElementException",
        "java/util/Comparator",
        "kotlin/",
        "org/jetbrains/annotations/",
        "io/roax/canon/",
    )

    /** Types that exist on the JDK but NOT on Android, or only above API 21. */
    private val forbidden = mapOf(
        "java/util/Base64" to "API 26+; use io.roax.canon.Base64Strict, which is stricter anyway",
        "java/util/HexFormat" to "JDK 17+ only, absent on Android; use io.roax.canon.Bytes",
        "java/time/" to "API 26+ without desugaring",
        "java/util/stream/" to "API 24+",
        "java/util/function/" to "API 24+",
        "java/util/Optional" to "API 24+",
        "java/lang/ProcessHandle" to "absent on Android",
        "javax/" to "not part of the Android runtime",
    )

    private fun classFiles(): List<File> {
        val roots = listOf(
            File("kotlin/roax-canon/build/classes/kotlin/main"),
            File("../kotlin/roax-canon/build/classes/kotlin/main"),
            File("roax-canon/build/classes/kotlin/main"),
        )
        val root = roots.firstOrNull { it.isDirectory }
            ?: File(Corpus2.repoRoot, "kotlin/roax-canon/build/classes/kotlin/main")
        assertTrue(root.isDirectory, "compiled classes not found at ${root.absolutePath}")
        return root.walkTopDown().filter { it.isFile && it.extension == "class" }.toList()
    }

    private object Corpus2 {
        val repoRoot: File by lazy {
            var dir: File? = File(".").absoluteFile
            while (dir != null) {
                if (File(dir, "corpus/conformance-corpus-1.0.json").isFile) return@lazy dir
                dir = dir.parentFile
            }
            File(".")
        }
    }

    @Test
    fun `the library references only JDK types the Android runtime has`() {
        val files = classFiles()
        assertTrue(files.size >= 10, "expected the whole library, found ${files.size} class files")

        val referenced = TreeSet<String>()
        for (f in files) referenced.addAll(classReferences(f))

        val violations = referenced.filter { name ->
            allowedPrefixes.none { name.startsWith(it) }
        }
        assertEquals(
            emptyList<String>(),
            violations,
            "these referenced types are outside the Android-safe allow-list",
        )

        for ((bad, why) in forbidden) {
            val hits = referenced.filter { it.startsWith(bad) }
            assertEquals(emptyList<String>(), hits, "$bad is not usable on Android: $why")
        }
    }

    @Test
    fun `the library is compiled to Java 11 bytecode`() {
        // Java 11 is class-file major version 55. Android's toolchain accepts it; a higher target
        // would need a newer AGP and a higher minSdk for no benefit here.
        for (f in classFiles()) {
            DataInputStream(f.inputStream().buffered()).use { input ->
                assertEquals(0xCAFEBABE.toInt(), input.readInt(), "${f.name} is not a class file")
                input.readUnsignedShort() // minor
                assertEquals(55, input.readUnsignedShort(), "${f.name} targets the wrong JVM version")
            }
        }
    }

    /** Reads the CONSTANT_Class entries out of a class file's constant pool. */
    private fun classReferences(file: File): Set<String> {
        DataInputStream(file.inputStream().buffered()).use { input ->
            input.readInt() // magic
            input.readUnsignedShort() // minor
            input.readUnsignedShort() // major
            val count = input.readUnsignedShort()
            val utf8 = HashMap<Int, String>()
            val classIndexes = ArrayList<Int>()
            var i = 1
            while (i < count) {
                when (val tag = input.readUnsignedByte()) {
                    1 -> utf8[i] = input.readUTF()
                    7 -> classIndexes.add(input.readUnsignedShort())
                    8, 16, 19, 20 -> input.skipBytes(2)
                    15 -> input.skipBytes(3)
                    3, 4, 9, 10, 11, 12, 17, 18 -> input.skipBytes(4)
                    5, 6 -> { input.skipBytes(8); i++ } // long and double take two slots
                    else -> throw IllegalStateException("unhandled constant pool tag $tag in $file")
                }
                i++
            }
            return classIndexes.mapNotNull { utf8[it] }
                // An array descriptor such as `[Ljava/lang/String;` names its element type.
                .map { it.trimStart('[').removePrefix("L").removeSuffix(";") }
                .filter { !it.startsWith("[") && it.length > 1 }
                .toSet()
        }
    }
}
