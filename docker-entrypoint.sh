#!/bin/sh
set -e

case "${1:-test}" in
    test)
        exec sh scripts/test.sh
        ;;
    ui)
        exec streamlit run clipforge/ui.py \
            --server.port 8501 --server.address 0.0.0.0 --server.headless true
        ;;
    api)
        exec uvicorn clipforge.api:app --host 0.0.0.0 --port "${PORT:-8080}"
        ;;
    run)
        shift
        exec python -m clipforge "$@"
        ;;
    *)
        exec "$@"
        ;;
esac
