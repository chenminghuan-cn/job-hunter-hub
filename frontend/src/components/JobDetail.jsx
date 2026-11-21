import React, { useEffect, useState } from 'react'
import {
  Space, Typography, Tag, Button, Divider, Drawer, Form, Input, InputNumber, Select, App, Image, Tabs,
  Collapse, Descriptions, Popconfirm, Spin, Table,
} from 'antd'
import {
  CopyOutlined, EditOutlined, ExportOutlined, PaperClipOutlined, UploadOutlined,
  CloseOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { get, patch, post, del } from '../api'
import { useMeta } from '../meta'
import ChannelLogo from './ChannelLogo'
import StateSelect from './StateSelect'
import ActivityLog from './ActivityLog'

/** 岗位详情抽屉 + 附件区。岗位列表和公司详情共用同一份，避免两套渲染。 */

export const PRIORITY = { 1: { label: 'P1 高', color: 'red' }, 2: { label: 'P2 中', color: 'orange' }, 3: { label: 'P3 低', color: 'default' } }
export const FIT = {
  apply: { label: '建议投递', color: 'green' },
  apply_after_gap: { label: '补材料后投', color: 'gold' },
  cautious: { label: '谨慎投递', color: 'orange' },
  skip: { label: '不建议投递', color: 'default' },
}
export const FIT_STATUS = {
  matched: { label: '已匹配', color: 'green' },
  phrasing_gap: { label: '表达缺口', color: 'blue' },
  insufficient: { label: '证据不足', color: 'orange' },
  real_gap: { label: '真实缺口', color: 'red' },
  unknown: { label: '待确认', color: 'default' },
}
const IMPORTANCE = { must: { label: '硬性', color: 'red' }, core: { label: '核心', color: 'blue' }, plus: { label: '加分', color: 'default' } }

export const PRESENCE = {
  open: { label: '在招', color: 'green' },
  stale: { label: '疑似下架', color: 'orange' },
  gone: { label: '已下架', color: 'default' },
}

export const ago = (t) => {
  if (!t) return '-'
  const mins = Math.max(0, Math.round((Date.now() - dayjs(t).valueOf()) / 60000))
  if (mins < 60) return `${mins} 分钟前`
  if (mins < 1440) return `${Math.round(mins / 60)} 小时前`
  return `${Math.round(mins / 1440)} 天前`
}

export function JobDrawer({ job, channelOf, onClose, onSaved, onListChange }) {
  const { meta } = useMeta()
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    setEditing(false)
    if (job) form.setFieldsValue({
      title: job.title, company_name: job.company_name, salary_raw: job.salary_raw,
      city: job.city, district: job.district, url: job.url, priority: job.priority,
      match_score: job.match_score, description: job.description, requirements: job.requirements,
      notes: job.notes, experience_req: job.experience_req, education_req: job.education_req,
      employment_type: job.employment_type, tags: job.tags || [],
    })
  }, [job])

  if (!job) return null
  const presence = PRESENCE[job.presence] || PRESENCE.open
  const images = (job.attachments || []).filter((a) => a.mime?.startsWith('image/'))
  const hasJd = !!(job.description || job.requirements)
  const attPending = !Array.isArray(job.attachments) && (job.att_count || 0) > 0

  const save = async () => {
    try {
      await patch(`/api/jobs/${job.id}`, await form.validateFields())
      message.success('已保存')
      onSaved()
    } catch (e) { message.error(e.message) }
  }
  const copyJd = () => {
    const text = [job.title, job.company_name, job.salary_raw, job.city, '',
      '【岗位描述】', job.description || '-', '', '【任职要求】', job.requirements || '-',
      '', job.url || ''].join('\n')
    navigator.clipboard?.writeText(text).then(() => message.success('JD 已复制'))
  }

  const KPI = ({ label, children }) => (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ fontSize: 11.5, color: '#98a2b3' }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 550, color: '#1d2939', marginTop: 2 }}>{children}</div>
    </div>
  )

  return (
    <Drawer width={760} open onClose={onClose} styles={{ body: { paddingTop: 16 } }} title={
      <Space size={8} wrap>
        <span style={{ fontSize: 15, fontWeight: 600 }}>{job.title}</span>
        <StateSelect machine="job" value={job.state} id={job.id} path="/api/jobs" onChanged={onSaved} />
        {(job.tags || []).map((t) => (
          <Tag key={t} color="purple" style={{ margin: 0, fontSize: 11 }}>{t}</Tag>
        ))}
      </Space>
    }>

      <Tabs size="small" defaultActiveKey="detail" items={[{
        key: 'detail',
        label: '详情',
        children: (
        <>
      {/* ---- 关键信息条 ---- */}
      <div style={{
        display: 'flex', gap: 16, padding: '12px 14px', background: '#fafbfc',
        border: '1px solid #f0f1f5', borderRadius: 10,
      }}>
        <KPI label="公司">
          <span onClick={() => onClose()} style={{ cursor: 'default' }}>{job.company_name}</span>
        </KPI>
        <KPI label="薪资"><span style={{ color: '#d97706' }}>{job.salary_raw || '面议'}</span></KPI>
        <KPI label="地点">{[job.city, job.district].filter(Boolean).join(' · ') || '-'}</KPI>
        <KPI label="在招">
          <Space size={5}>
            <Tag color={presence.color} style={{ margin: 0, fontSize: 11 }}>{presence.label}</Tag>
            <span>{job.open_days ?? 0} 天</span>
          </Space>
        </KPI>
        <KPI label="渠道"><ChannelLogo channel={channelOf(job.channel_code)} size={18} name={false} /></KPI>
      </div>

      {/* ---- JD 主体：阅读优先 ---- */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '18px 0 10px' }}>
        <Typography.Text strong style={{ fontSize: 14.5 }}>JD 详情</Typography.Text>
        <Tag style={{ margin: 0 }}>{job.experience_req || '经验未填'} · {job.education_req || '学历未填'}</Tag>
        <div style={{ marginLeft: 'auto' }}>
          <Space size={4}>
            <Button size="small" icon={<CopyOutlined />} onClick={copyJd}>复制 JD</Button>
            {job.url ? (
              <Button size="small" type="primary" ghost icon={<ExportOutlined />}
                      href={job.url} target="_blank">原始页面</Button>
            ) : null}
            <Button size="small" icon={<EditOutlined />} onClick={() => setEditing((v) => !v)}>
              {editing ? '取消编辑' : '编辑'}
            </Button>
          </Space>
        </div>
      </div>

      {editing ? (
        <Form form={form} layout="vertical" size="middle">
          <Form.Item name="description" label="岗位描述"><Input.TextArea rows={9} /></Form.Item>
          <Form.Item name="requirements" label="任职要求"><Input.TextArea rows={7} /></Form.Item>
          <Divider orientation="left" plain style={{ margin: '4px 0 12px' }}>其他字段</Divider>
          <Form.Item name="title" label="岗位名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="tags" label="标签（回车新增）">
            <Select mode="tags" placeholder="核心岗 / 已内推 / 待背调" tokenSeparators={[',', ' ']}
                    options={['核心岗', '已内推', '高薪', '外企', '远程'].map((t) => ({ value: t, label: t }))} />
          </Form.Item>
          <Space.Compact block>
            <Form.Item name="company_name" label="公司" style={{ flex: 1 }}><Input /></Form.Item>
            <Form.Item name="salary_raw" label="薪资（原文）" style={{ flex: 1, marginLeft: 10 }}><Input placeholder="30-55K·15薪" /></Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item name="city" label="城市" style={{ flex: 1 }}><Input /></Form.Item>
            <Form.Item name="district" label="区域" style={{ flex: 1, margin: '0 10px' }}><Input /></Form.Item>
            <Form.Item name="priority" label="优先级" style={{ width: 100 }}>
              <Select options={Object.entries(PRIORITY).map(([v, x]) => ({ value: +v, label: x.label }))} />
            </Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item name="experience_req" label="经验" style={{ flex: 1 }}><Input /></Form.Item>
            <Form.Item name="education_req" label="学历" style={{ flex: 1, margin: '0 10px' }}><Input /></Form.Item>
            <Form.Item name="employment_type" label="类型" style={{ flex: 1 }}><Input /></Form.Item>
          </Space.Compact>
          <Form.Item name="url" label="原始链接"><Input /></Form.Item>
          <Form.Item name="match_score" label="匹配度（0-100）"><InputNumber min={0} max={100} style={{ width: 140 }} /></Form.Item>
          <Form.Item name="notes" label="我的备注"><Input.TextArea rows={3} /></Form.Item>
          <Space>
            <Button type="primary" onClick={save}>保存修改</Button>
            <Button onClick={() => setEditing(false)}>取消</Button>
          </Space>
        </Form>
      ) : hasJd ? (
        <>
          {job.description ? <JdBlock title="岗位描述" text={job.description} /> : null}
          {job.requirements ? <JdBlock title="任职要求" text={job.requirements} /> : null}
          {job.notes ? (
            <div style={{ marginTop: 12 }}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>我的备注</Typography.Text>
              <div style={{ fontSize: 13, color: '#475467', lineHeight: 1.8, whiteSpace: 'pre-wrap', marginTop: 4 }}>
                {job.notes}
              </div>
            </div>
          ) : null}
        </>
      ) : attPending ? (
        <div style={{ padding: '28px 0', textAlign: 'center' }}><Spin /></div>
      ) : images.length ? (
        <ScreenshotWall images={images} />
      ) : (
        <div style={{
          border: '1px dashed #e4e7ec', borderRadius: 10, padding: '18px 16px', textAlign: 'center',
          color: '#98a2b3', fontSize: 13, background: '#fcfcfd',
        }}>
          采集侧没给到 JD 正文
          {job.url ? <> · <a href={job.url} target="_blank" rel="noreferrer">打开原始页面看</a></> : null}
          <div style={{ fontSize: 11.5, marginTop: 6 }}>
            可以让采集 Agent 在 job.upsert 里补 description / requirements，或用 job.add_attachment 传 JD 截图
          </div>
        </div>
      )}

      {/* ---- 附件（JD 截图 / 海报）---- */}
      <AttachmentSection job={job} onChanged={onListChange}
                         hideImages={!hasJd && images.length > 0} />

      {/* ---- 附属信息 ---- */}
      <Collapse ghost style={{ marginTop: 14 }} items={[
        {
          key: 'meta',
          label: <Typography.Text style={{ fontSize: 13 }}>更多信息（发布者 / 生命周期 / 源数据）</Typography.Text>,
          children: (
            <>
              <Descriptions column={2} size="small" bordered items={[
                { key: 'publisher', label: '发布者', children: job.publisher_name ? `${job.publisher_name}${job.publisher_type ? `（${job.publisher_type}）` : ''}` : '-' },
                { key: 'posted', label: '发布时间', children: job.posted_at || '-' },
                { key: 'first', label: '首次发现', children: `${job.first_seen_at || '-'}（${job.open_days ?? 0} 天前）` },
                { key: 'last_seen', label: '最后确认', children: `${job.last_seen_at || '-'}（${ago(job.last_seen_at)}）` },
                { key: 'seen', label: '被采集次数', children: `${job.seen_count ?? 1} 次` },
                { key: 'changed', label: '内容最近变更', children: job.last_change_at ? ago(job.last_change_at) : '-' },
                { key: 'closed', label: '判定下架', children: job.closed_at ? `${job.closed_at}（${job.gone_reason || '-'}）` : '-' },
                { key: 'priority', label: '优先级', children: (PRIORITY[job.priority] || PRIORITY[3]).label },
                { key: 'match', label: '匹配度', children: job.match_score != null ? `${job.match_score} 分` : '-' },
                { key: 'sid', label: '源 ID', children: <span className="mono">{job.source_job_id || '-'}</span> },
                { key: 'fp', label: '指纹', children: <span className="mono" style={{ wordBreak: 'break-all' }}>{job.fingerprint}</span> },
              ]} />
              <pre className="mono" style={{ background: '#fafbfc', padding: 12, borderRadius: 8, marginTop: 10, maxHeight: 220, overflow: 'auto' }}>
                {JSON.stringify({ extra: job.extra, raw: job.raw }, null, 2)}
              </pre>
            </>
          ),
        },
      ]} />
        </>
        ),
      }, {
        key: 'fit',
        label: '匹配评估',
        children: <FitPanel job={job} />,
      }, {
        key: 'resume',
        label: '简历',
        children: <JobResumePanel job={job} />,
      }, {
        key: 'log',
        label: '操作日志',
        children: <ActivityLog entity="job" entityId={job.id} />,
      }]} />
    </Drawer>
  )
}

export function AttachmentSection({ job, onChanged, hideImages = false }) {
  const { message } = App.useApp()
  const [items, setItems] = useState(job?.attachments || [])
  const [busy, setBusy] = useState(false)
  useEffect(() => { setItems(job?.attachments || []) }, [job?.id, job?.attachments])

  const upload = async (files) => {
    if (!files?.length) return
    setBusy(true)
    try {
      for (const f of files) {
        if (f.size > 8 * 1024 * 1024) { message.error(`${f.name} 超过 8MB`); continue }
        const b64 = await new Promise((resolve, reject) => {
          const fr = new FileReader()
          fr.onload = () => resolve(String(fr.result))
          fr.onerror = reject
          fr.readAsDataURL(f)
        })
        const r = await post(`/api/jobs/${job.id}/attachments`,
                             { filename: f.name, data_base64: b64 })
        if (!r.created) message.info(`${f.name} 已存在，跳过`)
      }
      const fresh = await get(`/api/jobs/${job.id}`)
      setItems(fresh.attachments || [])
      onChanged?.()
      message.success('已上传')
    } catch (e) {
      message.error(e.message)
    } finally { setBusy(false) }
  }

  const remove = async (aid) => {
    await del(`/api/attachments/${aid}`)
    setItems((cur) => cur.filter((x) => x.id !== aid))
    onChanged?.()
    message.success('已删除')
  }

  const blocked = ['rejected', 'archived'].includes(job.state)
  const images = items.filter((x) => x.mime?.startsWith('image/'))
  const files = items.filter((x) => !x.mime?.startsWith('image/'))

  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <Typography.Text strong style={{ fontSize: 13.5 }}>附件</Typography.Text>
        <span style={{ fontSize: 11.5, color: '#98a2b3' }}>
          {items.length ? `${items.length} 个` : 'JD 截图 / 岗位海报'} · 截图只留最新一张
        </span>
        {blocked ? (
          <Tag color="default" style={{ marginLeft: 'auto', margin: 0 }}>已放弃/归档，拒收附件</Tag>
        ) : (
          <label style={{ marginLeft: 'auto' }}>
            <input type="file" multiple accept="image/png,image/jpeg,image/webp,image/gif,application/pdf"
                   style={{ display: 'none' }}
                   onChange={(e) => { upload([...e.target.files]); e.target.value = '' }} />
            <Button size="small" icon={<UploadOutlined />} loading={busy}>上传</Button>
          </label>
        )}
      </div>

      {items.length === 0 ? (
        <div style={{ fontSize: 12, color: '#b9c0cc' }}>
          没有附件。采集 Agent 可以用 job.add_attachment 传 JD 截图（base64 或图片 URL）。
        </div>
      ) : (
        <>
          <Image.PreviewGroup>
            <Space size={8} wrap style={{ display: hideImages ? 'none' : undefined }}>
              {images.map((a) => (
                <div key={a.id} style={{ position: 'relative' }}>
                  <Image src={`/files/${a.rel_path}`} width={84} height={84} alt={a.filename}
                         preview={{ mask: null }}
                         style={{ objectFit: 'cover', borderRadius: 8, border: '1px solid #eef0f4' }} />
                  <Popconfirm title="删除这张？" onConfirm={() => remove(a.id)}>
                    <Button size="small" type="text" danger icon={<CloseOutlined />}
                            style={{ position: 'absolute', top: -6, right: -6, background: '#fff', borderRadius: '50%', boxShadow: '0 1px 3px rgba(0,0,0,.15)', width: 20, height: 20, minWidth: 20, padding: 0 }} />
                  </Popconfirm>
                </div>
              ))}
            </Space>
          </Image.PreviewGroup>
          {files.map((a) => (
            <div key={a.id} style={{ marginTop: 8, fontSize: 12.5 }}>
              <PaperClipOutlined style={{ color: '#98a2b3' }} />{' '}
              <a href={`/files/${a.rel_path}`} target="_blank" rel="noreferrer">{a.filename}</a>
              <span style={{ color: '#98a2b3' }}> · {Math.round((a.size || 0) / 1024)} KB</span>
              <Popconfirm title="删除？" onConfirm={() => remove(a.id)}>
                <Button size="small" type="link" danger style={{ fontSize: 12 }}>删除</Button>
              </Popconfirm>
            </div>
          ))}
        </>
      )}
    </div>
  )
}

function JobResumePanel({ job }) {
  const { message } = App.useApp()
  const [rows, setRows] = useState(null)
  const [cur, setCur] = useState(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    setReady(false)
    const t = setTimeout(() => setReady(true), 220)   // 避开抽屉展开动画
    return () => clearTimeout(t)
  }, [cur?.id])

  const load = async () => {
    try {
      const list = await get('/api/resumes', { job_id: job.id })
      setRows(list)
      if (list.length) setCur(await get(`/api/resumes/${list[0].id}`))
      else setCur(null)
    } catch (e) { message.error(e.message) }
  }
  useEffect(() => { load() }, [job.id])

  if (!rows) return <div style={{ padding: 32, textAlign: 'center' }}><Spin /></div>

  if (!rows.length) {
    return (
      <div style={{
        border: '1px dashed #e4e7ec', borderRadius: 10, padding: '20px 16px', textAlign: 'center',
        color: '#98a2b3', fontSize: 13, background: '#fcfcfd',
      }}>
        这个岗位还没有定制简历
        <div style={{ fontSize: 11.5, marginTop: 6 }}>
          让分析 Agent 用 job-match 判完再 resume.submit 生成；也可以到
          <a href="/resume" style={{ margin: '0 4px' }}>简历页</a>
          看全部版本
        </div>
      </div>
    )
  }

  const pick = async (id) => setCur(await get(`/api/resumes/${id}`))

  return (
    <div>
      <Space wrap style={{ marginBottom: 10 }}>
        {rows.length > 1 ? (
          <Select size="small" style={{ minWidth: 240 }} value={cur?.id} onChange={pick}
                  options={rows.map((r) => ({
                    value: r.id,
                    label: `${r.filename} · ${dayjs(r.created_at).format('MM-DD HH:mm')}`,
                  }))} />
        ) : null}
        {cur?.pdf_url ? (
          <Button size="small" type="primary" icon={<ExportOutlined />} href={cur.pdf_url} target="_blank">
            下载 PDF（无高亮）
          </Button>
        ) : <Tag color="orange">PDF 未生成</Tag>}
        <Button size="small" href="/resume" target="_blank">在简历页打开</Button>
        <span style={{ fontSize: 11.5, color: '#98a2b3' }}>
          {cur?.pdf_pages ? `PDF ${cur.pdf_pages} 页 · ` : ''}{cur?.changes?.length || 0} 处改动
        </span>
      </Space>

      <div style={{ maxHeight: 'calc(100vh - 330px)', overflow: 'auto', background: '#f5f6fa', borderRadius: 8 }}>
        <iframe title={`resume-${cur?.id}`} srcDoc={ready ? (cur?.html || '') : ''} sandbox=""
                style={{ width: '100%', minHeight: 760, border: 'none', background: '#fff' }} />
      </div>

      {cur?.changes?.length ? (
        <div style={{ marginTop: 10 }}>
          <Typography.Text strong style={{ fontSize: 13 }}>改动清单</Typography.Text>
          {cur.changes.map((c, i) => (
            <div key={i} style={{ fontSize: 12.5, lineHeight: 1.9, marginTop: 4 }}>
              <Tag color="gold" style={{ marginRight: 6 }}>{i + 1}</Tag>
              {c.where ? <b style={{ marginRight: 6 }}>{c.where}</b> : null}
              {c.before ? <span style={{ color: '#98a2b3', textDecoration: 'line-through' }}>{c.before}</span> : null}
              {c.before && c.after ? <span style={{ margin: '0 6px', color: '#98a2b3' }}>→</span> : null}
              {c.after ? <span>{c.after}</span> : null}
              {c.why ? <div style={{ color: '#667085', paddingLeft: 26 }}>为什么：{c.why}</div> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function FitPanel({ job }) {
  const rep = job.fit_report && typeof job.fit_report === 'object' ? job.fit_report : {}
  const verdict = FIT[job.fit_verdict]
  if (!job.fit_verdict && !job.fit_reason) {
    return (
      <div style={{
        border: '1px dashed #e4e7ec', borderRadius: 10, padding: '20px 16px', textAlign: 'center',
        color: '#98a2b3', fontSize: 13, background: '#fcfcfd',
      }}>
        这个岗位还没有匹配评估
        <div style={{ fontSize: 11.5, marginTop: 6 }}>
          让<b>分析 Agent</b> 跑一遍 job-match（拆 JD → 对照简历证据 → 结论），用 <span className="mono">job.fit</span> 写回来
        </div>
      </div>
    )
  }
  const reqs = rep.requirements || []
  const gates = rep.hard_gates || []
  const gaps = rep.gaps || []
  const strategy = rep.strategy || {}

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, marginBottom: 14 }}>
        <Tag color={verdict?.color} style={{ margin: 0, fontSize: 12 }}>{verdict?.label || '未给结论'}</Tag>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13.5, color: '#1d2939', lineHeight: 1.8 }}>{job.fit_reason || '（没有写理由）'}</div>
          <div style={{ fontSize: 11.5, color: '#98a2b3', marginTop: 4 }}>
            {job.fit_at ? `评估于 ${job.fit_at}` : ''}{rep.source ? ` · ${rep.source}` : ''}
          </div>
        </div>
      </div>

      {reqs.length ? (
        <>
          <Typography.Text strong style={{ fontSize: 13 }}>要求 — 证据矩阵</Typography.Text>
          <Table size="small" rowKey={(r, i) => i} pagination={false} style={{ marginTop: 6, marginBottom: 14 }}
                 dataSource={reqs}
                 columns={[
                   { title: 'JD 要求', dataIndex: 'req', width: '38%',
                     render: (v) => <span style={{ fontSize: 12.5 }}>{v}</span> },
                   { title: '重要性', dataIndex: 'importance', width: 74,
                     render: (v) => <Tag color={IMPORTANCE[v]?.color} style={{ margin: 0, fontSize: 10.5 }}>{IMPORTANCE[v]?.label || v}</Tag> },
                   { title: '我的证据', dataIndex: 'evidence', width: '28%',
                     render: (v) => <span style={{ fontSize: 12, color: v ? '#475467' : '#b9c0cc' }}>{v || '未提供'}</span> },
                   { title: '状态', dataIndex: 'status', width: 84,
                     render: (v) => <Tag color={FIT_STATUS[v]?.color} style={{ margin: 0, fontSize: 10.5 }}>{FIT_STATUS[v]?.label || v}</Tag> },
                   { title: '风险 / 下一步', dataIndex: 'risk',
                     render: (v) => <span style={{ fontSize: 12, color: '#667085' }}>{v || '-'}</span> },
                 ]} />
        </>
      ) : null}

      {gates.length ? (
        <>
          <Typography.Text strong style={{ fontSize: 13 }}>硬性门槛</Typography.Text>
          <div style={{ margin: '6px 0 14px' }}>
            {gates.map((g, i) => (
              <div key={i} style={{ fontSize: 12.5, lineHeight: 1.9 }}>
                <Tag color={g.status === 'pass' ? 'green' : g.status === 'fail' ? 'red' : 'default'}
                     style={{ marginRight: 6, fontSize: 10.5 }}>
                  {g.status === 'pass' ? '满足' : g.status === 'fail' ? '不满足' : '待确认'}
                </Tag>
                {g.item}{g.note ? <span style={{ color: '#98a2b3' }}> · {g.note}</span> : null}
              </div>
            ))}
          </div>
        </>
      ) : null}

      {gaps.length ? (
        <>
          <Typography.Text strong style={{ fontSize: 13 }}>优先补强</Typography.Text>
          <div style={{ margin: '6px 0 14px' }}>
            {gaps.map((g, i) => (
              <div key={i} style={{ fontSize: 12.5, lineHeight: 1.9 }}>
                <Tag color={{ phrasing: 'blue', evidence: 'orange', skill: 'purple' }[g.type] || 'default'}
                     style={{ marginRight: 6, fontSize: 10.5 }}>
                  {{ phrasing: '调表达', evidence: '补证据', skill: '补能力' }[g.type] || g.type}
                </Tag>
                {g.item}{g.action ? <span style={{ color: '#98a2b3' }}> → {g.action}</span> : null}
              </div>
            ))}
          </div>
        </>
      ) : null}

      {(strategy.resume_version || (strategy.confirm || []).length) ? (
        <>
          <Typography.Text strong style={{ fontSize: 13 }}>投递策略</Typography.Text>
          <div style={{ fontSize: 12.5, lineHeight: 1.9, marginTop: 6, color: '#475467' }}>
            {strategy.resume_version ? <div>简历版本：{strategy.resume_version}</div> : null}
            {(strategy.confirm || []).map((q, i) => <div key={i}>待确认：{q}</div>)}
          </div>
        </>
      ) : null}
    </div>
  )
}

function ScreenshotWall({ images }) {
  return (
    <div>
      <div style={{ fontSize: 12.5, color: '#667085', marginBottom: 6 }}>
        没采集到 JD 正文 · 下面是截图（点图可放大）
      </div>
      <Image.PreviewGroup>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {images.map((a) => (
            <div key={a.id}>
              <Image
                src={`/files/${a.rel_path}`}
                alt={a.filename}
                width="100%"
                preview={{ mask: null }}
                style={{
                  width: '100%', display: 'block', borderRadius: 10,
                  border: '1px solid #eef0f4', background: '#fafbfc',
                }}
                placeholder={<div style={{ height: 180, background: '#fafbfc', borderRadius: 10 }} />}
              />
              {a.caption ? (
                <div style={{ fontSize: 11.5, color: '#98a2b3', marginTop: 4 }}>{a.caption}</div>
              ) : null}
            </div>
          ))}
        </div>
      </Image.PreviewGroup>
    </div>
  )
}

function JdBlock({ title, text }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 12.5, color: '#667085', marginBottom: 6 }}>{title}</div>
      <div style={{
        whiteSpace: 'pre-wrap', fontSize: 13.5, lineHeight: 1.95, color: '#344054',
        background: '#fafbfc', border: '1px solid #f0f1f5', borderRadius: 10, padding: '14px 16px',
        wordBreak: 'break-word',
      }}>
        {text && text.trim() ? text : <span style={{ color: '#b9c0cc' }}>（该岗位没有采集到{title}）</span>}
      </div>
    </div>
  )
}

