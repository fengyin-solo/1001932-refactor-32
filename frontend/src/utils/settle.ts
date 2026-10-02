/**
 * 电量结算展示口径：金额一律固定两位小数。
 *
 * 列表页、详情弹层、导出后的金额展示都走这里，避免不同入口各写一套
 * toFixed/字符串拼接导致同一张结算单显示得不一样。
 * 金额本身以后端共用口径（settle_calc）算出的结果为准，这里只负责显示。
 */
export function formatAmount(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const amount = typeof value === 'number' ? value : Number(String(value).trim())
  if (!Number.isFinite(amount)) return '—'
  return amount.toFixed(2)
}
