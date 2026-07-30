#!/usr/bin/env bash
# Regression coverage for the corpus gate's complete/failure/incomplete exit contract.
# All wrapper cases use tool stubs and all direct checks are read-only.

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/roax-gate-status.XXXXXX")"
STUB_BIN="$TEST_TMP/bin"
STUB="$HERE/testdata/gate_status_stub.sh"
CORPUS="$REPO_ROOT/corpus/conformance-corpus-1.0.json"
SALT_SET_SOURCE="$REPO_ROOT/corpus/fixtures/salts"
SALT_SET_FILES=("$SALT_SET_SOURCE"/*.json)
SALT_SET_COUNT="${#SALT_SET_FILES[@]}"

trap 'rm -rf "$TEST_TMP"' EXIT

mkdir -p "$STUB_BIN"
ln -s "$STUB" "$STUB_BIN/python3"
ln -s "$STUB" "$STUB_BIN/node"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

run_wrapper_case() {
  label="$1"
  expected="$2"
  build_status="$3"
  check_status="$4"
  schema_status="$5"
  # Required rather than defaulted, because a defaulted status would be indistinguishable from
  # the first `--references` of a case that passes flags, and every step's status is stated.
  profile_rule_status="$6"
  shift 6

  output="$TEST_TMP/$label.out"
  log="$TEST_TMP/$label.log"
  : > "$log"
  env \
    PATH="$STUB_BIN:$PATH" \
    ROAX_REFERENCES= \
    ROAX_NODE_MODULES= \
    ROAX_EXTRACTED_RECORDS=/ambient/records \
    ROAX_GATE_STUB_LOG="$log" \
    ROAX_GATE_STUB_CORPUS="$CORPUS" \
    ROAX_GATE_STUB_BUILD_STATUS="$build_status" \
    ROAX_GATE_STUB_CHECK_STATUS="$check_status" \
    ROAX_GATE_STUB_SCHEMA_STATUS="$schema_status" \
    ROAX_GATE_STUB_PROFILE_RULE_STATUS="$profile_rule_status" \
    bash "$HERE/run.sh" "$@" > "$output" 2>&1
  actual=$?
  [ "$actual" -eq "$expected" ] ||
    fail "$label exited $actual, expected $expected; output: $(tr '\n' ' ' < "$output")"
}

run_direct_case() {
  label="$1"
  expected="$2"
  shift 2

  output="$TEST_TMP/$label.out"
  "$@" > "$output" 2>&1
  actual=$?
  [ "$actual" -eq "$expected" ] ||
    fail "$label exited $actual, expected $expected; output: $(tr '\n' ' ' < "$output")"
}

# The four dependency combinations.
run_wrapper_case neither 2 2 2 0 0
grep -F "class 10: NOT RUN" "$TEST_TMP/neither.out" >/dev/null ||
  fail "missing --references did not report class 10 NOT RUN"
grep -F -- "--references <path-to-schemata>" "$TEST_TMP/neither.out" >/dev/null ||
  fail "missing references did not name the --references flag"
grep -F -- "--modules <node_modules-with-ajv@8-and-ajv-formats>" \
  "$TEST_TMP/neither.out" >/dev/null ||
  fail "missing modules did not name the --modules flag"
if grep -F -- "--records" "$TEST_TMP/neither.log" >/dev/null; then
  fail "run.sh passed --records when --references was absent"
fi
grep -F "ROAX_EXTRACTED_RECORDS=<>" "$TEST_TMP/neither.log" >/dev/null ||
  fail "run.sh allowed an ambient extracted-records directory to bypass missing --references"

run_wrapper_case references_only 2 0 0 0 0 --references /stub/references
grep -F -- "--records" "$TEST_TMP/references_only.log" >/dev/null ||
  fail "run.sh did not pass extracted --records when --references was configured"

run_wrapper_case modules_only 2 2 2 0 0 --modules /stub/node_modules
if grep -F -- "--records" "$TEST_TMP/modules_only.log" >/dev/null; then
  fail "run.sh passed --records when only --modules was configured"
fi

run_wrapper_case both 0 0 0 0 0 \
  --references /stub/references --modules /stub/node_modules
grep -F "ALL CHECKS PASSED" "$TEST_TMP/both.out" >/dev/null ||
  fail "fully configured wrapper did not report a complete pass"

run_wrapper_case invalid_modules 2 0 0 2 0 \
  --references /stub/references --modules /stub/node_modules
grep -F "schema dependencies were unavailable" "$TEST_TMP/invalid_modules.out" >/dev/null ||
  fail "unavailable configured schema dependencies did not report NOT RUN"
grep -F -- "--modules <node_modules-with-ajv@8-and-ajv-formats>" \
  "$TEST_TMP/invalid_modules.out" >/dev/null ||
  fail "unavailable configured schema dependencies did not name the --modules remedy"

run_wrapper_case schema_failure 1 0 0 1 0 \
  --references /stub/references --modules /stub/node_modules
grep -F "CHECKS FAILED" "$TEST_TMP/schema_failure.out" >/dev/null ||
  fail "a schema verdict failure did not make the wrapper fail"

# The declared profile value rules are a gate step, so a refusal there fails the gate. Both
# implementations run, so the case is covered from each side independently.
run_wrapper_case profile_rule_failure 1 0 0 0 1 \
  --references /stub/references --modules /stub/node_modules
grep -F "CHECKS FAILED" "$TEST_TMP/profile_rule_failure.out" >/dev/null ||
  fail "a declared profile value rule failure did not make the wrapper fail"
grep -F "declared profile value rules" "$TEST_TMP/profile_rule_failure.out" >/dev/null ||
  fail "the profile value rule step did not name itself in the report"

# A real failure wins over an independently missing step.
run_wrapper_case failure_precedence 1 1 0 0 0 --references /stub/references
grep -F "NOT A PASS" "$TEST_TMP/failure_precedence.out" >/dev/null ||
  fail "byte equality obscured a preceding implementation failure"
grep -F "CHECKS FAILED" "$TEST_TMP/failure_precedence.out" >/dev/null ||
  fail "a real failure did not win over an independently missing step"

# --references accepts both the documented checkout root and this repository's parent layout.
PARENT_LAYOUT="$TEST_TMP/parent-layout"
CHECKOUT_LAYOUT="$TEST_TMP/checkout-layout"
mkdir -p "$PARENT_LAYOUT/schemata/src" "$CHECKOUT_LAYOUT/src"
FIND_SRC_ROOT='import sys
sys.path.insert(0, sys.argv[1])
import moh_records
actual = moh_records.find_src_root(sys.argv[2])
raise SystemExit(0 if actual == sys.argv[3] else f"got {actual!r}")'
run_direct_case references_parent_layout 0 \
  python3 -c "$FIND_SRC_ROOT" "$HERE" "$PARENT_LAYOUT" "$PARENT_LAYOUT/schemata/src"
run_direct_case references_checkout_layout 0 \
  python3 -c "$FIND_SRC_ROOT" "$HERE" "$CHECKOUT_LAYOUT" "$CHECKOUT_LAYOUT/src"

# The independent tools share the same incomplete status when external records are unavailable.
run_direct_case direct_build 2 env ROAX_REFERENCES= \
  python3 "$HERE/build_corpus.py" --check --report
grep -F "class 10: NOT RUN" "$TEST_TMP/direct_build.out" >/dev/null ||
  fail "build_corpus.py did not report class 10 NOT RUN"
grep -F -- "--references <path-to-schemata>" "$TEST_TMP/direct_build.out" >/dev/null ||
  fail "build_corpus.py did not name the --references flag"

run_direct_case direct_node 2 env ROAX_EXTRACTED_RECORDS= \
  node "$HERE/check_corpus.mjs"
grep -F "class 10: NOT RUN" "$TEST_TMP/direct_node.out" >/dev/null ||
  fail "check_corpus.mjs did not report class 10 NOT RUN"
grep -F -- "--references <path-to-schemata>" "$TEST_TMP/direct_node.out" >/dev/null ||
  fail "check_corpus.mjs did not name the --references flag"
grep -F "validated $SALT_SET_COUNT committed salt-set carriers" \
  "$TEST_TMP/direct_node.out" >/dev/null ||
  fail "check_corpus.mjs did not report every committed salt-set carrier"

run_direct_case direct_node_quiet 2 env ROAX_EXTRACTED_RECORDS= \
  node "$HERE/check_corpus.mjs" --quiet
grep -F "class 10: NOT RUN" "$TEST_TMP/direct_node_quiet.out" >/dev/null ||
  fail "check_corpus.mjs --quiet hid class 10 NOT RUN"
grep -F -- "--references <path-to-schemata>" "$TEST_TMP/direct_node_quiet.out" >/dev/null ||
  fail "check_corpus.mjs --quiet hid the --references remedy"

# Every standalone salt-set input is shape-checked before vector execution.
# Mutations use complete scratch copies so each case still exercises the directory-wide scan.
UNKNOWN_SALT_SETS="$TEST_TMP/salts-unknown-member"
UPPERCASE_SALT_SETS="$TEST_TMP/salts-uppercase"
mkdir -p "$UNKNOWN_SALT_SETS" "$UPPERCASE_SALT_SETS"
cp "${SALT_SET_FILES[@]}" "$UNKNOWN_SALT_SETS/" ||
  fail "could not prepare the unknown-member salt-set regression"
cp "${SALT_SET_FILES[@]}" "$UPPERCASE_SALT_SETS/" ||
  fail "could not prepare the uppercase-salt regression"

MUTATE_SALT_SET='import json, pathlib, sys
directory = pathlib.Path(sys.argv[1])
target = sorted(directory.glob("*.json"))[0]
with target.open(encoding="utf-8") as source:
    document = json.load(source)
if sys.argv[2] == "unknown":
    document["unexpected"] = True
else:
    first = document["salts"][0]
    salt = first["salt"] if isinstance(first, dict) else first
    changed = "A" + salt[1:]
    if isinstance(first, dict):
        first["salt"] = changed
    else:
        document["salts"][0] = changed
with target.open("w", encoding="utf-8") as output:
    json.dump(document, output, indent=2)
    output.write("\n")'
python3 -c "$MUTATE_SALT_SET" "$UNKNOWN_SALT_SETS" unknown ||
  fail "could not mutate a salt-set carrier with an unknown member"
python3 -c "$MUTATE_SALT_SET" "$UPPERCASE_SALT_SETS" uppercase ||
  fail "could not mutate a salt-set carrier with an uppercase salt"

run_direct_case salt_unknown_member 1 env ROAX_EXTRACTED_RECORDS= \
  node "$HERE/check_corpus.mjs" --quiet --salt-sets "$UNKNOWN_SALT_SETS"
grep -F "unknown member(s)" "$TEST_TMP/salt_unknown_member.out" >/dev/null ||
  fail "an unknown salt-set member was not rejected"

run_direct_case salt_uppercase 1 env ROAX_EXTRACTED_RECORDS= \
  node "$HERE/check_corpus.mjs" --quiet --salt-sets "$UPPERCASE_SALT_SETS"
grep -F "lowercase 32-hex" "$TEST_TMP/salt_uppercase.out" >/dev/null ||
  fail "an uppercase salt was not rejected"

# Missing external modules are incomplete. A broken extractor or missing committed type map is
# an actual gate failure.
MISSING_MODULES="$TEST_TMP/missing-modules"
mkdir -p "$MISSING_MODULES/schemata/src"
run_direct_case missing_module 2 \
  python3 "$HERE/build_corpus.py" --check --references "$MISSING_MODULES"
grep -F "not found under --references" "$TEST_TMP/missing_module.out" >/dev/null ||
  fail "a missing reference module did not report NOT RUN with the --references remedy"

BROKEN_REFERENCES="$TEST_TMP/broken-references"
BROKEN_MODULE="$BROKEN_REFERENCES/schemata/src/sg/gov/moh/vaccination-healthcert/1.0/sample-data.ts"
mkdir -p "$(dirname "$BROKEN_MODULE")"
printf "%s\n" "export const unrelated = {};" > "$BROKEN_MODULE"
run_direct_case extractor_failure 1 \
  python3 "$HERE/build_corpus.py" --check --references "$BROKEN_REFERENCES"
grep -F "class 10 FAILED" "$TEST_TMP/extractor_failure.out" >/dev/null ||
  fail "an extractor error was not classified as a gate failure"

EMPTY_MAPS="$TEST_TMP/empty-type-maps"
mkdir -p "$EMPTY_MAPS"
MISSING_TYPE_MAP='import sys
sys.path.insert(0, sys.argv[1])
import moh_records
moh_records.TYPE_MAP_DIR = sys.argv[2]
moh_records.build_record_vectors(sys.argv[3])'
run_direct_case missing_type_map 1 \
  python3 -c "$MISSING_TYPE_MAP" "$HERE" "$EMPTY_MAPS" "$MISSING_MODULES"
grep -F "committed corpus type map is missing" "$TEST_TMP/missing_type_map.out" >/dev/null ||
  fail "a missing committed type map was not classified as a gate failure"

# The Node runner treats disagreements among committed internal artifacts as failures, not as
# unavailable external inputs.
BAD_PAIRING_CORPUS="$TEST_TMP/bad-pairing-corpus.json"
BAD_MAP_CORPUS="$TEST_TMP/bad-map-corpus.json"
ENVELOPE_CARRIER_CORPUS="$TEST_TMP/envelope-carrier-corpus.json"
MUTATE_CORPUS='import json, sys
with open(sys.argv[1], encoding="utf-8") as source:
    corpus = json.load(source)
if sys.argv[3] == "pairing":
    vector = next(v for v in corpus["vectors"]["record"] if v.get("recordFile", "").startswith("corpus/"))
    vector["saltPairing"] = "positional" if vector["saltPairing"] != "positional" else "path"
elif sys.argv[3] == "map":
    corpus["vectors"]["typeMap"][0]["recordType"] = "org.roax.missing"
else:
    vector = next(v for v in corpus["vectors"]["record"] if v.get("recordFile", "").startswith("corpus/"))
    del vector["recordFile"]
    del vector["saltsFile"]
    del vector["saltPairing"]
    vector["envelopeFile"] = "corpus/fixtures/envelopes/full-copy-complete-salts.json"
with open(sys.argv[2], "w", encoding="utf-8") as target:
    json.dump(corpus, target)'
python3 -c "$MUTATE_CORPUS" "$CORPUS" "$BAD_PAIRING_CORPUS" pairing ||
  fail "could not prepare the saltPairing regression corpus"
python3 -c "$MUTATE_CORPUS" "$CORPUS" "$BAD_MAP_CORPUS" map ||
  fail "could not prepare the missing-type-map regression corpus"
python3 -c "$MUTATE_CORPUS" "$CORPUS" "$ENVELOPE_CARRIER_CORPUS" carrier ||
  fail "could not prepare the envelope-carrier regression corpus"

run_direct_case node_bad_pairing 1 \
  node "$HERE/check_corpus.mjs" --quiet --corpus "$BAD_PAIRING_CORPUS"
grep -F "declares saltPairing" "$TEST_TMP/node_bad_pairing.out" >/dev/null ||
  fail "a committed saltPairing disagreement was not classified as a Node failure"

run_direct_case node_missing_type_map 1 \
  node "$HERE/check_corpus.mjs" --quiet --corpus "$BAD_MAP_CORPUS"
grep -F "committed type map org.roax.missing not found" \
  "$TEST_TMP/node_missing_type_map.out" >/dev/null ||
  fail "a missing committed type map was not classified as a Node failure"

run_direct_case node_unsupported_carrier 1 \
  node "$HERE/check_corpus.mjs" --quiet --corpus "$ENVELOPE_CARRIER_CORPUS"
grep -F "unsupported envelopeFile carrier" \
  "$TEST_TMP/node_unsupported_carrier.out" >/dev/null ||
  fail "an unsupported schema-valid record carrier was not classified as a Node failure"

echo "ok: corpus gate status regression matrix"
