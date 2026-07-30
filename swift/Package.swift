// swift-tools-version: 5.9
import PackageDescription

// ROAX-CANON/1, the fourth independent implementation.
//
// Zero product dependencies. SHA-256 comes from CryptoKit where it exists and
// from the in-tree reference block otherwise; see Sources/ROAXCanon/Hashing.swift.
// The package builds for macOS and iOS because it is destined for an iOS app,
// and it also builds anywhere Swift does, because nothing here needs Darwin.
let package = Package(
    name: "ROAXCanon",
    platforms: [
        .macOS(.v13),
        .iOS(.v16),
    ],
    products: [
        .library(name: "ROAXCanon", targets: ["ROAXCanon"]),
        .executable(name: "roax-conformance", targets: ["roax-conformance"]),
    ],
    targets: [
        .target(name: "ROAXCanon"),
        // The corpus runner is a library rather than only an executable, so
        // `swift test` is a real gate over the committed corpus rather than a
        // second suite that could pass while the corpus failed.
        .target(name: "ROAXCanonCorpus", dependencies: ["ROAXCanon"]),
        .executableTarget(name: "roax-conformance", dependencies: ["ROAXCanonCorpus"]),
        .testTarget(name: "ROAXCanonTests", dependencies: ["ROAXCanon", "ROAXCanonCorpus"]),
    ]
)
