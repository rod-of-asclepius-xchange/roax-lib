plugins {
    kotlin("jvm") version "2.3.21" apply false
    id("com.android.library") version "9.2.1" apply false
}

// The whole build targets Java 11 bytecode. That is the Android-compatible floor this library
// commits to, and it is enforced rather than hoped for: `AndroidApiSurfaceTest` reads the compiled
// class files back and asserts that every JDK type they reference exists on Android.
subprojects {
    plugins.withId("org.jetbrains.kotlin.jvm") {
        extensions.configure<org.jetbrains.kotlin.gradle.dsl.KotlinJvmProjectExtension>("kotlin") {
            jvmToolchain(17)
            compilerOptions {
                jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_11)
                freeCompilerArgs.add("-Xjdk-release=11")
                allWarningsAsErrors.set(true)
            }
        }
        tasks.withType<JavaCompile>().configureEach {
            options.release.set(11)
        }
    }
}
