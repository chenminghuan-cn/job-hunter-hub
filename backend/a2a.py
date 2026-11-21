"""A2A 接入层：agent card + JSON-RPC(message/send) + HMAC 签名 + 按 agent 划分工具权限。

签名规范（每次请求都要带，各自用自己的 secret）：
  canonical = agent_id + "\\n" + timestamp + "\\n" + nonce + "\\n" + sha256_hex(raw_body)
  X-Signature = hex(hmac_sha256(secret, canonical))
Header：X-Agent-Id / X-Timestamp（秒）/ X-Nonce / X-Signature
容错：时间窗 300s，nonce 5 分钟内不可重复（防重放）。
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid

import service
from db import log, now, set_current_agent
from state import TransitionError, meta

TOLERANCE = 300  # 秒


class A2AError(Exception):
    def __init__(self, code, message, data=None):
        self.code = code
        self.message = message
        self.data = data


# ---------------------------------------------------------------- 签名
def verify(c, headers, body: bytes):
    headers = {k.lower(): v for k, v in headers.items()}  # dict / Starlette Headers 都能吃
    agent_id = headers.get("x-agent-id")
    ts = headers.get("x-timestamp")
    nonce = headers.get("x-nonce")
    sig = headers.get("x-signature")
    if not all([agent_id, ts, nonce, sig]):
        raise A2AError(-32001, "缺少签名头 X-Agent-Id/X-Timestamp/X-Nonce/X-Signature")
    row = c.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
    if not row:
        raise A2AError(-32001, "未知 agent")
    if not row["active"]:
        raise A2AError(-32001, "agent 已被禁用")
    try:
        drift = abs(time.time() - float(ts))
    except ValueError:
        raise A2AError(-32001, "X-Timestamp 非法")
    if drift > TOLERANCE:
        raise A2AError(-32001, f"时间戳偏差 {int(drift)}s 超过 {TOLERANCE}s")
    canonical = "\n".join([agent_id, ts, nonce, hashlib.sha256(body).hexdigest()])
    expected = hmac.new(row["secret"].encode(), canonical.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig.lower()):
        raise A2AError(-32001, "签名不匹配")
    try:
        c.execute("INSERT INTO nonces(agent_id,nonce,ts) VALUES (?,?,?)", (agent_id, nonce, time.time()))
    except Exception:
        raise A2AError(-32001, "nonce 重复（疑似重放）")
    c.execute("DELETE FROM nonces WHERE ts < ?", (time.time() - 3600,))
    c.execute("UPDATE agents SET last_seen_at=?, call_count=call_count+1 WHERE id=?", (now(), agent_id))
    return dict(row)


def scopes_of(agent) -> set:
    return {s.strip() for s in (agent.get("scopes") or "").split(",") if s.strip()}


# ---------------------------------------------------------------- 工具
def _t(scope, desc, params, fn, ret=None):
    return {"scope": scope, "description": desc, "params": params, "fn": fn, "returns": ret}


def _batch(c, items, actor, fn, key="job"):
    """批量写：单条失败不拖垮整批，逐条回报错误。"""
    if items is None:
        raise A2AError(-32602, "缺少待写入数据")
    if isinstance(items, dict):
        items = [items]
    created, updated, errors, ids = 0, 0, [], []
    for it in items:
        try:
            r = fn(c, dict(it), actor)
            ids.append(r[key]["id"])
            created += 1 if r["created"] else 0
            updated += 0 if r["created"] else 1
        except Exception as e:
            errors.append({"item": it.get("title") or it.get("name") or it.get("company_name"),
                           "error": str(e)})
    return {"created": created, "updated": updated, "ids": ids, "errors": errors}


def _jobs_payload(args):
    return args.get("jobs") if "jobs" in args else ([args] if args.get("title") else None)


def _upsert_jobs(c, args, actor):
    ch = args.get("channel")
    items = _jobs_payload(args) or []
    items = [it | {"channel": it.get("channel") or it.get("channel_code") or ch} for it in items]
    return _batch(c, items, actor, service.upsert_job)


def _upsert_companies(c, args, actor):
    items = args.get("companies") if "companies" in args else ([args] if args.get("name") else None)
    return _batch(c, items, actor, service.upsert_company, key="company")


TOOLS = {
    "stats.dashboard": _t("stats:read", "看板汇总：岗位各状态/在招分布、平均在招天数、待办数、渠道状态", {},
                          lambda c, a: service.dashboard(c)),

    "activity.list": _t("stats:read", "中台流水（谁在什么时候改了哪个对象）", {"limit": "int=50", "entity": "str 可选"},
                        lambda c, a: service.activity(c, int(a.get("limit") or 50), a.get("entity"))),

    "job.list": _t("job:read", "查岗位。返回项里带 tags / presence / open_days（在招天数）/ att_count（附件数）", {
        "q": "str 标题/公司/描述模糊", "channel": "str 渠道 code", "state": "str 工作流状态",
        "city": "str", "tag": "str 标签精确匹配", "presence": "open|stale|gone",
        "page": "int=1", "page_size": "int<=100", "sort": "created_at|updated_at|first_seen_at|priority|match_score"},
        lambda c, a: service.list_jobs(
            c, a.get("q"), a.get("channel"), a.get("state"), a.get("city"),
            a.get("company_id"), int(a.get("page") or 1), int(a.get("page_size") or 20),
            a.get("sort") or "created_at", a.get("tag"), a.get("presence")),
        ret="{items:[{id,title,company_name,salary_raw,city,url,description,requirements,tags,state,"
            "presence,open_days,first_seen_at,last_seen_at,seen_count,att_count}], total}"),

    "job.get": _t("job:read", "单个岗位详情（含 attachments 附件列表、生命周期字段）", {"id": "int"},
                  lambda c, a: service.get_job(c, int(a["id"]))),

    "job.upsert": _t("job:write",
        "幂等入库岗位，可批量。幂等键 = channel + source_job_id（没有则用 title+company+city 的哈希）。"
        "重复上报只更新不新增；tags 传数组即替换，不传则保留；"
        "在招状态/时长/首次发现时间不要传，服务端按上报历史自己算",
        {"jobs": "array 单条结构见 example_arguments；也可只传顶层一条",
         "channel": "str 渠道 code（必填，也可写 channel_code）", "source_job_id": "str 渠道内岗位 ID",
         "title": "str 必填", "company_name": "str 公司（不存在会自动建档）",
         "salary_raw": "str 原文如 30-55K·15薪，服务端解析", "salary_min": "int 可选",
         "salary_max": "int 可选", "salary_months": "int 可选",
         "city": "str", "district": "str", "employment_type": "str",
         "experience_req": "str 如 5-10年", "education_req": "str 如 本科及以上",
         "description": "str 岗位描述", "requirements": "str 任职要求",
         "url": "str 详情页地址（核心岗务必给）", "publisher_name": "str 发布人",
         "publisher_type": "hr|headhunter|employee|official|unknown",
         "posted_at": "str 发布时间", "match_score": "float 0-100", "priority": "int 1高|2中|3低",
         "tags": "array 如 [\"核心岗\"]", "extra": "object 渠道特有字段", "raw": "object 原始响应"},
        lambda c, a: _upsert_jobs(c, a, "agent"),
        ret="{created, updated, ids:[job_id], errors:[{item,error}]}；单条失败不影响整批，"
            "created=false 表示命中已有岗位（可能只是重复上报）"),

    "job.update": _t("job:write", "改岗位字段（不含状态；状态走 job.set_state）",
                     {"id": "int", "其余": "同 job.upsert 的字段，传了才改"},
                     lambda c, a: service.update_job(c, int(a["id"]), {k: v for k, v in a.items() if k != "id"}, "agent")),

    "job.sync_company": _t("job:write",
        "整家公司在某个渠道的「全量在招清单」。逐条幂等 upsert 后，把该渠道该公司不在清单里的在招岗位判为下架"
        "（gone_reason=company_sync）。分页只抓了一半时传 complete=false，就不会误杀",
        {"channel": "str 渠道 code", "company_name": "str 公司名（必填，决定判定范围）",
         "jobs": "array 同 job.upsert 单条结构", "complete": "bool 默认 true：是否代表该公司此刻的全部岗位",
         "reason": "str 可选，记在流水里"},
        lambda c, a: service.sync_company(c, a, "agent"),
        ret="{created, updated, ids:[job_id], gone_count, gone:[job_id], errors[]}"),

    "job.mark_gone": _t("job:write",
        "单个岗位下架：详情页 404 / 被删 / 停止招聘。之后若 upsert 又采到，会自动复招在同一行",
        {"id": "int（或 fingerprint，或 channel + source_job_id 组合定位）",
         "reason": "detail_404 | removed | other", "note": "str 可选，写进备注",
         "force": "bool 已经是 gone 时是否再处理一次"},
        lambda c, a: service.mark_gone(c, a, "agent"),
        ret="{changed, job:{presence,gone_reason,closed_at,open_days}}"),

    "job.add_attachment": _t("job:write",
        "上传 JD 截图 / 海报。同一岗位「只保留最新 1 张截图」，新图会顶掉旧图（连文件一起删）；"
        "同一张图（sha256 相同）不会重复存；状态为 rejected / archived 的岗位直接拒收",
        {"id": "int（或 channel + source_job_id 组合定位）", "filename": "str 文件名",
         "data_base64": "str 图片 base64，可带 data:image/png;base64, 前缀",
         "url": "str 公网可访问的图片地址，中台自己下载（与 data_base64 二选一）",
         "caption": "str 图片说明，如「BOSS 详情页截图」"},
        lambda c, a: _add_attachment(c, a),
        ret="{created, pruned:本次删掉几张旧图, attachment:{id,filename,mime,size,rel_path}}；"
            "created=false 表示这张图已存在"),

    "job.set_state": _t("job:state",
                        "推进岗位工作流状态（new→shortlisted→applied→interviewing→offer…），按状态机校验",
                        {"id": "int", "state": "str 目标状态",
                         "note": "str 为什么这么改，会写进操作日志（预审 Agent 必填）"},
                        lambda c, a: service.set_job_state(c, int(a["id"]), a["state"], "agent",
                                                          a.get("note")),
                        ret="job 对象；不允许的跳转返回 -32004 并列出可选状态"),

    "job.delete": _t("job:write", "物理删除岗位（连附件）。清理误采才用，正常下架请用 job.mark_gone / job.sync_company",
                     {"id": "int"}, lambda c, a: (service.delete_job(c, int(a["id"]), "agent"), {"deleted": int(a["id"])})[1]),

    "company.list": _t("company:read", "公司列表（带 job_count / contact_count / tags）", {
        "q": "str", "state": "str", "page": "int", "page_size": "int"},
        lambda c, a: service.list_companies(c, a.get("q"), a.get("state"),
                                            int(a.get("page") or 1), int(a.get("page_size") or 20))),

    "company.upsert": _t("company:write", "新增/更新公司。按公司名去空格小写去重；公司标签也在这传",
        {"companies": "array 或直接传一条", "name": "str 必填", "industry": "str",
         "scale": "str 如 500-2000人", "stage": "str 融资阶段", "city": "str", "website": "str",
         "tags": "array 如 [\"目标公司\"]", "notes": "str"},
        lambda c, a: _upsert_companies(c, a, "agent"),
        ret="{created, updated, ids:[company_id], errors[]}"),

    "company.set_state": _t("company:state", "推进公司状态（new→researching→target / blacklisted）",
                            {"id": "int", "state": "str", "note": "str 为什么这么改（写进日志）"}, 
                            lambda c, a: service.set_company_state(c, int(a["id"]), a["state"], "agent",
                                                                    a.get("note"))),

    "contact.list": _t("contact:read", "联系人列表（HR / 猎头 / 内推 / 面试官）",
                       {"q": "str", "type": "hr|headhunter|referral|interviewer|other",
                        "state": "str", "company_id": "int", "page": "int", "page_size": "int"},
                       lambda c, a: service.list_contacts(c, a.get("q"), a.get("type"), a.get("state"),
                                                          a.get("company_id"), int(a.get("page") or 1),
                                                          int(a.get("page_size") or 20))),

    "contact.upsert": _t("contact:write", "新增/更新联系人（按 姓名+公司+类型 去重）", {
        "name": "str 必填", "type": "hr|headhunter|referral|interviewer|other",
        "company_name": "str（公司不存在会自动建档）", "title": "str 职位",
        "wechat": "str", "phone": "str", "email": "str", "profile_url": "str 名片/主页链接",
        "channel_code": "str 来源渠道", "tags": "array", "notes": "str 沟通记录"},
        lambda c, a: service.upsert_contact(c, dict(a), "agent"),
        ret="{created, contact:{id,name,state,company_name,...}}"),

    "contact.set_state": _t("contact:state", "推进联系人状态（new→contacted→replied→following→closed / cold）",
                            {"id": "int", "state": "str", "note": "str 为什么这么改（写进日志）"},
                            lambda c, a: service.set_contact_state(c, int(a["id"]), a["state"], "agent",
                                                                   a.get("note"))),

    "channel.list": _t("channel:read", "信息源列表：状态、上次运行、下次计划、运行统计、配置",
                       {}, lambda c, a: service.list_channels(c)),

    "channel.get": _t("channel:read", "单个信息源详情（采不采之前先看 state）", {"code": "str"},
                      lambda c, a: service.get_channel(c, a["code"])),

    "channel.set_state": _t("channel:state",
        "上报信息源状态。需要人工介入时用 need_verify（滑块/短信）或 login_expired（登录失效），"
        "本人处理完会改回 active；paused/disabled 是本人主动停的，不要自己改回来",
        {"code": "str", "state": "active|need_verify|login_expired|degraded|paused|disabled",
         "note": "str 一句话原因，会显示在页面上", "evidence_url": "str 可选截图/链接"},
        lambda c, a: service.update_channel(c, a.pop("code"), {
            "state": a.get("state"),
            "state_note": a.get("note") or a.get("state_note")}, "agent"),
        ret="channel 对象；非法跳转返回 -32004"),

    "channel.report": _t("channel:state",
        "上报一次采集运行：状态 + 游标 + 本轮统计 + 下次计划（一次调用同时更新状态与运行信息）",
        {"code": "str 必填",
         "state": "str 可选，等价于 channel.set_state",
         "note": "str 可选，给人看的原因",
         "run": "{started_at, finished_at, scraped, created, updated, duplicates, errors:[{url,reason}]}",
         "cursor": "object 游标，如 {page:3,last_keyword:\"前端\"}",
         "next_check_at": "str 下次计划时间", "credentials_expire_at": "str 登录态过期时间",
         "device": "str 采集机标识"},
        lambda c, a: service.report_channel(c, a, "agent"),
        ret="channel 对象（含 state / state_note / last_run_at / next_check_at / run_stats）"),

    "channel.update": _t("channel:write", "改信息源配置（关键词/城市/频控等），不改状态",
                         {"code": "str", "config": "object", "note": "str"},
                         lambda c, a: service.update_channel(c, a.pop("code"), a, "agent")),

    "job.review": _t("job:review",
        "预审：标标签 / 分优先级 / 写匹配度 / 修正 JD 正文，并可同时推进工作流状态。"
        "不碰采集侧原始字段（标题/公司/薪资/链接）",
        {"id": "int 必填", "tags": "array 整份替换，如 [\"核心岗\",\"外企\"]",
         "priority": "int 1高|2中|3低", "match_score": "float 0-100",
         "notes": "str 预审结论", "description": "str 修正后的岗位描述",
         "requirements": "str 修正后的任职要求",
         "state": "str 可选，同时推进状态",
         "note": "str 一句话说明为什么这么预审/改状态（写进操作日志，强烈建议填）"},
        lambda c, a: service.review_job(c, a, "agent"),
        ret="job 对象（含 tags / priority / state / open_days）"),

    "job.fit": _t("job:review",
        "写 JD 匹配评估（按 job-match 技能的口径）：结论 + 一句话理由 + 要求-证据矩阵 + 硬门槛 + 补强建议。"
        "每个岗位都应该有一条，没有证据的要求写 status=unknown，不要编",
        {"id": "int 必填",
         "verdict": "apply 建议投递 | apply_after_gap 补充材料后投递 | cautious 谨慎投递 | skip 暂不建议",
         "reason": "str 一句话结论 + 最关键原因（会显示在列表和详情）",
         "requirements": "array [{req 要求原文, importance must|core|plus, evidence 我的哪段经历/作品, "
                         "status matched|phrasing_gap|insufficient|real_gap|unknown, risk 风险或下一步}]",
         "hard_gates": "array [{item 学历/年限/地点等门槛, status pass|fail|unknown, note}]",
         "gaps": "array [{type phrasing|evidence|skill, item, action}]",
         "strategy": "object {resume_version, 建议话术, confirm[] 待确认问题}",
         "source": "str 可选，技能/版本标识"},
        lambda c, a: service.set_job_fit(c, a, "agent"),
        ret="job 对象（含 fit_verdict / fit_reason / fit_report）"),

    "resume.submit": _t("job:review",
        "提交一份针对某个岗位定制的简历：html 里用 <mark> 包住改动过的句子（浏览时高亮），"
        "中台会自动去掉 mark 生成干净 PDF。文件名按 陈明欢_岗位方向_公司_YYYYMMDD 规范",
        {"job_id": "int 可选，关联岗位",
         "role": "str 岗位方向，如 AI 应用工程师",
         "company": "str 公司简称",
         "html": "str 完整 HTML 简历（A4 友好，内联 CSS；改动处用 <mark data-why=\"原因\">..</mark>）",
         "changes": "array [{where 位置, before 原文, after 现在, why 为什么改}]",
         "filename": "str 可选，不给就按规范自动命名"},
        lambda c, a: service.create_resume(c, a, "agent"),
        ret="{created, pdf: 是否成功生成 PDF, resume:{id, filename, pdf_url, changes}}"),

    "resume.list": _t("job:review", "看已提交的简历版本（只给元信息，不含 html）", {"job_id": "int 可选"},
                     lambda c, a: service.list_resumes(c, a.get("job_id"))),

    "resume.get": _t("job:review", "取某一版的完整 HTML，可以在它的基础上改而不是从零重写",
        {"id": "int 必填", "include_pdf": "bool 默认 false，true 时附带 PDF 的 base64"},
        lambda c, a: service.get_resume(c, int(a["id"]), include_html=True,
                                        include_pdf=bool(a.get("include_pdf")))),

    "resume.diff": _t("job:review", "版本 diff：默认和同岗位的上一版比，返回 unified diff 与两侧 changes",
        {"id": "int 新版", "base_id": "int 可选，指定老版本"},
        lambda c, a: service.diff_resumes(c, int(a["id"]),
                                          int(a["base_id"]) if a.get("base_id") else None)),

    "resume.source": _t("job:review",
        "读基准简历（本人原始简历 HTML）。改简历必须以它为事实边界，不要凭记忆编",
        {}, lambda c, a: service.get_resume_source(c, _resume_path(c))),

    "job.attachment.get": _t("job:read", "拿附件内容（base64）做多模态解析；默认最多 3 个、单个 3MB",
        {"job_id": "int 必填（也可写 id）", "attachment_id": "int 可选，只要一个"},
        lambda c, a: service.read_attachments(c, a),
        ret="{job_id, count, attachments:[{id,filename,mime,size,data_base64}]}"),

    "report.submit": _t("",
        "向中台提诉求/建议/问题（任何 Agent 都能提）。例如：某渠道薪资数据偏低、建议采集侧加最低薪资过滤；"
        "或请求本人开通权限。中台管理 Agent 会处理这些单子",
        {"title": "str 必填，一句话说清诉求",
         "kind": "suggestion|issue|data_quality|question",
         "content": "str 详细说明 + 你的建议",
         "severity": "low|normal|high",
         "target": "str 可选，指向对象：channel:boss / agent:collector-liepin / job:123"},
        lambda c, a: service.create_report(c, (a.get("_agent_row") or {}).get("id"), a),
        ret="{id, status:'open', ...}"),

    "report.list": _t("",
        "看诉求单。不传参只看你自己的；看全部或改别人的需要 agent:write",
        {"status": "open|accepted|rejected|done", "agent_id": "str 可选（需 agent:write）",
         "all": "bool 可选，true 看全部（需 agent:write）"},
        lambda c, a: _report_list(c, a)),

    "report.update": _t("agent:write",
        "管理 Agent 用：处理诉求单（接单/驳回/结单）并写回复",
        {"id": "int 必填", "status": "accepted|rejected|done|open",
         "response": "str 处理说明，会显示给提交方", "severity": "str 可选"},
        lambda c, a: service.update_report(c, int(a["id"]), a, "agent"),
        ret="report 对象"),

    "agent.config.get": _t("", "读自己的任务提示词与配置；带 agent_id 读别人需要 agent:write", {
        "agent_id": "str 可选，不传就是自己"}, lambda c, a: _agent_config_get(c, a)),
    "agent.config.set": _t("agent:write", "管理 Agent 用：改任意 Agent 的任务提示词 / 配置 / 权限 / 启用状态", {
        "agent_id": "str 必填", "prompt": "str 任务描述提示词（整段替换）",
        "config": "object 或 JSON 字符串（整份替换）",
        "scopes": "array 可选，改权限", "active": "bool 可选", "remark": "str 可选"},
        lambda c, a: _agent_config_set(c, a)),
    "agent.list": _t("agent:write", "管理 Agent 用：所有 Agent 的 id/权限/提示词/配置/运行状态", {},
                     lambda c, a: [_public_agent(x) for x in service.agents(c)]),

    "agent.capabilities": _t("", "工具书：返回你的身份、权限、能调用的工具、参数、返回结构、全局约定与状态机。功能更新后重新调一次即可",
        {"verbose": "bool 默认 false，true 返回全部参数与示例",
         "tool": "str 只看某个工具的完整说明（含 example_arguments）"},
        lambda c, a: _capabilities(a.get("_agent_row") or {}, a.get("_base_url"),
                                   bool(a.get("verbose")), a.get("tool"))),
}

def _resume_path(c):
    try:
        row = c.execute("SELECT config FROM agents WHERE id='analyst'").fetchone()
        cfg = json.loads(row["config"] or "{}") if row else {}
        return (cfg.get("profile") or {}).get("resume_path")
    except Exception:
        return None


def _report_list(c, a):
    me = a.get("_agent_row") or {}
    want_all = bool(a.get("all")) or bool(a.get("agent_id"))
    if want_all and "agent:write" not in scopes_of(me):
        # 没管理权限就只能看自己的
        return service.list_reports(c, a.get("status"), me.get("id"))
    return service.list_reports(c, a.get("status"), a.get("agent_id"))


def _public_agent(d):
    return {k: d.get(k) for k in ("id", "name", "kind", "scopes", "active", "prompt",
                                  "config", "call_count", "last_seen_at", "remark")}


def _agent_config_get(c, a):
    me = a.get("_agent_row") or {}
    target = a.get("agent_id")
    if target and target != me.get("id"):
        if "agent:write" not in scopes_of(me):
            raise A2AError(-32003, "读别的 Agent 的配置需要 agent:write", {"has": sorted(scopes_of(me))})
    row = service.get_agent(c, target or me.get("id"))
    if not row:
        raise KeyError("agent 不存在")
    return _public_agent(row)


def _agent_config_set(c, a):
    aid = a.get("agent_id") or a.get("id")
    if not aid:
        raise ValueError("agent_id 必填")
    fields = {k: a[k] for k in ("prompt", "config", "scopes", "active", "remark", "name", "kind")
              if k in a}
    if not fields:
        raise ValueError("没有要改的字段（prompt / config / scopes / active / remark）")
    return _public_agent(service.update_agent(c, aid, fields, "agent"))


def _add_attachment(c, a):
    jid = a.get("id") or a.get("job_id")
    if not jid:
        if not (a.get("channel") and a.get("source_job_id")):
            raise ValueError("需要 id，或 channel + source_job_id")
        row = c.execute("SELECT id FROM jobs WHERE channel_code=? AND source_job_id=?",
                        (a["channel"], str(a["source_job_id"]))).fetchone()
        if not row:
            raise KeyError(f"岗位不存在：{a['source_job_id']}")
        jid = row["id"]
    raw = a.get("data_base64") or a.get("data")
    data = base64.b64decode(raw.split(",")[-1]) if raw else None
    if data is None and not a.get("url"):
        raise ValueError("需要 data_base64 或 url")
    return service.save_attachment(c, int(jid), data, a.get("filename") or "",
                                   a.get("mime"), a.get("url"), a.get("caption"), "agent")


def _call(c, agent, tool, args, base_url=None):
    spec = TOOLS.get(tool)
    if not spec:
        raise A2AError(-32601, f"未知工具 {tool}", {"available": sorted(TOOLS)})
    if spec["scope"] and spec["scope"] not in scopes_of(agent):
        raise A2AError(-32003, f"agent 缺少权限 {spec['scope']}",
                       {"required": spec["scope"], "has": sorted(scopes_of(agent)),
                        "hint": "需要本人在「连接设置」里给这个 Agent 勾上对应权限，agent 自己无法提权，也不要重试"})
    if tool.startswith("agent.") or tool.startswith("report."):
        args["_agent_row"] = agent
        args["_base_url"] = base_url
    try:
        result = spec["fn"](c, dict(args or {}))
    except A2AError:
        raise
    except TransitionError as e:
        raise A2AError(-32004, str(e), {"from": e.args, "hint": "状态机不允许这步跳转"})
    except KeyError as e:
        raise A2AError(-32002, f"未找到：{e}")
    except Exception as e:
        raise A2AError(-32000, f"{type(e).__name__}: {e}")
    return {"tool": tool, "result": result}


CONVENTIONS = [
    "幂等键：channel + source_job_id（没有则 title+company+city 的哈希）。重复上报只更新，不会新增。",
    "在招生命周期由服务端算：first_seen_at / last_seen_at / seen_count / open_days / presence(open|stale|gone)。"
    "不要上报这些，也不要自己判断在招时长。",
    "整家公司批量抓完后用 job.sync_company + complete=true：清单里没有的在招岗位会被判下架；"
    "分页只抓一半就传 complete=false。",
    "详情页 404 / 岗位被删：用 job.mark_gone，不要用 job.delete。之后又采到会自动复招。",
    "截图只保留最新一张：同一岗位再传新图会顶掉旧图（返回 pruned），所以反复重截不会占空间。",
    "状态为 rejected / archived 的岗位已明确不要：不要给它传附件，服务端会拒收。",
    "tags 是数组，传了就整体替换；不传则保持原样。公司的标签走 company.upsert。",
    "状态只能走状态机允许的下一步，非法跳转返回 -32004，返回体里带可选状态，不要硬试。",
    "缺权限返回 -32003：不要重试、不要试图提权，等本人到「连接设置」开通。",
    "出站请求请设置正常 User-Agent（Cloudflare 会拦 Python-urllib 默认 UA，返回 error 1010）。",
    "开跑前先看自己的任务提示词与配置：agent.capabilities 回包里的 you.prompt / you.config"
    "（也可单独调 agent.config.get）。本人或管理 Agent 会改这两项来调整你的行为，不要硬编码。",
    "每个渠道的抓取意图（关键词 / 圈子 / 城市 / 频控 / 过滤规则 / 用哪个字段当 source_job_id）"
    "放在 channel.config 里：开跑前先 channel.get 读它，别自己猜；没配就按你的判断来。",
    "每个进到 shortlisted 的岗位都应该有一条 job.fit 评估（结论 + 为什么 + 要求逐条对照），"
    "没有证据的要求标 unknown，不要为了好看编；不要输出伪精确的百分比分数。",
    "改简历前先调 resume.source 读基准简历（本人原始简历），事实以它为准；"
    "要迭代就 resume.get 拿上一版 HTML 再改，改完 resume.submit，用 resume.diff 自查差异。",
    "有困难或建议用 report.submit 提诉求（如某渠道薪资数据偏低、建议加最低薪资过滤），"
    "别自己去改别人的配置；中台管理 Agent 会处理。"
    "预审（打标签 / 分优先级 / 修正 JD / 推进状态）用 job.review，它不碰采集侧原始字段。",
    "什么时候采集、采什么内容由你判断；中台只负责存储、状态和口径。",
]

CHANNEL_REPORT_SCHEMA = {
    "code": "渠道 code，必填",
    "state": "可选，等同于 channel.set_state（active/need_verify/login_expired/degraded/paused/disabled）",
    "note": "可选，给本人看的一句话原因，例如「滑块连续失败 3 次」",
    "run": {
        "started_at": "2026-11-21 09:00:00",
        "finished_at": "2026-11-21 09:04:12",
        "scraped": 120, "created": 8, "updated": 3, "duplicates": 109,
        "errors": [{"url": "https://...", "reason": "timeout"}],
    },
    "cursor": {"page": 3, "last_keyword": "前端"},
    "next_check_at": "2026-11-21 13:00:00",
    "credentials_expire_at": "2026-12-01 00:00:00",
    "device": "home-pc-01",
}


def _as_json(v):
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v or "{}")
    except Exception:
        return {}


def _capabilities(agent_row, base_url, verbose=False, tool=None):
    """唯一的自描述接口：agent 靠签名确定身份，然后拿到自己那一份能力清单。"""
    mine = scopes_of(agent_row)
    base = (base_url or "").rstrip("/")
    allowed = {k: v for k, v in TOOLS.items() if not v["scope"] or v["scope"] in mine}
    denied = sorted(k for k, v in TOOLS.items() if v["scope"] and v["scope"] not in mine)

    if tool:
        spec = TOOLS.get(tool)
        if not spec:
            raise KeyError(f"未知工具 {tool}")
        if tool in denied:
            raise A2AError(-32003, f"你没有 {tool} 的权限（需要 {spec['scope']}）")
        out = {"tool": tool, "description": spec["description"],
               "required_scope": spec["scope"] or None, "params": spec["params"],
               "returns": spec.get("returns")}
        if tool == "channel.report":
            out["example_arguments"] = CHANNEL_REPORT_SCHEMA
        if tool == "job.sync_company":
            out["example_arguments"] = {
                "channel": "liepin", "company_name": "某公司", "complete": True,
                "jobs": [{"source_job_id": "l-1", "title": "高级前端工程师",
                          "salary_raw": "30-55K·15薪", "city": "上海",
                          "url": "https://www.liepin.com/job/xxx", "tags": ["核心岗"]}],
                "note": "该公司在猎聘的在招岗位全量；不在列表里的会被判下架"}
        if tool == "job.add_attachment":
            out["example_arguments"] = {"channel": "liepin", "source_job_id": "l-1",
                                        "filename": "jd.png", "caption": "JD 截图",
                                        "url": "https://example.com/jd.png"}
        if tool == "job.mark_gone":
            out["example_arguments"] = {"channel": "liepin", "source_job_id": "l-1",
                                        "reason": "detail_404", "note": "详情页已 404"}
        if tool == "job.upsert":
            out["example_arguments"] = {"jobs": [{
                "channel": "liepin", "source_job_id": "l-100293", "title": "高级前端工程师",
                "company_name": "某公司", "salary_raw": "30-55K·15薪", "city": "上海",
                "url": "https://...", "description": "...", "publisher_name": "李萌",
                "publisher_type": "hr", "extra": {"hunter": True}, "raw": {"任意": "原始响应"}}]}
        return out

    tools = []
    for name, spec in sorted(allowed.items()):
        item = {"name": name, "description": spec["description"]}
        if verbose:
            item["required_scope"] = spec["scope"] or None
            item["params"] = spec["params"]
            if spec.get("returns"):
                item["returns"] = spec["returns"]
        tools.append(item)

    out = {
        "you": {"agent_id": agent_row.get("id"), "name": agent_row.get("name"),
                "kind": agent_row.get("kind"), "scopes": sorted(mine),
                "prompt": agent_row.get("prompt") or None,
                "config": _as_json(agent_row.get("config"))},
        "endpoint": f"{base}/a2a" if base else "/a2a",
        "auth": {
            "algorithm": "HMAC-SHA256(secret, canonical) hex",
            "headers": ["X-Agent-Id", "X-Timestamp(秒)", "X-Nonce(随机且不复用)", "X-Signature"],
            "canonical": "agent_id + \"\\n\" + timestamp + \"\\n\" + nonce + \"\\n\" + sha256_hex(raw_body)",
            "tolerance_seconds": TOLERANCE,
        },
        "envelope": {"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {
            "message": {"role": "user", "parts": [
                {"kind": "data", "data": {"tool": "<工具名>", "arguments": {}}}]}}},
        "tools": tools,
        "denied_tools": denied,
        "conventions": CONVENTIONS,
        "hint": "tools 里只能看到你有权限的工具；verbose=true 看参数/返回/示例，tool=<名字> 看单个工具完整说明。"
                "denied_tools 需要本人在页面开通，agent 自己无法提权。",
        "error_codes": {"-32001": "签名/时间戳/nonce 问题", "-32002": "对象不存在",
                        "-32003": "缺权限", "-32004": "状态机不允许的跳转", "-32602": "参数问题"},
        "state_machines": {k: {s["value"]: {"label": s["label"], "next": s["next"]}
                               for s in v["states"]} for k, v in meta().items()},
    }
    if "channel:state" in mine:
        out["channel_report_schema"] = CHANNEL_REPORT_SCHEMA
    return out


# ---------------------------------------------------------------- JSON-RPC
def agent_card(base_url: str):
    skills = []
    for name, spec in sorted(TOOLS.items()):
        skills.append({
            "id": name.replace(".", "-"),
            "name": name,
            "description": spec["description"],
            "tags": ["recruit", name.split(".")[0]],
            "examples": [],
            "x-required-scope": spec["scope"],
            "x-params": spec["params"],
        })
    return {
        "protocolVersion": "0.2.6",
        "name": "Job Hunter Hub",
        "description": "个人应聘中台：岗位/公司/联系人/信息源 的采集与状态维护接口",
        "url": f"{base_url}/a2a",
        "version": "0.1.0",
        "preferredTransport": "JSONRPC",
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "securitySchemes": {
            "hmac": {"type": "apiKey", "in": "header",
                     "name": "X-Signature",
                     "description": "HMAC-SHA256(secret, agent_id\\ntimestamp\\nnonce\\nsha256(body))，"
                                    "配 X-Agent-Id / X-Timestamp / X-Nonce"}
        },
        "skills": skills,
    }


def _data_part(message):
    for p in (message or {}).get("parts") or []:
        if p.get("kind") in ("data", "application/json") and isinstance(p.get("data"), dict):
            return p["data"]
    raise A2AError(-32602, "message.parts 里需要一个 kind=data 的对象，形如 "
                           '{"tool":"job.upsert","arguments":{...}}')


def handle(c, agent, payload: dict, base_url: str | None = None):
    """处理一个 JSON-RPC 2.0 请求体。"""
    rid = payload.get("id")
    method = payload.get("method")
    if payload.get("jsonrpc") != "2.0" or not method:
        raise A2AError(-32600, "只支持 JSON-RPC 2.0")
    actor = f"agent:{agent['id']}"
    set_current_agent(actor)

    if method in ("message/send", "message/stream"):
        params = payload.get("params") or {}
        envelope = _data_part(params.get("message"))
        tool = envelope.get("tool")
        args = envelope.get("arguments") or envelope.get("args") or {}
        if not tool:
            raise A2AError(-32602, "缺少 tool")
        try:
            out = _call(c, agent, tool, args, base_url)
        finally:
            set_current_agent(None)
        task_id = (params.get("message") or {}).get("taskId") or uuid.uuid4().hex
        log(c, actor, f"a2a.{tool}", None, None, {"args": sorted(args)})
        return {
            "jsonrpc": "2.0", "id": rid,
            "result": {
                "task": {
                    "id": task_id,
                    "contextId": (params.get("message") or {}).get("contextId") or uuid.uuid4().hex,
                    "status": {"state": "completed", "timestamp": now()},
                    "artifacts": [{"artifactId": secrets.token_hex(8), "name": tool,
                                   "parts": [{"kind": "data", "data": out}]}],
                }
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "tools": [{"name": k, "description": v["description"],
                       "requiredScope": v["scope"], "params": v["params"],
                       "allowed": v["scope"] in scopes_of(agent)}
                      for k, v in sorted(TOOLS.items())]}}

    if method == "tasks/get":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "id": (payload.get("params") or {}).get("id"),
            "status": {"state": "completed"}, "note": "本服务同步返回，任务不入库"}}

    raise A2AError(-32601, f"不支持的方法 {method}", {"supported": ["message/send", "tools/list", "tasks/get"]})


def sign(agent_id: str, secret: str, body: bytes, ts=None, nonce=None):
    """给调用方/调试用的签名助手。"""
    ts = ts or str(int(time.time()))
    nonce = nonce or secrets.token_hex(8)
    canonical = "\n".join([agent_id, ts, nonce, hashlib.sha256(body).hexdigest()])
    sig = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return {"X-Agent-Id": agent_id, "X-Timestamp": ts, "X-Nonce": nonce, "X-Signature": sig}


__all__ = ["verify", "handle", "agent_card", "onboarding_text", "sign", "TOOLS", "A2AError"]
