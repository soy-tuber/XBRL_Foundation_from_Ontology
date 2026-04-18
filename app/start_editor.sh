#!/bin/bash
cd "$(dirname "$0")/.."
source .venv/bin/activate
exec uvicorn app.editor_server:app --host 0.0.0.0 --port 8503
