#!/usr/bin/env bash
# 把本机 8010 暴露成 Cloudflare 二级域名（需要先 cloudflared tunnel login 授权过域名）
# 用法: ./deploy/tunnel.sh [子域名] [主域名] [隧道名]   默认 jobs chenminghuan.com jobhub
set -e
SUB="${1:-jobs}"
DOMAIN="${2:-chenminghuan.com}"
NAME="${3:-jobhub}"
HOSTNAME_FULL="$SUB.$DOMAIN"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

[ -f "$HOME/.cloudflared/cert.pem" ] || { echo "❌ 先执行 cloudflared tunnel login 并在浏览器授权 $DOMAIN"; exit 1; }

if ! cloudflared tunnel list --output json 2>/dev/null | grep -q "\"name\":\"$NAME\""; then
  cloudflared tunnel create "$NAME"
fi
TID=$(cloudflared tunnel list --output json | python3 -c "import json,sys;print([t['id'] for t in json.load(sys.stdin) if t['name']=='$NAME'][0])")
echo "隧道 $NAME = $TID"

cloudflared tunnel route dns "$NAME" "$HOSTNAME_FULL" 2>/dev/null || echo "（DNS 记录已存在，跳过）"

cat > "$HOME/.cloudflared/config.yml" <<CFG
tunnel: $TID
credentials-file: $HOME/.cloudflared/$TID.json
ingress:
  - hostname: $HOSTNAME_FULL
    service: http://127.0.0.1:8010
  - service: http_status:404
CFG

LABEL="com.chenminghuan.jobhub-tunnel"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$ROOT/data/logs"
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/cloudflared</string>
    <string>--no-autoupdate</string>
    <string>--config</string><string>$HOME/.cloudflared/config.yml</string>
    <string>tunnel</string><string>run</string><string>$NAME</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$ROOT/data/logs/tunnel.log</string>
  <key>StandardErrorPath</key><string>$ROOT/data/logs/tunnel.err.log</string>
</dict>
</plist>
PLIST_EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
sleep 6
code=$(curl -s -o /dev/null -w '%{http_code}' "https://$HOSTNAME_FULL/healthz")
echo "https://$HOSTNAME_FULL/healthz -> $code"
[ "$code" = "200" ] && echo "✅ 已上线：https://$HOSTNAME_FULL" || echo "⚠️ 还没通，看 data/logs/tunnel.err.log"
