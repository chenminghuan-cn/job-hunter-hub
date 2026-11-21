import React, { useState } from 'react'
import { Dropdown, Tag, App, Modal, Input, Space, Button, Typography } from 'antd'
import { DownOutlined } from '@ant-design/icons'
import { useMeta, stateInfo } from '../meta'
import { patch } from '../api'

/**
 * 状态维护控件：只列出状态机允许的下一步，点击即调 PATCH 接口。
 * 页面上的"手动维护"统一走这里，和 A2A 的 job.set_state / contact.set_state 同一套校验。
 */
export default function StateSelect({ machine, value, id, onChanged, path, size = 'default', extra = {} }) {
  const { meta } = useMeta()
  const { message } = App.useApp()
  const [pending, setPending] = useState(null)
  const [note, setNote] = useState('')
  const info = stateInfo(meta, machine, value)
  const next = info.next || []

  const items = next.map((v) => {
    const s = stateInfo(meta, machine, v)
    return { key: v, label: <span><Tag color={s.color}>{s.label}</Tag></span> }
  })

  const commit = async (key, why) => {
    try {
      await patch(`${path}/${id}`, { state: key, note: why || undefined, ...extra })
      const s = stateInfo(meta, machine, key)
      message.success(`已更新为「${s.label}」`)
      onChanged?.()
    } catch (e) {
      message.error(e.message)
    }
  }
  const onClick = ({ key }) => { setPending(key); setNote('') }

  if (!next.length) return <Tag color={info.color}>{info.label}</Tag>
  const target = pending ? stateInfo(meta, machine, pending) : null
  return (
    <>
      <Dropdown menu={{ items, onClick }} trigger={['click']}>
        <Tag color={info.color} style={{ cursor: 'pointer', margin: 0 }}>
          {info.label} <DownOutlined style={{ fontSize: 9 }} />
        </Tag>
      </Dropdown>
      <Modal open={!!pending} title={`改为「${target?.label || ''}」`} okText="确认"
             onCancel={() => setPending(null)}
             onOk={async () => { const k = pending; setPending(null); await commit(k, note) }}>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12.5 }}>
          说明为什么这么改（可选，会记进操作日志；Agent 改状态时也会留这一条）。
        </Typography.Paragraph>
        <Input.TextArea rows={3} value={note} onChange={(e) => setNote(e.target.value)}
                        placeholder={info.label + ' → ' + (target?.label || '') + '，因为…'} />
      </Modal>
    </>
  )
}
