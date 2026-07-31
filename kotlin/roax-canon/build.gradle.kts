plugins {
    kotlin("jvm")
    `java-library`
}

description = "ROAX-CANON/1 - canonical serialization, commitment and selective disclosure"

dependencies {
    // Zero runtime dependencies, deliberately.
    //
    // Everything this library needs is in java.lang, java.security, java.text and java.nio: SHA-256
    // from MessageDigest, the CSPRNG from SecureRandom, NFC from java.text.Normalizer, and strict
    // UTF-8 from a CharsetDecoder. The JSON reader, the base64 codec and the hex codec are written
    // here because every off-the-shelf one on this platform destroys something the specification
    // requires - see the class documentation on JsonReader, Base64Strict and Bytes.
    //
    // That is also what makes the artifact consumable from Android without a transitive graph.
    testImplementation(platform("org.junit:junit-bom:5.14.4"))
    testImplementation("org.junit.jupiter:junit-jupiter")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

/**
 * `-Proax.testJdk=25` runs the tests on a different JDK than the one that compiled them.
 *
 * This exists for one specific measurement. ROAX-CANON/1 section 6.1 pins Unicode 15.1, and the
 * NFC tables are a property of the runtime rather than of this library: JDK 17 ships Unicode 13.0
 * and JDK 25 ships 16.0, so no installed JDK is the pinned version. Running the whole corpus on
 * both is how `kotlin/FINDINGS.md` measures what that gap actually costs rather than asserting it
 * is harmless.
 */
val testJdk = (findProperty("roax.testJdk") as String?)?.toInt()

tasks.test {
    useJUnitPlatform()
    // The corpus tests read fixtures by repository-relative path.
    workingDir = rootProject.projectDir.parentFile
    if (testJdk != null) {
        javaLauncher.set(
            javaToolchains.launcherFor {
                languageVersion.set(JavaLanguageVersion.of(testJdk))
            },
        )
    }
    testLogging {
        events("failed")
        showStandardStreams = true
    }
}
