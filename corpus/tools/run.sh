#!/usr/bin/env bash
# Check the ROAX conformance corpus end to end, and print what was actually measured.
#
# Five steps, in the order that makes a failure legible:
#
#   1. implementation A rebuilds the corpus and compares it with the committed file;
#   2. implementation B recomputes the derived fields of every runnable committed vector;
#   3. its emitted file is compared byte for byte, excluding copied-through NOT RUN vectors
#      from the cross-implementation claim;
#   4. every artifact is validated against the repository's JSON Schemas;
#   5. both implementations' declared profile value rules are self-tested.
#
# Step 3 is the cross-implementation comparison.
# Step 1 alone only proves one program is self-consistent.
#
# Step 5 is separate from the corpus on purpose. Ruled decision D13a keeps value-domain
# validation out of the canonicalization layer, so those rules are the profile layer's and a
# corpus vector would demand them from implementations that by that ruling do not carry them.
# The corpus pins the accept case through class 10; step 5 pins the refusals.
#
# Usage:
#   corpus/tools/run.sh [--references DIR] [--modules NODE_MODULES]
#
# --references  a read-only checkout of the Open-Attestation schemata package. Without it,
#               class 10 reports NOT RUN and the gate exits 2. It never reports green unrun.
# --modules     a node_modules holding ajv@8 and ajv-formats. Without it, step 4 reports NOT RUN
#               and the gate exits 2. Ajv lives outside this tree by design: the root package.json
#               is the TypeScript library's, not a place for schema tooling.
#
# Exit status:
#   0  every configured check completed and passed;
#   1  at least one check ran and failed;
#   2  no check failed, but at least one check or vector was NOT RUN.

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORPUS_DIR="$(dirname "$HERE")"
WORK="${TMPDIR:-/tmp}/roax-corpus-run.$$"
REFERENCES="${ROAX_REFERENCES:-}"
MODULES="${ROAX_NODE_MODULES:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --references) REFERENCES="$2"; shift 2 ;;
    --modules) MODULES="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$WORK"
trap 'rm -rf "$WORK"' EXIT

status=0
ref_args=()
[ -n "$REFERENCES" ] && ref_args=(--references "$REFERENCES")
record_args=()
[ -n "$REFERENCES" ] && record_args=(--records "$WORK/records")

record_status() {
  case "$1" in
    0) ;;
    2)
      # A real failure takes precedence over an incomplete check.
      if [ "$status" -eq 0 ]; then
        status=2
      fi
      ;;
    *)
      status=1
      ;;
  esac
}

echo "=== 1. implementation A (Python) rebuilds and compares"
if [ -z "$REFERENCES" ]; then
  echo "  class 10: NOT RUN - rerun with --references <path-to-schemata>"
fi
# `${a[@]+"${a[@]}"}` rather than `"${ref_args[@]}"`: under `set -u`, bash before 4.4 - which
# includes the 3.2 that ships with macOS - treats an EMPTY array's expansion as an unbound
# variable and aborts. That fires on exactly the documented path of running without
# --references, which the arguments are optional for.
python3 "$HERE/build_corpus.py" --check --report --extract-to "$WORK/records" ${ref_args[@]+"${ref_args[@]}"}
step1_status=$?
record_status "$step1_status"

echo
echo "=== 2. implementation B (Node) recomputes every runnable vector"
# This wrapper owns the extraction path. Clear a direct-runner environment override so a stale
# directory cannot make class 10 run after this invocation reported missing --references.
ROAX_EXTRACTED_RECORDS='' node "$HERE/check_corpus.mjs" \
  ${record_args[@]+"${record_args[@]}"} --emit "$WORK/corpus-b.json"
step2_status=$?
record_status "$step2_status"

echo
echo "=== 3. byte comparison"
if cmp -s "$CORPUS_DIR/conformance-corpus-1.0.json" "$WORK/corpus-b.json"; then
  if [ "$step1_status" -eq 0 ] && [ "$step2_status" -eq 0 ]; then
    echo "  ok: implementation B emits a byte-identical corpus for the generated vectors"
  elif { [ "$step1_status" -ne 0 ] && [ "$step1_status" -ne 2 ]; } ||
       { [ "$step2_status" -ne 0 ] && [ "$step2_status" -ne 2 ]; }; then
    echo "  NOT A PASS: emitted bytes match, but a preceding implementation step failed"
    echo "  note: byte equality cannot override that failure"
  else
    echo "  INCOMPLETE: the emitted file is byte-identical, but NOT RUN vectors were copied through"
    echo "  NOT CHECKED: copied-through fields are not a cross-implementation assertion"
  fi
  # A byte comparison can say nothing about rows that were never generated into the committed
  # corpus, including the two class-10 records blocked by unresolved type-map paths.
  echo "  scope: rows not generated into the committed corpus are not cross-checked here"
else
  echo "  FAIL: the two implementations disagree"
  diff "$CORPUS_DIR/conformance-corpus-1.0.json" "$WORK/corpus-b.json" | head -40
  record_status 1
fi

echo
echo "=== 4. JSON Schema validation (Ajv 8, strict, plus ajv-formats)"
if [ -n "$MODULES" ]; then
  node "$HERE/validate_schemas.mjs" --modules "$MODULES"
  step4_status=$?
  if [ "$step4_status" -eq 2 ]; then
    echo "  NOT RUN: schema dependencies were unavailable; rerun with a valid" \
      "--modules <node_modules-with-ajv@8-and-ajv-formats>"
  fi
  record_status "$step4_status"
else
  echo "  NOT RUN: rerun with --modules <node_modules-with-ajv@8-and-ajv-formats>"
  record_status 2
fi

echo
echo "=== 5. declared profile value rules (both implementations)"
python3 "$HERE/profile_rules.py"
record_status $?
node "$HERE/profile_rules.mjs"
record_status $?

echo
case "$status" in
  0) echo "ALL CHECKS PASSED" ;;
  1) echo "CHECKS FAILED" ;;
  2) echo "CHECKS INCOMPLETE: one or more checks were NOT RUN" ;;
esac
exit "$status"
