#!/bin/bash
# OOM-PHASE3: CI check — fail if runtime code bypasses singleton pattern.
# Catches rogue SentinelRetriever() or SentinelStoreBack() direct instantiation.
# Excludes: tests/, scripts/, briefs/, and the singleton definition itself.

set -e

ERRORS=0

# Check SentinelRetriever() — exclude _get_global_instance definition and tests
ROGUE_RETRIEVER=$(grep -rn 'SentinelRetriever()' --include='*.py' \
  --exclude-dir=tests --exclude-dir=scripts --exclude-dir=briefs --exclude-dir=.claude \
  . 2>/dev/null | grep -v '_get_global_instance\|_allow_direct\|_instance = cls()' || true)

if [ -n "$ROGUE_RETRIEVER" ]; then
  echo "ERROR: Direct SentinelRetriever() instantiation found (use _get_global_instance()):"
  echo "$ROGUE_RETRIEVER"
  ERRORS=$((ERRORS + 1))
fi

# Check SentinelStoreBack() — exclude _get_global_instance definition and tests
ROGUE_STOREBACK=$(grep -rn 'SentinelStoreBack()' --include='*.py' \
  --exclude-dir=tests --exclude-dir=scripts --exclude-dir=briefs --exclude-dir=.claude \
  . 2>/dev/null | grep -v '_get_global_instance\|_allow_direct\|_instance = cls()' || true)

if [ -n "$ROGUE_STOREBACK" ]; then
  echo "ERROR: Direct SentinelStoreBack() instantiation found (use _get_global_instance()):"
  echo "$ROGUE_STOREBACK"
  ERRORS=$((ERRORS + 1))
fi

if [ $ERRORS -gt 0 ]; then
  echo ""
  echo "FAILED: $ERRORS singleton violation(s) found."
  echo "Fix: Replace ClassName() with ClassName._get_global_instance()"
  exit 1
fi

echo "OK: No singleton violations found."
