/** Shared display helpers for prices / pct (A-share UI). */

export function formatPct(val) {
  if (val == null) return '-'
  const num = Number(val)
  if (Number.isNaN(num)) return '-'
  const sign = num > 0 ? '+' : ''
  return `${sign}${num.toFixed(2)}%`
}

export function formatNum(val, digits = 2) {
  if (val == null) return '-'
  const num = Number(val)
  if (Number.isNaN(num)) return '-'
  return num.toFixed(digits)
}

export function pctClass(val) {
  if (val == null) return ''
  const num = Number(String(val).replace('%', ''))
  if (Number.isNaN(num)) return ''
  if (num > 0) return 'up'
  if (num < 0) return 'down'
  return ''
}

export function formatDateTime(dt) {
  if (!dt) return '-'
  return String(dt).replace('T', ' ').slice(0, 19)
}
