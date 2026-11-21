#!/usr/bin/env bash
# 把中台本身注册成 launchd 常驻服务（开机自启、崩溃自动拉起），监听 127.0.0.1:8010
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.chenminghuan.jobhub"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$ROOT/data/logs"

[ -d "$ROOT/backend/.venv" ] || ( cd "$ROOT/backend" && uv venv .venv && . .venv/bin/activate && uv pip install -q -r requirements.txt )
[ -d "$ROOT/frontend/dist" ] || ( cd "$ROOT/frontend" && npm install && npm run build )

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$ROOT/backend/.venv/bin/python</string>
    <string>-m</string><string>uvicorn</string>
    <string>main:app</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>8010</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT/backend</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$ROOT/data/logs/app.log</string>
  <key>StandardErrorPath</key><string>$ROOT/data/logs/app.err.log</string>
</dict>
</plist>
PLIST_EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
sleep 2
curl -sf http://127.0.0.1:8010/healthz >/dev/null && echo "✅ 中台已常驻：http://127.0.0.1:8010  (log: data/logs/app.log)" \
  || { echo "❌ 启动失败，看 data/logs/app.err.log"; exit 1; }
echo "   页面口令：$(cat "$ROOT/data/admin_password.txt" 2>/dev/null || echo '见启动日志')"
