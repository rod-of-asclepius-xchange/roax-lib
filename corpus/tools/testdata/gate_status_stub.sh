#!/usr/bin/env bash
# Test-only stand-in for python3 and node.
# test_gate_status.sh symlinks both names to this file and selects the behavior through
# environment variables, so run.sh's orchestration can be tested without touching artifacts.

set -u

tool="$(basename "$0")"
{
  printf "%s" "$tool"
  for arg in "$@"; do
    printf " <%s>" "$arg"
  done
  printf " ROAX_EXTRACTED_RECORDS=<%s>" "${ROAX_EXTRACTED_RECORDS:-}"
  printf "\n"
} >> "$ROAX_GATE_STUB_LOG"

case "$tool" in
  python3)
    # run.sh calls python3 twice: build_corpus.py at step 1 and profile_rules.py at step 5.
    # They have independent exit statuses, so the stub selects on which one it was handed.
    case "${1:-}" in
      *profile_rules.py)
        exit "${ROAX_GATE_STUB_PROFILE_RULE_STATUS:-0}"
        ;;
      *)
        exit "${ROAX_GATE_STUB_BUILD_STATUS:-0}"
        ;;
    esac
    ;;
  node)
    case "${1:-}" in
      *check_corpus.mjs)
        emit=""
        previous=""
        for arg in "$@"; do
          if [ "$previous" = "--emit" ]; then
            emit="$arg"
            break
          fi
          previous="$arg"
        done
        if [ -z "$emit" ]; then
          echo "test stub: check_corpus.mjs received no --emit" >&2
          exit 1
        fi
        cp "$ROAX_GATE_STUB_CORPUS" "$emit"
        exit "${ROAX_GATE_STUB_CHECK_STATUS:-0}"
        ;;
      *validate_schemas.mjs)
        exit "${ROAX_GATE_STUB_SCHEMA_STATUS:-0}"
        ;;
      *profile_rules.mjs)
        exit "${ROAX_GATE_STUB_PROFILE_RULE_STATUS:-0}"
        ;;
      *)
        echo "test stub: unexpected node command ${1:-<none>}" >&2
        exit 1
        ;;
    esac
    ;;
  *)
    echo "test stub: unexpected executable name $tool" >&2
    exit 1
    ;;
esac
