import React, { useEffect, useState } from 'react'
import { Card, Col, Empty, Row, Space, Tag, Tooltip, Typography, Skeleton, Badge, Alert, Button } from 'antd'
import {
  ProfileOutlined, SendOutlined, ThunderboltOutlined, TrophyOutlined,
  TeamOutlined, BankOutlined, ClockCircleOutlined, ApiOutlined, CommentOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { get } from '../api'
import { useMeta, stateInfo } from '../meta'
import ChannelLogo from '../components/ChannelLogo'
import { ACTION_TEXT, actorLabel } from '../activityText'
import { Link } from 'react-router-dom'

function Kpi({ icon, label, value, color, bg, hint }) {
  return (
    <Card styles={{ body: { padding: 18 } }} style={{ height: '100%' }}>
      <Space align="start" size={14}>
        <div style={{ width: 40, height: 40, borderRadius: 11, background: bg, color, display: 'grid', placeItems: 'center', fontSize: 18 }}>
          {icon}
        </div>
        <div>
          <div style={{ color: '#667085', fontSize: 12.5, marginBottom: 2 }}>{label}</div>
          <div className="kpi-value">{value ?? '-'}</div>
          <div style={{ color: '#98a2b3', fontSize: 11.5 }}>{hint}</div>
        </div>
      </Space>
    </Card>
  )
}

function Funnel({ meta, jobs }) {
  const states = (meta?.machines?.job.states || []).filter((s) => !['archived', 'rejected'].includes(s.value))
  const max = Math.max(1, ...states.map((s) => jobs.by_state[s.value] || 0))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 11 }}>
      {states.map((s) => {
        const n = jobs.by_state[s.value] || 0
        return (
          <div key={s.value} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 82, fontSize: 12.5, color: '#475467' }}>{s.label}</div>
            <div style={{ flex: 1, height: 22, background: '#f2f4f7', borderRadius: 6, overflow: 'hidden' }}>
              <div style={{
                width: `${Math.max(n ? 4 : 0, (n / max) * 100)}%`, height: '100%',
                background: n ? 'linear-gradient(90deg,#6366f1,#8b5cf6)' : 'transparent',
                borderRadius: 6, transition: 'width .4s',
              }} />
            </div>
            <div style={{ width: 28, textAlign: 'right', fontWeight: 600, fontSize: 13 }}>{n}</div>
          </div>
        )
      })}
    </div>
  )
}

export default function Dashboard() {
  const { meta } = useMeta()
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)

  const load = () => {
    setErr(null)
    get('/api/dashboard').then(setData).catch((e) => setErr(e.message))
  }
  useEffect(() => { load() }, [])

  if (err) {
    return (
      <Alert type="error" showIcon message="看板加载失败"
             description={<span style={{ fontSize: 12.5 }}>
               {err}
               <br />后端日志：<span className="mono">data/logs/app.err.log</span>
             </span>}
             action={<Button size="small" onClick={load}>重试</Button>} />
    )
  }
  if (!data) return <Skeleton active paragraph={{ rows: 8 }} />
  const { jobs, contacts, companies, channels, activity } = data
  const needHuman = data.channels_need_human || []

  return (
    <div>
      <Row gutter={[14, 14]}>
        <Col xs={12} lg={6}>
          <Kpi icon={<ProfileOutlined />} label="岗位总数" value={jobs.total} color="#4f46e5" bg="#eef2ff"
               hint={`本周新增 ${jobs.week} · 今日 ${jobs.new_today}`} />
        </Col>
        <Col xs={12} lg={6}>
          <Kpi icon={<ThunderboltOutlined />} label="待处理（新发现）" value={jobs.todo} color="#d97706" bg="#fef3c7"
               hint="去岗位列表筛选「新发现」" />
        </Col>
        <Col xs={12} lg={6}>
          <Kpi icon={<SendOutlined />} label="已投递 / 进行中" value={jobs.applied} color="#0891b2" bg="#cffafe"
               hint={`面试中 ${jobs.interviewing}`} />
        </Col>
        <Col xs={12} lg={6}>
          <Kpi icon={<TrophyOutlined />} label="Offer" value={jobs.offers} color="#059669" bg="#d1fae5"
               hint={`联系人 ${contacts.total} · 公司 ${companies.total}`} />
        </Col>
      </Row>

      <Row gutter={[14, 14]} style={{ marginTop: 14 }}>
        <Col xs={24} xl={14}>
          <Card title="岗位推进漏斗" extra={<Typography.Text type="secondary" style={{ fontSize: 12 }}>点击状态可手动维护</Typography.Text>}>
            <Funnel meta={meta} jobs={jobs} />
            <div style={{ marginTop: 16, paddingTop: 14, borderTop: '1px dashed #eef0f4', display: 'flex', gap: 18, fontSize: 12.5, color: '#667085' }}>
              <span><Badge color="#98a2b3" /> 已放弃 {jobs.by_state.rejected || 0}</span>
              <span><Badge color="#d0d5dd" /> 已归档 {jobs.by_state.archived || 0}</span>
              {jobs.stale ? <span><Badge color="#f59e0b" /> 疑似下架 {jobs.stale}</span> : null}
              {jobs.avg_open_days != null ? <span>平均在招 {jobs.avg_open_days} 天</span> : null}
              <span style={{ marginLeft: 'auto' }}><Link to="/jobs">查看全部岗位 →</Link></span>
            </div>
          </Card>
        </Col>
        <Col xs={24} xl={10}>
          <Card title="信息源" extra={<Link to="/channels" style={{ fontSize: 12 }}>管理 →</Link>}
                styles={{ body: { paddingTop: 8, paddingBottom: 8 } }}>
            {channels.map((c) => {
              const s = stateInfo(meta, 'channel', c.state)
              const total = channels.reduce((a, b) => a + b.job_count, 0) || 1
              return (
                <div key={c.code} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0' }}>
                  <ChannelLogo channel={c} size={20} name={false} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5 }}>
                      <span style={{ color: '#344054' }}>{c.name}</span>
                      <span style={{ color: '#667085' }}>{c.job_count}</span>
                    </div>
                    <div style={{ height: 4, background: '#f2f4f7', borderRadius: 3, marginTop: 4 }}>
                      <div style={{ width: `${(c.job_count / total) * 100}%`, height: '100%', background: '#a5b4fc', borderRadius: 3 }} />
                    </div>
                  </div>
                  <Tag color={s.color} style={{ margin: 0, fontSize: 11 }}>{s.label}</Tag>
                </div>
              )
            })}
          </Card>
        </Col>
      </Row>

      <Row gutter={[14, 14]} style={{ marginTop: 14 }}>
        <Col xs={24} xl={14}>
          <Card title="最近动态" extra={<Typography.Text type="secondary" style={{ fontSize: 12 }}><ClockCircleOutlined /> 采集与维护流水</Typography.Text>}
                styles={{ body: { maxHeight: 330, overflow: 'auto', paddingTop: 12 } }}>
            {activity.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> : activity.map((a) => (
              <div key={a.id} style={{ display: 'flex', gap: 10, padding: '6px 0', fontSize: 12.5 }}>
                <span style={{ color: '#98a2b3', width: 108, flex: '0 0 auto' }}>{dayjs(a.ts).format('MM-DD HH:mm')}</span>
                <Tag color={a.actor?.startsWith('agent') ? 'purple' : 'default'} style={{ margin: 0, fontSize: 11, flex: '0 0 auto' }}>
                  {actorLabel(a.actor)}
                </Tag>
                <span style={{ color: '#344054', flex: 1 }}>
                  {ACTION_TEXT[a.action] || a.action}
                  {a.entity ? (
                    <span style={{ color: '#98a2b3' }}> · {a.entity}{a.entity_id != null ? `#${a.entity_id}` : ''}</span>
                  ) : null}
                </span>
              </div>
            ))}
          </Card>
        </Col>
        <Col xs={24} xl={10}>
          <Card title="待办" styles={{ body: { paddingTop: 10 } }}>
            <Space direction="vertical" size={10} style={{ width: '100%' }}>
              <TodoRow icon={<ThunderboltOutlined />} color="#d97706" text="新岗位待筛选" count={jobs.todo} to="/jobs?state=new" />
              {needHuman.length ? (
                <TodoRow icon={<ApiOutlined />} color="#dc2626"
                         text={`信源待人工处理（${needHuman.map((c) => c.name).join('、')}）`}
                         count={needHuman.length} to="/channels" />
              ) : null}
              {data.reports?.open ? (
                <TodoRow icon={<CommentOutlined />} color="#0891b2" text="Agent 诉求待处理" count={data.reports.open} to="/reports" />
              ) : null}
              <TodoRow icon={<TeamOutlined />} color="#4f46e5" text="联系人待首次触达" count={contacts.todo} to="/contacts?state=new" />
              <TodoRow icon={<BankOutlined />} color="#0891b2" text="公司待调研" count={companies.by_state.new || 0} to="/companies?state=new" />
              <TodoRow icon={<TrophyOutlined />} color="#059669" text="面试/Offer 跟进" count={(jobs.by_state.offer || 0) + jobs.interviewing} to="/jobs?state=interviewing" />
            </Space>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

function TodoRow({ icon, color, text, count, to }) {
  return (
    <Link to={to} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 12px', borderRadius: 9, background: '#fafbfc', border: '1px solid #f0f1f5' }}>
      <span style={{ color }}>{icon}</span>
      <span style={{ flex: 1, color: '#344054', fontSize: 13 }}>{text}</span>
      <Tag color={count ? color : 'default'} style={{ margin: 0 }}>{count}</Tag>
    </Link>
  )
}
