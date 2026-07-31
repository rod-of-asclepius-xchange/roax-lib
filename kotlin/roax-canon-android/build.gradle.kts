// AGP 9 carries Kotlin support built in, so `org.jetbrains.kotlin.android` is not applied here and
// applying it is an error: https://kotl.in/gradle/agp-built-in-kotlin
plugins {
    id("com.android.library")
}

/**
 * The Android packaging of the same library sources.
 *
 * There is deliberately NO separate source set: this module compiles `:roax-canon`'s `src/main`
 * directly, so the Android artifact cannot drift from the JVM one. A second copy of the
 * canonicalization code is the failure mode ruled decision D is trying to avoid between LANGUAGES,
 * and it would be no better inside one.
 *
 * `minSdk` is 21 because that is the floor the API surface is checked against by
 * `AndroidApiSurfaceTest`, which is what actually keeps `java.util.Base64` (API 26+) and
 * `java.util.HexFormat` (absent) out of the library.
 */
android {
    namespace = "io.roax.canon"
    compileSdk = 36

    defaultConfig {
        minSdk = 21
        consumerProguardFiles("consumer-rules.pro")
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    sourceSets {
        named("main") {
            kotlin.setSrcDirs(listOf(project(":roax-canon").file("src/main/kotlin")))
            manifest.srcFile("src/main/AndroidManifest.xml")
            res.setSrcDirs(emptyList<String>())
        }
    }

    // The unit tests live in :roax-canon, where they run on a real JVM against the committed
    // corpus. Duplicating them here would run the same assertions on the same bytecode.
    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

