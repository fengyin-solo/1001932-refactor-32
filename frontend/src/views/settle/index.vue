<template>
  <section class="page" data-module="settle">
    <header class="page-head">
      <div>
        <h2>电量结算管理</h2>
        <p class="page-desc">维护电量结算单，围绕结算单号、结算周期、所属场站、上网电量做登记、筛选与状态流转。</p>
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
        <select v-model="status">
          <option value="">全部</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
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
          <td v-for="column in columns" :key="column">
            {{ moneyColumns.includes(column) ? formatAmount(row[column]) : (row[column] ?? '—') }}
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button
              v-for="action in availableActions(row)"
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

    <div v-if="detail" class="settle-mask" @click.self="closeDetail">
      <div class="settle-dialog">
        <header class="settle-dialog-head">
          <h3>结算单详情 · {{ detail.结算单号 }}</h3>
          <button class="link" type="button" @click="closeDetail">关闭</button>
        </header>
        <dl class="settle-detail">
          <template v-for="column in columns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ moneyColumns.includes(column) ? formatAmount(detail[column]) : (detail[column] ?? '—') }}</dd>
          </template>
          <dt>金额口径</dt>
          <dd>
            {{ detail.status === '已结清'
              ? `按结清当时快照保留（${detail['口径版本'] ?? '历史口径'}）`
              : `现行口径（${detail['口径版本'] ?? '现行口径'}）` }}
          </dd>
        </dl>
        <p class="settle-dialog-tip">详情金额与列表、导出清单取同一份结算口径结果。</p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { formatAmount } from '@/utils/settle'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/settle'
const columns = ["结算单号", "结算周期", "所属场站", "上网电量", "结算电价", "补贴金额", "结算金额", "结算状态"]
// 金额列统一走 formatAmount，展示口径与后端口径及导出清单保持一致。
const moneyColumns = ["补贴金额", "结算金额"]
const actions = ["提交核算", "提交复核", "确认结清"]
const statuses = ["待核算", "已核算", "待复核", "已结清"]
// 已结清之后不允许再执行动作，防止已核对固化的金额被重新流转。
const FINAL_STATUS = '已结清'

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const status = ref('')
const detail = ref<Row | null>(null)

const stats = computed(() => {
  const pending = rows.value.filter((row) => row.status !== FINAL_STATUS).length
  const monthPower = rows.value.reduce(
    (sum, row) => sum + (Number(row['上网电量']) || 0),
    0,
  )
  const settledAmount = rows.value
    .filter((row) => row.status === FINAL_STATUS)
    .reduce((sum, row) => sum + (Number(row['结算金额']) || 0), 0)
  return [
    { label: '待处理单据', value: pending },
    { label: '当前上网电量(kWh)', value: monthPower.toLocaleString() },
    { label: '已结清金额(元)', value: formatAmount(settledAmount) },
  ]
})

function queryString(): string {
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (status.value) params.set('status', status.value)
  return params.toString()
}

function availableActions(row: Row): string[] {
  return row.status === FINAL_STATUS ? [] : actions
}

function resetFilters() {
  keyword.value = ''
  status.value = ''
  void reload()
}

function exportRows() {
  // 带上当前查询条件，导出的清单就是列表看到的那一批；金额由后端同一份口径生成。
  const query = queryString()
  window.open(`${ENDPOINT}/export${query ? `?${query}` : ''}`, '_blank')
}

function openCreate() {
  errorMessage.value = '电量结算单登记入口尚未接入审批流'
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('电量结算单详情读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '电量结算单详情读取失败'
  }
}

function closeDetail() {
  detail.value = null
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '电量结算动作未生效，请稍后重试')
    }
    detail.value = null
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '电量结算操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}?${queryString()}`)
    if (!response.ok) {
      throw new Error('电量结算单列表读取失败')
    }
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
.settle-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.settle-dialog {
  width: 480px;
  max-width: calc(100vw - 32px);
  background: #fff;
  border-radius: 8px;
  padding: 16px 20px;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.2);
}
.settle-dialog-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.settle-dialog-head h3 { font-size: 15px; margin: 0; }
.settle-detail {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 6px 12px;
  margin: 8px 0;
  font-size: 13px;
}
.settle-detail dt { color: var(--muted); }
.settle-detail dd { margin: 0; }
.settle-dialog-tip { color: var(--muted); font-size: 12px; margin: 8px 0 0; }
</style>
