rootProject.name = "roax-canon-kotlin"

pluginManagement {
    repositories {
        gradlePluginPortal()
        google()
        mavenCentral()
    }
}

dependencyResolutionManagement {
    repositories {
        mavenCentral()
        google()
    }
}

include(":roax-canon")

// The Android library is an OPTIONAL module, included only when an SDK is actually locatable.
//
// The library itself is plain Kotlin/JVM compiled to Java 11 bytecode with an Android-safe API
// surface, and `AndroidApiSurfaceTest` proves that from the class files with no SDK involved. This
// module exists so the AAR is a real build product rather than a claim, but gating it keeps
// `gradle build` working for a contributor who has no Android SDK - which is everyone who is only
// touching the canonicalization code, and which matters because this repository has no CI to fall
// back on.
// `-Proax.skipAndroid=true` forces the JVM-only configuration, which is how the SDK-absent branch
// is exercised on a machine that happens to have an SDK installed.
val skipAndroid = (startParameter.projectProperties["roax.skipAndroid"] ?: "false").toBoolean()

val androidSdk: String? = if (skipAndroid) null else sequenceOf(
    System.getenv("ANDROID_HOME"),
    System.getenv("ANDROID_SDK_ROOT"),
    file("local.properties").takeIf { it.isFile }
        ?.readLines()
        ?.firstOrNull { it.startsWith("sdk.dir=") }
        ?.removePrefix("sdk.dir="),
    "${System.getProperty("user.home")}/Library/Android/sdk",
    "${System.getProperty("user.home")}/Android/Sdk",
).filterNotNull().firstOrNull { File(it, "platforms").isDirectory }

if (androidSdk != null) {
    gradle.extra["roax.androidSdk"] = androidSdk
    include(":roax-canon-android")
} else {
    logger.lifecycle(
        "roax-canon: no Android SDK found, so :roax-canon-android is not configured. " +
            "The JVM library still builds, and AndroidApiSurfaceTest still proves its API surface " +
            "is Android-safe. Set ANDROID_HOME to build the AAR.",
    )
}
