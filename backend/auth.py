"""邮箱验证码登录：6 位码 + HttpOnly 签名 Cookie 会话。

发信走可插拔的 mailer（data/mail.json 或环境变量）：
  mode=worker  POST 到自建的小 Worker，由 Cloudflare send_email 从 jobs@chenminghuan.com 发出
  mode=smtp    常规 SMTP（有邮箱密码时用）
  mode=log     不真发，验证码只写本地日志（仅限本机调试，读过日志的人才能登录）
"""
import base64
import hashlib
import hmac
import html
import json
import os
import random
import secrets
import smtplib
import time
import urllib.request
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MAIL_CONF = DATA / "mail.json"

CODE_TTL = 600          # 验证码 10 分钟
CODE_RESEND = 60        # 60 秒内不许重发
CODE_MAX_PER_HOUR = 8   # 每小时上限
CODE_TRIES = 5          # 单个码最多试 5 次
SESSION_DAYS = 30


def _env(key, default=None):
    return os.environ.get(key) or default


def allowed_emails() -> set:
    raw = _env("JOBHUB_ALLOWED_EMAILS", "me@chenminghuan.com")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def mail_from() -> str:
    return _env("JOBHUB_MAIL_FROM", "jobs@chenminghuan.com")


def mail_config() -> dict:
    """优先环境变量，其次 data/mail.json（chmod 600，不进 git）。"""
    cfg = {"mode": _env("JOBHUB_MAIL_MODE", "")}
    if MAIL_CONF.exists():
        try:
            cfg = {**json.loads(MAIL_CONF.read_text()), **{k: v for k, v in cfg.items() if v}}
        except Exception:
            pass
    overrides = {
        "worker_url": _env("JOBHUB_MAIL_WORKER_URL"),
        "worker_secret": _env("JOBHUB_MAIL_WORKER_SECRET"),
        "smtp_host": _env("JOBHUB_SMTP_HOST"),
        "smtp_port": _env("JOBHUB_SMTP_PORT"),
        "smtp_user": _env("JOBHUB_SMTP_USER"),
        "smtp_pass": _env("JOBHUB_SMTP_PASS"),
    }
    cfg.update({k: v for k, v in overrides.items() if v})
    if not cfg.get("mode"):
        cfg["mode"] = "log"
    return cfg


# ---------------------------------------------------------------- 发信
def _mail_html(code: str, email: str) -> str:
    return f"""<div style="font-family:-apple-system,'PingFang SC',sans-serif;max-width:480px;margin:0 auto;padding:32px 24px;color:#1d2939">
  <div style="font-size:13px;color:#667085;letter-spacing:.5px">JOB HUNTER HUB</div>
  <h2 style="margin:10px 0 18px;font-size:20px">应聘中台登录验证码</h2>
  <div style="font-size:32px;letter-spacing:8px;font-weight:700;color:#4f46e5;background:#eef2ff;border-radius:10px;padding:16px;text-align:center">{code}</div>
  <p style="font-size:13px;color:#475467;line-height:1.9;margin-top:18px">
    10 分钟内有效，仅可使用一次。<br>登录账号：{html.escape(email)}<br>
    不是你本人操作？忽略这封邮件即可，账号不受影响。
  </p>
</div>"""


def send_mail(to: str, subject: str, html_body: str) -> dict:
    cfg = mail_config()
    mode = (cfg.get("mode") or "log").lower()
    sender = mail_from()
    if mode == "worker":
        url, secret = cfg.get("worker_url"), cfg.get("worker_secret")
        if not url or not secret:
            raise RuntimeError("mail.json 缺少 worker_url / worker_secret")
        body = json.dumps({"from": sender, "to": to, "subject": subject,
                           "html": html_body}).encode()
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        req = urllib.request.Request(url, body, {
            "Content-Type": "application/json",
            "X-Signature": sig,
            "User-Agent": "jobhub-mailer/1.0",
        }, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            return {"mode": mode, "status": r.status, "body": r.read()[:200].decode(errors="ignore")}
    if mode == "smtp":
        msg = EmailMessage()
        msg["From"] = formataddr(("应聘中台", sender))
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg.set_content("请使用支持 HTML 的客户端查看验证码。")
        msg.add_alternative(html_body, subtype="html")
        port = int(cfg.get("smtp_port") or 465)
        with smtplib.SMTP_SSL(cfg["smtp_host"], port, timeout=20) if port == 465 else \
                smtplib.SMTP(cfg["smtp_host"], port, timeout=20) as s:
            if port != 465:
                s.starttls()
            s.login(cfg["smtp_user"], cfg["smtp_pass"])
            s.send_message(msg)
        return {"mode": mode, "status": 250}
    return {"mode": "log", "status": 0}


# ---------------------------------------------------------------- 会话
def _secret() -> bytes:
    f = DATA / "session_secret"
    if not f.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        f.write_text(secrets.token_hex(32))
        f.chmod(0o600)
    return f.read_text().strip().encode()


def make_session(email: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({
        "e": email, "exp": int(time.time()) + SESSION_DAYS * 86400,
        "j": secrets.token_hex(4),
    }).encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{sig}"


def read_session(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    payload, _, sig = token.rpartition(".")
    expect = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expect):
        return None
    try:
        pad = "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload + pad))
    except Exception:
        return None
    if data.get("exp", 0) < time.time():
        return None
    return data.get("e")


# ---------------------------------------------------------------- 验证码
def request_code(c, email: str, ip: str = "") -> dict:
    email = (email or "").strip().lower()
    if email not in allowed_emails():
        raise PermissionError("该邮箱不在允许名单内")
    now = time.time()
    last = c.execute("SELECT created_at FROM auth_codes WHERE email=? ORDER BY id DESC LIMIT 1",
                     (email,)).fetchone()
    if last and now - last["created_at"] < CODE_RESEND:
        raise ValueError(f"请 {CODE_RESEND - int(now - last['created_at'])} 秒后再试")
    hour_ago = now - 3600
    if c.execute("SELECT COUNT(*) FROM auth_codes WHERE email=? AND created_at>?",
                 (email, hour_ago)).fetchone()[0] >= CODE_MAX_PER_HOUR:
        raise ValueError("请求过于频繁，请稍后再试")

    code = f"{random.randint(0, 999999):06d}"
    c.execute("INSERT INTO auth_codes(email, code_hash, created_at, expires_at, tries, ip)"
              " VALUES (?,?,?,?,0,?)",
              (email, hashlib.sha256(code.encode()).hexdigest(), now, now + CODE_TTL, ip))
    c.execute("DELETE FROM auth_codes WHERE expires_at < ?", (now - 86400,))

    result = send_mail(email, "应聘中台 · 登录验证码", _mail_html(code, email))
    if result["mode"] == "log":
        # 未配置发信渠道时的兜底：验证码只写服务日志（要登录必须先能读到本机日志）
        print(f"[auth] 未配置发信，验证码 {code} -> {email}（10 分钟内有效）", flush=True)
    return {"sent_to": email, "mode": result["mode"], "ttl": CODE_TTL}


def verify_code(c, email: str, code: str) -> str:
    email = (email or "").strip().lower()
    code = (code or "").strip()
    row = c.execute("SELECT * FROM auth_codes WHERE email=? ORDER BY id DESC LIMIT 1",
                    (email,)).fetchone()
    if not row:
        raise ValueError("请先获取验证码")
    if time.time() > row["expires_at"]:
        raise ValueError("验证码已过期，请重新获取")
    if row["tries"] >= CODE_TRIES:
        raise ValueError("尝试次数过多，请重新获取验证码")
    c.execute("UPDATE auth_codes SET tries=tries+1 WHERE id=?", (row["id"],))
    if not hmac.compare_digest(hashlib.sha256(code.encode()).hexdigest(), row["code_hash"]):
        left = CODE_TRIES - row["tries"] - 1
        raise ValueError(f"验证码不正确，还可尝试 {max(left, 0)} 次")
    c.execute("DELETE FROM auth_codes WHERE email=?", (email,))
    c.execute("INSERT INTO activity(ts,actor,action,entity,detail) VALUES (?,?,?,?,?)",
              (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), email, "auth.login", "user",
               json.dumps({"ip": None})))
    return make_session(email)
