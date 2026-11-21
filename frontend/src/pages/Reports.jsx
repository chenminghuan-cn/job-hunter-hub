import React, { useEffect, useState } from 'react'
import {
  Button, Card, Empty, Input, Modal, Select, Space, Table, Tag, Typography, App, DatePicker,
} from 'antd'
import { ReloadOutlined, CheckOutlined, CloseOutlined, CommentOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { get, patch, del } from '../api'

const KIND = {
  suggestion: { label: '建议', color: 'blue' },
  issue: { label: '问题', color: 'red' },
  data_quality: { label: '数据质量', color: 'orange' },
  question: { label: '提问', color: 'default' },
}
const STATUS = {
  open: { label: '待处理', color: 'gold' },
  accepted: { label: '已接受', color: 'green' },
  rejected: { label: '已驳回', color: 'default' },
  done: { label: '已结单', color: 'blue' },
}
const SEV = { low: { label: '低', color: 'default' }, normal: { label: '中', color: 'blue' }, high: { label: '高', color: 'red' } }

export default function Reports() {
  const { message } = App.useApp()
  const [rows, setRows] = useState([])
  const [status, setStatus] = useState('open')
  const [loading, setLoading] = useState(false)
  const [current, setCurrent] = useState(null)

  const load = () => {
    setLoading(true)
    get('/api/reports', { status: status || undefined })
      .then(setRows).catch((e) => message.error(e.message)).finally(() => setLoading(false))
  }
  useEffect(load, [status])

  const openCount = rows.filter((r) => r.status === 'open').length

  return (
    <>
      <Card styles={{ body: { padding: 16 } }}>
        <Space wrap style={{ marginBottom: 14 }}>
          <Select style={{ width: 150 }} value={status} onChange={setStatus}
                  options={[{ value: '', label: '全部状态' },
                            ...Object.entries(STATUS).map(([v, x]) => ({ value: v, label: x.label }))]} />
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          <span style={{ fontSize: 12.5, color: '#667085' }}>
            共 {rows.length} 条{status === 'open' ? `，待处理 ${openCount} 条` : ''}
          </span>
        </Space>

        <Table rowKey="id" size="middle" dataSource={rows} loading={loading}
               locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有诉求单，Agent 都很满意" /> }}
               columns={[
                 {
                   title: '诉求', dataIndex: 'title',
                   render: (t, r) => (
                     <div style={{ cursor: 'pointer' }} onClick={() => setCurrent(r)}>
                       <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                         <span style={{ fontWeight: 550 }}>{t}</span>
                         <Tag color={KIND[r.kind]?.color} style={{ margin: 0, fontSize: 10.5 }}>
                           {KIND[r.kind]?.label || r.kind}
                         </Tag>
                         {r.severity !== 'normal'
                           ? <Tag color={SEV[r.severity]?.color} style={{ margin: 0, fontSize: 10.5 }}>{SEV[r.severity]?.label}</Tag>
                           : null}
                       </div>
                       {r.content ? (
                         <div style={{ fontSize: 12, color: '#667085', marginTop: 2,
                                       overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 620 }}>
                           {r.content}
                         </div>
                       ) : null}
                     </div>
                   ),
                 },
                 { title: '来自', dataIndex: 'agent_id', width: 170,
                   render: (v) => <span className="mono" style={{ fontSize: 12 }}>{v}</span> },
                 { title: '指向', dataIndex: 'target', width: 150,
                   render: (v) => (v ? <span className="mono" style={{ fontSize: 12, color: '#667085' }}>{v}</span> : '-') },
                 {
                   title: '状态', dataIndex: 'status', width: 100,
                   render: (v) => <Tag color={STATUS[v]?.color} style={{ margin: 0 }}>{STATUS[v]?.label || v}</Tag>,
                 },
                 {
                   title: '提交时间', dataIndex: 'created_at', width: 130,
                   render: (v) => <span style={{ fontSize: 12, color: '#667085' }}>{dayjs(v).format('MM-DD HH:mm')}</span>,
                 },
                 {
                   title: '', width: 90, align: 'right',
                   render: (_, r) => <Button size="small" type="text" icon={<CommentOutlined />}
                                             onClick={() => setCurrent(r)}>处理</Button>,
                 },
               ]} />
      </Card>

      <ReportModal report={current} onClose={() => setCurrent(null)}
                   onSaved={() => { setCurrent(null); load() }} />
    </>
  )
}

function ReportModal({ report, onClose, onSaved }) {
  const { message } = App.useApp()
  const [response, setResponse] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => { if (report) setResponse(report.response || '') }, [report?.id])
  if (!report) return null

  const act = async (status) => {
    setSaving(true)
    try {
      await patch(`/api/reports/${report.id}`, { status, response })
      message.success(status === 'rejected' ? '已驳回' : status === 'done' ? '已结单' : '已接单')
      onSaved()
    } catch (e) { message.error(e.message) } finally { setSaving(false) }
  }
  const saveResp = async () => {
    setSaving(true)
    try {
      await patch(`/api/reports/${report.id}`, { response })
      message.success('回复已保存')
      onSaved()
    } catch (e) { message.error(e.message) } finally { setSaving(false) }
  }

  return (
    <Modal open onCancel={onClose} width={620} title={
      <Space size={8}>
        <span>{report.title}</span>
        <Tag color={STATUS[report.status]?.color} style={{ margin: 0 }}>{STATUS[report.status]?.label}</Tag>
      </Space>
    } footer={null}>
      <div style={{ fontSize: 12.5, color: '#667085', marginBottom: 12 }}>
        来自 <span className="mono">{report.agent_id}</span>
        {report.target ? <> · 指向 <span className="mono">{report.target}</span></> : null}
        {' · '}{dayjs(report.created_at).format('YYYY-MM-DD HH:mm')}
      </div>

      <div style={{
        whiteSpace: 'pre-wrap', fontSize: 13, lineHeight: 1.9, color: '#344054',
        background: '#fafbfc', border: '1px solid #f0f1f5', borderRadius: 10, padding: '12px 14px',
        marginBottom: 14,
      }}>
        {report.content || '（没有详细说明）'}
      </div>

      <div style={{ fontSize: 13, fontWeight: 550, marginBottom: 6 }}>处理说明（会回给提交方）</div>
      <Input.TextArea rows={4} value={response} onChange={(e) => setResponse(e.target.value)}
                      placeholder="例：已让 BOSS 采集侧加最低薪资校验，下轮生效" />

      <Space style={{ marginTop: 14 }} wrap>
        {report.status === 'open' ? (
          <>
            <Button type="primary" icon={<CheckOutlined />} loading={saving} onClick={() => act('accepted')}>接单</Button>
            <Button icon={<CloseOutlined />} loading={saving} onClick={() => act('rejected')}>驳回</Button>
            <Button loading={saving} onClick={() => act('done')}>直接结单</Button>
          </>
        ) : report.status === 'accepted' ? (
          <>
            <Button type="primary" loading={saving} onClick={() => act('done')}>结单</Button>
            <Button onClick={() => act('rejected')} loading={saving}>驳回</Button>
          </>
        ) : (
          <Button onClick={() => act('open')} loading={saving}>重新打开</Button>
        )}
        <Button onClick={saveResp} loading={saving}>只保存回复</Button>
        <Button type="text" onClick={onClose}>关闭</Button>
        <Button type="text" danger style={{ marginLeft: 'auto' }} loading={saving}
                onClick={async () => {
                  await del(`/api/reports/${report.id}`)
                  message.success('已删除')
                  onSaved()
                }}>删除</Button>
      </Space>
    </Modal>
  )
}
