/** 市场页共用数字展示 */
export function formatYi(val, digits = 2) {
  if (val == null || Number.isNaN(Number(val))) return '-'
  const n = Number(val)
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}`
}

/** 金额：元 → 万/亿/万亿 */
export function formatAmount(val) {
  if (val == null || Number.isNaN(Number(val))) return '-'
  const n = Number(val)
  const sign = n < 0 ? '-' : ''
  const a = Math.abs(n)
  if (a >= 1e12) return `${sign}${(a / 1e12).toFixed(2)} 万亿`
  if (a >= 1e8) return `${sign}${(a / 1e8).toFixed(2)} 亿`
  if (a >= 1e4) return `${sign}${(a / 1e4).toFixed(2)} 万`
  return `${sign}${a.toFixed(0)}`
}

/** ETF 份额：份 → 亿份/万份 */
export function formatShare(val) {
  if (val == null || Number.isNaN(Number(val))) return '-'
  const n = Number(val)
  const a = Math.abs(n)
  if (a >= 1e8) return `${(n / 1e8).toFixed(2)} 亿份`
  if (a >= 1e4) return `${(n / 1e4).toFixed(2)} 万份`
  return `${n.toFixed(0)} 份`
}

export function formatTurnover(val) {
  return formatAmount(val)
}
