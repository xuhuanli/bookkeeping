import { reactive, ref } from 'vue'

export function useLedger() {
  const state = reactive({ orders: [], transactions: [], styles: [] })
  const reports = reactive({ total: {}, months: [] })
  const revision = ref(0), hasUndo = ref(false), busy = ref(false), loading = ref(true), error = ref('')
  async function request(path, options = {}) {
    const headers = { ...options.headers }
    if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json'
    if (options.method && options.method !== 'GET' && path !== '/api/images') headers['X-Ledger-Revision'] = String(revision.value)
    let response
    try { response = await fetch(path, { ...options, headers }) } catch { throw new Error('无法连接电脑上的服务，请检查电脑是否开机、手机是否连接同一 Wi-Fi。') }
    const payload = await response.json()
    if (!response.ok) {
      const detail = payload.detail
      if (Array.isArray(detail)) throw new Error('请检查必填项、日期和金额。金额最多保留两位小数。')
      throw new Error(detail || '操作未完成，请重试。')
    }
    return payload
  }
  function apply(result) {
    Object.assign(state, result.data); revision.value = result.revision; hasUndo.value = result.hasUndo
    if (result.reports) Object.assign(reports, result.reports)
  }
  async function load() { loading.value = true; error.value = ''; try { apply(await request('/api/ledger')) } catch (e) { error.value = e.message } finally { loading.value = false } }
  async function mutate(path, method = 'POST', body) {
    if (busy.value) throw new Error('正在保存，请稍等。')
    busy.value = true
    try { const result = await request(path, { method, body: body === undefined ? undefined : JSON.stringify(body) }); apply(result); return result } finally { busy.value = false }
  }
  async function upload(file) { const data = new FormData(); data.append('file', file); return (await request('/api/images', { method: 'POST', body: data })).url }
  return { state, reports, revision, hasUndo, busy, loading, error, load, mutate, upload }
}
