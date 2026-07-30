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
            self.assertIn("10       0       0        2  NOT RUN", result.stdout)
            self.assertIn(f"attempted {first_attempt} and {fallback_attempt}", result.stdout)
            self.assertIn(
                "rerun with --references /path/to/schemata",
                result.stdout,
            )
            self.assertIn(
                "RESULT: INCOMPLETE / NOT RUN "
                "(736 assertions passed; 2 not run; 18/19 classes passed)",
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
            module = Path(directory) / REFERENCE_MODULE
            module.parent.mkdir(parents=True)
            module.write_text(
                "export const sampleDocument = makeDocument();\n",
                encoding="utf-8",
            )

            result = self.run_runner("--references", directory)

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(
                f"could not extract 'sampleDocument' from reference module {module}",
                result.stdout,
            )
            self.assertIn("ValueError: unsupported literal", result.stdout)
            self.assertNotIn(
                "rerun with --references /path/to/schemata",
                result.stdout,
            )
            self.assertIn(
                "RESULT: FAIL " "(736 passed; 2 failed; 0 not run; 18/19 classes passed)",
                result.stdout,
            )
            self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_unsupported_reject_shape_is_a_failure(self) -> None:
        results = run_corpus.Results()

        run_corpus.run_reject(
            [
                {
                    "class": 3,
                    "name": "unsupported-shape",
                    "input": {"notAnEscape": True},
                    "reason": "invalid-json",
                }
            ],
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

    def test_envelope_two_record_vector_is_not_run_rather_than_a_failure(self) -> None:
        """A vector this package CANNOT run must not render as one that ran and failed.

        `typeMapId` selects `RESERVED_V2`, which `build_tree` rejects because specification
        section 4.2 requires selecting the exact map by a reproduced content ID from a
        published DFA artifact and this package implements neither. That is a
        could-not-check, which this module's docstring makes a third status contributing to
        exit 2, so reporting it through `bad` would collapse the three-way contract.

        No committed corpus 1.0 record vector carries `typeMapId`, so this is unreachable
        today and becomes reachable on the corpus rebuild `AGENTS.md` records as pending.
        """
        results = run_corpus.Results()

        run_corpus.run_record(
            [
                {
                    "class": 10,
                    "name": "envelope-two-selector",
                    "recordType": "org.roax.corpus.synthetic",
                    "schemaVersion": "1.0",
                    "recordId": "urn:uuid:11111111-1111-4111-8111-111111111111",
                    "issuerId": "did:web:example.invalid",
                    "typeMapId": "sha256:" + "0" * 64,
                }
            ],
            lambda _record_type: None,
            results,
            references=None,
            authorize_empty=False,
        )

        self.assertFalse(results.failed, "a vector that cannot run must never report FAIL")
        self.assertEqual(len(results.not_run[10]), 1)
        self.assertIn("envelope-two-selector", results.not_run[10][0])
        self.assertIn("typeMapId", results.not_run[10][0])

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


if __name__ == "__main__":
    unittest.main()
