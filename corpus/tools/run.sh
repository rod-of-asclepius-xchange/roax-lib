#!/usr/bin/env bash
# Check the ROAX conformance corpus end to end, and print what was actually measured.
#
# Four steps, in the order that makes a failure legible:
#
#   1. implementation A rebuilds the corpus and compares it with the committed file;
#   2. implementation B recomputes every derived value and rewrites the corpus;
#   3. the two files are compared byte for byte;
#   4. every artifact is validated against the repository's JSON Schemas.
#
# Step 3 is the one that matters. Step 1 alone only proves one program is self-consistent.
#
# Usage:
#   corpus/tools/run.sh [--references DIR] [--modules NODE_MODULES]
#
# --references  a read-only checkout of the Open-Attestation schemata package. Without it,
#               class 10 reports SKIPPED. It never reports green unrun.
# --modules     a node_modules holding ajv@8 and ajv-formats. Without it, step 4 is skipped and
#               says so. The repository has no package manifest by design.

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

echo "=== 1. implementation A (Python) rebuilds and compares"
python3 "$HERE/build_corpus.py" --check --report --extract-to "$WORK/records" "${ref_args[@]}" || status=1

echo
echo "=== 2. implementation B (Node) recomputes every derived value"
node "$HERE/check_corpus.mjs" --records "$WORK/records" --emit "$WORK/corpus-b.json" || status=1

echo
echo "=== 3. byte comparison"
if cmp -s "$CORPUS_DIR/conformance-corpus-1.0.json" "$WORK/corpus-b.json"; then
  echo "  ok: the two implementations produce a byte-identical corpus"
  # Said plainly, because a byte comparison is easy to over-read: implementation B COPIES
  # THROUGH any vector it reported SKIPPED above rather than recomputing it, so those vectors
  # match trivially. Whatever step 2 skipped, step 3 does not cover.
  echo "  note: any vector reported SKIPPED in step 2 was copied through, not recomputed"
else
  echo "  FAIL: the two implementations disagree"
  diff "$CORPUS_DIR/conformance-corpus-1.0.json" "$WORK/corpus-b.json" | head -40
  status=1
fi

echo
echo "=== 4. JSON Schema validation (Ajv 8, strict, plus ajv-formats)"
if [ -n "$MODULES" ]; then
  node "$HERE/validate_schemas.mjs" --modules "$MODULES" || status=1
else
  echo "  SKIPPED: pass --modules <node_modules with ajv@8 ajv-formats> to run this step"
fi

echo
if [ "$status" -eq 0 ]; then echo "ALL CHECKS PASSED"; else echo "CHECKS FAILED"; fi
exit "$status"
