import React, { useEffect, useMemo, useState } from 'react'
import {
  Button, Card, Col, Empty, Popconfirm, Row, Space, Tag, App, Skeleton, Typography,
} from 'antd'
import { DeleteOutlined, DownloadOutlined, ReloadOutlined, FileTextOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { get, del, post } from '../api'

export default function Resume() {
  const { message } = App.useApp()
  const [list, setList] = useState(null)
  const [current, setCurrent] = useState(null)
  const [source, setSource] = useState(null)
  const [ready, setReady] = useState(false)

  const open = async (row) => {
    if (!row) return
    const full = await get(`/api/resumes/${row.id}`)
    setCurrent(full)
  }

  // 列表接口不带 html（太大），选中项单独拉全文
  const load = () => get('/api/resumes').then(async (rows) => {
    setList(rows)
    const pick = rows.find((r) => r.id === current?.id) || rows[0]
    if (pick) await open(pick)
    else setCurrent(null)
  }).catch((e) => message.error(e.message))

  useEffect(() => { load() }, [])
  useEffect(() => {
    setReady(false)
    const t = setTimeout(() => setReady(true), 120)
    return () => clearTimeout(t)
  }, [current?.id])
  useEffect(() => {
    get('/api/resume-source').then((s) => {
      const { html, ...rest } = s || {}
      setSource({ ...rest, bytes: html ? html.length : 0 })
    }).catch(() => {})
  }, [])

  if (!list) return <Skeleton active paragraph={{ rows: 10 }} />

  return (
    <>
      <Card size="small" style={{ marginBottom: 14 }}
            title={<Space size={8}>
              <span style={{ fontSize: 13 }}>基准简历</span>
              {source?.source
                ? <Tag color="green">已就位 · {source.name || '未命名'} · {Math.round((source.bytes || 0) / 1024)} KB</Tag>
                : <Tag color="orange">还没有，Agent 改简历没有事实依据</Tag>}
            </Space>}
            extra={
              <label>
                <input type="file" accept=".html,.htm" style={{ display: 'none' }}
                       onChange={async (e) => {
                         const f = e.target.files?.[0]
                         if (!f) return
                         const html = await f.text()
                         await post('/api/resume-source', { name: f.name, html })
                         message.success('基准简历已上传')
                         const s = await get('/api/resume-source')
                         setSource({ ...s, bytes: (s.html || '').length })
                         e.target.value = ''
                       }} />
                <Button size="small">{source?.source ? '替换' : '上传 HTML'}</Button>
              </label>
            }>
        <div style={{ fontSize: 12, color: '#667085' }}>
          {source?.source
            ? <>来源：<span className="mono">{source.path || source.name}</span> · {source.created_at || ''}</>
            : '把原始简历 HTML 拖进来（或上传），分析 Agent 就能通过 resume.source 读到它，只改措辞不动事实。'}
        </div>
      </Card>

      {!list.length ? (
        <Card>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={
            <span>还没有定制简历。让分析 Agent 针对某个岗位生成一版（它会调 resume.submit）</span>
          } />
        </Card>
      ) : (
        <Row gutter={14}>
          <Col xs={24} lg={7}>
            <Card title="版本列表" size="small" extra={<Button size="small" icon={<ReloadOutlined />} onClick={load} />}
                  styles={{ body: { padding: 8, maxHeight: 'calc(100vh - 220px)', overflow: 'auto' } }}>
              {list.map((r) => (
                <div key={r.id} onClick={() => open(r)} style={{
                  padding: '10px 12px', borderRadius: 8, cursor: 'pointer', marginBottom: 6,
                  background: current?.id === r.id ? '#eef2ff' : 'transparent',
                  border: `1px solid ${current?.id === r.id ? '#c7d2fe' : 'transparent'}`,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <FileTextOutlined style={{ color: '#4f46e5' }} />
                    <span style={{ fontWeight: 550, fontSize: 13 }}>{r.role || '未命名方向'}</span>
                    {r.company ? <Tag style={{ margin: 0, fontSize: 10.5 }}>{r.company}</Tag> : null}
                  </div>
                  <div style={{ fontSize: 11.5, color: '#98a2b3', marginTop: 3 }}>
                    {dayjs(r.created_at).format('MM-DD HH:mm')} · {r.changes?.length || 0} 处改动
                    {r.pdf_url ? '' : ' · PDF 未生成'}
                  </div>
                </div>
              ))}
            </Card>
          </Col>

          <Col xs={24} lg={17}>
            {current ? (
              <Card
                size="small"
                title={
                  <Space size={8} wrap>
                    <span style={{ fontWeight: 600 }}>{current.role || '定制简历'}</span>
                    {current.company ? <Tag color="blue" style={{ margin: 0 }}>{current.company}</Tag> : null}
                    <span className="mono" style={{ fontSize: 11.5, color: '#98a2b3' }}>{current.filename}.pdf</span>
                  </Space>
                }
                extra={
                  <Space size={6}>
                    {current.pdf_url ? (
                      <Button size="small" type="primary" icon={<DownloadOutlined />} href={current.pdf_url} target="_blank">
                        下载 PDF（无高亮）
                      </Button>
                    ) : (
                      <Tag color="orange">PDF 尚未生成</Tag>
                    )}
                    <Popconfirm title="删除这个版本？" onConfirm={async () => {
                      await del(`/api/resumes/${current.id}`)
                      message.success('已删除')
                      setCurrent(null)
                      load()
                    }}>
                      <Button size="small" danger type="text" icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </Space>
                }
                styles={{ body: { padding: 0 } }}
              >
                <div style={{ maxHeight: 'calc(100vh - 260px)', overflow: 'auto', background: '#f5f6fa' }}>
                  <iframe
                    title="resume-preview"
                    srcDoc={ready ? current.html : ''}
                    sandbox=""
                    style={{ width: '100%', minHeight: 900, border: 'none', background: '#fff' }}
                  />
                </div>
              </Card>
            ) : <Card><Skeleton active /></Card>}
          </Col>
        </Row>
      )}

      {current?.changes?.length ? (
        <Card size="small" style={{ marginTop: 14 }} title={`这次改了 ${current.changes.length} 处（PDF 里不带高亮）`}>
          {current.changes.map((c, i) => (
            <div key={i} style={{ fontSize: 12.5, lineHeight: 1.9, marginBottom: 6 }}>
              <Tag color="gold" style={{ marginRight: 6 }}>{i + 1}</Tag>
              {c.where ? <b style={{ marginRight: 6 }}>{c.where}</b> : null}
              {c.before ? <span style={{ color: '#98a2b3', textDecoration: 'line-through' }}>{c.before}</span> : null}
              {c.before && c.after ? <span style={{ margin: '0 6px', color: '#98a2b3' }}>→</span> : null}
              {c.after ? <span style={{ color: '#1d2939' }}>{c.after}</span> : null}
              {c.why ? <div style={{ color: '#667085', paddingLeft: 26 }}>为什么：{c.why}</div> : null}
            </div>
          ))}
        </Card>
      ) : null}
    </>
  )
}
