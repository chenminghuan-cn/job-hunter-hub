#!/usr/bin/env bash
# 把中台本身注册成 launchd 常驻服务（开机自启、崩溃自动拉起），监听 127.0.0.1:8010
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="${JOBHUB_LABEL:-com.jobhub.app}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$ROOT/data/logs"

[ -d "$ROOT/backend/.venv" ] || ( cd "$ROOT/backend" && uv venv .venv && . .venv/bin/activate && uv pip install -q -r requirements.txt )
[ -d "$ROOT/frontend/dist" ] || ( cd "$ROOT/frontend" && npm install && npm run build )

# 可选：把当前 shell 里这几个变量固化进 launchd（本机私有配置不进仓库）
EXTRA_ENV=""
for v in JOBHUB_ALLOWED_EMAILS JOBHUB_MAIL_FROM JOBHUB_OWNER_NAME JOBHUB_MAIL_MODE \
         JOBHUB_MAIL_WORKER_URL JOBHUB_MAIL_WORKER_SECRET JOBHUB_CHROME JOBHUB_SEED_DEMO; do
  val="$(printenv "$v" 2>/dev/null || true)"
  [ -n "$val" ] && EXTRA_ENV="$EXTRA_ENV    <key>$v</key><string>$val</string>"$'\n'
done

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
$EXTRA_ENV
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
echo "   登录：邮箱验证码（JOBHUB_ALLOWED_EMAILS=${JOBHUB_ALLOWED_EMAILS:-admin@example.com} 需配好发信通道）"
