import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App as AntApp, ConfigProvider, Spin } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import App from './App'
import Login from './pages/Login'
import { MetaProvider } from './meta'
import { get } from './api'
import './index.css'

dayjs.locale('zh-cn')

function Boot() {
  const [state, setState] = useState('loading')
  const check = () => get('/api/auth/me').then(() => setState('in')).catch(() => setState('login'))
  useEffect(() => { check() }, [])

  if (state === 'loading') return <div style={{ padding: 80, textAlign: 'center' }}><Spin size="large" /></div>
  if (state === 'login') return <Login onSuccess={check} />
  return (
    <MetaProvider>
      <App />
    </MetaProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <ConfigProvider
    locale={zhCN}
    theme={{
      token: {
        colorPrimary: '#4f46e5',
        borderRadius: 8,
        fontFamily: "-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif",
        colorBgLayout: '#f5f6fa',
      },
      components: {
        Menu: { itemSelectedBg: '#eef2ff', itemSelectedColor: '#4f46e5', itemHeight: 38, borderRadius: 8 },
        Table: { headerBg: '#fafbfc', headerColor: '#667085' },
        Card: { boxShadowTertiary: 'none' },
      },
    }}
  >
    <AntApp>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Boot />
      </BrowserRouter>
    </AntApp>
  </ConfigProvider>,
)
