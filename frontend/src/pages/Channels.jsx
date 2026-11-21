import React, { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Col, Collapse, Form, Input, Modal, Row, Select, Space, Tag,
  Typography, App, Divider, Empty,
} from 'antd'
import { PlusOutlined, SettingOutlined, ReloadOutlined } from '@ant-design/icons'
import { get, patch, post } from '../api'
import { useMeta } from '../meta'
import ChannelLogo from '../components/ChannelLogo'
import StateSelect from '../components/StateSelect'
import { CHANNEL_NOTES } from '../channelNotes'

const KIND_LABEL = { job_board: '岗位平台', social: '社交平台', community: '社区', messenger: '内容渠道', other: '其他' }

export default function Channels() {
  const { meta, reload } = useMeta()
  const { message } = App.useApp()
  const [channels, setChannels] = useState(null)
  const [editing, setEditing] = useState(null)
  const [creating, setCreating] = useState(false)

  const load = () => get('/api/channels').then(setChannels).catch((e) => message.error(e.message))
  useEffect(() => { load() }, [])

  const saveConfig = async (code, config) => {
    await patch(`/api/channels/${code}`, { config })
    message.success('配置已保存')
    setEditing(null)
    load()
  }

  return (
    <>
      <Row gutter={[14, 14]}>
        {(channels || []).map((c) => {
          const note = CHANNEL_NOTES[c.code]
          return (
            <Col key={c.code} xs={24} md={12} xl={8}>
              <Card styles={{ body: { padding: 16 } }} style={{ height: '100%' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                  <ChannelLogo channel={c} size={38} name={false} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <Typography.Text strong style={{ fontSize: 14.5 }}>{c.name}</Typography.Text>
                      <Tag style={{ margin: 0, fontSize: 11 }}>{KIND_LABEL[c.kind] || c.kind || '未分类'}</Tag>
                    </div>
                    <div style={{ fontSize: 12, color: '#98a2b3', marginTop: 2 }}>
                      <span className="mono">{c.code}</span> · {c.job_count} 个岗位
                    </div>
                  </div>
                  <StateSelect machine="channel" value={c.state} id={c.code} path="/api/channels"
                               onChanged={() => { load(); reload() }} />
                </div>

                <div style={{ marginTop: 12, fontSize: 12.5, color: '#667085', minHeight: 38 }}>
                  {note ? note.kind : '自定义信息源'}
                  {note?.fields?.length ? <div style={{ color: '#98a2b3', marginTop: 2 }}>字段：{note.fields.slice(0, 3).join('、')}…</div> : null}
                </div>

                {(c.state === 'need_verify' || c.state === 'login_expired') ? (
                  <div style={{ marginTop: 8, background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, padding: '8px 10px' }}>
                    <div style={{ fontSize: 12, color: '#b42318', lineHeight: 1.7 }}>
                      Agent 上报：{c.state_note || (c.state === 'need_verify' ? '需要人工验证（滑块/短信）' : '登录态失效，需要重新登录')}
                    </div>
                    <Button size="small" type="link" style={{ padding: 0, height: 20, fontSize: 12 }}
                            onClick={async () => {
                              await patch(`/api/channels/${c.code}`, { state: 'active', state_note: '' })
                              message.success('已标记处理，恢复采集中')
                              load(); reload()
                            }}>我已处理 → 恢复采集中</Button>
                  </div>
                ) : null}

                <div style={{ marginTop: 8, fontSize: 11.5, color: '#98a2b3', lineHeight: 1.9 }}>
                  <div>上次运行：{c.last_run_at || '未上报'}{c.last_run_at && c.run_stats?.last_run
                    ? ` · 抓 ${c.run_stats.last_run.scraped ?? '-'} / 新 ${c.run_stats.last_run.created ?? '-'} / 错 ${(c.run_stats.last_run.errors || []).length}` : ''}</div>
                  {c.next_check_at ? <div>下次计划：{c.next_check_at}</div> : null}
                  {c.run_stats?.credentials_expire_at ? <div>凭据过期：{c.run_stats.credentials_expire_at}</div> : null}
                  {c.state_note && c.state === 'active' ? <div style={{ color: '#d97706' }}>备注：{c.state_note}</div> : null}
                </div>

                <Divider style={{ margin: '10px 0' }} />
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 12, color: '#98a2b3' }}>
                    配置 {c.config && Object.keys(c.config).length ? `${Object.keys(c.config).length} 项` : '空'}
                  </span>
                  <Space>
                    {c.home_url ? <a href={c.home_url} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>站点</a> : null}
                    <Button size="small" icon={<SettingOutlined />} onClick={() => setEditing(c)}>配置</Button>
                  </Space>
                </div>
              </Card>
            </Col>
          )
        })}
        <Col xs={24}>
          <Button type="dashed" icon={<PlusOutlined />} block onClick={() => setCreating(true)} style={{ height: 44 }}>
            新增信息源
          </Button>
        </Col>
      </Row>

      <Card style={{ marginTop: 14 }} title="各渠道结构差异 & 接入建议"
            extra={<Typography.Text type="secondary" style={{ fontSize: 12 }}>写死的是结构差异，不是字段 —— 差异用 extra / raw 承载</Typography.Text>}>
        <Collapse ghost items={Object.entries(CHANNEL_NOTES).map(([code, n]) => ({
          key: code,
          label: (
            <Space>
              <ChannelLogo channel={channels?.find((c) => c.code === code)} size={18} />
              <b>{channels?.find((c) => c.code === code)?.name || code}</b>
              <Tag style={{ margin: 0 }}>{n.kind}</Tag>
            </Space>
          ),
          children: (
            <div style={{ fontSize: 12.8, lineHeight: 2, paddingLeft: 4 }}>
              <div><b>可获取字段：</b>{n.fields.join('、')}</div>
              <div><b>坑：</b>{n.pitfalls.join('；')}</div>
              <div><b>映射建议：</b><span className="mono">{n.mapping}</span></div>
            </div>
          ),
        }))} />
      </Card>

      <ConfigModal channel={editing} onClose={() => setEditing(null)} onSave={saveConfig} />
      <CreateChannelModal open={creating} onClose={() => setCreating(false)}
                          onCreated={() => { setCreating(false); load(); reload() }} />
    </>
  )
}

function ConfigModal({ channel, onClose, onSave }) {
  const [text, setText] = useState('{}')
  const [err, setErr] = useState('')
  const { message } = App.useApp()

  useEffect(() => { if (channel) setText(JSON.stringify(channel.config || {}, null, 2)) }, [channel])
  if (!channel) return null

  const ok = async () => {
    try {
      const v = JSON.parse(text || '{}')
      await onSave(channel.code, v)
    } catch (e) {
      setErr(e.message)
      message.error('JSON 不合法')
    }
  }

  return (
    <Modal open onCancel={onClose} onOk={ok} title={`${channel.name} · 采集配置`} okText="保存" width={560}>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12.5 }}>
        这里存的是「采集侧约定」，例如关键词、城市、频控、登录账号别名。中台只存不用，Agent 拉取后自行执行。
      </Typography.Paragraph>
      <Input.TextArea rows={12} value={text} onChange={(e) => { setText(e.target.value); setErr('') }}
                      className="mono" />
      {err ? <Typography.Text type="danger" style={{ fontSize: 12 }}>{err}</Typography.Text> : null}
      <div style={{ marginTop: 8 }}>
        <Tag>示例</Tag>
        <span className="mono" style={{ fontSize: 12, color: '#667085' }}>
          {'{"keywords":["前端","Node"],"cities":["上海","杭州"],"cron":"*/30 * * * *","concurrency":1}'}
        </span>
      </div>
    </Modal>
  )
}

function CreateChannelModal({ open, onClose, onCreated }) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    const v = await form.validateFields()
    setSaving(true)
    try {
      await post('/api/channels', v)
      message.success('已新增渠道')
      form.resetFields()
      onCreated()
    } catch (e) { message.error(e.message) } finally { setSaving(false) }
  }

  return (
    <Modal open={open} onCancel={onClose} onOk={submit} confirmLoading={saving} title="新增信息源" okText="新增" width={520}>
      <Alert type="warning" showIcon style={{ marginBottom: 12 }}
             message="logo 建议放 frontend/public/logos/ 下再用 /logos/xxx.png 引用，避免外链失效。" />
      <Form form={form} layout="vertical" size="middle" initialValues={{ kind: 'job_board' }}>
        <Space.Compact block>
          <Form.Item name="code" label="code（英文字母，Agent 上报时用）" rules={[{ required: true }]} style={{ flex: 1 }}>
            <Input placeholder="如 zhilian" />
          </Form.Item>
          <Form.Item name="name" label="显示名" rules={[{ required: true }]} style={{ flex: 1, marginLeft: 10 }}>
            <Input placeholder="智联招聘" />
          </Form.Item>
        </Space.Compact>
        <Space.Compact block>
          <Form.Item name="kind" label="类型" style={{ flex: 1 }}>
            <Select options={Object.entries(KIND_LABEL).map(([v, l]) => ({ value: v, label: l }))} />
          </Form.Item>
          <Form.Item name="logo" label="logo 路径" style={{ flex: 1, marginLeft: 10 }}>
            <Input placeholder="/logos/xxx.png" />
          </Form.Item>
        </Space.Compact>
        <Form.Item name="home_url" label="站点地址"><Input placeholder="https://..." /></Form.Item>
        <Form.Item name="note" label="备注"><Input.TextArea rows={2} /></Form.Item>
      </Form>
    </Modal>
  )
}
