#!/bin/sh
set -e

case "${1:-test}" in
    test)
        exec python -m unittest discover -s tests
        ;;
    ui)
        exec streamlit run clipforge/ui.py \
            --server.port 8501 --server.address 0.0.0.0 --server.headless true
        ;;
    run)
        shift
        exec python -m clipforge "$@"
        ;;
    *)
        exec "$@"
        ;;
esac
