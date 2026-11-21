#!/usr/bin/env bash
# 开发模式：后端 :8010（热重载） + 前端 :5199
set -e
cd "$(dirname "$0")"
if [ ! -d backend/.venv ]; then
  ( cd backend && uv venv .venv && . .venv/bin/activate && uv pip install -q -r requirements.txt )
fi
( cd backend && . .venv/bin/activate && python -m uvicorn main:app --reload --port 8010 ) &
( cd frontend && [ -d node_modules ] || npm install; npm run dev ) &
trap 'kill 0' INT TERM
wait
