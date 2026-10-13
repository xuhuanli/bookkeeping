export const today = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' })
export const cents = value => Math.round((Number(value) + Number.EPSILON) * 100)
export const round = value => cents(value) / 100
export const money = value => new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value || 0)
export const total = (rows, get = row => row.amount) => rows.reduce((n, row) => n + cents(get(row)), 0) / 100
export const balance = o => (cents(o.price) - cents(o.received) - cents(o.discount)) / 100
export const statuses = { booked: '待制作', making: '制作中', ready: '待发货', shipped: '已发货', delivered: '已完成' }
export const categories = ['采购-布料','采购-耗材辅料','采购-工具','每周合并发货运费','其他支出','收入-定金','收入-尾款','其他收入']
export const clone = value => JSON.parse(JSON.stringify(value))
export const dayLabel = day => day ? `${Number(day.slice(5,7))}月${Number(day.slice(8,10))}日` : '未约定'
export function download(url, name) { const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove() }
export function orderText(o) { return `手作订单确认\n顾客：${o.customer}\n订单：${o.id}\n下单日期：${o.date}\n款式：${o.style}\n订单报价：¥${money(o.price)}\n已收定金：¥${money(o.deposit)}\n已收尾款：¥${money(o.final)}\n抹零 / 优惠：¥${money(o.discount)}\n待收尾款：¥${money(balance(o))}\n状态：${statuses[o.status]}${o.due ? '\n预计交付：'+o.due : ''}${o.tracking ? '\n快递单号：'+o.tracking : ''}${o.note ? '\n备注：'+o.note : ''}` }
// LAN HTTP on phones often has no Clipboard API. Keep a copy fallback available.
export async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true }
  const input = document.createElement('textarea'); input.value = text; input.style.position = 'fixed'; input.style.opacity = '0'; document.body.appendChild(input); input.focus(); input.select(); input.setSelectionRange(0, text.length)
  const copied = document.execCommand('copy'); input.remove(); return copied
}
