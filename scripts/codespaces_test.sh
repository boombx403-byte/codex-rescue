#!/usr/bin/env bash
set -euo pipefail

echo "======================================================"
echo "  Codex Rescue - Cloud Validation & Test Runner       "
echo "======================================================"

export PYTHONPATH="src:${PYTHONPATH:-}"

echo ""
echo "[1/4] Running CLI smoke check..."
codex-rescue --version
codex-rescue --help > /dev/null
echo "  -> CLI smoke check passed."

echo ""
echo "[2/4] Running core test suite (unittest)..."
python -m unittest discover -s tests -v

echo ""
echo "[3/4] Running E2E test suites (Tier 1 & Tier 2)..."
python -m unittest discover -s tests/e2e -v

echo ""
echo "[4/4] Running fixture harness validation..."
python -m codex_rescue.harness fixtures --output .validation-output/codespaces

echo ""
echo "======================================================"
echo "  ALL TESTS & VALIDATIONS PASSED IN CODESPACES!       "
echo "======================================================"
