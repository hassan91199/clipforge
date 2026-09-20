#!/bin/sh
# Browser tier (Playwright) - the real app in a real browser, stubbed
# pipeline, zero API cost. Skipped by the default gate; run explicitly here.
# One-time setup if missing:
#   .venv/bin/pip install playwright && .venv/bin/playwright install chromium
set -e
cd "$(dirname "$0")/.."

if [ -x ".venv/bin/python" ]; then
    PYTHON=.venv/bin/python
else
    PYTHON=python
fi

if ! "$PYTHON" -c "import playwright" 2>/dev/null; then
    echo "Playwright is not installed. One-time setup:"
    echo "  $PYTHON -m pip install playwright"
    echo "  $PYTHON -m playwright install chromium"
    exit 1
fi

RUN_BROWSER_TESTS=1 "$PYTHON" -m unittest discover -s tests -p "test_browser.py" -v
