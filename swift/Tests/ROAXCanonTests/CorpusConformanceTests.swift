import XCTest
@testable import ROAXCanon
import ROAXCanonCorpus

/// The committed corpus, run as a test rather than only as an executable.
///
/// `corpus/README.md`: with five independent libraries and no shared code the
/// corpus is the whole enforcement mechanism for cross-language agreement. A
/// suite that passed while the corpus failed would be measuring the wrong
/// thing, so `swift test` runs it.
final class CorpusConformanceTests: XCTestCase {

    static func repoRoot() -> URL? {
        var url = URL(fileURLWithPath: #filePath).standardizedFileURL
        while true {
            if FileManager.default.fileExists(
                atPath: url.appendingPathComponent("corpus/conformance-corpus-1.0.json").path
            ) { return url }
            let parent = url.deletingLastPathComponent()
            if parent.path == url.path { return nil }
            url = parent
        }
    }

    /// Every vector the corpus can run without an input from outside this tree.
    ///
    /// Class 10 needs the pinned third-party reference checkout, which
    /// `.gitignore` excludes by design, so it is NOT RUN here unless
    /// `ROAX_REFERENCE_RECORDS` names a directory of extracted records. A NOT
    /// RUN vector is never counted as passed.
    func testCommittedCorpusPasses() throws {
        guard let root = Self.repoRoot() else {
            XCTFail("cannot locate the repository root from \(#filePath)")
            return
        }
        let references = ProcessInfo.processInfo.environment["ROAX_REFERENCE_RECORDS"]
            .map { URL(fileURLWithPath: $0) }

        let runner = try CorpusRunner(
            root: root,
            referenceRecords: references,
            // The corpus reading of specification section 3.3; the divergence
            // and its exact cost are asserted by
            // `testSpecificationEmptyContainerReadingCostsExactlyTwoVectors`.
            emptyContainerPolicy: .assignedWithoutMapAuthorization
        )
        runner.run()

        XCTAssertEqual(
            runner.report.failed, 0,
            "corpus failures:\n" + runner.report.failures.joined(separator: "\n")
        )
        XCTAssertGreaterThan(runner.report.passed, 480, "far fewer vectors ran than the corpus holds")

        if references == nil {
            XCTAssertEqual(runner.report.notRun, 4,
                           "only the four class-10 vectors may be NOT RUN without a reference checkout")
        } else {
            XCTAssertEqual(runner.report.notRun, 0,
                           "with a reference checkout every vector must run")
        }
    }

    /// **The release-blocking corpus defect, measured rather than described.**
    ///
    /// Specification section 3.3 says tags 6 and 7 are assigned "only when the
    /// exact selected map authorizes that structured path and observed kind",
    /// because assigning them earlier lets an unknown empty issuer extension
    /// bypass decision D7's fail-closed rule. The committed corpus does not
    /// implement that rule: `corpus/type-maps/org.roax.corpus.synthetic.json`
    /// declares `a.b` for `jsonKind: "null"` alone while two class-5 fixtures
    /// carry an empty array and an empty object there.
    ///
    /// This test pins the cost at exactly 2 vectors, so the finding cannot
    /// silently grow or shrink, and so that a corpus fix is detected here as
    /// this assertion changing rather than as a mystery.
    func testSpecificationEmptyContainerReadingCostsExactlyTwoVectors() throws {
        guard let root = Self.repoRoot() else { return XCTFail("no repo root") }
        let runner = try CorpusRunner(
            root: root,
            referenceRecords: ProcessInfo.processInfo.environment["ROAX_REFERENCE_RECORDS"]
                .map { URL(fileURLWithPath: $0) },
            emptyContainerPolicy: .mapAuthorized
        )
        runner.run()

        XCTAssertEqual(runner.report.failed, 2, """
            Under the specification reading exactly two class-5 vectors must fail.
            Actual failures:
            \(runner.report.failures.joined(separator: "\n"))
            """)
        for failure in runner.report.failures {
            XCTAssertTrue(
                failure.contains("record-structure-empty-array")
                    || failure.contains("record-structure-empty-object"),
                "an unexpected vector fails under the specification reading: \(failure)"
            )
        }
    }
}
