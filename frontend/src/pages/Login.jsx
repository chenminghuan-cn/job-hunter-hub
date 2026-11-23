import React, { useEffect, useRef, useState } from 'react'
import { App, Button, Card, Form, Input, Space, Typography } from 'antd'
import { MailOutlined, SafetyOutlined, ArrowLeftOutlined } from '@ant-design/icons'
import { post } from '../api'

export default function Login({ onSuccess }) {
  const { message } = App.useApp()
  const [step, setStep] = useState('email')
  const [email, setEmail] = useState('')
  const [sending, setSending] = useState(false)
  const [verifying, setVerifying] = useState(false)
  const [left, setLeft] = useState(0)
  const [hint, setHint] = useState('')
  const timer = useRef(null)

  useEffect(() => () => clearInterval(timer.current), [])

  const countdown = (s) => {
    setLeft(s)
    clearInterval(timer.current)
    timer.current = setInterval(() => {
      setLeft((v) => {
        if (v <= 1) { clearInterval(timer.current); return 0 }
        return v - 1
      })
    }, 1000)
  }

  const send = async (addr) => {
    const target = (addr || email).trim()
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(target)) return message.error('邮箱格式不对')
    setSending(true)
    try {
      const r = await post('/api/auth/request-code', { email: target })
      setEmail(target)
      setStep('code')
      countdown(60)
      setHint(r.mode === 'log'
        ? '当前未配置发信渠道，验证码写在本机日志：data/logs/app.log'
        : `验证码已发送到 ${target}，10 分钟内有效`)
      message.success('验证码已发送')
    } catch (e) {
      message.error(e.message)
    } finally {
      setSending(false)
    }
  }

  const verify = async (code) => {
    setVerifying(true)
    try {
      await post('/api/auth/verify', { email, code: (code || '').trim() })
      message.success('登录成功')
      onSuccess?.()
    } catch (e) {
      message.error(e.message)
    } finally {
      setVerifying(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 24,
      background: 'radial-gradient(1200px 600px at 20% -10%, #eef2ff 0%, #f7f8fc 45%, #f5f6fa 100%)',
    }}>
      <div style={{ width: 400, maxWidth: '100%' }}>
        <Space align="center" size={12} style={{ marginBottom: 22 }}>
          <img src="/favicon.svg" width={40} height={40} alt="应聘中台" style={{ borderRadius: 12 }} />
          <div>
            <div style={{ fontWeight: 650, fontSize: 16, lineHeight: 1.3 }}>应聘中台</div>
            <div style={{ fontSize: 12, color: '#98a2b3' }}>Job Hunter Hub</div>
          </div>
        </Space>

        <Card style={{ boxShadow: '0 12px 40px rgba(16,24,40,.08)', border: '1px solid #eef0f4' }}
              styles={{ body: { padding: 26 } }}>
          {step === 'email' ? (
            <>
              <Typography.Title level={4} style={{ marginTop: 0, marginBottom: 6 }}>邮箱登录</Typography.Title>
              <Typography.Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 20 }}>
                输入你的收件邮箱，我会发一封包含 6 位验证码的邮件。
              </Typography.Paragraph>
              <Form layout="vertical" onFinish={({ email: e }) => send(e)} initialValues={{ email }}>
                <Form.Item name="email" label="邮箱"
                           rules={[{ required: true, type: 'email', message: '请输入正确的邮箱' }]}>
                  <Input size="large" prefix={<MailOutlined style={{ color: '#98a2b3' }} />} placeholder="you@example.com" />
                </Form.Item>
                <Button type="primary" htmlType="submit" size="large" block loading={sending}>
                  发送验证码
                </Button>
              </Form>
            </>
          ) : (
            <>
              <Button type="link" size="small" icon={<ArrowLeftOutlined />} style={{ paddingLeft: 0, marginBottom: 6 }}
                      onClick={() => { setStep('email'); setLeft(0) }}>
                换个邮箱
              </Button>
              <Typography.Title level={4} style={{ marginTop: 0, marginBottom: 6 }}>输入验证码</Typography.Title>
              <Typography.Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 14 }}>
                已发送至 <b style={{ color: '#475467' }}>{email}</b>
              </Typography.Paragraph>
              {hint ? (
                <div style={{
                  fontSize: 12, color: '#8a6d3b', background: '#fffbeb', border: '1px solid #fde68a',
                  borderRadius: 8, padding: '8px 10px', marginBottom: 14, lineHeight: 1.7,
                }}>{hint}</div>
              ) : null}
              <Form onFinish={({ code }) => verify(code)}>
                <Form.Item name="code" rules={[{ required: true, len: 6, message: '请输入 6 位验证码' }]}>
                  <Input size="large" maxLength={6} autoFocus inputMode="numeric"
                         prefix={<SafetyOutlined style={{ color: '#98a2b3' }} />}
                         placeholder="6 位数字"
                         style={{ letterSpacing: 6, fontSize: 18, fontWeight: 600 }} />
                </Form.Item>
                <Button type="primary" htmlType="submit" size="large" block loading={verifying}>登录</Button>
              </Form>
              <div style={{ marginTop: 12, textAlign: 'center', fontSize: 12.5, color: '#98a2b3' }}>
                {left > 0
                  ? <span>{left} 秒后可重新发送</span>
                  : <Button type="link" size="small" loading={sending} onClick={() => send(email)}>重新发送验证码</Button>}
              </div>
            </>
          )}
        </Card>

        <div style={{ marginTop: 16, fontSize: 11.5, color: '#b9c0cc', textAlign: 'center', lineHeight: 1.9 }}>
          仅限本人使用 · 验证码 10 分钟有效 · 登录状态保持 30 天
        </div>
      </div>
    </div>
  )
}
