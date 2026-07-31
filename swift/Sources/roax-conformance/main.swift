import Foundation
import ROAXCanon
import ROAXCanonCorpus

// The corpus runner for the Swift implementation of ROAX-CANON/1.
//
//   swift run roax-conformance [--root <repo>] [--references <dir>]
//                              [--empty-containers spec|corpus]
//
// Exit status follows `corpus/README.md`:
//   0  every check and vector ran and passed
//   1  at least one check ran and failed
//   2  nothing failed, but at least one check or vector was NOT RUN

func findRepoRoot(from start: URL) -> URL? {
    var url = start.standardizedFileURL
    while true {
        if FileManager.default.fileExists(
            atPath: url.appendingPathComponent("corpus/conformance-corpus-1.0.json").path
        ) { return url }
        let parent = url.deletingLastPathComponent()
        if parent.path == url.path { return nil }
        url = parent
    }
}

var rootArgument: String? = ProcessInfo.processInfo.environment["ROAX_CORPUS_ROOT"]
var referencesArgument: String? = ProcessInfo.processInfo.environment["ROAX_REFERENCE_RECORDS"]
var emptyContainerPolicy = EmptyContainerPolicy.assignedWithoutMapAuthorization

func usageError(_ detail: String) -> Never {
    FileHandle.standardError.write(Data("\(detail)\n".utf8))
    // 64 rather than 2: a mistyped flag is a usage error, and a caller that
    // treats NOT RUN as tolerable must not also tolerate this.
    exit(64)
}

var arguments = Array(CommandLine.arguments.dropFirst())
while let flag = arguments.first {
    arguments.removeFirst()

    /// A flag's value, or a usage error. Taking `arguments.first` and
    /// tolerating nil would overwrite an environment-supplied value with
    /// nothing, so a missing value would silently un-set `ROAX_CORPUS_ROOT`.
    func value(of flag: String) -> String {
        guard let next = arguments.first, !next.hasPrefix("--") else {
            usageError("\(flag) needs a value")
        }
        arguments.removeFirst()
        return next
    }

    switch flag {
    case "--root":
        rootArgument = value(of: flag)
    case "--references":
        referencesArgument = value(of: flag)
    case "--empty-containers":
        // An unrecognized mode is a usage error, never a silent fallback to the
        // corpus reading: falling back would exit 0 while the operator believed
        // they had run the specification reading that costs 2 class-5 vectors.
        switch value(of: flag) {
        case "spec": emptyContainerPolicy = .mapAuthorized
        case "corpus": emptyContainerPolicy = .assignedWithoutMapAuthorization
        case let mode: usageError("--empty-containers takes spec or corpus, not \(mode.debugDescription)")
        }
    default:
        usageError("unknown flag \(flag)")
    }
}

let start = rootArgument.map { URL(fileURLWithPath: $0) }
    ?? URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
guard let root = findRepoRoot(from: start) else {
    FileHandle.standardError.write(Data(
        "cannot find corpus/conformance-corpus-1.0.json from \(start.path); pass --root\n".utf8
    ))
    exit(64)
}

let referenceRecords = referencesArgument.map { URL(fileURLWithPath: $0) }

print("ROAX-CANON/1 conformance, Swift implementation")
print("  corpus root      \(root.path)")
print("  hash             \(SHA256Hash.identifier)")
print("  NFC              Foundation precomposedStringWithCanonicalMapping, declared pin "
      + "\(NFC.declaredUnicodeVersion) (see swift/FINDINGS.md finding 5)")
switch emptyContainerPolicy {
case .assignedWithoutMapAuthorization:
    print("  empty containers CORPUS reading - tags 6 and 7 assigned without map authorization.")
    print("                   Specification section 3.3 requires the map to authorize them; the")
    print("                   committed corpus does not implement that rule. Run with")
    print("                   --empty-containers spec to see the 2 class-5 vectors it costs.")
case .mapAuthorized:
    print("  empty containers SPECIFICATION reading - section 3.3 as written.")
}
if let referenceRecords {
    print("  reference records \(referenceRecords.path)")
} else {
    print("  reference records NOT SUPPLIED; class 10 will report NOT RUN")
}

do {
    let runner = try CorpusRunner(
        root: root,
        referenceRecords: referenceRecords,
        emptyContainerPolicy: emptyContainerPolicy
    )
    runner.run()
    runner.report.print()
    exit(runner.report.exitCode)
} catch {
    FileHandle.standardError.write(Data("runner failed to start: \(error)\n".utf8))
    exit(1)
}
