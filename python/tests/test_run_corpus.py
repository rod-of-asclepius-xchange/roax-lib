"""Terminal-status regressions for the standalone conformance runner."""

from __future__ import annotations

import os
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import run_corpus  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "python" / "tools" / "run_corpus.py"
REFERENCE_MODULE = (
    Path("schemata")
    / "src"
    / "sg"
    / "gov"
    / "moh"
    / "recovery-healthcert"
    / "2.0"
    / "sample-data.ts"
)
# Class 10 covers two profiles since the vaccination bindings were ruled, and a fixture that
# supplies only one of them leaves the other genuinely NOT RUN. That would blur the parse-failure
# test below, whose whole point is that an unparseable module is reported as a FAILURE and never
# as a missing reference.
VACCINATION_MODULE = (
    Path("schemata")
    / "src"
    / "sg"
    / "gov"
    / "moh"
    / "vaccination-healthcert"
    / "1.0"
    / "sample-data.ts"
)
UNPARSEABLE_EXPORTS = (
    (REFERENCE_MODULE, "sampleDocument"),
    (VACCINATION_MODULE, "sampleVaccineHealthCert"),
)


class RunnerStatusTests(unittest.TestCase):
    def run_runner(
        self,
        *args: str,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("ROAX_REFERENCES", None)
        if environment:
            env.update(environment)
        return subprocess.run(
            [sys.executable, str(RUNNER), *args],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def test_missing_reference_module_is_incomplete_exit_two(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_runner("--references", directory)

            first_attempt = Path(directory) / REFERENCE_MODULE
            fallback_attempt = Path(directory) / Path(*REFERENCE_MODULE.parts[1:])
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            # Four rather than two: class 10 gained the vaccination record once its two
            # unresolved paths were ruled (`docs/type-maps.md` section 1.1).
            self.assertIn("10       0       0        4  NOT RUN", result.stdout)
            self.assertIn(f"attempted {first_attempt} and {fallback_attempt}", result.stdout)
            self.assertIn(
                "rerun with --references /path/to/schemata",
                result.stdout,
            )
            self.assertIn(
                "RESULT: INCOMPLETE / NOT RUN "
                "(785 assertions passed; 4 not run; 19/20 classes passed)",
                result.stdout,
            )
            self.assertNotIn("RESULT: PASS", result.stdout)
            self.assertNotIn("Skipped:", result.stdout)

    def test_roax_references_supplies_the_default_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_runner(environment={"ROAX_REFERENCES": directory})

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(f"references        {directory}", result.stdout)
            self.assertIn(str(Path(directory) / REFERENCE_MODULE), result.stdout)
            self.assertIn("RESULT: INCOMPLETE / NOT RUN", result.stdout)

    def test_reference_parse_failure_is_a_failure_instead_of_a_crash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            # BOTH class-10 modules, so nothing in the class is NOT RUN for an unrelated
            # reason. The assertion below is that an unparseable module is reported as a
            # FAILURE and never as a missing reference, and a half-populated checkout would
            # put the missing-reference hint in the output legitimately and blur exactly that.
            modules = []
            for relative, export in UNPARSEABLE_EXPORTS:
                module = Path(directory) / relative
                module.parent.mkdir(parents=True, exist_ok=True)
                module.write_text(f"export const {export} = makeDocument();\n", encoding="utf-8")
                modules.append((module, export))

            result = self.run_runner("--references", directory)

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            for module, export in modules:
                self.assertIn(
                    f"could not extract {export!r} from reference module {module}",
                    result.stdout,
                )
            self.assertIn("ValueError: unsupported literal", result.stdout)
            self.assertNotIn(
                "rerun with --references /path/to/schemata",
                result.stdout,
            )
            self.assertIn(
                "RESULT: FAIL " "(785 passed; 4 failed; 0 not run; 19/20 classes passed)",
                result.stdout,
            )
            self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_unsupported_reject_shape_is_a_failure(self) -> None:
        results = run_corpus.Results()

        def unreachable_maps(record_type: str):
            raise AssertionError(f"a shapeless reject vector must not resolve {record_type}")

        run_corpus.run_reject(
            [
                {
                    "class": 3,
                    "name": "unsupported-shape",
                    "input": {"notAnEscape": True},
                    "reason": "invalid-json",
                }
            ],
            unreachable_maps,
            results,
        )

        self.assertEqual(
            results.failed[3],
            ["unsupported-shape: unsupported reject-vector input shape"],
        )
        self.assertFalse(results.not_run)

    def test_missing_committed_type_map_is_a_failure(self) -> None:
        results = run_corpus.Results()
        missing = "/tmp/roax-missing-committed-type-map.json"

        def maps(_record_type: str):
            raise FileNotFoundError(2, "No such file or directory", missing)

        run_corpus.run_type_map(
            [
                {
                    "class": 11,
                    "name": "missing-map",
                    "recordType": "org.roax.missing",
                }
            ],
            maps,
            results,
        )

        self.assertEqual(
            results.failed[11],
            [f"missing-map: committed corpus type map is missing: {missing}"],
        )
        self.assertFalse(results.not_run)

    def test_record_vector_envelope_carrier_is_a_failure(self) -> None:
        results = run_corpus.Results()

        run_corpus.run_record(
            [
                {
                    "class": 10,
                    "name": "unsupported-carrier",
                    "envelopeFile": "corpus/fixtures/envelopes/example.json",
                }
            ],
            lambda _record_type: None,
            results,
            references=None,
            authorize_empty=False,
        )

        self.assertEqual(
            results.failed[10],
            ["unsupported-carrier: unsupported record-vector envelope carrier"],
        )
        self.assertFalse(results.not_run)

    def test_envelope_two_record_vector_runs_rather_than_reporting_not_run(self) -> None:
        """A record vector selecting `RESERVED_V2` is RUN, not skipped.

        THIS TEST REPLACES ONE THAT ASSERTED THE OPPOSITE. It required such a vector to be
        reported NOT RUN, because `build_tree` refused `RESERVED_V2` outright "until an
        artifact-aware resolver can reproduce and select the exact content ID". That refusal
        was over-broad: an issuer knows which artifact it used and supplies its identifier,
        and nothing about committing `roax.typeMap.id` requires fetching or reproducing
        anything. Specification section 11.2 marks that leaf emitted ALWAYS, so the refusal
        made this package unable to issue any record the current specification admits.

        A vector that CAN run must not be reported NOT RUN either: could-not-check is a third
        status for work genuinely blocked on a missing input, and using it for work the
        package can do would hide a failure behind an excuse.
        """
        results = run_corpus.Results()
        record_file = os.path.join(
            run_corpus.REPO, "corpus", "fixtures", "records", "roundtrip-carriers.json"
        )
        salts_file = os.path.join(
            run_corpus.REPO, "corpus", "fixtures", "salts", "roundtrip-every-carrier-form.json"
        )

        run_corpus.run_record(
            [
                {
                    "class": 10,
                    "name": "envelope-two-selector",
                    "recordType": "org.roax.corpus.synthetic",
                    "schemaVersion": "1.0",
                    "recordId": "urn:uuid:11111111-1111-4111-8111-111111111111",
                    "issuerId": "did:web:corpus.roax.invalid",
                    "issuerKeyId": "did:web:corpus.roax.invalid#key-1",
                    "typeMapId": "sha256:" + "0" * 64,
                    "recordFile": os.path.relpath(record_file, run_corpus.REPO),
                    "saltsFile": os.path.relpath(salts_file, run_corpus.REPO),
                    "saltPairing": "path",
                    "leafCount": 0,
                    "root": "0" * 64,
                }
            ],
            lambda record_type: run_corpus.DisplayPatternTypeMap.from_file(
                os.path.join(run_corpus.TYPE_MAP_DIR, f"{record_type}.json")
            ),
            results,
            references=None,
            authorize_empty=False,
        )

        self.assertFalse(results.not_run, "a vector this package can run must never be skipped")
        # The vector's pinned figures above are deliberately wrong, so what is asserted is
        # that the runner REACHED them: a refusal would have produced neither comparison.
        self.assertEqual(len(results.failed[10]), 2)
        self.assertIn("leafCount", results.failed[10][0])
        self.assertIn("root", results.failed[10][1])

    def test_record_salt_pairing_disagreement_is_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "record.json").write_text('{"marker":"m"}', encoding="utf-8")
            (root / "salts.json").write_text(
                json.dumps({"pairing": "path", "salts": []}),
                encoding="utf-8",
            )
            vector = {
                "class": 5,
                "name": "contradictory-pairing",
                "recordFile": "record.json",
                "saltsFile": "salts.json",
                "saltPairing": "positional",
                "recordType": "org.roax.corpus.synthetic",
                "schemaVersion": "1.0",
                "recordId": "urn:uuid:11111111-1111-4111-8111-111111111111",
                "issuerId": "did:web:corpus.roax.invalid",
            }
            results = run_corpus.Results()

            with mock.patch.object(run_corpus, "REPO", directory):
                run_corpus.run_record(
                    [vector],
                    lambda _record_type: self.fail("type map must not be read after mismatch"),
                    results,
                    references=None,
                    authorize_empty=False,
                )

        self.assertEqual(len(results.failed[5]), 1)
        self.assertIn("salt document declares pairing 'path'", results.failed[5][0])
        self.assertIn("vector requires 'positional'", results.failed[5][0])
        self.assertFalse(results.not_run)

    def test_unknown_record_salt_pairing_is_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "record.json").write_text('{"marker":"m"}', encoding="utf-8")
            (root / "salts.json").write_text(
                json.dumps({"pairing": "path", "salts": []}),
                encoding="utf-8",
            )
            vector = {
                "class": 5,
                "name": "unknown-pairing",
                "recordFile": "record.json",
                "saltsFile": "salts.json",
                "saltPairing": "guess",
                "recordType": "org.roax.corpus.synthetic",
                "schemaVersion": "1.0",
                "recordId": "urn:uuid:11111111-1111-4111-8111-111111111111",
                "issuerId": "did:web:corpus.roax.invalid",
            }
            results = run_corpus.Results()

            with mock.patch.object(run_corpus, "REPO", directory):
                run_corpus.run_record(
                    [vector],
                    lambda _record_type: self.fail("type map must not be read after mismatch"),
                    results,
                    references=None,
                    authorize_empty=False,
                )

        self.assertEqual(
            results.failed[5],
            [
                "unknown-pairing: invalid committed salt set: ValueError: "
                "unknown vector saltPairing 'guess'"
            ],
        )
        self.assertFalse(results.not_run)


class RoundTripComparisonTests(unittest.TestCase):
    """What class 20's comparison may and may not assert.

    A comparator that failed a conforming implementation would be the corpus being wrong in the
    most damaging direction, so the three aspects the specification leaves free are pinned as
    ACCEPTED here, and everything else is pinned as still refused.
    """

    def compare(self, produced, expected):
        return run_corpus._first_difference(
            run_corpus._normalized_for_comparison(run_corpus._comparable(produced)),
            run_corpus._normalized_for_comparison(run_corpus._comparable(expected)),
        )

    def leaf(self, index, key, **extra):
        return {
            "segments": [{"key": key}],
            "index": index,
            "tag": 2,
            "value": key,
            "salt": f"{index:032x}",
            "auditPath": [],
            **extra,
        }

    def disclosed(self, leaves):
        return {"canon": "ROAX-CANON/1", "disclosure": {"mode": "selective", "leaves": leaves}}

    def full(self, salts):
        return {"canon": "ROAX-CANON/1", "record": {"a": 1}, "salts": salts}

    def test_display_path_present_on_one_side_only_is_not_a_difference(self):
        # `schemas/envelope-1.0.json` leaves `displayPath` out of `disclosedLeaf.required`, and
        # section 5.2 makes it display only, so a producer may omit it.
        produced = self.disclosed([self.leaf(0, "a")])
        expected = self.disclosed([self.leaf(0, "a", displayPath="a")])
        self.assertIsNone(self.compare(produced, expected))
        self.assertIsNone(self.compare(expected, produced))

    def test_leaf_and_salt_array_order_is_not_a_difference(self):
        produced = self.disclosed([self.leaf(1, "b"), self.leaf(0, "a")])
        expected = self.disclosed([self.leaf(0, "a"), self.leaf(1, "b")])
        self.assertIsNone(self.compare(produced, expected))
        entries = [
            {"segments": [{"key": "a"}], "salt": "00" * 16},
            {"segments": [{"key": "b"}, {"index": 3}], "salt": "11" * 16},
        ]
        self.assertIsNone(self.compare(self.full(entries[::-1]), self.full(entries)))

    def test_member_order_is_not_a_difference(self):
        produced = {"disclosure": {"leaves": [], "mode": "selective"}, "canon": "ROAX-CANON/1"}
        expected = {"canon": "ROAX-CANON/1", "disclosure": {"mode": "selective", "leaves": []}}
        self.assertIsNone(self.compare(produced, expected))

    def test_everything_the_specification_does_fix_is_still_asserted(self):
        base = self.leaf(0, "a")
        for changed in (
            {**base, "value": None},
            {k: v for k, v in base.items() if k != "value"},
            {**base, "salt": "ff" * 16},
            {**base, "tag": 3},
            {**base, "index": 1},
            {**base, "segments": [{"key": "b"}]},
            {**base, "auditPath": ["ab" * 32]},
        ):
            with self.subTest(changed=sorted(changed)):
                difference = self.compare(self.disclosed([changed]), self.disclosed([base]))
                self.assertIsNotNone(difference)
        # A dropped leaf and a dropped salt are both length differences, and both still fail.
        self.assertIsNotNone(self.compare(self.disclosed([]), self.disclosed([base])))
        self.assertIsNotNone(
            self.compare(self.full([]), self.full([{"segments": [], "salt": "00" * 16}]))
        )

    def test_a_number_keeps_its_source_text(self):
        # `0.010` is not `0.01`: trailing zeros in a decimal are significant, and the full copy
        # carries the record's own literals (specification sections 6.2 and 7.3).
        self.assertIsNotNone(
            self.compare(
                {"record": {"a": run_corpus.JsonNumber("0.01")}},
                {"record": {"a": run_corpus.JsonNumber("0.010")}},
            )
        )


if __name__ == "__main__":
    unittest.main()
