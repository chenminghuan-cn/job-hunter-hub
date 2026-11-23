"""业务层：页面接口和 A2A 工具共用同一套读写逻辑，避免两套行为。"""
import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path

from db import log, norm_name, now
from state import check

JOB_FIELDS = {
    "title", "company_name", "company_id", "salary_raw", "salary_min", "salary_max",
    "salary_months", "city", "district", "employment_type", "experience_req",
    "education_req", "description", "requirements", "url", "publisher_name",
    "publisher_type", "contact_id", "posted_at", "collected_at", "deadline",
    "priority", "match_score", "notes", "channel_code", "source_job_id", "tags",
}
COMPANY_FIELDS = {"name", "industry", "scale", "stage", "city", "website", "source", "tags", "notes"}
CONTACT_FIELDS = {
    "name", "type", "company_id", "company_name", "title", "wechat", "phone", "email",
    "profile_url", "channel_code", "last_contact_at", "tags", "notes",
}
JOB_SORT = {"created_at", "updated_at", "priority", "match_score", "collected_at",
            "posted_at", "first_seen_at", "last_seen_at", "open_days", "fit_at"}

# 只有这些字段变了才算「岗位内容更新」；raw / extra 每抓一次都可能不同，不参与判定
JOB_MEANINGFUL = ("title", "company_name", "salary_raw", "salary_min", "salary_max",
                  "city", "district", "description", "requirements", "url",
                  "publisher_name", "employment_type", "experience_req", "education_req")

STALE_DAYS = int(os.environ.get("JOBHUB_STALE_DAYS", 7))    # 多少天没再看到 → 疑似下架
GONE_DAYS = int(os.environ.get("JOBHUB_GONE_DAYS", 21))     # 多少天没再看到 → 判定下架
OPEN_DAYS_EXPR = ("CAST(julianday(COALESCE(closed_at, datetime('now','localtime'))) "
                  "- julianday(COALESCE(first_seen_at, created_at)) AS INTEGER)")
OPEN_DAYS_SQL = f"{OPEN_DAYS_EXPR} AS open_days"
ATT_COUNT_SQL = "(SELECT COUNT(*) FROM job_attachments WHERE job_attachments.job_id=jobs.id) AS att_count"

SALARY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-~—至]\s*(\d+(?:\.\d+)?)\s*([KkWw千万])")

# ---------------------------------------------------------------- 附件（JD 截图/海报）
UPLOAD_DIR = Path(os.environ.get(
    "JOBHUB_UPLOAD_DIR", Path(__file__).resolve().parent.parent / "data" / "uploads"))
MAX_ATTACH = 8 * 1024 * 1024          # 单张 8MB 上限
KEEP_IMAGES = int(os.environ.get("JOBHUB_KEEP_IMAGES", 1))   # 每个岗位只留最新 N 张截图
NO_ATTACH_STATES = {"rejected", "archived"}                  # 明确不要的岗位：拒收附件
MIME_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
            "image/gif": ".gif", "application/pdf": ".pdf"}


def sniff_mime(data: bytes):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"%PDF":
        return "application/pdf"
    return None


def _safe_name(name: str) -> str:
    name = re.sub(r"[^\w.\-\u4e00-\u9fa5]+", "_", (name or "attachment"))[:80]
    return name or "attachment"


def save_attachment(c, job_id: int, data: bytes | None = None, filename: str = "",
                    mime: str | None = None, url: str | None = None,
                    caption: str | None = None, actor="agent"):
    """把 Agent 传的图片/PDF 落盘到 data/uploads，同一岗位同内容只存一份。"""
    job = c.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        raise KeyError("岗位不存在")
    if job["state"] in NO_ATTACH_STATES:
        raise ValueError(f"该岗位状态是「{job['state']}」，已明确不要，拒收附件（先改状态再传）")
    if data is None:
        if not url:
            raise ValueError("需要 data_base64 或 url")
        if not re.match(r"^https?://", url):
            raise ValueError("url 必须是 http(s)")
        req = urllib.request.Request(url, headers={"User-Agent": "jobhub-agent/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read(MAX_ATTACH + 1)
        filename = filename or url.split("?")[0].rsplit("/", 1)[-1]
    if len(data) > MAX_ATTACH:
        raise ValueError(f"文件超过 {MAX_ATTACH // 1024 // 1024}MB 上限")
    real = sniff_mime(data)
    if not real:
        raise ValueError("只支持 png/jpg/webp/gif/pdf")
    mime = real
    sha = hashlib.sha256(data).hexdigest()
    dup = c.execute("SELECT * FROM job_attachments WHERE job_id=? AND sha256=?",
                    (job_id, sha)).fetchone()
    if dup:
        return {"created": False, "attachment": dict(dup)}

    ext = MIME_EXT[mime]
    rel = f"jobs/{job_id}/{sha[:12]}{ext}"
    path = UPLOAD_DIR / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    name = _safe_name(filename or f"attachment{ext}")
    if not name.lower().endswith(ext):
        name = Path(name).stem + ext
    cur = c.execute(
        "INSERT INTO job_attachments(job_id,filename,mime,size,sha256,rel_path,caption,created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (job_id, name, mime, len(data), sha, rel, caption, now()))
    log(c, actor, "job.attachment", "job", job_id, {"name": name, "size": len(data)})
    dropped = prune_images(c, job_id) if mime.startswith("image/") else 0
    return {"created": True, "pruned": dropped, "attachment": dict(c.execute(
        "SELECT * FROM job_attachments WHERE id=?", (cur.lastrowid,)).fetchone())}


def prune_images(c, job_id: int, keep: int | None = None) -> int:
    """只保留最新 N 张截图，旧的连文件一起删。"""
    keep = KEEP_IMAGES if keep is None else keep
    rows = c.execute(
        "SELECT * FROM job_attachments WHERE job_id=? AND mime LIKE 'image/%' ORDER BY id DESC",
        (job_id,)).fetchall()
    n = 0
    for r in rows[keep:]:
        c.execute("DELETE FROM job_attachments WHERE id=?", (r["id"],))
        try:
            (UPLOAD_DIR / r["rel_path"]).unlink(missing_ok=True)
        except Exception:
            pass
        n += 1
    return n


def purge_rejected_attachments(c, actor="ui"):
    """把已放弃/已归档岗位的附件连文件一起清掉，回收磁盘。"""
    rows = c.execute(
        "SELECT a.* FROM job_attachments a JOIN jobs j ON j.id=a.job_id"
        " WHERE j.state IN ('rejected','archived')").fetchall()
    for r in rows:
        c.execute("DELETE FROM job_attachments WHERE id=?", (r["id"],))
        try:
            (UPLOAD_DIR / r["rel_path"]).unlink(missing_ok=True)
        except Exception:
            pass
    freed = sum(r["size"] for r in rows)
    if rows:
        log(c, actor, "attachment.purge", detail={"count": len(rows), "bytes": freed})
    return {"count": len(rows), "bytes": freed}


def list_attachments(c, job_id: int):
    rows = c.execute("SELECT * FROM job_attachments WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_attachment(c, aid: int, actor="ui"):
    row = c.execute("SELECT * FROM job_attachments WHERE id=?", (aid,)).fetchone()
    if not row:
        raise KeyError("附件不存在")
    c.execute("DELETE FROM job_attachments WHERE id=?", (aid,))
    try:
        (UPLOAD_DIR / row["rel_path"]).unlink(missing_ok=True)
    except Exception:
        pass
    log(c, actor, "job.attachment.delete", "job", row["job_id"], {"id": aid})
    return {"ok": True}


def parse_salary(raw):
    """'30-55K·15薪' -> (30000, 55000, 15)。解析不出来就返回 (None, None, None)。"""
    if not raw:
        return None, None, None
    s = str(raw).replace(",", "")
    months = None
    m = re.search(r"[·*x×]?\s*(1[0-9])\s*薪", s)
    if m:
        months = int(m.group(1))
    g = SALARY_RE.search(s)
    if not g:
        return None, None, months
    lo, hi, unit = float(g.group(1)), float(g.group(2)), g.group(3).lower()
    mul = {"k": 1000, "w": 10000, "万": 10000, "千": 1000}[unit]
    return int(lo * mul), int(hi * mul), months


def j(obj):
    return json.loads(obj) if obj else None


def parse_json_fields(d: dict, keys=("tags", "extra", "raw", "config", "run_stats", "fit_report")) -> dict:
    """SQLite 里 JSON 字段是字符串，出口统一转成对象（页面和 A2A 都拿到一致的类型）。"""
    if not d:
        return d
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v[:1] in "[{":
            try:
                d[k] = json.loads(v)
            except Exception:
                pass
    return d


def fingerprint(channel: str, source_job_id, title: str, company: str, city=None) -> str:
    if source_job_id:
        return f"{channel}:{source_job_id}"
    base = "|".join([channel, (title or "").strip().lower(), norm_name(company), (city or "").lower()])
    return f"{channel}:h:{hashlib.sha1(base.encode()).hexdigest()[:16]}"


# ---------------------------------------------------------------- companies
def ensure_company(c, name: str, actor="ui", extra: dict | None = None):
    if not name:
        return None
    n = norm_name(name)
    row = c.execute("SELECT * FROM companies WHERE name_norm=?", (n,)).fetchone()
    if row:
        return dict(row)
    ts = now()
    cur = c.execute(
        "INSERT INTO companies(name,name_norm,industry,scale,stage,city,website,source,state,"
        "tags,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?, 'new', ?,?,?,?)",
        (name.strip(), n, (extra or {}).get("industry"), (extra or {}).get("scale"),
         (extra or {}).get("stage"), (extra or {}).get("city"), (extra or {}).get("website"),
         (extra or {}).get("source"), json.dumps((extra or {}).get("tags") or [], ensure_ascii=False),
         (extra or {}).get("notes"), ts, ts),
    )
    log(c, actor, "company.create", "company", cur.lastrowid, {"name": name})
    return dict(c.execute("SELECT * FROM companies WHERE id=?", (cur.lastrowid,)).fetchone())


def list_companies(c, q=None, state=None, page=1, page_size=20):
    where, args = [], []
    if q:
        where.append("(name LIKE ? OR industry LIKE ? OR city LIKE ?)")
        args += [f"%{q}%"] * 3
    _in(where, args, "state", state)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = c.execute(f"SELECT COUNT(*) FROM companies {w}", args).fetchone()[0]
    rows = c.execute(
        f"SELECT *, (SELECT COUNT(*) FROM jobs WHERE jobs.company_id=companies.id) AS job_count,"
        f" (SELECT COUNT(*) FROM contacts WHERE contacts.company_id=companies.id) AS contact_count"
        f" FROM companies {w} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        args + [page_size, (page - 1) * page_size],
    ).fetchall()
    return {"items": [parse_json_fields(dict(r)) for r in rows], "total": total}


def upsert_company(c, data: dict, actor="ui"):
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("name 必填")
    row = c.execute("SELECT * FROM companies WHERE name_norm=?", (norm_name(name),)).fetchone()
    if not row:
        comp = ensure_company(c, name, actor, data)
        return {"created": True, "company": comp}
    sets, args = [], []
    for k, v in data.items():
        if k in COMPANY_FIELDS and k != "name":
            sets.append(f"{k}=?")
            args.append(json.dumps(v, ensure_ascii=False) if k == "tags" and not isinstance(v, str) else v)
    if sets:
        sets.append("updated_at=?")
        args += [now(), row["id"]]
        c.execute(f"UPDATE companies SET {', '.join(sets)} WHERE id=?", args)
        log(c, actor, "company.update", "company", row["id"], sorted(data))
    return {"created": False, "company": dict(c.execute("SELECT * FROM companies WHERE id=?", (row["id"],)).fetchone())}


def set_company_state(c, cid: int, target: str, actor="ui", note: str | None = None):
    row = c.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
    if not row:
        raise KeyError("公司不存在")
    check("company", row["state"], target)
    c.execute("UPDATE companies SET state=?, updated_at=? WHERE id=?", (target, now(), cid))
    log(c, actor, "company.state", "company", cid,
        {"from": row["state"], "to": target, "note": note})
    return dict(c.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone())


# ---------------------------------------------------------------- contacts
def list_contacts(c, q=None, type_=None, state=None, company_id=None, page=1, page_size=20):
    where, args = [], []
    if q:
        where.append("(name LIKE ? OR company_name LIKE ? OR title LIKE ? OR wechat LIKE ? OR email LIKE ?)")
        args += [f"%{q}%"] * 5
    _in(where, args, "type", type_)
    _in(where, args, "state", state)
    if company_id:
        where.append("company_id=?")
        args.append(company_id)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = c.execute(f"SELECT COUNT(*) FROM contacts {w}", args).fetchone()[0]
    rows = c.execute(
        f"SELECT * FROM contacts {w} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        args + [page_size, (page - 1) * page_size],
    ).fetchall()
    return {"items": [parse_json_fields(dict(r)) for r in rows], "total": total}


def get_contact(c, cid):
    row = c.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    return dict(row) if row else None


def upsert_contact(c, data: dict, actor="ui"):
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("name 必填")
    company_id = data.get("company_id")
    if not company_id and data.get("company_name"):
        comp = ensure_company(c, data["company_name"], actor)
        company_id = comp["id"] if comp else None
    cid = data.pop("id", None)
    if not cid:
        row = c.execute(
            "SELECT id FROM contacts WHERE name=? AND COALESCE(company_id,-1)=? AND type=?",
            (name, company_id if company_id is not None else -1, data.get("type") or "hr"),
        ).fetchone()
        cid = row["id"] if row else None
    if cid:
        sets, args = [], []
        for k, v in data.items():
            if k in CONTACT_FIELDS:
                sets.append(f"{k}=?")
                args.append(json.dumps(v, ensure_ascii=False) if k == "tags" and not isinstance(v, str) else v)
        if company_id:
            sets.append("company_id=?")
            args.append(company_id)
        if sets:
            sets.append("updated_at=?")
            args += [now(), cid]
            c.execute(f"UPDATE contacts SET {', '.join(sets)} WHERE id=?", args)
            log(c, actor, "contact.update", "contact", cid, sorted(data))
        return {"created": False, "contact": get_contact(c, cid)}
    ts = now()
    cur = c.execute(
        "INSERT INTO contacts(name,type,company_id,company_name,title,wechat,phone,email,profile_url,"
        "channel_code,state,last_contact_at,tags,notes,created_at,updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?, 'new', ?,?,?,?,?)",
        (name, data.get("type") or "hr", company_id, data.get("company_name"), data.get("title"),
         data.get("wechat"), data.get("phone"), data.get("email"), data.get("profile_url"),
         data.get("channel_code"), data.get("last_contact_at"),
         json.dumps(data.get("tags") or [], ensure_ascii=False), data.get("notes"), ts, ts),
    )
    log(c, actor, "contact.create", "contact", cur.lastrowid, {"name": name})
    return {"created": True, "contact": get_contact(c, cur.lastrowid)}


def set_contact_state(c, cid: int, target: str, actor="ui", note: str | None = None):
    row = c.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    if not row:
        raise KeyError("联系人不存在")
    check("contact", row["state"], target)
    touch = now() if target in ("contacted", "replied", "following") else row["last_contact_at"]
    c.execute("UPDATE contacts SET state=?, last_contact_at=?, updated_at=? WHERE id=?",
              (target, touch, now(), cid))
    log(c, actor, "contact.state", "contact", cid,
        {"from": row["state"], "to": target, "note": note})
    return get_contact(c, cid)


# ---------------------------------------------------------------- jobs
def _csv(v):
    if v is None:
        return []
    return [x for x in (v if isinstance(v, (list, tuple)) else str(v).split(",")) if x]


def _in(where, args, col, values):
    """支持单值或多值（前端多选传 a,b,c）。"""
    vals = _csv(values)
    if not vals:
        return
    if len(vals) == 1:
        where.append(f"{col}=?")
        args.append(vals[0])
    else:
        where.append(f"{col} IN ({','.join(['?'] * len(vals))})")
        args.extend(vals)


def job_facets(c):
    """筛选项数据源：库里真实存在的标签 + 城市。"""
    tags = {}
    for r in c.execute("SELECT tags FROM jobs WHERE tags IS NOT NULL AND tags != '[]'"):
        try:
            for t in json.loads(r[0] or "[]"):
                tags[t] = tags.get(t, 0) + 1
        except Exception:
            pass
    cities = [r[0] for r in c.execute(
        "SELECT city, COUNT(*) n FROM jobs WHERE city IS NOT NULL AND city != ''"
        " GROUP BY city ORDER BY n DESC LIMIT 40")]
    return {
        "tags": [{"value": k, "count": v} for k, v in sorted(tags.items(), key=lambda x: -x[1])],
        "cities": cities,
    }


def list_jobs(c, q=None, channel=None, state=None, city=None, company_id=None,
              page=1, page_size=20, sort="created_at", tag=None, presence=None, fit=None,
              priority=None, order="desc"):
    where, args = [], []
    if q:
        where.append("(title LIKE ? OR company_name LIKE ? OR description LIKE ?)")
        args += [f"%{q}%"] * 3
    _in(where, args, "channel_code", channel)
    _in(where, args, "state", state)
    if city:
        where.append("city LIKE ?")
        args.append(f"%{city}%")
    if company_id:
        where.append("company_id=?")
        args.append(company_id)
    tags = _csv(tag)
    if tags:
        where.append("(" + " OR ".join(["tags LIKE ?"] * len(tags)) + ")")
        args.extend([f'%"{t}"%' for t in tags])
    fits = _csv(fit)
    if fits:
        parts, fargs = [], []
        others = [f for f in fits if f != "none"]
        if "none" in fits:
            parts.append("fit_verdict IS NULL")
        if others:
            parts.append(f"fit_verdict IN ({','.join(['?'] * len(others))})")
            fargs.extend(others)
        where.append("(" + " OR ".join(parts) + ")")
        args.extend(fargs)
    _in(where, args, "presence", presence)
    _in(where, args, "priority", priority)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    sort = sort if sort in JOB_SORT else "created_at"
    total = c.execute(f"SELECT COUNT(*) FROM jobs {w}", args).fetchone()[0]
    direction = "ASC" if str(order).lower() == "asc" else "DESC"
    order_by = f"{OPEN_DAYS_EXPR} {direction}" if sort == "open_days" else f"{sort} {direction}"
    rows = c.execute(
        f"SELECT *, {OPEN_DAYS_SQL}, {ATT_COUNT_SQL} FROM jobs {w} ORDER BY {order_by}, id DESC LIMIT ? OFFSET ?",
        args + [page_size, (page - 1) * page_size],
    ).fetchall()
    return {"items": [parse_json_fields(dict(r)) for r in rows], "total": total}


def get_job(c, jid):
    row = c.execute(f"SELECT *, {OPEN_DAYS_SQL}, {ATT_COUNT_SQL} FROM jobs WHERE id=?", (jid,)).fetchone()
    if not row:
        return None
    d = parse_json_fields(dict(row))
    d["attachments"] = list_attachments(c, jid)
    return d


def update_job(c, jid, data: dict, actor="ui"):
    row = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if not row:
        raise KeyError("岗位不存在")
    sets, args = [], []
    for k, v in data.items():
        if k in JOB_FIELDS:
            sets.append(f"{k}=?")
            args.append(json.dumps(v, ensure_ascii=False) if k == "tags" and not isinstance(v, str) else v)
    if "salary_raw" in data and not ({"salary_min", "salary_max"} & set(data)):
        lo, hi, months = parse_salary(data["salary_raw"])
        sets += ["salary_min=?", "salary_max=?", "salary_months=?"]
        args += [lo, hi, months if months else row["salary_months"]]
    if data.get("company_name") and data["company_name"] != row["company_name"]:
        comp = ensure_company(c, data["company_name"], actor)
        sets.append("company_id=?")
        args.append(comp["id"] if comp else None)
    if sets:
        sets += ["last_change_at=?", "updated_at=?"]
        args += [now(), now(), jid]
        c.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", args)
        log(c, actor, "job.update", "job", jid, sorted(data))
    return get_job(c, jid)


def upsert_job(c, data: dict, actor="ui"):
    """按指纹幂等写入：同渠道同 source_job_id 不会重复入库，只更新非空字段。"""
    channel = data.get("channel") or data.get("channel_code")
    if not channel:
        raise ValueError("channel 必填")
    if not c.execute("SELECT 1 FROM channels WHERE code=?", (channel,)).fetchone():
        raise ValueError(f"未知渠道 {channel}，请先在信息源里新增")
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("title 必填")
    company_name = (data.get("company_name") or data.get("company") or "").strip()
    source_job_id = data.get("source_job_id") or data.get("source_id")
    fp = fingerprint(channel, source_job_id, title, company_name, data.get("city"))
    existing = c.execute("SELECT * FROM jobs WHERE fingerprint=?", (fp,)).fetchone()

    comp = ensure_company(c, company_name, actor) if company_name else None
    lo, hi = data.get("salary_min"), data.get("salary_max")
    months = data.get("salary_months")
    if not lo and not hi and data.get("salary_raw"):
        lo, hi, months = parse_salary(data["salary_raw"])

    fields = {
        "title": title,
        "company_name": company_name or (existing["company_name"] if existing else ""),
        "company_id": comp["id"] if comp else (existing["company_id"] if existing else None),
        "salary_raw": data.get("salary_raw"), "salary_min": lo, "salary_max": hi,
        "salary_months": months, "city": data.get("city"), "district": data.get("district"),
        "employment_type": data.get("employment_type"),
        "experience_req": data.get("experience_req"),
        "education_req": data.get("education_req"),
        "description": data.get("description"), "requirements": data.get("requirements"),
        "url": data.get("url"), "publisher_name": data.get("publisher_name"),
        "publisher_type": data.get("publisher_type"),
        "contact_id": data.get("contact_id"),
        "posted_at": data.get("posted_at"), "deadline": data.get("deadline"),
        "collected_at": data.get("collected_at") or now(),
        "match_score": data.get("match_score"),
        "notes": data.get("notes"),
    }
    tags_raw = data.get("tags")
    if tags_raw is None:
        tags_json = None
    elif isinstance(tags_raw, str):
        tags_json = tags_raw          # 已是 JSON 字符串
    else:
        tags_json = json.dumps([str(t).strip() for t in tags_raw if str(t).strip()], ensure_ascii=False)
    extra = data.get("extra") if isinstance(data.get("extra"), str) else json.dumps(data.get("extra") or {}, ensure_ascii=False)
    raw = data.get("raw") if isinstance(data.get("raw"), str) else json.dumps(data.get("raw") or {}, ensure_ascii=False)

    if existing:
        # 幂等：同一 channel + source_job_id 永远落到同一行；
        # 生命周期由服务端自己算，Agent 不需要上报在招状态
        changed = any(
            fields.get(k) not in (None, "") and str(fields.get(k)) != str(existing[k])
            for k in JOB_MEANINGFUL
        )
        ts = now()
        sets, args = [], []
        for k, v in fields.items():
            if v is not None and v != "":
                sets.append(f"{k}=?")
                args.append(v)
        merged_extra = {**(j(existing["extra"]) or {}), **(j(extra) or {})}
        sets += ["extra=?", "raw=?", "last_seen_at=?", "seen_count=seen_count+1"]
        args += [json.dumps(merged_extra, ensure_ascii=False), raw, ts]
        if changed:
            sets.append("last_change_at=?")
            args.append(ts)
        if tags_json is not None:
            sets.append("tags=?")
            args.append(tags_json)
        if existing["presence"] != "open":      # 下架的岗位又出现了 → 重新在招
            sets += ["presence=?", "closed_at=?", "gone_reason=?"]
            args += ["open", None, None]
        sets.append("updated_at=?")
        args += [ts, existing["id"]]
        c.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", args)
        log(c, actor, "job.upsert.update", "job", existing["id"],
            {"fingerprint": fp, "changed": changed})
        return {"created": False, "changed": changed, "job": get_job(c, existing["id"])}

    ts = now()
    cur = c.execute(
        "INSERT INTO jobs(channel_code,source_job_id,fingerprint,title,company_id,company_name,"
        "salary_raw,salary_min,salary_max,salary_months,city,district,employment_type,"
        "experience_req,education_req,description,requirements,url,publisher_name,publisher_type,"
        "contact_id,posted_at,collected_at,deadline,state,priority,match_score,extra,raw,notes,"
        "first_seen_at,last_seen_at,last_change_at,seen_count,presence,tags,created_at,updated_at)"
        " VALUES (" + ",".join(["?"] * 24) + ", 'new', ?,?,?,?,?,?,?,?, 1, 'open', ?, ?, ?)",
        (channel, source_job_id, fp, title, fields["company_id"], fields["company_name"],
         fields["salary_raw"], lo, hi, months, fields["city"], fields["district"],
         fields["employment_type"], fields["experience_req"], fields["education_req"],
         fields["description"], fields["requirements"], fields["url"], fields["publisher_name"],
         fields["publisher_type"], fields["contact_id"], fields["posted_at"],
         fields["collected_at"], fields["deadline"], data.get("priority") or 3,
         fields["match_score"], extra, raw, fields["notes"],
         ts, ts, ts,                       # first_seen_at / last_seen_at / last_change_at
         tags_json or "[]", ts, ts),       # tags / created_at / updated_at
    )
    log(c, actor, "job.create", "job", cur.lastrowid,
        {"channel": channel, "title": title, "company": company_name})
    return {"created": True, "job": get_job(c, cur.lastrowid)}


def set_job_state(c, jid: int, target: str, actor="ui", note: str | None = None):
    row = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if not row:
        raise KeyError("岗位不存在")
    check("job", row["state"], target)
    c.execute("UPDATE jobs SET state=?, updated_at=? WHERE id=?", (target, now(), jid))
    log(c, actor, "job.state", "job", jid,
        {"from": row["state"], "to": target, "title": row["title"], "note": note})
    return get_job(c, jid)


def delete_job(c, jid, actor="ui"):
    c.execute("DELETE FROM jobs WHERE id=?", (jid,))
    log(c, actor, "job.delete", "job", jid)


def mark_gone(c, args: dict, actor="agent"):
    """单个岗位下架：详情页 404 / 被删。按 id，或 channel + source_job_id 定位。"""
    row = None
    if args.get("id"):
        row = c.execute("SELECT * FROM jobs WHERE id=?", (int(args["id"]),)).fetchone()
    elif args.get("fingerprint"):
        row = c.execute("SELECT * FROM jobs WHERE fingerprint=?", (args["fingerprint"],)).fetchone()
    elif args.get("channel") and args.get("source_job_id"):
        row = c.execute("SELECT * FROM jobs WHERE channel_code=? AND source_job_id=?",
                        (args["channel"], str(args["source_job_id"]))).fetchone()
    if not row:
        raise KeyError("岗位不存在")
    if row["presence"] == "gone" and not args.get("force"):
        return {"changed": False, "job": get_job(c, row["id"])}
    ts = now()
    reason = args.get("reason") or "detail_404"
    c.execute("UPDATE jobs SET presence='gone', gone_reason=?,"
              " closed_at=COALESCE(closed_at, ?), updated_at=? WHERE id=?",
              (reason, ts, ts, row["id"]))
    if args.get("note") is not None:
        c.execute("UPDATE jobs SET notes=? WHERE id=?", (args["note"], row["id"]))
    log(c, actor, "job.mark_gone", "job", row["id"], {"reason": reason})
    return {"changed": True, "job": get_job(c, row["id"])}


def sync_company(c, args: dict, actor="agent"):
    """整家公司在某渠道的全量岗位清单。complete=True 时，清单里没有的在招岗位直接判下架。"""
    channel = args.get("channel") or args.get("channel_code")
    company_name = (args.get("company_name") or args.get("company") or "").strip()
    if not channel or not company_name:
        raise ValueError("channel / company_name 必填")
    items = args.get("jobs") or args.get("items") or []
    if isinstance(items, dict):
        items = [items]
    complete = bool(args.get("complete", True))

    created = updated = 0
    ids = []
    errors = []
    for it in items:
        try:
            r = upsert_job(c, {**it, "channel": channel, "company_name": company_name}, actor)
            ids.append(r["job"]["id"])
            created += 1 if r["created"] else 0
            updated += 0 if r["created"] else 1
        except Exception as e:  # 单条坏数据不拖垮整家
            errors.append({"title": it.get("title"), "error": str(e)})

    comp = ensure_company(c, company_name, actor)
    gone = []
    if complete and comp:
        rows = c.execute(
            "SELECT id FROM jobs WHERE channel_code=? AND company_id=?"
            " AND presence IN ('open','stale')", (channel, comp["id"])).fetchall()
        ts = now()
        for r in rows:
            if r["id"] not in ids:
                c.execute("UPDATE jobs SET presence='gone', gone_reason='company_sync',"
                          " closed_at=COALESCE(closed_at, ?), updated_at=? WHERE id=?",
                          (ts, ts, r["id"]))
                gone.append(r["id"])
        if gone:
            log(c, actor, "job.sync_company", "company", comp["id"],
                {"channel": channel, "gone": len(gone), "listed": len(ids)})
    return {"created": created, "updated": updated, "ids": ids,
            "gone": gone, "gone_count": len(gone), "errors": errors}

REVIEW_FIELDS = {"tags", "priority", "match_score", "notes", "description", "requirements"}

# job-match 口径：结论 + 逐条要求状态
FIT_VERDICTS = ("apply", "apply_after_gap", "cautious", "skip")
FIT_STATUS = ("matched", "phrasing_gap", "insufficient", "real_gap", "unknown")


def set_job_fit(c, args: dict, actor="agent"):
    """写入 JD 匹配评估（job-match 结构）：结论、一句话理由、要求-证据矩阵、硬门槛、补强建议。"""
    jid = int(args.get("id") or 0)
    if not jid:
        raise ValueError("id 必填")
    verdict = args.get("verdict")
    if verdict and verdict not in FIT_VERDICTS:
        raise ValueError(f"verdict 只能是 {FIT_VERDICTS}")
    if not verdict and not args.get("reason"):
        raise ValueError("至少给 verdict 或 reason")
    reqs = args.get("requirements") or []
    for r in reqs:
        st = r.get("status")
        if st and st not in FIT_STATUS:
            raise ValueError(f"requirements[].status 只能是 {FIT_STATUS}")
    report = {
        "requirements": reqs,
        "hard_gates": args.get("hard_gates") or [],
        "gaps": args.get("gaps") or [],
        "strategy": args.get("strategy") or {},
        "source": args.get("source") or "job-match",
        "updated_at": now(),
    }
    row = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if not row:
        raise KeyError("岗位不存在")
    c.execute(
        "UPDATE jobs SET fit_verdict=COALESCE(?, fit_verdict),"
        " fit_reason=COALESCE(?, fit_reason), fit_report=?, fit_at=?, updated_at=? WHERE id=?",
        (verdict, args.get("reason"), json.dumps(report, ensure_ascii=False), now(), now(), jid))
    log(c, actor, "job.fit", "job", jid,
        {"verdict": verdict, "reason": (args.get("reason") or "")[:80],
         "requirements": len(reqs),
         "status_counts": {s: sum(1 for r in reqs if r.get("status") == s) for s in FIT_STATUS}})
    return get_job(c, jid)


def review_job(c, args: dict, actor="agent"):
    """预审：改标签/优先级/匹配度/JD 修正，并可同时推进状态。不碰采集侧的原始字段。"""
    jid = int(args.get("id") or 0)
    if not jid:
        raise ValueError("id 必填")
    data = {k: v for k, v in args.items() if k in REVIEW_FIELDS and v is not None}
    if data:
        update_job(c, jid, data, actor)
    if args.get("state"):
        set_job_state(c, jid, args["state"], actor, args.get("note"))
    log(c, actor, "job.review", "job", jid, {"fields": sorted(data), "state": args.get("state")})
    return get_job(c, jid)


def read_attachments(c, args: dict, max_items: int = 3, max_bytes: int = 3 * 1024 * 1024):
    """给多模态 Agent 读图：返回 base64。默认最多 3 个、单个 3MB 以内。"""
    jid = args.get("job_id") or args.get("id")
    if not jid:
        raise ValueError("job_id 必填")
    rows = list_attachments(c, int(jid))
    if args.get("attachment_id"):
        rows = [r for r in rows if r["id"] == int(args["attachment_id"])]
    out = []
    for r in rows[:max_items]:
        if r["size"] > max_bytes:
            out.append({"id": r["id"], "filename": r["filename"], "mime": r["mime"],
                        "size": r["size"],
                        "skipped": f"超过 {max_bytes // 1024 // 1024}MB，未返回内容"})
            continue
        path = UPLOAD_DIR / r["rel_path"]
        raw = path.read_bytes() if path.exists() else b""
        out.append({"id": r["id"], "filename": r["filename"], "mime": r["mime"],
                    "size": r["size"], "caption": r["caption"],
                    "data_base64": base64.b64encode(raw).decode() if raw else None})
    return {"job_id": int(jid), "count": len(out), "attachments": out}


# ---------------------------------------------------------------- 简历定制
RESUME_DIR = UPLOAD_DIR / "resumes"
CHROME_BIN = os.environ.get("JOBHUB_CHROME",
                            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def _slug(t: str, limit: int = 20) -> str:
    t = re.sub(r"[\\/:*?\"'<>|\s]+", "", (t or "").strip())
    return t[:limit] or "未命名"


def build_resume_filename(role: str, company: str, when: str | None = None) -> str:
    """规范命名：<姓名>_岗位方向_公司_YYYYMMDD（姓名取 JOBHUB_OWNER_NAME，可留空）"""
    d = (when or now())[:10].replace("-", "")
    prefix = (os.environ.get("JOBHUB_OWNER_NAME") or "").strip()
    parts = [p for p in (prefix, _slug(role), _slug(company), d) if p]
    return "_".join(parts)


MARK_RE = re.compile(r"</?mark\b[^>]*>")


def strip_marks(html: str) -> str:
    """浏览版用 <mark> 高亮；PDF 版去掉标记，保证干净。"""
    return MARK_RE.sub("", html or "")


def render_pdf(html: str, out_path) -> bool:
    """用本机 Chrome 无头模式把 HTML 打成 A4 PDF（去页眉页脚）。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        tmp = f.name
    try:
        subprocess.run(
            [CHROME_BIN, "--headless", "--disable-gpu", "--no-sandbox",
             "--no-pdf-header-footer", "--virtual-time-budget=4000",
             f"--print-to-pdf={out_path}", f"file://{tmp}"],
            check=True, capture_output=True, timeout=120,
        )
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception as e:
        try:
            (out_path.parent / "render.err.log").write_text(f"{type(e).__name__}: {e}\n")
        except OSError:
            pass
        return False
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def pdf_pages(path) -> int | None:
    """数一下 PDF 的页对象，给 Agent 做 A4 溢出自检。"""
    try:
        data = path.read_bytes()
        return len(re.findall(rb"/Type\s*/Page[^s]", data)) or None
    except OSError:
        return None


def create_resume(c, data: dict, actor="agent"):
    html = data.get("html") or ""
    if len(html) < 200:
        raise ValueError("html 太短，至少要是一份完整简历")
    role = (data.get("role") or data.get("title") or "").strip()
    company = (data.get("company") or "").strip()
    fname = data.get("filename") or build_resume_filename(role, company)
    rid = c.execute(
        "INSERT INTO resumes(job_id,filename,role,company,changes,html,agent_id,created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (data.get("job_id"), fname, role, company,
         json.dumps(data.get("changes") or [], ensure_ascii=False), html,
         (actor or "").replace("agent:", ""), now())).lastrowid
    pdf_rel = f"resumes/{fname}.pdf"
    ok = render_pdf(strip_marks(html), UPLOAD_DIR / pdf_rel)
    pages = pdf_pages(UPLOAD_DIR / pdf_rel) if ok else None
    if ok:
        c.execute("UPDATE resumes SET pdf_rel=?, pdf_pages=? WHERE id=?", (pdf_rel, pages, rid))
    log(c, actor, "resume.create", "resume", rid,
        {"filename": fname, "pdf": ok, "pages": pages, "marks": len(MARK_RE.findall(html)),
         "changes": len(data.get("changes") or [])})
    return {"created": True, "pdf": ok, "pdf_pages": pages,
            "marks": len(MARK_RE.findall(html)), "resume": get_resume(c, rid)}


def get_resume(c, rid: int, include_html=True, include_pdf=False):
    row = c.execute("SELECT * FROM resumes WHERE id=?", (rid,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["changes"] = json.loads(d.get("changes") or "[]")
    d["pdf_url"] = f"/files/{d['pdf_rel']}" if d.get("pdf_rel") else None
    if d.get("pdf_rel") and d.get("pdf_pages") is None:
        pages = pdf_pages(UPLOAD_DIR / d["pdf_rel"])
        if pages:
            c.execute("UPDATE resumes SET pdf_pages=? WHERE id=?", (pages, rid))
            d["pdf_pages"] = pages
    if not include_html:
        d.pop("html", None)
    if include_pdf and d.get("pdf_rel"):
        p = UPLOAD_DIR / d["pdf_rel"]
        d["pdf_base64"] = base64.b64encode(p.read_bytes()).decode() if p.exists() else None
    return d


TAG_RE = re.compile(r"<[^>]+>")


def _plain_text(html: str) -> str:
    """按行抽纯文本，用于 diff（保留段落边界）。"""
    import html as _html
    t = re.sub(r"<(br|/p|/li|/h[1-6]|/div)\b[^>]*>", "\n", html or "", flags=re.I)
    t = TAG_RE.sub("", t)
    t = _html.unescape(t)
    return "\n".join(l.strip() for l in t.splitlines() if l.strip())


def diff_resumes(c, a_id: int, b_id: int | None = None, context: int = 2):
    """版本 diff：b 不传则和它的上一版比。返回统一 diff + 两侧 changes。"""
    import difflib
    a = c.execute("SELECT * FROM resumes WHERE id=?", (a_id,)).fetchone()
    if not a:
        raise KeyError("版本不存在")
    if b_id:
        b = c.execute("SELECT * FROM resumes WHERE id=?", (b_id,)).fetchone()
    else:
        b = c.execute(
            "SELECT * FROM resumes WHERE id<? AND (job_id IS ? OR job_id=?)"
            " ORDER BY id DESC LIMIT 1",
            (a_id, a["job_id"], a["job_id"])).fetchone()
    if not b:
        return {"no_base": True, "to": {"id": a["id"], "filename": a["filename"],
                                        "changes": json.loads(a["changes"] or "[]")},
                "hint": "这是该岗位的第一版，没有可比的上一版"}
    old, new = _plain_text(b["html"]).splitlines(), _plain_text(a["html"]).splitlines()
    lines = list(difflib.unified_diff(old, new, fromfile=f"#{b['id']} {b['filename']}",
                                      tofile=f"#{a['id']} {a['filename']}", n=context, lineterm=""))
    added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    return {
        "from": {"id": b["id"], "filename": b["filename"],
                 "changes": json.loads(b["changes"] or "[]")},
        "to": {"id": a["id"], "filename": a["filename"],
               "changes": json.loads(a["changes"] or "[]")},
        "added_lines": added, "removed_lines": removed,
        "diff": "\n".join(lines)[:20000],
    }


def save_resume_source(c, data: dict, actor="ui"):
    html = data.get("html") or ""
    if len(html) < 200:
        raise ValueError("简历 HTML 太短")
    cur = c.execute("INSERT INTO resume_sources(name,html,path,created_at) VALUES (?,?,?,?)",
                    (data.get("name") or "基准简历", html, data.get("path"), now()))
    log(c, actor, "resume.source", "resume_source", cur.lastrowid, {"name": data.get("name")})
    return get_resume_source(c)


def get_resume_source(c, fallback_path: str | None = None):
    """优先用页面上传的基准简历；没有就读 config 里的路径（服务端本机能读到）。"""
    row = c.execute("SELECT * FROM resume_sources ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        return {"source": "uploaded", "id": row["id"], "name": row["name"],
                "html": row["html"], "path": row["path"], "created_at": row["created_at"]}
    if fallback_path:
        p = Path(fallback_path)
        if p.exists():
            return {"source": "file", "path": str(p), "name": p.name,
                    "html": p.read_text(encoding="utf-8", errors="ignore"),
                    "created_at": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")}
    return {"source": None, "html": None,
            "hint": "还没有基准简历：在「简历」页上传原始 HTML，或让本人把文件路径告诉我"}


def list_resumes(c, job_id=None, limit=100):
    if job_id:
        rows = c.execute("SELECT id FROM resumes WHERE job_id=? ORDER BY id DESC LIMIT ?",
                         (job_id, limit)).fetchall()
    else:
        rows = c.execute("SELECT id FROM resumes ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = get_resume(c, r[0])
        if d:
            d.pop("html", None)
            out.append(d)
    return out


def delete_resume(c, rid: int, actor="ui"):
    row = c.execute("SELECT * FROM resumes WHERE id=?", (rid,)).fetchone()
    if not row:
        raise KeyError("简历不存在")
    c.execute("DELETE FROM resumes WHERE id=?", (rid,))
    if row["pdf_rel"]:
        try:
            (UPLOAD_DIR / row["pdf_rel"]).unlink(missing_ok=True)
        except OSError:
            pass
    log(c, actor, "resume.delete", "resume", rid)
    return {"ok": True}


# ---------------------------------------------------------------- Agent 诉求单
REPORT_KINDS = ("suggestion", "issue", "data_quality", "question")
REPORT_STATUS = {"open": ["accepted", "rejected", "done"],
                 "accepted": ["done", "rejected"],
                 "rejected": ["open"],
                 "done": ["open"]}


def create_report(c, agent_id: str, data: dict):
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("title 必填")
    kind = data.get("kind") or "suggestion"
    if kind not in REPORT_KINDS:
        raise ValueError(f"kind 只能是 {REPORT_KINDS}")
    ts = now()
    cur = c.execute(
        "INSERT INTO agent_reports(agent_id,kind,title,content,severity,target,status,created_at,updated_at)"
        " VALUES (?,?,?,?,?,?, 'open', ?,?)",
        (agent_id, kind, title, data.get("content"), data.get("severity") or "normal",
         data.get("target"), ts, ts))
    log(c, f"agent:{agent_id}", "report.submit", "report", cur.lastrowid,
        {"title": title, "kind": kind})
    return dict(c.execute("SELECT * FROM agent_reports WHERE id=?", (cur.lastrowid,)).fetchone())


def list_reports(c, status=None, agent_id=None, limit=100):
    where, args = [], []
    if status:
        where.append("status=?")
        args.append(status)
    if agent_id:
        where.append("agent_id=?")
        args.append(agent_id)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    rows = c.execute(f"SELECT * FROM agent_reports {w} ORDER BY id DESC LIMIT ?",
                     args + [limit]).fetchall()
    return [dict(r) for r in rows]


def update_report(c, rid: int, data: dict, actor="agent"):
    row = c.execute("SELECT * FROM agent_reports WHERE id=?", (rid,)).fetchone()
    if not row:
        raise KeyError("诉求不存在")
    sets, args = [], []
    status = data.get("status")
    if status and status != row["status"]:
        if status not in REPORT_STATUS.get(row["status"], []):
            raise ValueError(f"不允许 {row['status']} -> {status}")
        sets.append("status=?")
        args.append(status)
    for k in ("response", "severity", "target"):
        if data.get(k) is not None:
            sets.append(f"{k}=?")
            args.append(data[k])
    if not sets:
        raise ValueError("没有要改的字段（status / response / severity / target）")
    sets.append("updated_at=?")
    args += [now(), rid]
    c.execute(f"UPDATE agent_reports SET {', '.join(sets)} WHERE id=?", args)
    log(c, actor, "report.update", "report", rid, {"status": status})
    return dict(c.execute("SELECT * FROM agent_reports WHERE id=?", (rid,)).fetchone())


def delete_report(c, rid: int, actor="ui"):
    if not c.execute("SELECT 1 FROM agent_reports WHERE id=?", (rid,)).fetchone():
        raise KeyError("诉求不存在")
    c.execute("DELETE FROM agent_reports WHERE id=?", (rid,))
    log(c, actor, "report.delete", "report", rid)
    return {"ok": True}


def sweep_presence(c, stale_days: int | None = None, gone_days: int | None = None):
    """服务端自己判下架：不靠 Agent 报。一段时间没被重新采集到 → 疑似下架 → 下架。"""
    stale_days = stale_days or STALE_DAYS
    gone_days = gone_days or GONE_DAYS
    stale = c.execute(
        "UPDATE jobs SET presence='stale'"
        " WHERE presence='open' AND last_seen_at IS NOT NULL"
        "   AND last_seen_at < datetime('now','localtime',?)",
        (f"-{stale_days} day",)).rowcount
    gone = c.execute(
        "UPDATE jobs SET presence='gone', gone_reason='sweep',"
        " closed_at=COALESCE(closed_at, datetime('now','localtime'))"
        " WHERE presence IN ('open','stale') AND last_seen_at IS NOT NULL"
        "   AND last_seen_at < datetime('now','localtime',?)",
        (f"-{gone_days} day",)).rowcount
    if stale or gone:
        log(c, "system", "job.presence.sweep", detail={"stale": stale, "gone": gone,
                                                        "stale_days": stale_days, "gone_days": gone_days})
    return {"stale": stale, "gone": gone}


# ---------------------------------------------------------------- channels
CHANNEL_FIELDS = ("name", "logo", "kind", "home_url", "config", "note",
                  "state_note", "last_run_at", "next_check_at", "run_stats")


def list_channels(c):
    rows = c.execute("SELECT * FROM channels ORDER BY name").fetchall()
    counts = dict(c.execute(
        "SELECT channel_code, COUNT(*) FROM jobs GROUP BY channel_code").fetchall())
    out = []
    for r in rows:
        d = json.loads(json.dumps(dict(r)))
        d["job_count"] = counts.get(d["code"], 0)
        for k in ("config", "run_stats", "tags"):
            if isinstance(d.get(k), str):
                try:
                    d[k] = json.loads(d[k] or "{}")
                except Exception:
                    d[k] = {}
        out.append(d)
    return out


def get_channel(c, code):
    for ch in list_channels(c):
        if ch["code"] == code:
            return ch
    return None


def update_channel(c, code, data: dict, actor="ui"):
    row = c.execute("SELECT * FROM channels WHERE code=?", (code,)).fetchone()
    if not row:
        raise KeyError("渠道不存在")
    sets, args = [], []
    for k in CHANNEL_FIELDS:
        if k in data and data[k] is not None:
            v = data[k]
            if k in ("config", "run_stats") and not isinstance(v, str):
                v = json.dumps(v, ensure_ascii=False)
            sets.append(f"{k}=?")
            args.append(v)
    if "state" in data and data["state"] and data["state"] != row["state"]:
        check("channel", row["state"], data["state"])
        sets += ["state=?", "state_updated_at=?"]
        args += [data["state"], now()]
        log(c, actor, "channel.state", "channel", None,
            {"code": code, "from": row["state"], "to": data["state"],
             "note": data.get("state_note")})
    if sets:
        sets.append("updated_at=?")
        args += [now(), code]
        c.execute(f"UPDATE channels SET {', '.join(sets)} WHERE code=?", args)
    return get_channel(c, code)


def report_channel(c, args: dict, actor="agent"):
    """采集 Agent 汇报一次运行：状态、原因、游标、统计、下次计划。"""
    code = args.get("code")
    if not code:
        raise ValueError("code 必填")
    row = c.execute("SELECT * FROM channels WHERE code=?", (code,)).fetchone()
    if not row:
        raise KeyError(f"未知渠道 {code}")

    run = args.get("run") or {}
    stats = dict(json.loads(row["run_stats"] or "{}"))
    if run:
        stats = {
            "last_run": rr_clean(run),
            "history": (stats.get("history") or [])[-9:] + [{
                "at": run.get("finished_at") or now(),
                "scraped": run.get("scraped"),
                "created": run.get("created"),
                "updated": run.get("updated"),
                "errors": len(run.get("errors") or []),
            }],
            "cursor": args.get("cursor") or stats.get("cursor"),
            "credentials_expire_at": args.get("credentials_expire_at") or stats.get("credentials_expire_at"),
            "device": args.get("device") or stats.get("device"),
        }
    payload = {
        "state_note": args.get("note") or row["state_note"],
        "last_run_at": run.get("finished_at") or now(),
        "next_check_at": args.get("next_check_at"),
        "run_stats": stats,
    }
    if args.get("state"):
        payload["state"] = args["state"]
    log(c, actor, "channel.report", "channel", None,
        {"code": code, "state": args.get("state"), "run": {k: run.get(k) for k in
         ("scraped", "created", "updated", "duplicates") if k in run}})
    return update_channel(c, code, payload, actor)


def rr_clean(run: dict) -> dict:
    keys = ("started_at", "finished_at", "scraped", "created", "updated", "duplicates", "errors")
    return {k: run[k] for k in keys if run.get(k) is not None}


def create_channel(c, data: dict, actor="ui"):
    code = (data.get("code") or "").strip()
    name = (data.get("name") or "").strip()
    if not code or not name:
        raise ValueError("code / name 必填")
    ts = now()
    c.execute(
        "INSERT INTO channels(code,name,logo,kind,home_url,state,config,note,created_at,updated_at)"
        " VALUES (?,?,?,?,?, 'active', ?,?,?,?)",
        (code, name, data.get("logo"), data.get("kind") or "job_board", data.get("home_url"),
         json.dumps(data.get("config") or {}, ensure_ascii=False), data.get("note"), ts, ts),
    )
    log(c, actor, "channel.create", "channel", None, {"code": code})
    return get_channel(c, code)


# ---------------------------------------------------------------- dashboard
def dashboard(c):
    job_states = dict(c.execute("SELECT state, COUNT(*) FROM jobs GROUP BY state").fetchall())
    presence = dict(c.execute("SELECT presence, COUNT(*) FROM jobs GROUP BY presence").fetchall())
    avg_open = c.execute(f"SELECT ROUND(AVG({OPEN_DAYS_EXPR}), 1) FROM jobs").fetchone()[0]
    contact_states = dict(c.execute("SELECT state, COUNT(*) FROM contacts GROUP BY state").fetchall())
    company_states = dict(c.execute("SELECT state, COUNT(*) FROM companies GROUP BY state").fetchall())
    channels = list_channels(c)
    total_jobs = sum(job_states.values())
    return {
        "jobs": {
            "total": total_jobs,
            "by_state": job_states,
            "new_today": c.execute(
                "SELECT COUNT(*) FROM jobs WHERE date(created_at)=date('now','localtime')").fetchone()[0],
            "week": c.execute(
                "SELECT COUNT(*) FROM jobs WHERE created_at>=datetime('now','-7 day','localtime')").fetchone()[0],
            "applied": sum(job_states.get(s, 0) for s in ("applied", "interviewing", "offer", "accepted")),
            "interviewing": job_states.get("interviewing", 0),
            "offers": job_states.get("offer", 0) + job_states.get("accepted", 0),
            "todo": job_states.get("new", 0),
            "presence": presence,
            "stale": presence.get("stale", 0),
            "gone": presence.get("gone", 0),
            "avg_open_days": avg_open,
        },
        "contacts": {"total": sum(contact_states.values()), "by_state": contact_states,
                     "todo": contact_states.get("new", 0)},
        "companies": {"total": sum(company_states.values()), "by_state": company_states},
        "channels": channels,
        "reports": {
            "open": c.execute("SELECT COUNT(*) FROM agent_reports WHERE status='open'").fetchone()[0],
            "recent": [dict(r) for r in c.execute(
                "SELECT * FROM agent_reports ORDER BY id DESC LIMIT 5").fetchall()],
        },
        "channels_need_human": [
            {"code": c["code"], "name": c["name"], "state": c["state"],
             "state_note": c.get("state_note")}
            for c in channels if c["state"] in ("need_verify", "login_expired")
        ],
        "activity": [dict(r) for r in c.execute(
            "SELECT * FROM activity ORDER BY id DESC LIMIT 12").fetchall()],
    }


def clear_demo(c):
    n = 0
    for t in ("jobs", "contacts", "companies"):
        cur = c.execute(f"DELETE FROM {t} WHERE is_demo=1")
        n += cur.rowcount
    log(c, "ui", "maintenance.clear_demo", detail=f"删除 {n} 条示例数据")
    return n


def activity(c, limit=50, entity=None, entity_id=None):
    where, args = [], []
    if entity:
        where.append("entity=?")
        args.append(entity)
    if entity_id is not None:
        where.append("entity_id=?")
        args.append(entity_id)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    rows = c.execute(f"SELECT * FROM activity {w} ORDER BY id DESC LIMIT ?", args + [limit]).fetchall()
    return [dict(r) for r in rows]


AGENT_EDIT_FIELDS = ("name", "kind", "remark", "active", "prompt", "config", "scopes")


def get_agent(c, aid: str):
    row = c.execute("SELECT * FROM agents WHERE id=?", (aid,)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["config"] = json.loads(d.get("config") or "{}")
    except Exception:
        d["config"] = {}
    return d


def agents(c):
    rows = c.execute("SELECT * FROM agents ORDER BY created_at").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["config"] = json.loads(d.get("config") or "{}")
        except Exception:
            d["config"] = {}
        out.append(d)
    return out


def update_agent(c, aid: str, data: dict, actor="ui"):
    """改 Agent 的元信息 / 权限 / 任务提示词 / 配置。config 必须是合法 JSON。"""
    row = c.execute("SELECT * FROM agents WHERE id=?", (aid,)).fetchone()
    if not row:
        raise KeyError("agent 不存在")
    sets, args = [], []
    for k in AGENT_EDIT_FIELDS:
        if k not in data:
            continue
        v = data[k]
        if k == "scopes":
            v = ",".join(v) if isinstance(v, (list, tuple)) else str(v)
        elif k == "config":
            if isinstance(v, str):
                try:
                    json.loads(v)
                except Exception as e:
                    raise ValueError(f"config 不是合法 JSON：{e}")
            else:
                v = json.dumps(v, ensure_ascii=False)
        elif k == "active":
            v = int(v)
        sets.append(f"{k}=?")
        args.append(v)
    if not sets:
        return get_agent(c, aid)
    args.append(aid)
    c.execute(f"UPDATE agents SET {', '.join(sets)} WHERE id=?", args)
    log(c, actor, "agent.update", "agent", None,
        {"id": aid, "fields": sorted(set(data) & set(AGENT_EDIT_FIELDS))})
    return get_agent(c, aid)
