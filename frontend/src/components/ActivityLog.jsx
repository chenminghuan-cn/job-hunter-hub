import React, { useEffect, useState } from 'react'
import { Empty, Spin, Tag, Timeline, Typography, App } from 'antd'
import dayjs from 'dayjs'
import { get } from '../api'
import { ACTION_TEXT, actorLabel } from '../activityText'

/** 任意对象的操作日志：谁在什么时候做了什么、从什么状态到什么状态、为什么这么做 */
export default function ActivityLog({ entity, entityId, limit = 50 }) {
  const { message } = App.useApp()
  const [rows, setRows] = useState(null)

  useEffect(() => {
    if (entityId == null) return
    setRows(null)
    get('/api/activity', { entity, entity_id: entityId, limit })
      .then(setRows).catch((e) => message.error(e.message))
  }, [entity, entityId])

  if (!rows) return <div style={{ padding: 32, textAlign: 'center' }}><Spin /></div>
  if (!rows.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有操作记录" style={{ padding: 24 }} />
  }

  const parse = (t) => { try { return JSON.parse(t || '{}') } catch { return {} } }

  return (
    <Timeline
      style={{ marginTop: 8 }}
      items={rows.map((r) => {
        const d = parse(r.detail)
        const isAgent = (r.actor || '').startsWith('agent:')
        return {
          key: r.id,
          color: isAgent ? 'purple' : 'blue',
          children: (
            <div style={{ fontSize: 12.8, lineHeight: 1.8 }}>
              <div>
                <span style={{ color: '#98a2b3', marginRight: 8 }}>{dayjs(r.ts).format('MM-DD HH:mm:ss')}</span>
                <Tag color={isAgent ? 'purple' : 'default'} style={{ marginRight: 6, fontSize: 11 }}>
                  {actorLabel(r.actor)}
                </Tag>
                <span style={{ color: '#344054', fontWeight: 550 }}>
                  {ACTION_TEXT[r.action] || r.action}
                </span>
                {d.from && d.to ? (
                  <span style={{ color: '#667085', marginLeft: 6 }}>{d.from} → {d.to}</span>
                ) : null}
              </div>
              {d.note ? (
                <div style={{
                  marginTop: 4, color: '#475467', background: '#fafbfc', border: '1px solid #f0f1f5',
                  borderRadius: 8, padding: '6px 10px', whiteSpace: 'pre-wrap',
                }}>
                  {d.note}
                </div>
              ) : null}
            </div>
          ),
        }
      })}
    />
  )
}
