import React from 'react'
import { Avatar, Tag, Tooltip } from 'antd'

export default function ChannelLogo({ channel, size = 18, name = true, tag = false }) {
  if (!channel) return <span style={{ color: '#bbb' }}>-</span>
  const img = (
    <Avatar
      shape="square"
      size={size}
      src={channel.logo}
      style={{ background: '#fff', border: '1px solid #eee', flex: '0 0 auto' }}
    >
      {(channel.name || '?')[0]}
    </Avatar>
  )
  if (!name) return <Tooltip title={channel.name}>{img}</Tooltip>
  const body = (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap' }}>
      {img}
      <span>{channel.name}</span>
    </span>
  )
  return tag ? <Tag style={{ padding: '2px 8px', margin: 0, background: '#fff' }}>{body}</Tag> : body
}
