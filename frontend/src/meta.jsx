import React, { createContext, useContext, useEffect, useState } from 'react'
import { get } from './api'

const MetaCtx = createContext(null)

export function MetaProvider({ children }) {
  const [meta, setMeta] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    get('/api/meta').then(setMeta).catch((e) => setError(e.message))
  }, [])
  return <MetaCtx.Provider value={{ meta, error, reload: () => get('/api/meta').then(setMeta) }}>{children}</MetaCtx.Provider>
}

export const useMeta = () => useContext(MetaCtx)

/** 状态定义查表：meta.machines[machine].states */
export function stateInfo(meta, machine, value) {
  const m = meta?.machines?.[machine]
  const s = m?.states?.find((x) => x.value === value)
  return s || { value, label: value || '-', color: 'default', next: [] }
}

export function stateOptions(meta, machine, includeAll = false) {
  return (meta?.machines?.[machine]?.states || [])
    .filter((s) => includeAll || s.value !== 'archived')
    .map((s) => ({ value: s.value, label: s.label }))
}

export function channelMap(meta) {
  return Object.fromEntries((meta?.channels || []).map((c) => [c.code, c]))
}
