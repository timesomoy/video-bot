#!/bin/sh
# offline tests (no internet needed)
cd "$(dirname "$0")/.." || exit 1
python3 tests/test_captions.py && python3 tests/test_gemini.py && python3 tests/test_mail.py && python3 tests/test_parse.py && (cd worker && node --test worker.test.mjs 2>&1 | grep -E "^# (pass|fail)")
