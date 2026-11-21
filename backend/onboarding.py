"""给 Agent 的接入说明文本：所有 Agent 共用同一份，只有 agent_id / secret 不同。

故意不列具体工具、不写这个 Agent 该怎么做 —— 让 Agent 自己去调 agent.capabilities 查，
所以加工具、改参数都不用改这里。
"""


def onboarding_text(agent_row, base_url) -> str:
    base = (base_url or "https://jobs.chenminghuan.com").rstrip("/")
    return f"""# 应聘中台 · Agent 接入说明

你是接入「应聘中台」的 Agent。中台在你这侧只需要**出站 HTTPS**，不需要任何入站端口。

## 1. 入口

POST {base}/a2a
Content-Type: application/json          （JSON-RPC 2.0）

## 2. 你的身份

X-Agent-Id: {agent_row.get('id')}
secret:     {agent_row.get('secret')}

secret 只用来算签名：不要写进日志、不要提交到代码仓库。

## 3. 每个请求都要签名

canonical = agent_id + "\\n" + timestamp + "\\n" + nonce + "\\n" + sha256_hex(raw_body)
X-Signature = hex(HMAC_SHA256(secret, canonical))

四个请求头：X-Agent-Id / X-Timestamp（秒级 Unix 时间）/ X-Nonce（每次随机、绝不重复）/ X-Signature。
时间窗 ±300 秒，nonce 用过一次即作废（防重放）。

请求体：

{{"jsonrpc":"2.0","id":1,"method":"message/send","params":{{"message":{{"role":"user",
  "parts":[{{"kind":"data","data":{{"tool":"<工具名>","arguments":{{}}}}}}]}}}}}}

## 4. 你能做什么：先问接口，不要猜

本说明不列具体工具，能力由服务端按你的密钥实时下发。开工前先调：

  tool = "agent.capabilities"，arguments = {{}}

返回：你是谁、你有哪些权限、你能调用哪些工具、各对象的状态机、错误码、上报格式。
需要更细时按需展开：

  arguments = {{"verbose": true}}                  → 带上每个工具的参数与示例
  arguments = {{"tool": "<工具名>"}}               → 只要那个工具的完整说明与示例参数

返回里 `tools` 是你能调的，`denied_tools` 是存在但你无权调用的（只有名字）。
没权限说明需要本人在页面上开通，你自己无法提权，也不要去试。

## 5. 通用约定

- 写数据前先查一次：拿不准字段就往 `agent.capabilities` 里问，不要凭记忆拼参数。
- 采集岗位走 upsert，按 `channel + source_job_id` 幂等；重复上报只会更新，不会重复入库。
  渠道特有的字段放 `extra`，原始响应原样放 `raw`。
- 状态推进走各对象的 `*.set_state`，服务端按状态机校验；非法跳转返回 `-32004`，返回体里列出可选状态。
- 你所在机器的采集节奏、采什么内容，由你自己判断；中台只负责存储、状态和口径。
- 返回码：`-32001` 签名/时间戳/nonce、`-32002` 对象不存在、`-32003` 缺权限、
  `-32004` 状态机不允许、`-32602` 参数问题。
- 出站请求请带一个正常的 User-Agent（Cloudflare 会拦 `Python-urllib` 默认 UA）。
"""
