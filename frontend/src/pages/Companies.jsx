import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Button, Card, Collapse, Drawer, Form, Input, Modal, Select, Space, Table, Tabs, Tag, Typography, App, Badge,
} from 'antd'
import { PlusOutlined, ReloadOutlined, LinkOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { get, patch, post } from '../api'
import { useMeta } from '../meta'
import { JobDrawer, PRESENCE } from '../components/JobDetail'
import ActivityLog from '../components/ActivityLog'
import StateSelect from '../components/StateSelect'

export default function Companies() {
  const { meta } = useMeta()
  const { message } = App.useApp()
  const [sp, setSp] = useSearchParams()
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [detail, setDetail] = useState(null)
  const [creating, setCreating] = useState(false)

  const filters = useMemo(() => ({
    q: sp.get('q') || '',
    state: sp.get('state') ? sp.get('state').split(',').filter(Boolean) : [],
  }), [sp])
  const setFilter = (k, v) => {
    const next = new URLSearchParams(sp)
    const val = Array.isArray(v) ? v.join(',') : v
    if (val) next.set(k, val); else next.delete(k)
    setSp(next, { replace: true })
    setPage(1)
  }

  // 记住上次筛选：URL 没带条件时用本地存的
  useEffect(() => {
    if (sp.toString()) return
    try {
      const saved = localStorage.getItem('jh_companies_filters')
      const obj = saved ? JSON.parse(saved) : null
      if (obj && Object.keys(obj).length) setSp(new URLSearchParams(obj), { replace: true })
    } catch { /* ignore */ }
  }, [])
  useEffect(() => {
    if (sp.toString()) localStorage.setItem('jh_companies_filters', JSON.stringify(Object.fromEntries(sp)))
  }, [sp])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await get('/api/companies', { ...filters, page, page_size: pageSize })
      setRows(r.items); setTotal(r.total)
    } catch (e) { message.error(e.message) } finally { setLoading(false) }
  }, [filters, page, pageSize])

  useEffect(() => { load() }, [load])

  const columns = [
    {
      title: '公司', dataIndex: 'name', width: 220,
      render: (v, r) => (
        <div style={{ cursor: 'pointer' }} onClick={() => setDetail(r)}>
          <div style={{ fontWeight: 550 }}>{v}</div>
          <div style={{ fontSize: 12, color: '#667085' }}>{[r.industry, r.stage].filter(Boolean).join(' · ') || '-'}</div>
        </div>
      ),
    },
    { title: '规模', dataIndex: 'scale', width: 130, render: (v) => v || '-' },
    {
      title: '标签', dataIndex: 'tags', width: 150,
      render: (t) => (t && t.length
        ? <Space size={[4, 4]} wrap>{t.map((x) => <Tag key={x} color="purple" style={{ margin: 0, fontSize: 11 }}>{x}</Tag>)}</Space>
        : <span style={{ color: '#bbb' }}>-</span>),
    },
    { title: '城市', dataIndex: 'city', width: 90, render: (v) => v || '-' },
    { title: '在库岗位', dataIndex: 'job_count', width: 96, render: (v) => <Badge count={v} showZero color="#6366f1" /> },
    { title: '联系人', dataIndex: 'contact_count', width: 90, render: (v) => <Badge count={v} showZero color="#8b5cf6" /> },
    {
      title: '状态', dataIndex: 'state', width: 110,
      render: (s, r) => <StateSelect machine="company" value={s} id={r.id} path="/api/companies"
                                     onChanged={() => { load(); setDetail(null) }} />,
    },
    {
      title: '更新时间', dataIndex: 'updated_at', width: 120,
      render: (v) => <span style={{ fontSize: 12, color: '#667085' }}>{dayjs(v).format('MM-DD HH:mm')}</span>,
    },
  ]

  return (
    <>
      <Card styles={{ body: { padding: 16 } }}>
        <Space wrap style={{ marginBottom: 14 }}>
          <Input.Search placeholder="搜索公司 / 行业 / 城市" allowClear defaultValue={filters.q}
                        style={{ width: 260 }} onSearch={(v) => setFilter('q', v)} />
          <Select mode="multiple" placeholder="状态" allowClear maxTagCount="responsive" style={{ minWidth: 140 }} value={filters.state}
                  onChange={(v) => setFilter('state', v)}
                  options={(meta?.machines.company.states || []).map((s) => ({ value: s.value, label: s.label }))} />
          <Button icon={<ReloadOutlined />} onClick={load} />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>新增公司</Button>
        </Space>
        <Table rowKey="id" size="middle" columns={columns} dataSource={rows} loading={loading}
               scroll={{ x: 900 }}
               pagination={{ current: page, pageSize, total, showSizeChanger: true, showTotal: (t) => `共 ${t} 家公司`,
                             onChange: (p, ps) => { setPage(p); setPageSize(ps) } }} />
      </Card>

      <CompanyDrawer company={detail} onClose={() => setDetail(null)}
                     onSaved={() => { load(); setDetail(null) }} />
      <CreateCompanyModal open={creating} onClose={() => setCreating(false)}
                          onCreated={() => { setCreating(false); load() }} />
    </>
  )
}

function CompanyDrawer({ company, onClose, onSaved }) {
  const { meta } = useMeta()
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [jobs, setJobs] = useState(null)
  const [jobDetail, setJobDetail] = useState(null)
  const [loading, setLoading] = useState(false)

  const channelOf = (code) => (meta?.channels || []).find((c) => c.code === code)

  const loadJobs = () => {
    if (!company) return
    setLoading(true)
    get('/api/jobs', { company_id: company.id, page_size: 100, sort: 'first_seen_at' })
      .then((r) => setJobs(r.items))
      .catch((e) => message.error(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (company) { form.setFieldsValue(company); setJobs(null); loadJobs() }
  }, [company?.id])

  if (!company) return null

  const save = async () => {
    try {
      await patch(`/api/companies/${company.id}`, await form.validateFields())
      message.success('已保存')
      onSaved()
    } catch (e) { message.error(e.message) }
  }

  const KPI = ({ label, children }) => (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ fontSize: 11.5, color: '#98a2b3' }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 550, color: '#1d2939', marginTop: 2 }}>{children}</div>
    </div>
  )

  const columns = [
    {
      title: '岗位', dataIndex: 'title',
      render: (t, r) => (
        <div style={{ cursor: 'pointer' }} onClick={() => setJobDetail(r)}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap' }}>
            <span style={{ color: '#1d2939' }}>{t}</span>
            {(r.tags || []).map((x) => (
              <Tag key={x} color="purple" style={{ margin: 0, fontSize: 10.5, lineHeight: '17px' }}>{x}</Tag>
            ))}
            {r.att_count ? <span style={{ fontSize: 11, color: '#98a2b3' }}>📎 {r.att_count}</span> : null}
          </div>
        </div>
      ),
    },
    {
      title: '薪资', dataIndex: 'salary_raw', width: 120,
      render: (v) => <span style={{ color: '#d97706', fontSize: 12.5 }}>{v || '面议'}</span>,
    },
    { title: '城市', dataIndex: 'city', width: 80, render: (v) => v || '-' },
    {
      title: '状态', dataIndex: 'state', width: 104,
      render: (v, r) => <StateSelect machine="job" value={v} id={r.id} path="/api/jobs"
                                     onChanged={() => { loadJobs(); onSaved() }} />,
    },
    {
      title: '在招', dataIndex: 'open_days', width: 100,
      render: (d, r) => {
        const p = PRESENCE[r.presence] || PRESENCE.open
        return (
          <Space size={4} style={{ whiteSpace: 'nowrap' }}>
            <Tag color={p.color} style={{ margin: 0, fontSize: 10.5 }}>{p.label}</Tag>
            <span style={{ fontSize: 12, color: '#667085' }}>{d ?? 0} 天</span>
          </Space>
        )
      },
    },
  ]

  return (
    <>
      <Drawer width={720} open onClose={onClose} styles={{ body: { paddingTop: 16 } }} title={
        <Space size={8} wrap>
          <span style={{ fontSize: 15, fontWeight: 600 }}>{company.name}</span>
          <StateSelect machine="company" value={company.state} id={company.id} path="/api/companies" onChanged={onSaved} />
          {(company.tags || []).map((t) => <Tag key={t} color="purple" style={{ margin: 0, fontSize: 11 }}>{t}</Tag>)}
        </Space>
      }>
        <div style={{
          display: 'flex', gap: 16, padding: '12px 14px', background: '#fafbfc',
          border: '1px solid #f0f1f5', borderRadius: 10,
        }}>
          <KPI label="在库岗位"><span style={{ color: '#4f46e5' }}>{jobs?.length ?? company.job_count ?? 0}</span></KPI>
          <KPI label="联系人">{company.contact_count ?? 0}</KPI>
          <KPI label="行业">{company.industry || '-'}</KPI>
          <KPI label="规模">{company.scale || '-'}</KPI>
          <KPI label="融资">{company.stage || '-'}</KPI>
          <KPI label="城市">{company.city || '-'}</KPI>
        </div>

        <Tabs size="small" style={{ marginTop: 12 }} items={[{
          key: 'jobs',
          label: `岗位 ${jobs?.length ?? ''}`.trim(),
          children: (
            <>
              <div style={{ marginBottom: 8, fontSize: 11.5, color: '#98a2b3' }}>
                点岗位名看 JD / 截图
                {company.website ? (
                  <a href={company.website} target="_blank" rel="noreferrer" style={{ marginLeft: 10 }}>官网</a>
                ) : null}
              </div>
              <Table rowKey="id" size="small" columns={columns} dataSource={jobs || []} loading={loading}
                     pagination={(jobs?.length || 0) > 10 ? { pageSize: 10, size: 'small' } : false}
                     locale={{ emptyText: '这家公司还没有岗位记录' }} />
            </>
          ),
        }, {
          key: 'log',
          label: '操作日志',
          children: <ActivityLog entity="company" entityId={company.id} />,
        }, {
          key: 'info',
          label: '公司信息',
          children: (
            <Form form={form} layout="vertical" size="middle">
              <Form.Item name="industry" label="行业"><Input /></Form.Item>
              <Form.Item name="tags" label="标签（回车新增）">
                <Select mode="tags" placeholder="目标公司 / 外企 / 已投过" tokenSeparators={[',', ' ']}
                        options={['目标公司', '外企', '大厂', '已投过', '已拉黑'].map((t) => ({ value: t, label: t }))} />
              </Form.Item>
              <Space.Compact block>
                <Form.Item name="scale" label="规模" style={{ flex: 1 }}><Input placeholder="500-2000人" /></Form.Item>
                <Form.Item name="stage" label="融资阶段" style={{ flex: 1, marginLeft: 10 }}><Input placeholder="B轮 / 已上市" /></Form.Item>
              </Space.Compact>
              <Space.Compact block>
                <Form.Item name="city" label="城市" style={{ flex: 1 }}><Input /></Form.Item>
                <Form.Item name="website" label="官网" style={{ flex: 2, marginLeft: 10 }}><Input /></Form.Item>
              </Space.Compact>
              <Form.Item name="notes" label="备注 / 背调信息"><Input.TextArea rows={4} /></Form.Item>
              <Button type="primary" onClick={save}>保存修改</Button>
            </Form>
          ),
        }]} />
      </Drawer>

      <JobDrawer job={jobDetail} channelOf={channelOf} onClose={() => setJobDetail(null)}
                 onListChange={loadJobs} onSaved={() => { setJobDetail(null); loadJobs() }} />
    </>
  )
}

function CreateCompanyModal({ open, onClose, onCreated }) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const submit = async () => {
    const v = await form.validateFields()
    setSaving(true)
    try {
      await post('/api/companies', v)
      message.success('已新增')
      form.resetFields()
      onCreated()
    } catch (e) { message.error(e.message) } finally { setSaving(false) }
  }
  return (
    <Modal open={open} onCancel={onClose} onOk={submit} confirmLoading={saving} title="新增公司" okText="新增" width={500}>
      <Form form={form} layout="vertical" size="middle">
        <Form.Item name="name" label="公司名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Space.Compact block>
          <Form.Item name="industry" label="行业" style={{ flex: 1 }}><Input /></Form.Item>
          <Form.Item name="city" label="城市" style={{ flex: 1, marginLeft: 10 }}><Input /></Form.Item>
        </Space.Compact>
        <Space.Compact block>
          <Form.Item name="scale" label="规模" style={{ flex: 1 }}><Input /></Form.Item>
          <Form.Item name="stage" label="融资阶段" style={{ flex: 1, marginLeft: 10 }}><Input /></Form.Item>
        </Space.Compact>
        <Form.Item name="website" label="官网"><Input /></Form.Item>
        <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
      </Form>
    </Modal>
  )
}
