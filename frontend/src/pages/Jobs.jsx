import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Button, Card, Descriptions, Drawer, Form, Input, InputNumber, Modal, Popconfirm,
  Select, Space, Table, Tag, Tooltip, Typography, App, Divider, Collapse, Empty, Alert, Image, Spin,
} from 'antd'
import {
  PlusOutlined, ReloadOutlined, DeleteOutlined, CopyOutlined, EditOutlined,
  ArrowUpOutlined, ArrowDownOutlined,
  ExportOutlined, PaperClipOutlined, UploadOutlined, CloseOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { get, patch, post, del } from '../api'
import { useMeta, stateInfo, stateOptions } from '../meta'
import ChannelLogo from '../components/ChannelLogo'
import StateSelect from '../components/StateSelect'

import { JobDrawer, PRIORITY, PRESENCE, FIT, ago } from '../components/JobDetail'

export default function Jobs() {
  const { meta, reload } = useMeta()
  const { message } = App.useApp()
  const [sp, setSp] = useSearchParams()
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [detail, setDetail] = useState(null)
  const [creating, setCreating] = useState(false)
  const [facets, setFacets] = useState({ tags: [], cities: [] })

  const channelOf = useCallback((code) => (meta?.channels || []).find((c) => c.code === code), [meta])
  const csv = (k) => (sp.get(k) ? sp.get(k).split(',').filter(Boolean) : [])
  const filters = useMemo(() => ({
    q: sp.get('q') || '',
    channel: csv('channel'),
    state: csv('state'),
    city: sp.get('city') || '',
    tag: sp.get('tag') || '',
    presence: csv('presence'),
    fit: csv('fit'),
    priority: csv('priority'),
    sort: sp.get('sort') || 'created_at',
    order: sp.get('order') || 'desc',
  }), [sp])

  // 记住上次的筛选：URL 里没有筛选条件时，用本地存的
  useEffect(() => {
    if (sp.toString()) return
    try {
      const saved = localStorage.getItem('jh_jobs_filters')
      const obj = saved ? JSON.parse(saved) : null
      if (obj && Object.keys(obj).length) setSp(new URLSearchParams(obj), { replace: true })
    } catch { /* ignore */ }
  }, [])

  // URL 里的筛选（含从别处带参进来、浏览器前进后退）都记下来
  useEffect(() => {
    if (!sp.toString()) return
    localStorage.setItem('jh_jobs_filters', JSON.stringify(Object.fromEntries(sp)))
  }, [sp])

  const setFilter = (k, v) => {
    const next = new URLSearchParams(sp)
    const val = Array.isArray(v) ? v.join(',') : v
    if (val) next.set(k, val); else next.delete(k)
    setSp(next, { replace: true })
    localStorage.setItem('jh_jobs_filters', JSON.stringify(Object.fromEntries(next)))
    setPage(1)
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await get('/api/jobs', { ...filters, page, page_size: pageSize })
      setRows(r.items)
      setTotal(r.total)
    } catch (e) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }, [filters, page, pageSize])

  useEffect(() => { load() }, [load])

  // 列表里已经带了 JD 等全部字段：先用行数据瞬间开抽屉，再去后台补最新值
  useEffect(() => { get('/api/facets').then(setFacets).catch(() => {}) }, [])

  const openDetail = (row) => {
    setDetail(row)
    get(`/api/jobs/${row.id}`)
      .then((fresh) => setDetail((cur) => (cur && cur.id === fresh.id ? { ...cur, ...fresh } : cur)))
      .catch(() => {})
  }

  const columns = [
    {
      title: '岗位', dataIndex: 'title', width: '30%',
      render: (t, r) => (
        <div style={{ cursor: 'pointer' }} onClick={() => openDetail(r)}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 550, color: '#1d2939' }}>{t}</span>
            {(r.tags || []).map((tag) => (
              <Tag key={tag} color="purple" style={{ margin: 0, fontSize: 10.5, lineHeight: '17px' }}>{tag}</Tag>
            ))}
            {r.att_count ? (
              <span style={{ fontSize: 11, color: '#98a2b3' }}><PaperClipOutlined /> {r.att_count}</span>
            ) : null}
            {r.fit_verdict ? (
              <Tooltip title={r.fit_reason || ''} placement="top">
                <Tag color={FIT[r.fit_verdict]?.color} style={{ margin: 0, fontSize: 10.5 }}>
                  {FIT[r.fit_verdict]?.label}
                </Tag>
              </Tooltip>
            ) : null}
          </div>
          <div style={{ fontSize: 12, color: '#667085' }}>{r.company_name}{r.publisher_name ? ` · ${r.publisher_name}` : ''}</div>
        </div>
      ),
    },
    {
      title: '渠道', dataIndex: 'channel_code', width: 120,
      render: (c) => <ChannelLogo channel={channelOf(c)} size={18} name={false} />,
    },
    {
      title: '薪资', dataIndex: 'salary_raw', width: 130,
      render: (v, r) => (
        <div>
          <div style={{ color: '#d97706', fontWeight: 500 }}>{v || '面议'}</div>
          {r.salary_min ? <div style={{ fontSize: 11, color: '#98a2b3' }}>{Math.round(r.salary_min / 1000)}k–{Math.round(r.salary_max / 1000)}k</div> : null}
        </div>
      ),
    },
    { title: '城市', dataIndex: 'city', width: 90, render: (v, r) => v ? `${v}${r.district ? '·' + r.district : ''}` : '-' },
    {
      title: '状态', dataIndex: 'state', width: 120,
      render: (s, r) => (
        <StateSelect machine="job" value={s} id={r.id} path="/api/jobs"
                     onChanged={() => { load(); setDetail(null) }} />
      ),
    },
    {
      title: '优先', dataIndex: 'priority', width: 78,
      render: (p) => { const x = PRIORITY[p] || PRIORITY[3]; return <Tag color={x.color}>{x.label}</Tag> },
    },
    {
      title: '在招', dataIndex: 'open_days', width: 132,
      render: (d, r) => {
        const p = PRESENCE[r.presence] || PRESENCE.open
        return (
          <div style={{ whiteSpace: 'nowrap' }}>
            <Space size={5}>
              <Tag color={p.color} style={{ margin: 0, fontSize: 11 }}>{p.label}</Tag>
              <span style={{ fontSize: 12.5, color: '#475467' }}>{d ?? 0} 天</span>
            </Space>
            <div style={{ fontSize: 11, color: '#98a2b3', marginTop: 2 }}>最后确认 {ago(r.last_seen_at)}</div>
          </div>
        )
      },
    },
    {
      title: '', width: 44, align: 'right', fixed: 'right',
      render: (_, r) => (
        <Popconfirm title="删除这个岗位？" onConfirm={async () => { await del(`/api/jobs/${r.id}`); message.success('已删除'); load() }}>
          <Button type="text" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ]

  return (
    <>
      <Card styles={{ body: { padding: 16 } }}>
        <Space wrap style={{ marginBottom: 14, width: '100%' }}>
          <Input.Search placeholder="搜索岗位 / 公司 / 描述" allowClear defaultValue={filters.q}
                        style={{ width: 260 }} onSearch={(v) => setFilter('q', v)} />
          <Select mode="multiple" placeholder="渠道" allowClear maxTagCount="responsive" style={{ minWidth: 140 }} value={filters.channel}
                  onChange={(v) => setFilter('channel', v)}
                  options={(meta?.channels || []).map((c) => ({
                    value: c.code,
                    label: <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                      <img src={c.logo} width={16} height={16} style={{ borderRadius: 3 }} />{c.name}</span>,
                  }))} />
          <Select mode="multiple" placeholder="状态" allowClear maxTagCount="responsive" style={{ minWidth: 140 }} value={filters.state}
                  onChange={(v) => setFilter('state', v)} options={stateOptions(meta, 'job', true)} />
          <Input placeholder="城市" allowClear style={{ width: 100 }} defaultValue={filters.city}
                 onPressEnter={(e) => setFilter('city', e.target.value)} onBlur={(e) => setFilter('city', e.target.value)} />
          <Select mode="multiple" placeholder="标签" allowClear maxTagCount="responsive"
                  style={{ minWidth: 150 }} value={filters.tag} showSearch
                  filterOption={(input, opt) => String(opt.label).includes(input)}
                  onChange={(v) => setFilter('tag', v)}
                  options={(facets.tags || []).map((t) => ({
                    value: t.value, label: `${t.value} (${t.count})`,
                  }))} />
          <Select mode="multiple" placeholder="优先级" allowClear maxTagCount="responsive"
                  style={{ minWidth: 120 }} value={filters.priority}
                  onChange={(v) => setFilter('priority', v)}
                  options={[{ value: '1', label: 'P1 高' }, { value: '2', label: 'P2 中' },
                            { value: '3', label: 'P3 低' }]} />
          <Select style={{ width: 132 }} value={filters.sort} onChange={(v) => setFilter('sort', v)}
                  options={[{ value: 'created_at', label: '按收集时间' },
                            { value: 'priority', label: '按优先级' },
                            { value: 'match_score', label: '按匹配度' },
                            { value: 'open_days', label: '按在招天数' },
                            { value: 'updated_at', label: '按更新时间' }]} />
          <Button icon={filters.order === 'asc' ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
                  onClick={() => setFilter('order', filters.order === 'asc' ? 'desc' : 'asc')}>
            {filters.order === 'asc' ? '升序' : '降序'}
          </Button>
          <Select mode="multiple" placeholder="评估" allowClear maxTagCount="responsive" style={{ minWidth: 120 }} value={filters.fit}
                  onChange={(v) => setFilter('fit', v)}
                  options={[{ value: 'none', label: '未评估' },
                            ...Object.entries(FIT).map(([v, x]) => ({ value: v, label: x.label }))]} />
          <Select mode="multiple" placeholder="在招状态" allowClear maxTagCount="responsive" style={{ minWidth: 120 }} value={filters.presence}
                  onChange={(v) => setFilter('presence', v)}
                  options={[{ value: 'open', label: '在招' }, { value: 'stale', label: '疑似下架' },
                            { value: 'gone', label: '已下架' }]} />
          <div style={{ flex: 1 }} />
          <Button icon={<ReloadOutlined />} onClick={load} />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>手动新增</Button>
        </Space>
        <Table
          rowKey="id" size="middle" columns={columns} dataSource={rows} loading={loading}
          pagination={{
            current: page, pageSize, total, showSizeChanger: true,
            showTotal: (t) => `共 ${t} 个岗位`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
          }}
          scroll={{ x: 'max-content' }}
        />
      </Card>

      <JobDrawer job={detail} channelOf={channelOf} onClose={() => setDetail(null)}
                 onListChange={load}
                 onSaved={() => { load(); setDetail(null) }} />
      <CreateJobModal open={creating} onClose={() => setCreating(false)}
                      onCreated={() => { setCreating(false); load(); reload() }} />
    </>
  )
}

function CreateJobModal({ open, onClose, onCreated }) {
  const { meta } = useMeta()
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    const v = await form.validateFields()
    setSaving(true)
    try {
      await post('/api/jobs', v)
      message.success('已新增')
      form.resetFields()
      onCreated()
    } catch (e) { message.error(e.message) } finally { setSaving(false) }
  }

  return (
    <Modal open={open} onCancel={onClose} onOk={submit} confirmLoading={saving} title="手动新增岗位" width={560} okText="新增">
      <Form form={form} layout="vertical" size="middle" initialValues={{ priority: 2 }}>
        <Space.Compact block>
          <Form.Item name="channel" label="渠道" rules={[{ required: true }]} style={{ flex: 1 }}>
            <Select placeholder="选择信息源" options={(meta?.channels || []).map((c) => ({ value: c.code, label: c.name }))} />
          </Form.Item>
          <Form.Item name="source_job_id" label="源 ID（可空）" style={{ flex: 1, marginLeft: 10 }}>
            <Input placeholder="渠道内的岗位 ID" />
          </Form.Item>
        </Space.Compact>
        <Form.Item name="title" label="岗位名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="company_name" label="公司" rules={[{ required: true }]}><Input /></Form.Item>
        <Space.Compact block>
          <Form.Item name="salary_raw" label="薪资" style={{ flex: 1 }}><Input placeholder="30-55K·15薪" /></Form.Item>
          <Form.Item name="city" label="城市" style={{ flex: 1, marginLeft: 10 }}><Input /></Form.Item>
          <Form.Item name="priority" label="优先级" style={{ width: 100, marginLeft: 10 }}>
            <Select options={Object.entries(PRIORITY).map(([v, x]) => ({ value: +v, label: x.label }))} />
          </Form.Item>
        </Space.Compact>
        <Form.Item name="url" label="链接"><Input /></Form.Item>
        <Form.Item name="description" label="描述"><Input.TextArea rows={3} /></Form.Item>
      </Form>
    </Modal>
  )
}
