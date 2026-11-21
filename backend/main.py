import base64
import json
import secrets
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import a2a
import auth
import onboarding
import service
from db import DB_PATH, SCOPES, db, init, log, now
from state import TransitionError, meta

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "frontend" / "dist"

app = FastAPI(title="Job Hunter Hub", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # ponytail: 本地中台直接放开，真要公网部署请在反代上收口
    allow_methods=["*"],
    allow_headers=["*"],
)

init()


# ---------------------------------------------------------------- 登录态
# 页面与 /api/* 需要邮箱验证码登录后的会话 Cookie；
# /a2a 与 agent-card 由 HMAC 签名保护，对 Agent 公开。
SESSION_COOKIE = "jh_session"
PUBLIC_PREFIXES = ("/a2a", "/.well-known/", "/api/auth/", "/healthz")
PROTECTED_PREFIXES = ("/api/", "/files/")


def current_user(request: Request) -> str | None:
    return auth.read_session(request.cookies.get(SESSION_COOKIE))


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path
    if path == "/a2a" or path.startswith(PUBLIC_PREFIXES) or not path.startswith(PROTECTED_PREFIXES):
        return await call_next(request)
    if not current_user(request):
        return JSONResponse({"detail": "未登录或登录已过期"}, status_code=401)
    return await call_next(request)


@app.post("/api/auth/request-code")
async def auth_request_code(request: Request):
    data = await request.json()
    ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "")
    with db() as c:
        try:
            return auth.request_code(c, data.get("email"), ip)
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except ValueError as e:
            raise HTTPException(429, str(e))
        except Exception as e:
            raise HTTPException(500, f"验证码发送失败：{e}")


@app.post("/api/auth/verify")
async def auth_verify(request: Request):
    data = await request.json()
    with db() as c:
        try:
            token = auth.verify_code(c, data.get("email"), data.get("code"))
        except ValueError as e:
            raise HTTPException(400, str(e))
    resp = JSONResponse({"ok": True, "email": (data.get("email") or "").strip().lower()})
    resp.set_cookie(SESSION_COOKIE, token, max_age=auth.SESSION_DAYS * 86400,
                    httponly=True, samesite="lax",
                    secure=request.url.scheme == "https", path="/")
    return resp


@app.get("/api/auth/me")
def auth_me(request: Request):
    email = current_user(request)
    if not email:
        raise HTTPException(401, "未登录")
    return {"email": email}


@app.post("/api/auth/logout")
def auth_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.middleware("http")
async def cache_headers(request: Request, call_next):
    """静态资源：带 hash 的 /assets/* 长缓存；index.html 与页面必须每次回源，否则改版后浏览器还看旧包。"""
    resp = await call_next(request)
    path = request.url.path
    if path.startswith("/assets/"):
        resp.headers["cache-control"] = "public, max-age=31536000, immutable"
    elif path.startswith("/logos/"):
        resp.headers["cache-control"] = "public, max-age=86400"
    elif not path.startswith(("/api/", "/a2a", "/files/", "/.well-known/")):
        resp.headers["cache-control"] = "no-cache, must-revalidate"
    return resp


# 下架判定是服务端的事：半小时最多扫一次，页面打开时顺手跑
SWEEP_STAMP = ROOT / "data" / ".last_sweep"


def maybe_sweep():
    try:
        if time.time() - SWEEP_STAMP.stat().st_mtime < 1800:
            return
    except FileNotFoundError:
        pass
    try:
        with db() as c:
            service.sweep_presence(c)
        SWEEP_STAMP.write_text(str(int(time.time())))
    except Exception:
        pass


def body_json(data):
    """库里 JSON 字段以字符串存，出参统一解析成对象，前端少写一次 JSON.parse。"""
    if isinstance(data, dict):
        for k in ("extra", "raw", "tags", "config"):
            if isinstance(data.get(k), str) and data[k][:1] in "[{":
                try:
                    data[k] = json.loads(data[k])
                except Exception:
                    pass
    return data


def page_args(request: Request):
    q = request.query_params
    return dict(
        q=q.get("q") or None,
        channel=q.get("channel") or None,
        state=q.get("state") or None,
        city=q.get("city") or None,
        company_id=q.get("company_id") or None,
        page=int(q.get("page") or 1),
        page_size=min(int(q.get("page_size") or 20), 200),
        sort=q.get("sort") or "created_at",
        tag=q.get("tag") or None,
        presence=q.get("presence") or None,
        fit=q.get("fit") or None,
        priority=q.get("priority") or None,
        order=q.get("order") or "desc",
    )


# ---------------------------------------------------------------- meta
@app.get("/api/meta")
def api_meta():
    with db() as c:
        channels = [body_json(x) for x in service.list_channels(c)]
    return {
        "machines": meta(),
        "channels": channels,
        "contact_types": [
            {"value": "hr", "label": "HR"},
            {"value": "headhunter", "label": "猎头"},
            {"value": "referral", "label": "内推"},
            {"value": "interviewer", "label": "面试官"},
            {"value": "other", "label": "其他"},
        ],
        "publisher_types": [
            {"value": "hr", "label": "HR"},
            {"value": "headhunter", "label": "猎头"},
            {"value": "employee", "label": "员工/内推"},
            {"value": "official", "label": "官方号"},
            {"value": "unknown", "label": "未知"},
        ],
        "scopes": SCOPES,
        "tools": [
            {"name": k, "scope": v["scope"], "description": v["description"], "params": v["params"]}
            for k, v in sorted(a2a.TOOLS.items())
        ],
        "db_path": str(DB_PATH),
    }


# ---------------------------------------------------------------- dashboard
@app.get("/api/dashboard")
def api_dashboard():
    maybe_sweep()
    with db() as c:
        return body_json(service.dashboard(c))


@app.get("/api/resume-source")
def api_resume_source():
    with db() as c:
        row = c.execute("SELECT config FROM agents WHERE id='analyst'").fetchone()
        cfg = json.loads(row["config"] or "{}") if row else {}
        return service.get_resume_source(c, (cfg.get("profile") or {}).get("resume_path"))


@app.post("/api/resume-source")
async def api_resume_source_upload(request: Request):
    data = await request.json()
    with db() as c:
        try:
            src = service.save_resume_source(c, data, "ui")
            return {"ok": True, "name": src.get("name"), "bytes": len(src.get("html") or "")}
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.get("/api/resumes")
def api_resumes(job_id: int | None = None):
    with db() as c:
        return service.list_resumes(c, job_id)


@app.get("/api/resumes/{rid}")
def api_resume(rid: int):
    with db() as c:
        r = service.get_resume(c, rid)
        if not r:
            raise HTTPException(404, "简历不存在")
        return r


@app.post("/api/resumes")
async def api_resume_create(request: Request):
    data = await request.json()
    with db() as c:
        try:
            return service.create_resume(c, data, "ui")
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.delete("/api/resumes/{rid}")
def api_resume_delete(rid: int):
    with db() as c:
        try:
            return service.delete_resume(c, rid, "ui")
        except KeyError as e:
            raise HTTPException(404, str(e))


@app.get("/api/reports")
def api_reports(status: str | None = None, agent_id: str | None = None, limit: int = 100):
    with db() as c:
        return service.list_reports(c, status, agent_id, min(limit, 500))


@app.patch("/api/reports/{rid}")
async def api_report_update(rid: int, request: Request):
    data = await request.json()
    with db() as c:
        try:
            return service.update_report(c, rid, data, "ui")
        except KeyError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.delete("/api/reports/{rid}")
def api_report_delete(rid: int):
    with db() as c:
        try:
            return service.delete_report(c, rid, "ui")
        except KeyError as e:
            raise HTTPException(404, str(e))


@app.get("/api/activity")
def api_activity(limit: int = 50, entity: str | None = None, entity_id: int | None = None):
    with db() as c:
        return service.activity(c, min(limit, 500), entity, entity_id)


# ---------------------------------------------------------------- jobs
@app.get("/api/jobs")
def api_jobs(request: Request):
    a = page_args(request)
    maybe_sweep()
    with db() as c:
        r = service.list_jobs(c, a["q"], a["channel"], a["state"], a["city"],
                              a["company_id"], a["page"], a["page_size"], a["sort"],
                              a["tag"], a["presence"], a["fit"], a["priority"], a["order"])
    return {"items": [body_json(i) for i in r["items"]], "total": r["total"]}


@app.get("/api/facets")
def api_facets():
    with db() as c:
        return service.job_facets(c)


@app.get("/api/jobs/{jid}")
def api_job(jid: int):
    with db() as c:
        j = service.get_job(c, jid)
        if not j:
            raise HTTPException(404, "岗位不存在")
        j["activities"] = service.activity(c, 20, "job")[:10]
        return body_json(j)


@app.post("/api/jobs")
async def api_job_create(request: Request):
    data = await request.json()
    with db() as c:
        try:
            return body_json(service.upsert_job(c, data, "ui")["job"])
        except (ValueError, TransitionError) as e:
            raise HTTPException(400, str(e))


@app.patch("/api/jobs/{jid}")
async def api_job_update(jid: int, request: Request):
    data = await request.json()
    with db() as c:
        try:
            note = data.pop("note", None)
            if data.get("state"):
                service.set_job_state(c, jid, data.pop("state"), "ui", note)
            j = service.update_job(c, jid, data, "ui") if data else service.get_job(c, jid)
            return body_json(j)
        except TransitionError as e:
            raise HTTPException(400, str(e))
        except KeyError as e:
            raise HTTPException(404, str(e))


@app.post("/api/jobs/{jid}/attachments")
async def api_job_attachment(jid: int, request: Request):
    data = await request.json()
    raw = data.get("data_base64") or ""
    try:
        blob = base64.b64decode(raw.split(",")[-1]) if raw else None
    except Exception:
        raise HTTPException(400, "data_base64 不是合法 base64")
    with db() as c:
        try:
            return service.save_attachment(c, jid, blob, data.get("filename") or "",
                                           data.get("mime"), data.get("url"), data.get("caption"), "ui")
        except ValueError as e:
            raise HTTPException(400, str(e))
        except KeyError as e:
            raise HTTPException(404, str(e))


@app.delete("/api/attachments/{aid}")
def api_attachment_delete(aid: int):
    with db() as c:
        try:
            return service.delete_attachment(c, aid, "ui")
        except KeyError as e:
            raise HTTPException(404, str(e))


@app.get("/files/{rel:path}")
def files(rel: str):
    root = service.UPLOAD_DIR.resolve()
    f = (root / rel).resolve()
    if not str(f).startswith(str(root)) or not f.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(f)


@app.delete("/api/jobs/{jid}")
def api_job_delete(jid: int):
    with db() as c:
        service.delete_job(c, jid, "ui")
    return {"ok": True}


# ---------------------------------------------------------------- companies
@app.get("/api/companies")
def api_companies(request: Request, state: str | None = None):
    q = request.query_params
    with db() as c:
        r = service.list_companies(c, q.get("q") or None, state,
                                   int(q.get("page") or 1), min(int(q.get("page_size") or 20), 200))
    return {"items": [body_json(i) for i in r["items"]], "total": r["total"]}


@app.post("/api/companies")
async def api_company_create(request: Request):
    data = await request.json()
    with db() as c:
        try:
            return body_json(service.upsert_company(c, data, "ui")["company"])
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.patch("/api/companies/{cid}")
async def api_company_update(cid: int, request: Request):
    data = await request.json()
    with db() as c:
        try:
            note = data.pop("note", None)
            if data.get("state"):
                service.set_company_state(c, cid, data.pop("state"), "ui", note)
            if not data:
                return body_json(dict(c.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()))
            data.pop("name", None)
            return body_json(service.upsert_company(
                c, {"name": c.execute("SELECT name FROM companies WHERE id=?", (cid,)).fetchone()["name"], **data}, "ui")["company"])
        except TransitionError as e:
            raise HTTPException(400, str(e))


# ---------------------------------------------------------------- contacts
@app.get("/api/contacts")
def api_contacts(request: Request, type: str | None = None, state: str | None = None,
                 company_id: int | None = None):
    q = request.query_params
    with db() as c:
        r = service.list_contacts(c, q.get("q") or None, type, state, company_id,
                                  int(q.get("page") or 1), min(int(q.get("page_size") or 20), 200))
    return {"items": [body_json(i) for i in r["items"]], "total": r["total"]}


@app.get("/api/contacts/{cid}")
def api_contact(cid: int):
    with db() as c:
        d = service.get_contact(c, cid)
        if not d:
            raise HTTPException(404, "联系人不存在")
        return body_json(d)


@app.post("/api/contacts")
async def api_contact_create(request: Request):
    data = await request.json()
    with db() as c:
        try:
            return body_json(service.upsert_contact(c, data, "ui")["contact"])
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.patch("/api/contacts/{cid}")
async def api_contact_update(cid: int, request: Request):
    data = await request.json()
    with db() as c:
        try:
            note = data.pop("note", None)
            if data.get("state"):
                service.set_contact_state(c, cid, data.pop("state"), "ui", note)
            if data:
                data["id"] = cid
                return body_json(service.upsert_contact(c, data, "ui")["contact"])
            return body_json(service.get_contact(c, cid))
        except TransitionError as e:
            raise HTTPException(400, str(e))


# ---------------------------------------------------------------- channels
@app.get("/api/channels")
def api_channels():
    with db() as c:
        return [body_json(x) for x in service.list_channels(c)]


@app.post("/api/channels")
async def api_channel_create(request: Request):
    data = await request.json()
    with db() as c:
        try:
            return body_json(service.create_channel(c, data, "ui"))
        except Exception as e:
            raise HTTPException(400, str(e))


@app.patch("/api/channels/{code}")
async def api_channel_update(code: str, request: Request):
    data = await request.json()
    with db() as c:
        try:
            return body_json(service.update_channel(c, code, data, "ui"))
        except TransitionError as e:
            raise HTTPException(400, str(e))
        except KeyError as e:
            raise HTTPException(404, str(e))


# ---------------------------------------------------------------- agents
@app.get("/api/agents")
def api_agents():
    with db() as c:
        return service.agents(c)


@app.post("/api/agents")
async def api_agent_create(request: Request):
    data = await request.json()
    aid = (data.get("id") or "").strip()
    if not aid:
        raise HTTPException(400, "id 必填")
    cfg = data.get("config") or {}
    if isinstance(cfg, str):
        try:
            json.loads(cfg)
        except Exception:
            raise HTTPException(400, "config 不是合法 JSON")
    else:
        cfg = json.dumps(cfg, ensure_ascii=False)
    with db() as c:
        if c.execute("SELECT 1 FROM agents WHERE id=?", (aid,)).fetchone():
            raise HTTPException(400, "agent id 已存在")
        c.execute(
            "INSERT INTO agents(id,name,kind,secret,scopes,active,remark,prompt,config,created_at)"
            " VALUES (?,?,?,?,?,1,?,?,?,?)",
            (aid, data.get("name") or aid, data.get("kind"), secrets.token_urlsafe(24),
             ",".join(data.get("scopes") or []), data.get("remark"),
             data.get("prompt"), cfg, now()))
        log(c, "ui", "agent.create", "agent", None, {"id": aid})
        return service.get_agent(c, aid)


@app.patch("/api/agents/{aid}")
async def api_agent_update(aid: str, request: Request):
    data = await request.json()
    with db() as c:
        try:
            return service.update_agent(c, aid, data, "ui")
        except KeyError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.get("/api/agents/{aid}/onboarding")
def api_onboarding(aid: str, request: Request, with_secret: int = 1):
    with db() as c:
        row = c.execute("SELECT * FROM agents WHERE id=?", (aid,)).fetchone()
        if not row:
            raise HTTPException(404, "agent 不存在")
        agent = dict(row)
        if not with_secret:
            agent["secret"] = "<已隐藏>"
        text = onboarding.onboarding_text(agent, str(request.base_url))
    # 含密钥版本把真实 secret 填进去（onboarding_text 里占位）
    if with_secret:
        text = text.replace("<见页面「显示密钥」>", agent["secret"])
    return {"agent_id": aid, "text": text}


@app.post("/api/agents/{aid}/selftest")
def api_agent_selftest(aid: str):
    """用该 agent 自己的密钥真实签一次 requests，验证链路（也方便用户点一下就确认能通）。"""
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    body = json.dumps(payload).encode()
    with db() as c:
        row = c.execute("SELECT * FROM agents WHERE id=?", (aid,)).fetchone()
        if not row:
            raise HTTPException(404, "agent 不存在")
        headers = a2a.sign(aid, row["secret"], body)
        try:
            agent = a2a.verify(c, headers, body)
            res = a2a.handle(c, agent, payload)
            return {"ok": True, "headers": headers, "response": res}
        except a2a.A2AError as e:
            return {"ok": False, "error": e.message}


@app.post("/api/agents/{aid}/rotate")
def api_agent_rotate(aid: str):
    with db() as c:
        if not c.execute("SELECT 1 FROM agents WHERE id=?", (aid,)).fetchone():
            raise HTTPException(404, "agent 不存在")
        secret = secrets.token_urlsafe(24)
        c.execute("UPDATE agents SET secret=? WHERE id=?", (secret, aid))
        log(c, "ui", "agent.rotate", "agent", None, {"id": aid})
        return {"id": aid, "secret": secret}


@app.delete("/api/agents/{aid}")
def api_agent_delete(aid: str):
    with db() as c:
        c.execute("DELETE FROM agents WHERE id=?", (aid,))
        log(c, "ui", "agent.delete", "agent", None, {"id": aid})
    return {"ok": True}


@app.post("/api/maintenance/purge-attachments")
def api_purge_attachments():
    with db() as c:
        return service.purge_rejected_attachments(c)


@app.post("/api/maintenance/sweep")
def api_sweep():
    with db() as c:
        return service.sweep_presence(c)


@app.post("/api/maintenance/clear-demo")
def api_clear_demo():
    with db() as c:
        return {"deleted": service.clear_demo(c)}


@app.get("/api/maintenance/export")
def api_export():
    with db() as c:
        return {
            "exported_at": now(),
            "channels": [dict(r) for r in c.execute("SELECT * FROM channels")],
            "companies": [dict(r) for r in c.execute("SELECT * FROM companies")],
            "contacts": [dict(r) for r in c.execute("SELECT * FROM contacts")],
            "jobs": [dict(r) for r in c.execute("SELECT * FROM jobs")],
        }


# ---------------------------------------------------------------- A2A
@app.get("/.well-known/agent-card.json")
def api_agent_card(request: Request):
    return a2a.agent_card(str(request.base_url).rstrip("/"))


@app.get("/api/a2a/info")
def api_a2a_info(request: Request):
    base = str(request.base_url).rstrip("/")
    return {
        "endpoint": f"{base}/a2a",
        "agent_card": f"{base}/.well-known/agent-card.json",
        "ui": f"{base}/",
        "signature": {
            "headers": ["X-Agent-Id", "X-Timestamp", "X-Nonce", "X-Signature"],
            "canonical": "agent_id\ntimestamp\nnonce\nsha256_hex(raw_body)",
            "algorithm": "HMAC-SHA256 hex",
            "tolerance_seconds": a2a.TOLERANCE,
            "replay_protection": "nonce 5 分钟内不可复用",
        },
    }


@app.post("/a2a")
async def api_a2a(request: Request):
    raw = await request.body()
    rid = None
    try:
        try:
            payload = json.loads(raw or b"{}")
        except Exception:
            raise a2a.A2AError(-32700, "body 不是合法 JSON")
        rid = payload.get("id")
        with db() as c:
            agent = a2a.verify(c, request.headers, raw)
            return a2a.handle(c, agent, payload, str(request.base_url))
    except a2a.A2AError as e:
        status = 401 if e.code == -32001 else 200
        return JSONResponse(
            {"jsonrpc": "2.0", "id": rid, "error": {"code": e.code, "message": e.message, "data": e.data}},
            status_code=status)


# ---------------------------------------------------------------- 前端静态文件
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{full_path:path}")
def spa(full_path: str):
    if full_path.startswith("api/") or full_path == "a2a":
        raise HTTPException(404, "not found")
    if full_path:
        f = (DIST / full_path).resolve()
        if str(f).startswith(str(DIST)) and f.is_file():
            return FileResponse(f)
    idx = DIST / "index.html"
    if idx.exists():
        return FileResponse(idx)
    return JSONResponse({"message": "前端未构建：cd frontend && npm i && npm run build，或开发模式跑 npm run dev"}, 404)
