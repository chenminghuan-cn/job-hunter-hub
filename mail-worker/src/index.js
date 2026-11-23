/**
 * jobhub-mailer：只干一件事 —— 校验 HMAC 后，用 Cloudflare send_email 从你的域名邮箱发信。
 * 中台后端调用它，避免在 Python 里存 SMTP 密码，也用正常渠道投递（不易进垃圾箱）。
 */
const enc = new TextEncoder()

const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('')

async function hmacHex(secret, data) {
  const key = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  return hex(await crypto.subtle.sign('HMAC', key, enc.encode(data)))
}

const json = (obj, status = 200) => new Response(JSON.stringify(obj), {
  status, headers: { 'content-type': 'application/json; charset=utf-8' },
})

export default {
  async fetch(req, env) {
    const url = new URL(req.url)
    if (url.pathname === '/healthz') return json({ ok: true })
    if (req.method !== 'POST') return json({ error: 'method not allowed' }, 405)

    const body = await req.text()
    const sig = (req.headers.get('x-signature') || '').toLowerCase()
    if (!env.MAIL_SECRET) return json({ error: 'MAIL_SECRET not configured' }, 500)
    const expect = await hmacHex(env.MAIL_SECRET, body)
    if (sig.length !== expect.length || sig !== expect) return json({ error: 'bad signature' }, 401)

    let p
    try { p = JSON.parse(body) } catch { return json({ error: 'bad json' }, 400) }
    const to = p.to
    const subject = p.subject
    if (!to || !subject) return json({ error: 'to / subject required' }, 400)

    try {
      const res = await env.EMAIL.send({
        from: p.from || 'noreply@example.com',
        to,
        subject,
        html: p.html || '<p></p>',
        text: p.text || subject,
      })
      return json({ ok: true, id: res?.messageId ?? null })
    } catch (e) {
      return json({ error: String(e) }, 502)
    }
  },
}
