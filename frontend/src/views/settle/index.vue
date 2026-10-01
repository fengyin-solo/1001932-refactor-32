<template>
  <section class="page" data-module="settle">
    <header class="page-head">
      <div>
        <h2>电量结算管理</h2>
        <p class="page-desc">金额口径统一为「上网电量 × 结算电价」，结算列表、结算详情、导出清单取同一份计算结果。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记电量结算单</button>
        <button class="btn" type="button" @click="exportRows">导出电量结算清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>结算单号</span>
        <input v-model="keyword" placeholder="按结算单号检索" />
      </label>
      <label class="filter-item">
        <span>结算状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['结算单号'] ?? '—' }}</td>
          <td>{{ row['结算周期'] ?? '—' }}</td>
          <td>{{ row['结算周期天数'] == null ? '—' : `${row['结算周期天数']} 天` }}</td>
          <td>{{ row['所属场站'] ?? '—' }}</td>
          <td class="num">{{ formatQuantity(row['上网电量']) }}</td>
          <td class="num">{{ formatPrice(row['结算电价']) }}</td>
          <td class="num">{{ formatMoney(row['补贴金额']) }}</td>
          <td class="num amount-cell">
            {{ formatMoney(row['结算金额']) }}
            <span v-if="row['锁定结算金额'] != null" class="lock-tag" title="已核对结清，金额按当初取值固化，口径调整不影响本单">已固化</span>
          </td>
          <td>{{ row['结算状态'] ?? row.status ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无电量结算数据，可先登记电量结算单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条电量结算记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 结算详情：金额直接取后端共用口径，与列表行逐分一致 -->
    <div v-if="detail" class="drawer-mask" @click.self="detail = null">
      <aside class="drawer">
        <header class="drawer-head">
          <h3>电量结算单详情</h3>
          <button class="link" type="button" @click="detail = null">关闭</button>
        </header>
        <dl class="detail-grid">
          <template v-for="field in detailFields" :key="field">
            <dt>{{ field }}</dt>
            <dd :class="{ num: numericFields.includes(field) }">{{ formatDetail(field, detail[field]) }}</dd>
          </template>
        </dl>
        <p v-if="detail['锁定结算金额'] != null" class="lock-note">
          本单已核对结清，结算金额按 {{ detail['锁定金额口径版本'] || '原口径' }} 取值固化为
          {{ formatMoney(detail['锁定结算金额']) }}，口径调整不会改变它。
        </p>
      </aside>
    </div>

    <!-- 登记结算单：金额由后端按共用口径计算，前端不自行乘算 -->
    <div v-if="creating" class="drawer-mask" @click.self="creating = false">
      <aside class="drawer">
        <header class="drawer-head">
          <h3>登记电量结算单</h3>
          <button class="link" type="button" @click="creating = false">关闭</button>
        </header>
        <form class="create-form" @submit.prevent="submitCreate">
          <label v-for="field in createFields" :key="field.key" class="filter-item">
            <span>{{ field.label }}{{ field.required ? ' *' : '' }}</span>
            <input
              v-model="createForm[field.key]"
              :type="field.numeric ? 'number' : 'text'"
              :step="field.key === '结算电价' ? '0.0001' : '0.01'"
              :placeholder="`请输入${field.label}`"
            />
          </label>
          <div class="form-actions">
            <button class="btn primary" type="submit">提交登记</button>
            <button class="btn ghost" type="button" @click="creating = false">取消</button>
          </div>
        </form>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/settle'
const columns = ['结算单号', '结算周期', '结算周期天数', '所属场站', '上网电量', '结算电价', '补贴金额', '结算金额', '结算状态']
const actions = ['提交核算', '提交复核', '确认结清']
const statuses = ['待核算', '已核算', '待复核', '已结清']

const numericFields = ['上网电量', '结算电价', '补贴金额', '结算金额', '锁定结算金额']
const detailFields = [
  '结算单号', '结算周期', '结算周期天数', '所属场站', '上网电量', '结算电价',
  '补贴金额', '结算金额', '结算状态', '金额口径版本', '锁定结算金额', '锁定金额口径版本',
]
const createFields = [
  { key: '结算单号', label: '结算单号', required: true, numeric: false },
  { key: '结算周期', label: '结算周期（如 2026-10 或 2026-10-01至2026-10-31）', required: true, numeric: false },
  { key: '所属场站', label: '所属场站', required: true, numeric: false },
  { key: '上网电量', label: '上网电量（kWh）', required: false, numeric: true },
  { key: '结算电价', label: '结算电价（元/kWh）', required: false, numeric: true },
  { key: '补贴金额', label: '补贴金额（元，不计入结算金额）', required: false, numeric: true },
] as const

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const detail = ref<Row | null>(null)
const creating = ref(false)
const createForm = ref<Record<string, string>>({})

const stats = computed(() => {
  const pending = rows.value.filter((r) => (r.status ?? r['结算状态']) === '待核算').length
  const currentMonth = new Date().toISOString().slice(0, 7)
  const monthEnergy = rows.value
    .filter((r) => String(r['结算周期'] ?? '').includes(currentMonth))
    .reduce((sum, r) => sum + Number(r['上网电量'] ?? 0), 0)
  const settledAmount = rows.value
    .filter((r) => (r.status ?? r['结算状态']) === '已结清')
    .reduce((sum, r) => sum + Number(r['结算金额'] ?? 0), 0)
  return [
    { label: '待核算单据', value: `${pending} 张` },
    { label: '本月上网电量', value: `${formatQuantity(monthEnergy)} kWh` },
    { label: '已结清金额', value: formatMoney(settledAmount) },
  ]
})

function formatMoney(value: unknown): string {
  const n = Number(value)
  if (value == null || value === '' || Number.isNaN(n)) return '—'
  return `¥ ${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatQuantity(value: unknown): string {
  const n = Number(value)
  if (value == null || value === '' || Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function formatPrice(value: unknown): string {
  const n = Number(value)
  if (value == null || value === '' || Number.isNaN(n)) return '—'
  return n.toFixed(4)
}

function formatDetail(field: string, value: unknown): string {
  if (field === '上网电量') return value == null || value === '' ? '—' : `${formatQuantity(value)} kWh`
  if (field === '结算电价') return value == null || value === '' ? '—' : `${formatPrice(value)} 元/kWh`
  if (field === '结算周期天数') return value == null || value === '' ? '—' : `${value} 天`
  if (['补贴金额', '结算金额', '锁定结算金额'].includes(field)) return formatMoney(value)
  return value == null || value === '' ? '—' : String(value)
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function buildQuery(extra: Record<string, string> = {}) {
  const params = new URLSearchParams(extra)
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (statusFilter.value) params.set('status', statusFilter.value)
  const query = params.toString()
  return query ? `?${query}` : ''
}

async function exportRows() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/export${buildQuery({ format: 'csv' })}`)
    if (!response.ok) throw new Error('电量结算清单导出失败')
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = '电量结算清单.csv'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '电量结算清单导出失败'
  }
}

function openCreate() {
  createForm.value = {}
  creating.value = true
}

async function submitCreate() {
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '电量结算单登记失败')
    }
    creating.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '电量结算单登记失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error('电量结算单详情读取失败')
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '电量结算单详情读取失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '电量结算动作未生效，请稍后重试')
    }
    await reload()
    if (detail.value && detail.value.id === row.id) detail.value = payload.entry
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '电量结算操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}${buildQuery()}`)
    if (!response.ok) throw new Error('电量结算单列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '电量结算列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.page-actions { display: flex; gap: 8px; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.amount-cell { white-space: nowrap; }
.lock-tag {
  margin-left: 6px;
  font-size: 11px;
  color: #b54708;
  background: #fffaeb;
  border: 1px solid #fedf89;
  border-radius: 4px;
  padding: 0 4px;
}
.drawer-mask {
  position: fixed;
  inset: 0;
  background: rgba(16, 24, 40, 0.45);
  display: flex;
  justify-content: flex-end;
  z-index: 50;
}
.drawer {
  width: 460px;
  max-width: 92vw;
  height: 100%;
  background: #fff;
  padding: 16px 20px;
  overflow-y: auto;
  box-shadow: -8px 0 24px rgba(16, 24, 40, 0.12);
}
.drawer-head { display: flex; justify-content: space-between; align-items: center; }
.drawer-head h3 { margin: 0; font-size: 16px; }
.detail-grid { display: grid; grid-template-columns: 130px 1fr; row-gap: 10px; column-gap: 12px; margin-top: 16px; }
.detail-grid dt { color: var(--muted); font-size: 13px; }
.detail-grid dd { margin: 0; font-size: 13px; }
.lock-note {
  margin-top: 16px;
  padding: 8px 10px;
  background: #fffaeb;
  border: 1px solid #fedf89;
  border-radius: 6px;
  color: #b54708;
  font-size: 12px;
}
.create-form { display: flex; flex-direction: column; gap: 12px; margin-top: 16px; }
.create-form .filter-item span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.create-form input { width: 100%; box-sizing: border-box; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.form-actions { display: flex; gap: 8px; margin-top: 8px; }
.filter-item select { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
</style>
