import React, { useState } from 'react'
import { Link, Route, Routes, useLocation } from 'react-router-dom'
import { Layout, Menu, Typography, Button, Space, Tooltip } from 'antd'
import {
  DashboardOutlined, ProfileOutlined, BankOutlined, TeamOutlined,
  ApiOutlined, LinkOutlined, LogoutOutlined, MenuFoldOutlined, MenuUnfoldOutlined, CommentOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import Dashboard from './pages/Dashboard'
import Jobs from './pages/Jobs'
import Companies from './pages/Companies'
import Contacts from './pages/Contacts'
import Channels from './pages/Channels'
import Settings from './pages/Settings'
import Reports from './pages/Reports'
import Resume from './pages/Resume'
import { useMeta } from './meta'
import { post } from './api'

const { Sider, Content, Header } = Layout

const NAV = [
  { key: '/', icon: <DashboardOutlined />, label: '数据看板' },
  { key: '/jobs', icon: <ProfileOutlined />, label: '岗位列表' },
  { key: '/companies', icon: <BankOutlined />, label: '公司列表' },
  { key: '/contacts', icon: <TeamOutlined />, label: '联系人列表' },
  { key: '/resume', icon: <FileTextOutlined />, label: '简历' },
  { key: '/reports', icon: <CommentOutlined />, label: 'Agent 诉求' },
  { key: '/channels', icon: <ApiOutlined />, label: '信息源' },
  { key: '/settings', icon: <LinkOutlined />, label: '连接设置' },
]

const TITLES = { '/': '数据看板', '/jobs': '岗位列表', '/companies': '公司列表', '/contacts': '联系人列表', '/channels': '信息源与渠道', '/reports': 'Agent 诉求', '/resume': '简历定制', '/settings': '连接设置' }

export default function App() {
  const loc = useLocation()
  const { meta } = useMeta()
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('jh_sider') === '1')
  const toggle = () => setCollapsed((v) => {
    localStorage.setItem('jh_sider', v ? '0' : '1')
    return !v
  })
  const selected = NAV.find((n) => n.key !== '/' && loc.pathname.startsWith(n.key))?.key || '/'

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={212} collapsedWidth={64} collapsed={collapsed} trigger={null} theme="light"
             style={{ borderRight: '1px solid #eef0f4', position: 'sticky', top: 0, height: '100vh', overflow: 'hidden' }}>
        <div style={{
          padding: collapsed ? '20px 0 14px' : '20px 20px 14px', display: 'flex',
          alignItems: 'center', justifyContent: collapsed ? 'center' : 'flex-start', gap: 10,
        }}>
          <img src="/favicon.svg" width={32} height={32} alt="应聘中台" style={{ borderRadius: 9, flex: '0 0 auto' }} />
          {!collapsed ? (
            <div style={{ whiteSpace: 'nowrap' }}>
              <div style={{ fontWeight: 650, fontSize: 15, lineHeight: 1.2 }}>应聘中台</div>
              <div style={{ fontSize: 11, color: '#98a2b3' }}>Job Hunter Hub</div>
            </div>
          ) : null}
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selected]}
          inlineCollapsed={collapsed}
          style={{ borderInlineEnd: 'none', padding: collapsed ? '4px 8px' : '4px 8px' }}
          items={NAV.map((n) => ({ ...n, label: <Link to={n.key}>{n.label}</Link> }))}
        />
        <div style={{
          position: 'absolute', bottom: 14, left: 0, right: 0, textAlign: 'center',
          fontSize: 11, color: '#b9c0cc', lineHeight: 1.6,
        }}>
          {collapsed ? (
            <Tooltip title="退出登录" placement="right">
              <Button type="text" size="small" icon={<LogoutOutlined />} style={{ color: '#98a2b3' }}
                      onClick={async () => { await post('/api/auth/logout', {}); window.location.reload() }} />
            </Tooltip>
          ) : (
            <div style={{ padding: '0 20px' }}>
              <div>{(meta?.channels || []).filter((c) => c.state === 'active').length} / {(meta?.channels || []).length} 渠道采集中</div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 4 }}>
                <span>v0.1.0 · 本地 SQLite</span>
                <Tooltip title="退出登录">
                  <Button type="text" size="small" icon={<LogoutOutlined />} style={{ color: '#98a2b3' }}
                          onClick={async () => { await post('/api/auth/logout', {}); window.location.reload() }} />
                </Tooltip>
              </div>
            </div>
          )}
        </div>
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px', height: 56, lineHeight: '56px', borderBottom: '1px solid #eef0f4', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Space size={10}>
            <Tooltip title={collapsed ? '展开菜单' : '收起菜单'} placement="bottomLeft">
              <Button type="text" size="small" style={{ marginLeft: -6 }}
                      icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={toggle} />
            </Tooltip>
            <Typography.Text strong style={{ fontSize: 15 }}>{TITLES[selected]}</Typography.Text>
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            采集 Agent 写数据 · 页面手动维护状态 · A2A 签名外放
          </Typography.Text>
        </Header>
        <Content style={{ padding: 20 }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/companies" element={<Companies />} />
            <Route path="/contacts" element={<Contacts />} />
            <Route path="/resume" element={<Resume />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/channels" element={<Channels />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}
