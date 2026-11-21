import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(os.environ.get(
    "RECRUIT_DB",
    Path(__file__).resolve().parent.parent / "data" / "recruit.db",
))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
  code        TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  logo        TEXT,
  kind        TEXT,          -- job_board | social | messenger | community
  home_url    TEXT,
  state       TEXT NOT NULL DEFAULT 'active',
  state_note  TEXT,          -- 状态原因：人工验证/登录失效/限流说明
  config      TEXT NOT NULL DEFAULT '{}',   -- 采集配置：关键词/账号/频控
  note        TEXT,
  is_demo     INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL,
  name_norm   TEXT NOT NULL,
  industry    TEXT,
  scale       TEXT,
  stage       TEXT,
  city        TEXT,
  website     TEXT,
  source      TEXT,
  state       TEXT NOT NULL DEFAULT 'new',
  tags        TEXT NOT NULL DEFAULT '[]',
  notes       TEXT,
  is_demo     INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_companies_norm ON companies(name_norm);

CREATE TABLE IF NOT EXISTS contacts (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  name            TEXT NOT NULL,
  type            TEXT NOT NULL DEFAULT 'hr',  -- hr | headhunter | referral | interviewer | other
  company_id      INTEGER REFERENCES companies(id) ON DELETE SET NULL,
  company_name    TEXT,
  title           TEXT,
  wechat          TEXT,
  phone           TEXT,
  email           TEXT,
  profile_url     TEXT,
  channel_code    TEXT,
  state           TEXT NOT NULL DEFAULT 'new',
  last_contact_at TEXT,
  tags            TEXT NOT NULL DEFAULT '[]',
  notes           TEXT,
  is_demo         INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_contacts_company ON contacts(company_id);
CREATE INDEX IF NOT EXISTS ix_contacts_state ON contacts(state);

CREATE TABLE IF NOT EXISTS jobs (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_code    TEXT NOT NULL,
  source_job_id   TEXT,
  fingerprint     TEXT NOT NULL,
  title           TEXT NOT NULL,
  company_id      INTEGER REFERENCES companies(id) ON DELETE SET NULL,
  company_name    TEXT NOT NULL,
  salary_raw      TEXT,
  salary_min      INTEGER,
  salary_max      INTEGER,
  salary_months   INTEGER,
  city            TEXT,
  district        TEXT,
  employment_type TEXT,
  experience_req  TEXT,
  education_req   TEXT,
  description     TEXT,
  requirements    TEXT,
  url             TEXT,
  publisher_name  TEXT,
  publisher_type  TEXT,
  contact_id      INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
  posted_at       TEXT,
  collected_at    TEXT,
  deadline        TEXT,
  state           TEXT NOT NULL DEFAULT 'new',
  first_seen_at   TEXT,          -- 首次被采集到（算在招时长用）
  last_seen_at    TEXT,          -- 最后一次仍看到它在招
  last_change_at  TEXT,          -- 内容真正发生变化的最后一次
  seen_count      INTEGER NOT NULL DEFAULT 1,
  fit_verdict     TEXT,          -- apply | apply_after_gap | cautious | skip（job-match 结论）
  fit_reason      TEXT,          -- 一句话推荐/不推荐理由
  fit_report      TEXT DEFAULT '{}',   -- 完整匹配矩阵 JSON
  fit_at          TEXT,          -- 评估时间
  presence        TEXT NOT NULL DEFAULT 'open',   -- open | stale | gone
  closed_at       TEXT,          -- 判定下架的时间
  gone_reason     TEXT,          -- sweep | company_sync | detail_404 | manual | agent
  tags            TEXT NOT NULL DEFAULT '[]',   -- 自定义标签（核心岗 / 已内推 …）
  priority        INTEGER NOT NULL DEFAULT 3,
  match_score     REAL,
  extra           TEXT NOT NULL DEFAULT '{}',   -- 渠道特有结构化字段
  raw             TEXT NOT NULL DEFAULT '{}',   -- 原始 payload，永不改写
  notes           TEXT,
  is_demo         INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_fp ON jobs(fingerprint);
CREATE INDEX IF NOT EXISTS ix_jobs_channel ON jobs(channel_code);
CREATE INDEX IF NOT EXISTS ix_jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS ix_jobs_company ON jobs(company_id);

CREATE TABLE IF NOT EXISTS job_attachments (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id     INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  filename   TEXT NOT NULL,
  mime       TEXT NOT NULL,
  size       INTEGER NOT NULL,
  sha256     TEXT NOT NULL,
  rel_path   TEXT NOT NULL,     -- 相对 data/uploads 的路径
  caption    TEXT,
  is_demo    INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_att_job ON job_attachments(job_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_att_job_sha ON job_attachments(job_id, sha256);

CREATE TABLE IF NOT EXISTS activity (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  ts        TEXT NOT NULL,
  actor     TEXT NOT NULL,      -- ui | agent:<id>
  action    TEXT NOT NULL,
  entity    TEXT,
  entity_id INTEGER,
  detail    TEXT
);
CREATE INDEX IF NOT EXISTS ix_activity_ts ON activity(ts);

CREATE TABLE IF NOT EXISTS agents (
  id           TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  kind         TEXT,
  secret       TEXT NOT NULL,
  scopes       TEXT NOT NULL,   -- 逗号分隔
  prompt       TEXT,            -- 任务描述（提示词），本人和 Agent 都能读
  config       TEXT NOT NULL DEFAULT '{}',   -- 自由 JSON，Agent 自己读、管理 Agent 改
  active       INTEGER NOT NULL DEFAULT 1,
  call_count   INTEGER NOT NULL DEFAULT 0,
  last_seen_at TEXT,
  remark       TEXT,
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nonces (
  agent_id TEXT NOT NULL,
  nonce    TEXT NOT NULL,
  ts       REAL NOT NULL,
  PRIMARY KEY (agent_id, nonce)
);

CREATE TABLE IF NOT EXISTS resume_sources (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT,
  html       TEXT NOT NULL,
  path       TEXT,               -- 来源文件路径（可选，便于回溯）
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resumes (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id     INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
  filename   TEXT NOT NULL,          -- 规范文件名（不含扩展）
  role       TEXT,                   -- 投的岗位方向
  company    TEXT,
  changes    TEXT NOT NULL DEFAULT '[]',   -- [{where, before, after, why}]
  html       TEXT NOT NULL,          -- 带 <mark> 的浏览版
  pdf_rel    TEXT,                   -- 干净版 PDF（相对 data/uploads）
  pdf_pages  INTEGER,                -- PDF 页数（A4 溢出自检用）
  agent_id   TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_resumes_job ON resumes(job_id);

CREATE TABLE IF NOT EXISTS agent_reports (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id   TEXT NOT NULL,
  kind       TEXT NOT NULL DEFAULT 'suggestion',  -- suggestion | issue | data_quality | question
  title      TEXT NOT NULL,
  content    TEXT,
  severity   TEXT NOT NULL DEFAULT 'normal',      -- low | normal | high
  target     TEXT,                                -- channel:boss / agent:xxx / job:123
  status     TEXT NOT NULL DEFAULT 'open',        -- open | accepted | rejected | done
  response   TEXT,                                -- 处理说明（中台管理 Agent 或本人写）
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_reports_status ON agent_reports(status, id);

CREATE TABLE IF NOT EXISTS auth_codes (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  email      TEXT NOT NULL,
  code_hash  TEXT NOT NULL,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  tries      INTEGER NOT NULL DEFAULT 0,
  ip         TEXT
);
CREATE INDEX IF NOT EXISTS ix_auth_codes_email ON auth_codes(email, id);
"""

CHANNELS = [
    ("liepin", "猎聘", "/logos/liepin.png", "job_board", "https://www.liepin.com"),
    ("boss", "BOSS直聘", "/logos/boss.png", "job_board", "https://www.zhipin.com"),
    ("linkedin", "领英", "/logos/linkedin.png", "social", "https://www.linkedin.com/jobs"),
    ("maimai", "脉脉", "/logos/maimai.png", "community", "https://maimai.cn"),
    ("xiaohongshu", "小红书", "/logos/xiaohongshu.png", "community", "https://www.xiaohongshu.com"),
    ("x", "X", "/logos/x.svg", "social", "https://x.com/search"),
    ("wechat_mp", "微信公众号", "/logos/wechat.svg", "messenger", "https://mp.weixin.qq.com"),
    ("jike", "即刻", "/logos/jike.png", "community", "https://web.okjike.com"),
]

SCOPES = [
    "stats:read",
    "job:read", "job:write", "job:state", "job:review",
    "company:read", "company:write", "company:state",
    "contact:read", "contact:write", "contact:state",
    "channel:read", "channel:write", "channel:state",
    "agent:write",   # 管理 Agent：能看/改其他 Agent 的提示词配置、管理诉求单
    "report:read",
]

DEFAULT_AGENTS = [
    ("collector-liepin", "采集 Agent（猎聘/BOSS 等）", "collector",
     "job:read,job:write,company:read,company:write,channel:read,channel:state,stats:read",
     "只管灌数据，不许改联系人状态、不许改岗位状态"),
    ("followup-hr", "跟单 Agent（HR/猎头沟通）", "followup",
     "contact:read,contact:write,contact:state,company:read,job:read,stats:read",
     "可以推进联系人状态，不能删除岗位"),
    ("analyst", "分析 Agent（预审）", "analyst",
     "stats:read,job:read,job:review,company:read,contact:read,channel:read",
     "预审：解析 JD/截图、打标签、定优先级、写匹配度、推进状态；不碰采集侧原始字段"),
    ("state-keeper", "中台管理", "followup",
     "job:read,job:state,company:read,company:state,contact:read,contact:state,stats:read",
     "只推进状态，不新增不删除：对应你想外放的「状态维护接口」"),
]


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def norm_name(s: str) -> str:
    return "".join((s or "").lower().split()).replace("（", "(").replace("）", ")")


@contextmanager
def db():
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


CURRENT_AGENT = {"actor": None}


def set_current_agent(actor: str | None):
    """A2A 请求期间设置，让 service 里写日志的 "agent" 变成真实 agent id。"""
    CURRENT_AGENT["actor"] = actor


def log(c, actor: str, action: str, entity: str = None, entity_id=None, detail=None):
    if actor == "agent" and CURRENT_AGENT["actor"]:
        actor = CURRENT_AGENT["actor"]
    c.execute(
        "INSERT INTO activity(ts,actor,action,entity,entity_id,detail) VALUES (?,?,?,?,?,?)",
        (now(), actor, action, entity, entity_id,
         detail if isinstance(detail, str) or detail is None else json.dumps(detail, ensure_ascii=False)),
    )


def init(seed_demo: bool = bool(os.environ.get("JOBHUB_SEED_DEMO"))):
    with db() as c:
        c.executescript(SCHEMA)
        _migrate(c)
        ts = now()
        for code, name, logo, kind, url in CHANNELS:
            c.execute(
                "INSERT OR IGNORE INTO channels(code,name,logo,kind,home_url,state,created_at,updated_at)"
                " VALUES (?,?,?,?,?, 'active', ?, ?)",
                (code, name, logo, kind, url, ts, ts),
            )
        for aid, name, kind, scopes, remark in DEFAULT_AGENTS:
            if not c.execute("SELECT 1 FROM agents WHERE id=?", (aid,)).fetchone():
                c.execute(
                    "INSERT INTO agents(id,name,kind,secret,scopes,active,remark,created_at)"
                    " VALUES (?,?,?,?,?,1,?,?)",
                    (aid, name, kind, secrets.token_urlsafe(24), scopes, remark, ts),
                )
        has = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        if seed_demo and has == 0:
            seed_demo_data(c)


def _migrate(c):
    """新增字段：老库自动补列 + 回填，不用手写迁移脚本。"""
    acols = {r["name"] for r in c.execute("PRAGMA table_info(agents)")}
    for name, ddl in [("prompt", "TEXT"), ("config", "TEXT NOT NULL DEFAULT '{}'")]:
        if name not in acols:
            c.execute(f"ALTER TABLE agents ADD COLUMN {name} {ddl}")

    jcols = {r["name"] for r in c.execute("PRAGMA table_info(jobs)")}
    for name, ddl in [
        ("first_seen_at", "TEXT"), ("last_seen_at", "TEXT"), ("last_change_at", "TEXT"),
        ("seen_count", "INTEGER NOT NULL DEFAULT 1"),
        ("presence", "TEXT NOT NULL DEFAULT 'open'"), ("closed_at", "TEXT"),
        ("gone_reason", "TEXT"), ("tags", "TEXT NOT NULL DEFAULT '[]'"),
        ("fit_verdict", "TEXT"), ("fit_reason", "TEXT"),
        ("fit_report", "TEXT DEFAULT '{}'"), ("fit_at", "TEXT"),
    ]:
        if name not in jcols:
            c.execute(f"ALTER TABLE jobs ADD COLUMN {name} {ddl}")
    c.execute("UPDATE jobs SET first_seen_at=COALESCE(first_seen_at, created_at),"
              " last_seen_at=COALESCE(last_seen_at, updated_at),"
              " last_change_at=COALESCE(last_change_at, updated_at)"
              " WHERE first_seen_at IS NULL OR last_seen_at IS NULL OR last_change_at IS NULL")

    rcols = {r["name"] for r in c.execute("PRAGMA table_info(resumes)")} if \
        c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='resumes'").fetchone() else set()
    if rcols and "pdf_pages" not in rcols:
        c.execute("ALTER TABLE resumes ADD COLUMN pdf_pages INTEGER")

    have = {r["name"] for r in c.execute("PRAGMA table_info(channels)")}
    for name, ddl in [
        ("state_note", "TEXT"),
        ("state_updated_at", "TEXT"),
        ("last_run_at", "TEXT"),
        ("next_check_at", "TEXT"),
        ("run_stats", "TEXT NOT NULL DEFAULT '{}'"),
    ]:
        if name not in have:
            c.execute(f"ALTER TABLE channels ADD COLUMN {name} {ddl}")


def seed_demo_data(c):
    """示例数据：填满页面用，带 is_demo=1，随时可一键清空。"""
    ts = now()
    days = lambda d: (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d %H:%M:%S")

    companies = [
        ("字节跳动", "互联网", "10000人以上", "已上市", "北京", "target"),
        ("蚂蚁集团", "金融科技", "10000人以上", "战略融资", "杭州", "researching"),
        ("米哈游", "游戏", "5000-10000人", "不需要融资", "上海", "target"),
        ("Shein", "跨境电商", "10000人以上", "已上市", "广州", "new"),
        ("某 AIGC 初创", "人工智能", "20-99人", "A轮", "深圳", "new"),
    ]
    cid = {}
    for name, ind, scale, stage, city, st in companies:
        cur = c.execute(
            "INSERT INTO companies(name,name_norm,industry,scale,stage,city,state,is_demo,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,1,?,?)",
            (name, norm_name(name), ind, scale, stage, city, st, ts, ts),
        )
        cid[name] = cur.lastrowid

    contacts = [
        ("李萌", "hr", "字节跳动", "招聘 HR", "limeng_hr", "new", "liepin", None),
        ("王强", "headhunter", "米哈游", "猎头顾问 · 游戏向", "wq_hunter", "contacted", "linkedin", days(6)),
        ("Amy Chen", "headhunter", "Shein", "Senior Recruiter", "amychen", "replied", "x", days(2)),
        ("张晓", "referral", "蚂蚁集团", "内部员工（内推）", "zhangxiao_mt", "following", "maimai", days(1)),
        ("周宇", "interviewer", "米哈游", "技术负责人", "zhouyu_mhy", "new", "wechat_mp", None),
    ]
    ctid = {}
    for name, typ, comp, title, wechat, st, ch, last in contacts:
        cur = c.execute(
            "INSERT INTO contacts(name,type,company_id,company_name,title,wechat,channel_code,state,"
            "last_contact_at,is_demo,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,1,?,?)",
            (name, typ, cid[comp], comp, title, wechat, ch, st, last, ts, ts),
        )
        ctid[name] = cur.lastrowid

    jobs = [
        ("boss", "b-88231", "高级前端工程师", "字节跳动", "30-55K·15薪", 30000, 55000, 15, "北京", "海淀区",
         "applied", 1, "limeng_hr", "hr", days(9), days(3),
         "负责抖音电商 C 端页面架构与性能优化。"),
        ("liepin", "l-100293", "资深 Node.js 后端", "蚂蚁集团", "35-60K·16薪", 35000, 60000, 16, "杭州", "西湖区",
         "interviewing", 1, "张晓", "referral", days(14), days(1),
         "负责支付中台 Node 服务，熟悉微服务治理。"),
        ("linkedin", "li-7741203", "Senior Full-Stack Engineer", "Shein", "$90k-130k", None, None, None, "广州", None,
         "shortlisted", 2, "Amy Chen", "headhunter", days(6), days(2),
         "React + Python, cross-border e-commerce platform."),
        ("maimai", "mm-556201", "游戏后端开发（Go）", "米哈游", "40-70K·14薪", 40000, 70000, 14, "上海", "徐汇区",
         "new", 2, "王强", "headhunter", days(2), days(2),
         "熟悉 Go / Redis / 分布式，有 MMORPG 经验优先。"),
        ("xiaohongshu", "xhs-9912", "AI 应用工程师（LLM）", "某 AIGC 初创", "25-45K", 25000, 45000, None, "深圳", "南山区",
         "new", 2, None, None, days(1), days(1),
         "小红书笔记来源：招聘帖，前端 React + LLM Agent 落地。"),
        ("wechat_mp", "wx-20241119-a7", "技术专家（大模型平台）", "字节跳动", "面议", None, None, None, "北京", None,
         "new", 3, None, None, days(4), days(4),
         "公众号「字节跳动招聘」推送岗位。"),
        ("x", "x-1880234", "Remote React Engineer", "Shein", "Negotiable", None, None, None, "远程", None,
         "rejected", 3, "Amy Chen", "headhunter", days(20), days(15),
         "Remote-friendly role posted on X."),
    ]
    for (ch, sid, title, comp, sal, smin, smax, months, city, dist, st, prio,
         pub, ptype, posted, collected, desc) in jobs:
        c.execute(
            "INSERT INTO jobs(channel_code,source_job_id,fingerprint,title,company_id,company_name,"
            "salary_raw,salary_min,salary_max,salary_months,city,district,description,"
            "publisher_name,publisher_type,posted_at,collected_at,state,priority,"
            "contact_id,is_demo,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
            (ch, sid, f"{ch}:{sid}", title, cid[comp], comp, sal, smin, smax, months, city, dist, desc,
             pub, ptype, posted, collected, st, prio,
             ctid.get(pub), ts, ts),
        )
    log(c, "system", "seed.demo", detail=f"{len(jobs)} 个示例岗位")
    # 示例数据的生命周期字段：首次发现按投递时间算，让「在招xx天」有真实感
    c.execute("UPDATE jobs SET first_seen_at=COALESCE(first_seen_at, posted_at, created_at),"
              " last_seen_at=COALESCE(last_seen_at, created_at),"
              " last_change_at=COALESCE(last_change_at, created_at),"
              " seen_count=COALESCE(seen_count, 3) WHERE is_demo=1")
