"""最小自检：python test_smoke.py  （用临时库，不碰 data/recruit.db）

覆盖最容易悄悄坏掉的三件事：状态机、幂等入库、签名与权限。
"""
import base64
import json
import os
import pathlib
import sys
import tempfile

os.environ["RECRUIT_DB"] = str(pathlib.Path(tempfile.mkdtemp()) / "smoke.db")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import a2a  # noqa: E402
import db  # noqa: E402
import service  # noqa: E402
from state import check  # noqa: E402


def expect_err(fn, needle):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        assert needle in str(e), f"错误信息不符：{e}"
    else:
        raise AssertionError(f"应该报错但没有：{needle}")


def main():
    db.init(seed_demo=False)

    # 状态机：允许的能过，跳步必须被拒
    assert check("job", "new", "shortlisted") == "shortlisted"
    expect_err(lambda: check("job", "new", "offer"), "不允许")
    expect_err(lambda: check("contact", "new", "closed"), "不允许")
    assert check("channel", "degraded", "active") == "active"

    # 薪资解析
    assert service.parse_salary("30-55K·15薪") == (30000, 55000, 15)
    assert service.parse_salary("25-45K") == (25000, 45000, None)
    assert service.parse_salary("面议") == (None, None, None)

    with db.db() as c:
        # 幂等入库 + 公司自动建档
        a = service.upsert_job(c, {"channel": "boss", "source_job_id": "x1", "title": "FE",
                                   "company_name": "ACME", "salary_raw": "20-30K"}, "test")
        assert a["created"]
        b = service.upsert_job(c, {"channel": "boss", "source_job_id": "x1", "title": "FE2",
                                   "company_name": "ACME"}, "test")
        assert not b["created"] and b["job"]["title"] == "FE2"
        assert b["job"]["salary_min"] == 20000, "更新时不应抹掉已解析薪资"
        assert c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 1

        # 签名：正常 / 篡改 / 重放
        agent = dict(c.execute("SELECT * FROM agents WHERE id='collector-liepin'").fetchone())
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
        h = a2a.sign("collector-liepin", agent["secret"], body)
        assert a2a.verify(c, h, body)["id"] == "collector-liepin"
        bad = dict(h)
        bad["X-Signature"] = "0" * 64
        expect_err(lambda: a2a.verify(c, bad, body), "签名不匹配")
        h2 = a2a.sign("collector-liepin", agent["secret"], body, nonce="replay-1")
        a2a.verify(c, h2, body)
        expect_err(lambda: a2a.verify(c, h2, body), "重放")

        # 权限：采集 agent 不许改联系人状态
        payload = {"jsonrpc": "2.0", "id": 2, "method": "message/send", "params": {"message": {"parts": [
            {"kind": "data", "data": {"tool": "contact.set_state", "arguments": {"id": 1, "state": "contacted"}}}]}}}
        expect_err(lambda: a2a.handle(c, agent, payload), "缺少权限")

        # 采集 agent 可以批量写岗位，并拿到 task 结果
        payload2 = {"jsonrpc": "2.0", "id": 3, "method": "message/send", "params": {"message": {"parts": [
            {"kind": "data", "data": {"tool": "job.upsert", "arguments": {"jobs": [
                {"channel": "liepin", "source_job_id": "l9", "title": "BE", "company_name": "B"},
                {"channel": "nope", "title": "bad"}]}}}]}}}
        res = a2a.handle(c, agent, payload2)
        task = res["result"]["task"]
        assert task["status"]["state"] == "completed"
        out = task["artifacts"][0]["parts"][0]["data"]["result"]
        assert out["created"] == 1 and len(out["errors"]) == 1, out

        # 非法状态跳转（job:state 需要专门授权的 agent，采集 agent 本身就没有该 scope）
        keeper = dict(c.execute("SELECT * FROM agents WHERE id='state-keeper'").fetchone())
        payload3 = {"jsonrpc": "2.0", "id": 4, "method": "message/send", "params": {"message": {"parts": [
            {"kind": "data", "data": {"tool": "job.set_state",
                                      "arguments": {"id": under_test_job_id(c), "state": "offer"}}}]}}}
        expect_err(lambda: a2a.handle(c, keeper, payload3), "不允许")
        # 合规跳转能过
        payload4 = {"jsonrpc": "2.0", "id": 5, "method": "message/send", "params": {"message": {"parts": [
            {"kind": "data", "data": {"tool": "job.set_state",
                                      "arguments": {"id": under_test_job_id(c), "state": "shortlisted"}}}]}}}
        ok = a2a.handle(c, keeper, payload4)
        assert ok["result"]["task"]["status"]["state"] == "completed"

        # 信源状态 + 运行上报（service 层，绕开权限只验逻辑）
        ch = service.report_channel(c, {
            "code": "boss", "state": "need_verify", "note": "滑块失败 3 次",
            "run": {"started_at": "2026-11-21 09:00:00", "finished_at": "2026-11-21 09:04:12",
                    "scraped": 120, "created": 8, "updated": 3, "duplicates": 109,
                    "errors": [{"url": "u", "reason": "timeout"}]},
            "cursor": {"page": 3}, "next_check_at": "2026-11-21 13:00:00"}, "agent")
        assert ch["state"] == "need_verify" and ch["state_note"] == "滑块失败 3 次", ch
        assert ch["run_stats"]["last_run"]["created"] == 8
        assert ch["run_stats"]["cursor"] == {"page": 3}
        assert ch["next_check_at"] == "2026-11-21 13:00:00"
        # 人工处理完能回采集中，非法跳转仍被拦
        assert service.update_channel(c, "boss", {"state": "active"}, "ui")["state"] == "active"
        expect_err(lambda: service.update_channel(c, "disabled_never_set", {}), "渠道")

        # 自描述接口：只谈自己权限范围内的工具，且能按需展开
        cap = a2a._capabilities(agent, "https://x.example", False, None)
        names = {t["name"] for t in cap["tools"]}
        assert "job.upsert" in names and "contact.set_state" not in names
        assert "contact.set_state" in cap["denied_tools"]
        assert cap["you"]["agent_id"] == "collector-liepin"
        detail = a2a._capabilities(agent, "https://x.example", False, "job.upsert")
        assert detail["example_arguments"]["jobs"][0]["channel"] == "liepin"
        expect_err(lambda: a2a._capabilities(agent, "", False, "contact.set_state"), "没有")

        # --- 生命周期：幂等 + 在招时长 + 自动下架（都是服务端算的，Agent 不上报）---
        first = service.upsert_job(c, {"channel": "boss", "source_job_id": "life-1",
                                       "title": "T1", "company_name": "C", "salary_raw": "20-30K"}, "test")
        jid = first["job"]["id"]
        assert first["job"]["seen_count"] == 1 and first["job"]["presence"] == "open"
        assert first["job"]["first_seen_at"] and first["job"]["open_days"] == 0

        again = service.upsert_job(c, {"channel": "boss", "source_job_id": "life-1",
                                       "title": "T1", "company_name": "C", "salary_raw": "20-30K",
                                       "raw": {"views": 42}}, "test")
        assert again["created"] is False and again["changed"] is False
        assert again["job"]["seen_count"] == 2, "重复上报要累加观察次数"
        assert c.execute("SELECT COUNT(*) FROM jobs WHERE source_job_id='life-1'").fetchone()[0] == 1

        changed = service.upsert_job(c, {"channel": "boss", "source_job_id": "life-1",
                                         "title": "T1", "company_name": "C", "salary_raw": "25-35K"}, "test")
        assert changed["changed"] is True and changed["job"]["salary_raw"] == "25-35K"
        assert changed["job"]["seen_count"] == 3

        # 模拟时间流逝（直接改 last_seen_at，不用等）
        c.execute("UPDATE jobs SET first_seen_at=datetime('now','localtime','-10 day'),"
                  " last_seen_at=datetime('now','localtime','-10 day') WHERE id=?", (jid,))
        assert service.sweep_presence(c)["stale"] >= 1
        j = service.get_job(c, jid)
        assert j["presence"] == "stale" and j["open_days"] >= 9, j

        c.execute("UPDATE jobs SET last_seen_at=datetime('now','localtime','-30 day') WHERE id=?", (jid,))
        assert service.sweep_presence(c)["gone"] >= 1
        j = service.get_job(c, jid)
        assert j["presence"] == "gone" and j["closed_at"] and j["open_days"] >= 10

        # 下架后又出现 → 自动复招
        back = service.upsert_job(c, {"channel": "boss", "source_job_id": "life-1",
                                      "title": "T1", "company_name": "C", "salary_raw": "25-35K"}, "test")
        assert back["job"]["presence"] == "open" and back["job"]["closed_at"] is None

        # --- 单个岗位下架（详情页 404）---
        gone = service.mark_gone(c, {"channel": "boss", "source_job_id": "life-1",
                                     "reason": "detail_404"}, "test")
        assert gone["changed"] is True and gone["job"]["presence"] == "gone"
        assert gone["job"]["gone_reason"] == "detail_404" and gone["job"]["closed_at"]
        assert service.mark_gone(c, {"id": jid, "reason": "other"}, "test")["changed"] is False
        back2 = service.upsert_job(c, {"channel": "boss", "source_job_id": "life-1",
                                       "title": "T1", "company_name": "C"}, "test")
        assert back2["job"]["presence"] == "open" and back2["job"]["gone_reason"] is None

        # --- 整家公司全量清单：清单里没有的在招岗位直接判下架 ---
        for sid, title in (("C-1", "A 岗"), ("C-2", "B 岗"), ("C-3", "C 岗")):
            service.upsert_job(c, {"channel": "maimai", "source_job_id": sid, "title": title,
                                   "company_name": "批量公司", "tags": ["核心岗"]}, "test")
        sync = service.sync_company(c, {"channel": "maimai", "company_name": "批量公司",
                                        "complete": True,
                                        "jobs": [{"source_job_id": "C-1", "title": "A 岗"},
                                                 {"source_job_id": "C-3", "title": "C 岗"}]}, "test")
        assert sync["gone_count"] == 1, sync
        remain = {r["source_job_id"]: r["presence"] for r in c.execute(
            "SELECT source_job_id, presence FROM jobs WHERE company_name='批量公司'")}
        assert remain == {"C-1": "open", "C-3": "open", "C-2": "gone"}, remain
        r_c2 = c.execute("SELECT gone_reason FROM jobs WHERE source_job_id='C-2'").fetchone()
        assert r_c2[0] == "company_sync"
        # complete=False 时不能判下架
        sync2 = service.sync_company(c, {"channel": "maimai", "company_name": "批量公司",
                                         "complete": False,
                                         "jobs": [{"source_job_id": "C-1", "title": "A 岗"}]}, "test")
        assert sync2["gone_count"] == 0
        # 标签：写入 + 按标签筛选 + 重新上报时替换
        assert service.list_jobs(c, tag="核心岗")["total"] == 3
        service.upsert_job(c, {"channel": "maimai", "source_job_id": "C-1",
                               "title": "A 岗", "tags": ["核心岗", "已内推"]}, "test")
        c1 = c.execute("SELECT tags FROM jobs WHERE source_job_id='C-1'").fetchone()[0]
        assert "已内推" in c1 and "核心岗" in c1, c1
        assert service.list_jobs(c, tag="已内推")["total"] == 1

        # --- 附件：只留最新一张截图 + 拒收已放弃岗位 ---
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        att_job = service.upsert_job(c, {"channel": "boss", "source_job_id": "att-1",
                                        "title": "附件岗位", "company_name": "附件公司"}, "test")["job"]["id"]
        a1 = service.save_attachment(c, att_job, png, "jd1.png", "image/png", caption="第一张", actor="test")
        assert a1["created"] and a1["pruned"] == 0
        same = service.save_attachment(c, att_job, png, "jd1.png", "image/png", actor="test")
        assert same["created"] is False, "同一张图不应重复存"
        a2 = service.save_attachment(c, att_job, png + b"\x00", "jd2.png", "image/png", actor="test")
        assert a2["created"] and a2["pruned"] == 1, "新截图要顶掉旧截图"
        atts = service.list_attachments(c, att_job)
        assert len(atts) == 1 and atts[0]["filename"].startswith("jd2"), atts
        assert not (service.UPLOAD_DIR / a1["attachment"]["rel_path"]).exists(), "旧文件要真删掉"
        assert (service.UPLOAD_DIR / a2["attachment"]["rel_path"]).exists()

        # 明确不要的岗位：拒收附件
        service.set_job_state(c, att_job, "rejected", "test")
        expect_err(lambda: service.save_attachment(c, att_job, png + b"\x01\x02", "jd3.png",
                                                   "image/png", actor="test"), "拒收附件")
        purged = service.purge_rejected_attachments(c, "test")
        assert purged["count"] == 1 and purged["bytes"] > 0
        assert service.list_attachments(c, att_job) == []

        # --- Agent 任务提示词 / 配置 ---
        edited = service.update_agent(c, "collector-liepin",
                                      {"prompt": "只抓前端岗位", "config": {"keywords": ["前端"]}}, "test")
        assert edited["prompt"] == "只抓前端岗位" and edited["config"]["keywords"] == ["前端"]
        expect_err(lambda: service.update_agent(c, "collector-liepin", {"config": "{bad"}, "test"),
                   "合法 JSON")

        me = dict(c.execute("SELECT * FROM agents WHERE id='collector-liepin'").fetchone())
        assert a2a._agent_config_get(c, {"_agent_row": me})["config"]["keywords"] == ["前端"]
        expect_err(lambda: a2a._agent_config_get(c, {"_agent_row": me, "agent_id": "analyst"}),
                   "agent:write")

        cfg_payload = {"jsonrpc": "2.0", "id": 9, "method": "message/send", "params": {"message": {"parts": [
            {"kind": "data", "data": {"tool": "agent.config.set",
                                      "arguments": {"agent_id": "analyst", "prompt": "你是只读分析员"}}}]}}}
        expect_err(lambda: a2a.handle(c, me, cfg_payload), "agent:write")   # 没有 agent:write

        c.execute("UPDATE agents SET scopes=scopes||',agent:write' WHERE id='collector-liepin'")
        admin = dict(c.execute("SELECT * FROM agents WHERE id='collector-liepin'").fetchone())
        res = a2a.handle(c, admin, cfg_payload)
        assert res["result"]["task"]["status"]["state"] == "completed"
        assert service.get_agent(c, "analyst")["prompt"] == "你是只读分析员"
        cap2 = a2a._capabilities(admin, "", False)
        assert cap2["you"]["prompt"] == "只抓前端岗位"
        assert cap2["you"]["config"]["keywords"] == ["前端"]

        # --- 预审 / 附件读取 / Agent 诉求 ---
        pre = service.review_job(c, {"id": jid, "tags": ["核心岗"], "priority": 1,
                                      "match_score": 88, "notes": "预审：技术栈匹配",
                                      "state": "shortlisted"}, "test")
        assert pre["tags"] == ["核心岗"] and pre["priority"] == 1
        assert pre["match_score"] == 88 and pre["state"] == "shortlisted"
        att = service.save_attachment(c, jid, png, "jd.png", "image/png", actor="test")
        got = service.read_attachments(c, {"job_id": jid})
        assert got["count"] == 1 and got["attachments"][0]["data_base64"]
        assert base64.b64decode(got["attachments"][0]["data_base64"]) == png

        rep = service.create_report(c, "collector-liepin", {
            "title": "BOSS 薪资偏低", "kind": "data_quality", "severity": "high",
            "target": "channel:boss", "content": "抓到的薪资少一个 0，建议采集侧加最低薪资校验"})
        assert rep["status"] == "open"
        expect_err(lambda: service.create_report(c, "x", {"title": "t", "kind": "nope"}), "kind")
        done = service.update_report(c, rep["id"], {"status": "accepted", "response": "已让采集侧加校验"}, "test")
        assert done["status"] == "accepted" and done["response"]
        expect_err(lambda: service.update_report(c, rep["id"], {"status": "open"}, "test"), "不允许")
        assert service.list_reports(c, status="accepted")[0]["id"] == rep["id"]
        assert service.dashboard(c)["reports"]["open"] == 0

        # --- JD 匹配评估（job-match 口径） ---
        fit = service.set_job_fit(c, {
            "id": jid, "verdict": "apply_after_gap", "reason": "方向对口但年限口径缺",
            "requirements": [
                {"req": "5 年平台经验", "importance": "must", "evidence": "2 个月做出中台",
                 "status": "insufficient", "risk": "可能被 HR 筛"},
                {"req": "Agent 运行时", "importance": "core", "evidence": "沙箱 + 凭据外置",
                 "status": "matched"}],
            "hard_gates": [{"item": "学历", "status": "pass", "note": "本科"}],
            "gaps": [{"type": "phrasing", "item": "产品身份", "action": "改成产品 + 开发"}],
            "strategy": {"resume_version": "AI 应用版"}},
            "test")
        assert fit["fit_verdict"] == "apply_after_gap" and fit["fit_report"]["requirements"][0]["status"] == "insufficient"
        assert fit["fit_at"] and fit["fit_reason"].startswith("方向")
        expect_err(lambda: service.set_job_fit(c, {"id": jid, "verdict": "maybe", "reason": "x"}, "test"),
                   "verdict")
        expect_err(lambda: service.set_job_fit(c, {"id": jid, "verdict": "apply",
                                                  "requirements": [{"req": "x", "status": "nope"}]}, "test"),
                   "status")
        assert service.list_jobs(c, fit="apply_after_gap")["total"] >= 1

        # --- 简历定制（命名 + 去 mark + 入库） ---
        assert service.build_resume_filename("AI应用工程师", "字节跳动", "2026-11-21 10:00:00") == \
            "陈明欢_AI应用工程师_字节跳动_20261121"
        assert service.strip_marks('<p><mark data-why="x">重点</mark>普通</p>') == '<p>重点普通</p>'
        html = ("<!doctype html><html><body><h1>陈明欢</h1>"
                "<p><mark data-why=\"个岗定制\">近 2 个月单人完成 Agent 中台 0→1</mark></p>"
                + "<p>技能：Node/Python</p>" * 12 + "</body></html>")
        rr = service.create_resume(c, {"job_id": jid, "role": "AI应用工程师", "company": "测试公司",
                                       "html": html,
                                       "changes": [{"where": "简介", "after": "强调 0→1", "why": "JD 要求"}]},
                                   "test")
        assert rr["resume"]["filename"].startswith("陈明欢_AI应用工程师_测试公司_")
        assert len(rr["resume"]["changes"]) == 1
        assert service.list_resumes(c)[0]["id"] == rr["resume"]["id"]
        # 回读全文 + diff + 基准简历
        full = service.get_resume(c, rr["resume"]["id"])
        assert full["html"] == html and "<mark" in full["html"]
        assert service.diff_resumes(c, rr["resume"]["id"]).get("no_base") is True
        rr2 = service.create_resume(c, {"job_id": jid, "role": "AI应用工程师", "company": "测试公司",
                                        "html": html.replace("技能：Node/Python", "技能：Node/Python/K8s"),
                                        "changes": []}, "test")
        d = service.diff_resumes(c, rr2["resume"]["id"])
        assert d["added_lines"] >= 1 or d["removed_lines"] >= 1, d
        src = service.save_resume_source(c, {"name": "base.html", "html": "<html>" + "x" * 400 + "</html>"}, "test")
        assert src["source"] == "uploaded" and src["html"]
        assert "html" not in service.list_resumes(c)[0]
        expect_err(lambda: service.create_resume(c, {"html": "too short"}, "test"), "太短")
        assert service.delete_resume(c, rr["resume"]["id"], "test")["ok"]

        # 看板统计（防止 SQL 拼接回归）
        dash = service.dashboard(c)
        assert dash["jobs"]["total"] >= 1 and dash["jobs"]["avg_open_days"] is not None
        assert "presence" in dash["jobs"] and "channels" in dash

    print("✅ smoke checks passed")


def under_test_job_id(c):
    return c.execute("SELECT id FROM jobs ORDER BY id LIMIT 1").fetchone()[0]


main()
