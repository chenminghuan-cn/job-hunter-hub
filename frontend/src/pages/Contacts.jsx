import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Button, Card, Descriptions, Drawer, Form, Input, Modal, Popconfirm, Select, Space,
  Table, Tabs, Tag, App, Divider, DatePicker, Empty,
} from 'antd'
import { PlusOutlined, ReloadOutlined, CopyOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { get, patch, post } from '../api'
import { useMeta, stateInfo } from '../meta'
import ChannelLogo from '../components/ChannelLogo'
import StateSelect from '../components/StateSelect'
import ActivityLog from '../components/ActivityLog'

const TYPE_COLOR = { hr: 'blue', headhunter: 'purple', referral: 'green', interviewer: 'cyan', other: 'default' }

export default function Contacts() {
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

  const filters = useMemo(() => ({
    q: sp.get('q') || '',
    type: sp.get('type') ? sp.get('type').split(',').filter(Boolean) : [],
    state: sp.get('state') ? sp.get('state').split(',').filter(Boolean) : [],
  }), [sp])

  const setFilter = (k, v) => {
    const next = new URLSearchParams(sp)
    const val = Array.isArray(v) ? v.join(',') : v
    if (val) next.set(k, val); else next.delete(k)
    setSp(next, { replace: true })
    setPage(1)
  }
  const typeLabel = (t) => (meta?.contact_types || []).find((x) => x.value === t)?.label || t
  const channelOf = (code) => (meta?.channels || []).find((c) => c.code === code)

  // 记住上次筛选：URL 没带条件时用本地存的
  useEffect(() => {
    if (sp.toString()) return
    try {
      const saved = localStorage.getItem('jh_contacts_filters')
      const obj = saved ? JSON.parse(saved) : null
      if (obj && Object.keys(obj).length) setSp(new URLSearchParams(obj), { replace: true })
    } catch { /* ignore */ }
  }, [])
  useEffect(() => {
    if (sp.toString()) localStorage.setItem('jh_contacts_filters', JSON.stringify(Object.fromEntries(sp)))
  }, [sp])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await get('/api/contacts', { ...filters, page, page_size: pageSize })
      setRows(r.items); setTotal(r.total)
    } catch (e) { message.error(e.message) } finally { setLoading(false) }
  }, [filters, page, pageSize])

  useEffect(() => { load() }, [load])

  const columns = [
    {
      title: '联系人', dataIndex: 'name', width: 180,
      render: (v, r) => (
        <div style={{ cursor: 'pointer' }} onClick={() => setDetail(r)}>
          <div style={{ fontWeight: 550 }}>{v}</div>
          <div style={{ fontSize: 12, color: '#667085' }}>{r.title || '-'}</div>
        </div>
      ),
    },
    { title: '类型', dataIndex: 'type', width: 88, render: (t) => <Tag color={TYPE_COLOR[t]}>{typeLabel(t)}</Tag> },
    { title: '公司', dataIndex: 'company_name', width: 140, render: (v) => v || '-' },
    {
      title: '联系方式', width: 210,
      render: (_, r) => (
        <div style={{ fontSize: 12, lineHeight: 1.7 }}>
          {r.wechat ? <div>微信 <span className="mono">{r.wechat}</span></div> : null}
          {r.email ? <div className="mono">{r.email}</div> : null}
          {r.phone ? <div className="mono">{r.phone}</div> : null}
          {!r.wechat && !r.email && !r.phone ? <span style={{ color: '#bbb' }}>-</span> : null}
        </div>
      ),
    },
    { title: '来源', dataIndex: 'channel_code', width: 90, render: (c) => <ChannelLogo channel={channelOf(c)} size={18} name={false} /> },
    {
      title: '状态', dataIndex: 'state', width: 110,
      render: (s, r) => <StateSelect machine="contact" value={s} id={r.id} path="/api/contacts"
                                     onChanged={() => { load(); setDetail(null) }} />,
    },
    {
      title: '最近联系', dataIndex: 'last_contact_at', width: 120,
      render: (v) => <span style={{ fontSize: 12, color: v ? '#475467' : '#bbb' }}>{v ? dayjs(v).format('MM-DD HH:mm') : '未联系'}</span>,
    },
  ]

  return (
    <>
      <Card styles={{ body: { padding: 16 } }}>
        <Space wrap style={{ marginBottom: 14 }}>
          <Input.Search placeholder="搜索姓名 / 公司 / 微信 / 邮箱" allowClear defaultValue={filters.q}
                        style={{ width: 260 }} onSearch={(v) => setFilter('q', v)} />
          <Select mode="multiple" placeholder="联系人类型" allowClear maxTagCount="responsive" style={{ minWidth: 150 }} value={filters.type}
                  onChange={(v) => setFilter('type', v)} options={meta?.contact_types} />
          <Select mode="multiple" placeholder="状态" allowClear maxTagCount="responsive" style={{ minWidth: 130 }} value={filters.state}
                  onChange={(v) => setFilter('state', v)}
                  options={(meta?.machines.contact.states || []).map((s) => ({ value: s.value, label: s.label }))} />
          <Button icon={<ReloadOutlined />} onClick={load} />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>新增联系人</Button>
        </Space>
        <Table rowKey="id" size="middle" columns={columns} dataSource={rows} loading={loading}
               scroll={{ x: 940 }}
               pagination={{ current: page, pageSize, total, showSizeChanger: true, showTotal: (t) => `共 ${t} 位联系人`,
                             onChange: (p, ps) => { setPage(p); setPageSize(ps) } }} />
      </Card>

      <ContactDrawer contact={detail} onClose={() => setDetail(null)}
                     onSaved={() => { load(); setDetail(null); reload() }} />
      <CreateContactModal open={creating} onClose={() => setCreating(false)}
                          onCreated={() => { setCreating(false); load() }} />
    </>
  )
}

function ContactDrawer({ contact, onClose, onSaved }) {
  const { meta } = useMeta()
  const { message } = App.useApp()
  const [form] = Form.useForm()

  useEffect(() => {
    if (contact) {
      form.setFieldsValue({
        ...contact,
        last_contact_at: contact.last_contact_at ? dayjs(contact.last_contact_at) : null,
      })
    }
  }, [contact])

  if (!contact) return null
  const save = async () => {
    try {
      const v = await form.validateFields()
      await patch(`/api/contacts/${contact.id}`, {
        ...v,
        last_contact_at: v.last_contact_at ? v.last_contact_at.format('YYYY-MM-DD HH:mm:ss') : null,
      })
      message.success('已保存')
      onSaved()
    } catch (e) { message.error(e.message) }
  }
  const copy = (t) => { navigator.clipboard?.writeText(t); message.success('已复制') }

  return (
    <Drawer width={560} open onClose={onClose} title={
      <Space>
        {contact.name}
        <StateSelect machine="contact" value={contact.state} id={contact.id} path="/api/contacts" onChanged={onSaved} />
      </Space>
    }>
      <Tabs size="small" items={[{
        key: 'detail',
        label: '详情',
        children: (<>
      <Descriptions column={2} size="small" bordered items={[
        { key: 'type', label: '类型', children: (meta?.contact_types || []).find((x) => x.value === contact.type)?.label || contact.type },
        { key: 'company', label: '公司', children: contact.company_name || '-' },
        { key: 'channel', label: '来源渠道', children: <ChannelLogo channel={(meta?.channels || []).find((c) => c.code === contact.channel_code)} size={16} /> },
        { key: 'last', label: '最近联系', children: contact.last_contact_at || '未联系' },
        {
          key: 'wechat', label: '微信', children: contact.wechat
            ? <Space size={4}>{contact.wechat}<Button size="small" type="text" icon={<CopyOutlined />} onClick={() => copy(contact.wechat)} /></Space> : '-',
        },
        { key: 'email', label: '邮箱', children: contact.email || '-' },
      ]} />

      <Divider orientation="left" plain style={{ marginTop: 20 }}>可编辑</Divider>
      <Form form={form} layout="vertical" size="middle">
        <Form.Item name="name" label="姓名" rules={[{ required: true }]}><Input /></Form.Item>
        <Space.Compact block>
          <Form.Item name="type" label="类型" style={{ flex: 1 }}>
            <Select options={meta?.contact_types} />
          </Form.Item>
          <Form.Item name="company_name" label="公司" style={{ flex: 1, marginLeft: 10 }}><Input /></Form.Item>
        </Space.Compact>
        <Form.Item name="title" label="职位 / 身份"><Input placeholder="招聘 HR / 猎头顾问 / 内推人" /></Form.Item>
        <Space.Compact block>
          <Form.Item name="wechat" label="微信" style={{ flex: 1 }}><Input /></Form.Item>
          <Form.Item name="phone" label="手机" style={{ flex: 1, marginLeft: 10 }}><Input /></Form.Item>
        </Space.Compact>
        <Form.Item name="email" label="邮箱"><Input /></Form.Item>
        <Form.Item name="profile_url" label="主页 / 名片链接"><Input /></Form.Item>
        <Form.Item name="last_contact_at" label="最近联系时间"><DatePicker showTime style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="notes" label="沟通记录"><Input.TextArea rows={3} placeholder="聊了什么、对方关注点、下一步" /></Form.Item>
        <Space>
          <Button type="primary" onClick={save}>保存修改</Button>
          <Button onClick={onClose}>关闭</Button>
        </Space>
      </Form>
        </>),
      }, {
        key: 'log',
        label: '操作日志',
        children: <ActivityLog entity="contact" entityId={contact.id} />,
      }]} />
    </Drawer>
  )
}

function CreateContactModal({ open, onClose, onCreated }) {
  const { meta } = useMeta()
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    const v = await form.validateFields()
    setSaving(true)
    try {
      await post('/api/contacts', v)
      message.success('已新增')
      form.resetFields()
      onCreated()
    } catch (e) { message.error(e.message) } finally { setSaving(false) }
  }

  return (
    <Modal open={open} onCancel={onClose} onOk={submit} confirmLoading={saving} title="新增联系人" okText="新增" width={520}>
      <Form form={form} layout="vertical" size="middle" initialValues={{ type: 'hr' }}>
        <Form.Item name="name" label="姓名" rules={[{ required: true }]}><Input /></Form.Item>
        <Space.Compact block>
          <Form.Item name="type" label="类型" style={{ flex: 1 }}><Select options={meta?.contact_types} /></Form.Item>
          <Form.Item name="company_name" label="公司" style={{ flex: 1, marginLeft: 10 }}><Input /></Form.Item>
        </Space.Compact>
        <Form.Item name="title" label="职位"><Input placeholder="招聘 HR / 猎头顾问" /></Form.Item>
        <Space.Compact block>
          <Form.Item name="wechat" label="微信" style={{ flex: 1 }}><Input /></Form.Item>
          <Form.Item name="phone" label="手机" style={{ flex: 1, marginLeft: 10 }}><Input /></Form.Item>
        </Space.Compact>
        <Form.Item name="email" label="邮箱"><Input /></Form.Item>
        <Form.Item name="channel_code" label="来源渠道">
          <Select allowClear options={(meta?.channels || []).map((c) => ({ value: c.code, label: c.name }))} />
        </Form.Item>
        <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
      </Form>
    </Modal>
  )
}
