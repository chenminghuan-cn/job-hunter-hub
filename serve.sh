#!/usr/bin/env bash
# 单端口模式：构建前端后由 FastAPI 一起托管，只开 :8010
set -e
cd "$(dirname "$0")"
( cd frontend && [ -d node_modules ] || npm install; npm run build )
cd backend
[ -d .venv ] || ( uv venv .venv && . .venv/bin/activate && uv pip install -q -r requirements.txt )
. .venv/bin/activate
exec python -m uvicorn main:app --host 0.0.0.0 --port "${PORT:-8010}"
