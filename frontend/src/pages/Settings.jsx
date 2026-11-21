import React, { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Col, Descriptions, Form, Input, Modal, Popconfirm, Row, Select, Space,
  Statistic, Switch, Table, Tabs, Tag, Typography, App, Divider, Checkbox, Tooltip,
} from 'antd'
import {
  KeyOutlined, CopyOutlined, ReloadOutlined, ExperimentOutlined, DeleteOutlined,
  ApiOutlined, PlusOutlined, ExportOutlined, SettingOutlined,
} from '@ant-design/icons'
import { get, patch, post, del } from '../api'
import { useMeta } from '../meta'

const SCOPE_COLOR = {
  'stats:read': 'default', 'job:read': 'blue', 'job:write': 'geekblue', 'job:state': 'purple',
  'company:read': 'cyan', 'company:write': 'geekblue', 'company:state': 'purple',
  'contact:read': 'green', 'contact:write': 'lime', 'contact:state': 'purple',
  'channel:read': 'gold', 'channel:write': 'orange', 'channel:state': 'purple',
}

export default function Settings() {
  const { meta } = useMeta()
  const { message } = App.useApp()
  const [info, setInfo] = useState(null)
  const [agents, setAgents] = useState([])
  const [secretOf, setSecretOf] = useState(null)
  const [creating, setCreating] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const [configOf, setConfigOf] = useState(null)

  const load = () => {
    get('/api/a2a/info').then(setInfo).catch(() => {})
    get('/api/agents').then(setAgents).catch((e) => message.error(e.message))
  }
  useEffect(load, [])
  if (!meta) return null

  const copy = (t, label = '已复制') => { navigator.clipboard?.writeText(t).then(() => message.success(label)) }

  const scopesOf = (a) => (a.scopes || '').split(',').filter(Boolean)

  const columns = [
    {
      title: 'Agent', dataIndex: 'id', width: 210,
      render: (v, r) => (
        <div>
          <div style={{ fontWeight: 600, fontSize: 13.5 }}>{r.name || v}</div>
          <div className="mono" style={{ fontSize: 11.5, color: '#98a2b3' }}>{v}</div>
          {r.prompt ? (
            <div style={{ fontSize: 11, color: '#98a2b3', marginTop: 2, maxWidth: 260,
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              📝 {r.prompt}
            </div>
          ) : null}
        </div>
      ),
    },
    {
      title: '权限', dataIndex: 'scopes', width: '38%',
      render: (s) => (
        <Space size={[4, 4]} wrap>
          {(s || '').split(',').filter(Boolean).map((x) => <Tag key={x} color={SCOPE_COLOR[x]} style={{ margin: 0, fontSize: 11 }}>{x}</Tag>)}
        </Space>
      ),
    },
    {
      title: '启用', dataIndex: 'active', width: 70,
      render: (v, r) => <Switch size="small" checked={!!v} onChange={async (val) => {
        await patch(`/api/agents/${r.id}`, { active: val ? 1 : 0 }); load()
      }} />,
    },
    { title: '调用', dataIndex: 'call_count', width: 70, render: (v) => <Typography.Text type="secondary">{v}</Typography.Text> },
    {
      title: '最近活跃', dataIndex: 'last_seen_at', width: 120,
      render: (v) => <span style={{ fontSize: 12, color: '#98a2b3' }}>{v || '从未调用'}</span>,
    },
    {
      title: '操作', width: 262, align: 'right',
      render: (_, r) => (
        <Space size={2}>
          <Tooltip title="任务提示词 / 配置项">
            <Button size="small" type="text"
                    icon={<SettingOutlined style={{ color: r.prompt ? '#4f46e5' : undefined }} />}
                    onClick={() => setConfigOf(r)} />
          </Tooltip>
          <Tooltip title="一键复制接入说明（所有 Agent 同一份文案，只含本 Agent 的 ID 和密钥）">
            <Button size="small" type="text" icon={<CopyOutlined />} onClick={async () => {
              try {
                const { text } = await get(`/api/agents/${r.id}/onboarding`, { with_secret: 1 })
                await navigator.clipboard.writeText(text)
                message.success('已复制，直接粘给 Agent 即可')
              } catch (e) { message.error(e.message || '复制失败') }
            }} />
          </Tooltip>
          <Tooltip title="查看密钥"><Button size="small" type="text" icon={<KeyOutlined />} onClick={() => setSecretOf(r)} /></Tooltip>
          <Tooltip title="签名自检（用它的密钥真实打一次 tools/list）">
            <Button size="small" type="text" icon={<ExperimentOutlined />} onClick={async () => {
              try { setTestResult({ agent: r.id, data: await post(`/api/agents/${r.id}/selftest`, {}) }) }
              catch (e) { message.error(e.message) }
            }} />
          </Tooltip>
          <Popconfirm title="重置密钥？旧密钥立即失效" onConfirm={async () => {
            const res = await post(`/api/agents/${r.id}/rotate`, {})
            message.success('已重置'); setSecretOf(res); load()
          }}>
            <Tooltip title="重置密钥"><Button size="small" type="text" icon={<ReloadOutlined />} /></Tooltip>
          </Popconfirm>
          <Popconfirm title="删除这个 Agent？" onConfirm={async () => { await del(`/api/agents/${r.id}`); load() }}>
            <Button size="small" type="text" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const curlExample = (agentId) => `BODY='{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"role":"user","parts":[{"kind":"data","data":{"tool":"job.upsert","arguments":{"jobs":[{"channel":"liepin","source_job_id":"l-1","title":"高级前端工程师","company_name":"某公司","salary_raw":"30-55K·15薪","city":"上海","url":"https://...","extra":{"hunter":true},"raw":{}}]}}}]}}}'
TS=$(date +%s); NONCE=$(openssl rand -hex 8); AID='${agentId}'; SECRET='<在页面上点钥匙图标查看>'
HASH=$(printf '%s' "$BODY" | openssl dgst -sha256 -hex | awk '{print $2}')
SIG=$(printf '%s\\n%s\\n%s\\n%s' "$AID" "$TS" "$NONCE" "$HASH" | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print $2}')

curl -s ${info?.endpoint || 'http://127.0.0.1:8010/a2a'} -H 'Content-Type: application/json' \\
  -H "X-Agent-Id: $AID" -H "X-Timestamp: $TS" -H "X-Nonce: $NONCE" -H "X-Signature: $SIG" \\
  -d "$BODY"`

  const pyExample = `import hashlib, hmac, json, time, secrets, requests

AGENT_ID, SECRET = "${agents[0]?.id || 'collector-liepin'}", "<密钥>"
body = json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "message/send",
    "params": {"message": {"role": "user", "parts": [
        {"kind": "data", "data": {"tool": "job.upsert", "arguments": {"jobs": [
            {"channel": "boss", "source_job_id": "b-1", "title": "Node 后端",
             "company_name": "某公司", "salary_raw": "35-60K·16薪", "city": "杭州"}]}}}]}}}).encode()

ts, nonce = str(int(time.time())), secrets.token_hex(8)
canonical = "\\n".join([AGENT_ID, ts, nonce, hashlib.sha256(body).hexdigest()])
sig = hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()

r = requests.post("${info?.endpoint || 'http://127.0.0.1:8010/a2a'}", data=body, headers={
    "Content-Type": "application/json", "X-Agent-Id": AGENT_ID,
    "X-Timestamp": ts, "X-Nonce": nonce, "X-Signature": sig})
print(r.json())`

  return (
    <>
      <Row gutter={[14, 14]}>
        <Col xs={24} xl={14}>
          <Card title={<Space><ApiOutlined />A2A 接入</Space>}
                extra={<Button size="small" icon={<ExportOutlined />} href="/.well-known/agent-card.json" target="_blank">Agent Card</Button>}>
            <Descriptions column={1} size="small" styles={{ label: { width: 110 } }}
              items={[
                {
                  key: 'ep', label: 'Endpoint',
                  children: <Space><span className="mono">{info?.endpoint}</span>
                    <Button size="small" type="text" icon={<CopyOutlined />} onClick={() => copy(info?.endpoint)} /></Space>,
                },
                {
                  key: 'card', label: '发现文档',
                  children: <span className="mono" style={{ fontSize: 12 }}>{info?.agent_card}</span>,
                },
                {
                  key: 'sig', label: '签名',
                  children: (
                    <div style={{ fontSize: 12.5, lineHeight: 1.9 }}>
                      <div>算法：<Tag>HMAC-SHA256</Tag> 每个 Agent 独立 secret</div>
                      <div>头：<span className="mono">X-Agent-Id / X-Timestamp / X-Nonce / X-Signature</span></div>
                      <div>签名串：<span className="mono">agent_id \n timestamp \n nonce \n sha256(body)</span></div>
                      <div style={{ color: '#667085' }}>时间窗 ±300s，nonce 不可重放；密钥泄露可在右侧一键重置。</div>
                    </div>
                  ),
                },
                {
                  key: 'methods', label: '方法',
                  children: <span className="mono" style={{ fontSize: 12 }}>message/send · tools/list · tasks/get</span>,
                },
              ]} />
            <Alert type="warning" showIcon style={{ marginTop: 10 }}
                   message="公网暴露前请在反代上加 TLS + IP 白名单；当前服务本身不做 IP 限制。" />
          </Card>
        </Col>
        <Col xs={24} xl={10}>
          <Card title="接入状态" styles={{ body: { paddingTop: 6 } }}>
            <Row>
              <Col span={8}><Statistic title="Agent" value={agents.length} valueStyle={{ fontSize: 22 }} /></Col>
              <Col span={8}><Statistic title="启用中" value={agents.filter((a) => a.active).length} valueStyle={{ fontSize: 22 }} /></Col>
              <Col span={8}><Statistic title="累计调用" value={agents.reduce((a, b) => a + (b.call_count || 0), 0)} valueStyle={{ fontSize: 22 }} /></Col>
            </Row>
            <Divider style={{ margin: '14px 0' }} />
            <div style={{ fontSize: 12.5, lineHeight: 1.9, color: '#475467' }}>
              设计原则：<b>采集 Agent 只写不改状态</b>；联系人状态只给跟单 Agent；分析 Agent 只看不改原始字段（能预审、打标签、改状态）；中台管理能调度其他 Agent。
              想加权限直接在右侧改，或在新建时勾选。
            </div>
          </Card>
        </Col>
      </Row>

      <Card title="Agent 与密钥" style={{ marginTop: 14 }}
            extra={<Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>新建 Agent</Button>}>
        <Table rowKey="id" size="middle" columns={columns} dataSource={agents} pagination={false} scroll={{ x: 900 }} />
      </Card>

      <Card title="工具权限目录" style={{ marginTop: 14 }}
            extra={<Typography.Text type="secondary" style={{ fontSize: 12 }}>调工具时后端按这张表校验 scope，缺权限直接 403</Typography.Text>}>
        <Table rowKey="name" size="small" pagination={{ pageSize: 10, size: 'small' }}
               dataSource={meta.tools}
               columns={[
                 { title: '工具', dataIndex: 'name', width: 160, render: (v) => <span className="mono">{v}</span> },
                 { title: '所需权限', dataIndex: 'scope', width: 130, render: (v) => <Tag color={SCOPE_COLOR[v]}>{v}</Tag> },
                 { title: '说明', dataIndex: 'description' },
                 {
                   title: '参数', dataIndex: 'params', width: '28%',
                   render: (p) => <span className="mono" style={{ fontSize: 11.5, color: '#667085' }}>{Object.keys(p || {}).join(', ') || '-'}</span>,
                 },
               ]} />
      </Card>

      <Card title="调用示例" style={{ marginTop: 14 }}>
        <Tabs items={[
          { key: 'curl', label: 'curl', children: <CodeBlock text={curlExample(agents[0]?.id || 'collector-liepin')} onCopy={copy} /> },
          { key: 'py', label: 'Python', children: <CodeBlock text={pyExample} onCopy={copy} /> },
          {
            key: 'agent', label: 'Agent 侧约定',
            children: (
              <div style={{ fontSize: 13, lineHeight: 2, color: '#344054' }}>
                <div>1. 先拉 <span className="mono">/.well-known/agent-card.json</span> 拿技能列表（每个技能带 <span className="mono">x-required-scope</span> 和 <span className="mono">x-params</span>）。</div>
                <div>2. 每个请求体是 JSON-RPC，工具调用放在 <span className="mono">message.parts[0].data = {'{tool, arguments}'}</span>。</div>
                <div>3. 批量上报用 <span className="mono">job.upsert</span> 的 <span className="mono">jobs</span> 数组：按 <span className="mono">channel + source_job_id</span> 幂等，重复上报只更新不新增。</div>
                <div>4. 平台改版时只改自己侧的字段映射，渠道专有字段塞 <span className="mono">extra</span>，原始响应塞 <span className="mono">raw</span>，中台无需迁移。</div>
                <div>5. 状态推进用 <span className="mono">*.set_state</span>，后端按状态机校验，非法跳转会返回 <span className="mono">-32004</span> 并列出可选状态。</div>
              </div>
            ),
          },
        ]} />
      </Card>

      <Card title="维护" style={{ marginTop: 14 }}>
        <Space wrap>
          <Button icon={<ExportOutlined />} onClick={async () => {
            const data = await get('/api/maintenance/export')
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
            const a = document.createElement('a')
            a.href = URL.createObjectURL(blob)
            a.download = `jobhub-export-${new Date().toISOString().slice(0, 10)}.json`
            a.click()
          }}>导出全部数据</Button>
          <Popconfirm title="把已放弃/已归档岗位的附件全部删掉（回收磁盘）"
                      onConfirm={async () => {
                        const r = await post('/api/maintenance/purge-attachments', {})
                        message.success(r.count ? `清理 ${r.count} 个附件，释放 ${Math.round(r.bytes / 1024)} KB` : '没有需要清理的附件')
                      }}>
            <Button>清理放弃岗位附件</Button>
          </Popconfirm>
          <Popconfirm title="清空所有 is_demo=1 的示例数据（真实数据不受影响）"
                      onConfirm={async () => { await post('/api/maintenance/clear-demo', {}); message.success('已清空示例数据'); load() }}>
            <Button danger>清空示例数据</Button>
          </Popconfirm>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            数据库：<span className="mono">{meta.db_path}</span>
          </Typography.Text>
        </Space>
      </Card>

      <SecretModal agent={secretOf} info={info} onClose={() => setSecretOf(null)} onCopy={copy} />
      <TestModal data={testResult} onClose={() => setTestResult(null)} />
      <AgentConfigModal agent={configOf} scopes={meta.scopes} onClose={() => setConfigOf(null)}
                        onSaved={() => { setConfigOf(null); load() }} />
      <CreateAgentModal open={creating} meta={meta} onClose={() => setCreating(false)}
                        onCreated={() => { setCreating(false); load() }} />
    </>
  )
}

function CodeBlock({ text, onCopy }) {
  return (
    <div style={{ position: 'relative' }}>
      <Button size="small" icon={<CopyOutlined />} style={{ position: 'absolute', right: 8, top: 8, zIndex: 2 }}
              onClick={() => onCopy(text, '示例已复制')}>复制</Button>
      <pre className="mono" style={{
        background: '#0f172a', color: '#e2e8f0', padding: 16, borderRadius: 10,
        overflow: 'auto', fontSize: 11.8, lineHeight: 1.75, margin: 0,
      }}>{text}</pre>
    </div>
  )
}

function AgentConfigModal({ agent, scopes, onClose, onSaved }) {
  const { message } = App.useApp()
  const [prompt, setPrompt] = useState('')
  const [cfg, setCfg] = useState('{}')
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!agent) return
    setPrompt(agent.prompt || '')
    setCfg(JSON.stringify(agent.config || {}, null, 2))
    setErr('')
  }, [agent?.id])

  if (!agent) return null

  const save = async () => {
    try { JSON.parse(cfg || '{}') } catch (e) { setErr('JSON 格式不对：' + e.message); return }
    setSaving(true)
    try {
      await patch(`/api/agents/${agent.id}`, { prompt, config: cfg })
      message.success('已保存，Agent 下次调用就能读到')
      onSaved()
    } catch (e) { message.error(e.message) } finally { setSaving(false) }
  }

  return (
    <Modal open onCancel={onClose} width={760} title={`${agent.id} · 任务与配置`} okText="保存"
           confirmLoading={saving} onOk={save}>

      <div style={{ fontSize: 13, fontWeight: 550, marginBottom: 6 }}>任务描述（提示词）</div>
      <Input.TextArea rows={9} value={prompt} onChange={(e) => setPrompt(e.target.value)}
                      placeholder={'例：你负责即刻与小红书的招聘帖采集。\n1. 只看 channel.state=active 的渠道；\n2. 帖子正文里没有明确公司名或联系方式的，跳过；\n3. 抓到 JD 截图就 job.add_attachment。'} />

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '16px 0 6px' }}>
        <span style={{ fontSize: 13, fontWeight: 550 }}>配置项（JSON）</span>
        <Button size="small" type="link" style={{ padding: 0, fontSize: 12 }}
                onClick={() => { try { setCfg(JSON.stringify(JSON.parse(cfg || '{}'), null, 2)); setErr('') } catch (e) { setErr(e.message) } }}>
          格式化
        </Button>
        <span style={{ fontSize: 11.5, color: '#98a2b3' }}>整份替换，可以放任意键值；Agent 侧自己解释</span>
      </div>
      <Input.TextArea rows={12} value={cfg} className="mono"
                      onChange={(e) => { setCfg(e.target.value); setErr('') }}
                      style={{ fontSize: 12 }} />
      {err ? <div style={{ fontSize: 12, color: '#dc2626', marginTop: 6 }}>{err}</div> : null}

      <div style={{ marginTop: 12, fontSize: 12, color: '#667085' }}>
        当前权限：{(agent.scopes || '').split(',').filter(Boolean).join(' / ') || '无'}
        {scopes?.includes('agent:write') && !(agent.scopes || '').includes('agent:write')
          ? '（可在创建/编辑时勾 agent:write 让它成为管理 Agent）' : ''}
      </div>
    </Modal>
  )
}

function SecretModal({ agent, info, onClose, onCopy }) {
  if (!agent) return null
  return (
    <Modal open onCancel={onClose} footer={<Button onClick={onClose}>关闭</Button>} title={`${agent.id} 的密钥`} width={560}>
      <Alert type="warning" showIcon style={{ marginBottom: 12 }}
             message="把它交给对应的 Agent（环境变量或密钥管理），不要提交到代码仓库。" />
      <Typography.Paragraph copyable={{ text: agent.secret, tooltips: ['复制', '已复制'] }} className="mono"
                            style={{ background: '#fafbfc', padding: 12, borderRadius: 8, wordBreak: 'break-all' }}>
        {agent.secret}
      </Typography.Paragraph>
      <div style={{ fontSize: 12.5, color: '#667085', lineHeight: 1.9 }}>
        <div>Agent ID：<span className="mono">{agent.id}</span></div>
        <div>Endpoint：<span className="mono">{info?.endpoint}</span></div>
        <div>权限：{(agent.scopes || '').split(',').filter(Boolean).join(' / ')}</div>
      </div>
    </Modal>
  )
}

function TestModal({ data, onClose }) {
  if (!data) return null
  const ok = data.data?.ok
  return (
    <Modal open onCancel={onClose} footer={<Button onClick={onClose}>关闭</Button>}
           title={`签名自检 · ${data.agent}`} width={640}>
      <Alert type={ok ? 'success' : 'error'} showIcon style={{ marginBottom: 12 }}
             message={ok ? '签名校验通过，工具调用链路正常' : `自检失败：${data.data?.error || '未知错误'}`} />
      <pre className="mono" style={{ background: '#fafbfc', padding: 12, borderRadius: 8, maxHeight: 340, overflow: 'auto' }}>
        {JSON.stringify(data.data, null, 2)}
      </pre>
    </Modal>
  )
}

function CreateAgentModal({ open, meta, onClose, onCreated }) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    const v = await form.validateFields()
    setSaving(true)
    try {
      await post('/api/agents', v)
      message.success('已创建，请到列表里点钥匙图标拿密钥')
      form.resetFields()
      onCreated()
    } catch (e) { message.error(e.message) } finally { setSaving(false) }
  }

  return (
    <Modal open={open} onCancel={onClose} onOk={submit} confirmLoading={saving} title="新建 Agent" okText="创建" width={640}>
      <Form form={form} layout="vertical" size="middle" initialValues={{ kind: 'collector', scopes: ['job:read', 'job:write', 'company:read', 'company:write', 'channel:read'] }}>
        <Space.Compact block>
          <Form.Item name="id" label="Agent ID（用作 X-Agent-Id）" rules={[{ required: true }]} style={{ flex: 1 }}>
            <Input placeholder="collector-zhilian" />
          </Form.Item>
          <Form.Item name="name" label="用途说明" style={{ flex: 1, marginLeft: 10 }}><Input placeholder="智联采集 Agent" /></Form.Item>
        </Space.Compact>
        <Form.Item name="kind" label="类型">
          <Select options={[
            { value: 'collector', label: '采集' }, { value: 'followup', label: '跟单' },
            { value: 'analyst', label: '分析/预审' }, { value: 'other', label: '其他' },
          ]} />
        </Form.Item>
        <Form.Item name="scopes" label="权限（建议最小化）">
          <Checkbox.Group style={{ width: '100%' }}>
            <Row gutter={[8, 8]}>
              {meta.scopes.map((s) => (
                <Col span={8} key={s}><Checkbox value={s}><span className="mono" style={{ fontSize: 12 }}>{s}</span></Checkbox></Col>
              ))}
            </Row>
          </Checkbox.Group>
        </Form.Item>
        <Form.Item name="remark" label="备注"><Input.TextArea rows={2} /></Form.Item>
      </Form>
    </Modal>
  )
}
