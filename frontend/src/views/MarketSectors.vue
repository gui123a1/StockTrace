<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MarketSubNav from '../components/MarketSubNav.vue'
import MarketDataStatus from '../components/MarketDataStatus.vue'
import { marketApi } from '../api/stocks.js'
import { formatDateTime, formatPct, pctClass } from '../utils/format.js'
import { formatAmount } from '../utils/marketFormat.js'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const error = ref('')
const data = ref(null)
const board = ref(route.query.board === 'concept' ? 'concept' : 'industry')
const q = ref(route.query.q || '')
const sort = ref(route.query.sort || 'net')
const order = ref(route.query.order === 'asc' ? 'asc' : 'desc')
const page = ref(Number(route.query.page) || 1)

const items = computed(() => data.value?.items || [])
const summary = computed(() => data.value?.summary || {})
const pagination = computed(() => data.value?.pagination || {
  page: 1,
  total_pages: 1,
  total: 0,
})
const inflowRows = computed(() => (data.value?.inflow_top || []).slice(0, 5))
const outflowRows = computed(() => (data.value?.outflow_top || []).slice(0, 5))
const inflowTotal = computed(() => inflowRows.value.reduce((sum, row) => sum + Number(row.net || 0), 0))
const outflowTotal = computed(() => outflowRows.value.reduce((sum, row) => sum + Number(row.net || 0), 0))
const netTone = computed(() => {
  const value = Number(summary.value.net_total || 0)
  if (value > 0) return '净流入'
  if (value < 0) return '净流出'
  return '资金平衡'
})

const insights = computed(() => {
  const concentration = summary.value.top_three_inflow_concentration_pct
  const breadth = summary.value.breadth_pct
  const divergenceCount = data.value?.divergences?.length || 0
  return [
    {
      tone: 'green',
      title: concentration == null ? '集中度待更新' : concentration >= 65 ? '主线集中' : '轮动较均衡',
      body: concentration == null
        ? '当前上游未提供可计算样本。'
        : `流入前三集中度 ${concentration.toFixed(1)}%，${concentration >= 65 ? '资金更偏向少数主线。' : '资金分布相对均衡。'}`,
    },
    {
      tone: 'amber',
      title: breadth == null ? '广度待更新' : breadth >= 50 ? '流入占优' : '流出占优',
      body: breadth == null
        ? '当前上游未提供可计算样本。'
        : `资金广度 ${breadth.toFixed(1)}%，${breadth >= 50 ? '净流入板块占多数。' : '净流出板块占多数。'}`,
    },
    {
      tone: 'blue',
      title: divergenceCount ? '存在价流背离' : '价流暂未背离',
      body: divergenceCount
        ? `发现 ${divergenceCount} 个显著价流背离板块，需结合后续价格确认。`
        : '当前横截面未发现显著价流背离。',
    },
  ]
})

function signedAmount(value) {
  const result = formatAmount(value)
  return Number(value) > 0 && result !== '-' ? `+${result}` : result
}

function metricWidth(value) {
  if (value == null || Number.isNaN(Number(value))) return '0%'
  return `${Math.min(100, Math.max(0, Number(value)))}%`
}

function barWidth(row, side) {
  const rows = side === 'in' ? inflowRows.value : outflowRows.value
  const maximum = Math.max(...rows.map(item => Math.abs(Number(item.net || 0))), 0)
  if (!maximum) return '0%'
  return `${Math.max(4, Math.abs(Number(row.net || 0)) / maximum * 100)}%`
}

function flowPath(side, index) {
  const rowY = 88 + index * 52
  const hubY = 164 + index * 10
  return side === 'out'
    ? `M 430 ${rowY} C 474 ${rowY}, 466 ${hubY}, 505 ${hubY}`
    : `M 695 ${hubY} C 734 ${hubY}, 726 ${rowY}, 770 ${rowY}`
}

function rowTitle(row) {
  return [
    row.name,
    `净额 ${signedAmount(row.net)}`,
    `流入 ${formatAmount(row.inflow)}`,
    `流出 ${formatAmount(row.outflow)}`,
    `涨跌 ${formatPct(row.change_pct)}`,
    `领涨 ${row.leader || '-'} ${formatPct(row.leader_pct)}`,
  ].join('\n')
}

async function load(reset = false) {
  if (reset) page.value = 1
  loading.value = true
  error.value = ''
  syncUrl()
  try {
    data.value = (await marketApi.getSectors({
      board: board.value,
      q: q.value || undefined,
      sort: sort.value,
      order: order.value,
      page: page.value,
      page_size: 50,
    })).data
    page.value = data.value.pagination?.page || 1
    syncUrl()
  } catch (e) {
    error.value = e.response?.data?.detail || '加载板块资金失败'
  } finally {
    loading.value = false
  }
}

function syncUrl() {
  router.replace({
    query: {
      ...(board.value === 'concept' ? { board: 'concept' } : {}),
      ...(q.value ? { q: q.value } : {}),
      ...(sort.value !== 'net' ? { sort: sort.value } : {}),
      ...(order.value !== 'desc' ? { order: order.value } : {}),
      ...(page.value > 1 ? { page: page.value } : {}),
    },
  })
}

function switchBoard(value) {
  board.value = value
  load(true)
}

function changePage(delta) {
  page.value += delta
  load()
}

function sortBy(field) {
  if (sort.value === field) order.value = order.value === 'desc' ? 'asc' : 'desc'
  else {
    sort.value = field
    order.value = 'desc'
  }
  load(true)
}

function sortMark(field) {
  if (sort.value !== field) return '↕'
  return order.value === 'desc' ? '↓' : '↑'
}

onMounted(load)
</script>

<template>
  <div class='page'>
    <MarketSubNav />
    <header class='page-header'>
      <div>
        <div class='title-row'>
          <h1>板块资金轮动</h1>
          <span class='live-badge'>当日快照</span>
        </div>
        <p>行业与概念板块的资金强弱、集中度和价流背离</p>
      </div>
      <div class='header-meta'>
        <span v-if='data?.updated_at'>更新 {{ formatDateTime(data.updated_at) }}</span>
        <button class='icon-button' type='button' title='刷新' aria-label='刷新' :disabled='loading' @click='load()'>↻</button>
      </div>
    </header>
    <div v-if='error' class='error-box'>{{ error }}</div>
    <section class='control-bar' aria-label='板块资金筛选'>
      <div class='segmented' aria-label='板块类型'>
        <button type='button' :class='{ active: board === `industry` }' @click='switchBoard(`industry`)'>行业资金</button>
        <button type='button' :class='{ active: board === `concept` }' @click='switchBoard(`concept`)'>概念资金</button>
      </div>
      <div class='period-tabs' aria-label='统计周期'>
        <button type='button' class='active'>当日</button>
        <button type='button' disabled title='积累日度快照后开放'>5日</button>
        <button type='button' disabled title='积累日度快照后开放'>10日</button>
        <button type='button' disabled title='积累日度快照后开放'>20日</button>
      </div>
      <form class='search-form' @submit.prevent='load(true)'>
        <input v-model.trim='q' aria-label='搜索板块或领涨股' placeholder='搜索板块或领涨股' />
        <button type='submit'>查询</button>
      </form>
    </section>

    <section class='snapshot-strip' aria-label='资金概览'>
      <div><span>板块样本</span><strong>{{ summary.sample_count ?? '-' }}</strong></div>
      <div><span>流入 / 流出</span><strong>{{ summary.inflow_count ?? '-' }} / {{ summary.outflow_count ?? '-' }}</strong></div>
      <div><span>资金广度</span><strong>{{ formatPct(summary.breadth_pct) }}</strong></div>
      <div><span>前三集中度</span><strong>{{ formatPct(summary.top_three_inflow_concentration_pct) }}</strong></div>
    </section>
    <section class='flow-shell'>
      <div class='flow-shell-header'>
        <div>
          <span class='eyebrow'>资金流向</span>
          <h2>{{ board === 'industry' ? '行业' : '概念' }}板块前五强弱</h2>
        </div>
        <span class='method-label'>当日横截面</span>
      </div>

      <div v-if='loading && !data' class='flow-loading'>正在加载板块资金...</div>
      <div v-else class='flow-stage'>
        <svg class='flow-lines' viewBox='0 0 1200 360' preserveAspectRatio='none' aria-hidden='true'>
          <path v-for='(_, index) in outflowRows' :key='`out-${index}`' class='line-out' :d='flowPath(`out`, index)' />
          <path v-for='(_, index) in inflowRows' :key='`in-${index}`' class='line-in' :d='flowPath(`in`, index)' />
        </svg>

        <div class='flow-column flow-column-out'>
          <div class='column-heading'>
            <div><span>净流出板块</span><small>前五合计</small></div>
            <strong class='down'>{{ signedAmount(outflowTotal) }}</strong>
          </div>
          <div class='flow-list'>
            <div v-for='(row, index) in outflowRows' :key='row.name' class='flow-row' :title='rowTitle(row)'>
              <span class='rank rank-out'>{{ String(index + 1).padStart(2, '0') }}</span>
              <div class='flow-name'><b>{{ row.name }}</b><small>{{ row.leader || '暂无领涨股' }}</small></div>
              <div class='flow-track'><i class='flow-fill' :style='{ width: barWidth(row, `out`) }'></i></div>
              <strong class='flow-value down'>{{ signedAmount(row.net) }}</strong>
            </div>
          </div>
        </div>
        <div class='flow-core-wrap'>
          <div class='flow-core'>
            <span class='flow-symbol' aria-hidden='true'>⇄</span>
            <small>{{ netTone }}</small>
            <strong :class='pctClass(summary.net_total)'>{{ signedAmount(summary.net_total) }}</strong>
            <span>板块净额</span>
          </div>
        </div>

        <div class='flow-column flow-column-in'>
          <div class='column-heading'>
            <div><span>净流入板块</span><small>前五合计</small></div>
            <strong class='up'>{{ signedAmount(inflowTotal) }}</strong>
          </div>
          <div class='flow-list'>
            <div v-for='(row, index) in inflowRows' :key='row.name' class='flow-row' :title='rowTitle(row)'>
              <span class='rank rank-in'>{{ String(index + 1).padStart(2, '0') }}</span>
              <div class='flow-name'><b>{{ row.name }}</b><small>{{ row.leader || '暂无领涨股' }}</small></div>
              <div class='flow-track'><i class='flow-fill' :style='{ width: barWidth(row, `in`) }'></i></div>
              <strong class='flow-value up'>{{ signedAmount(row.net) }}</strong>
            </div>
          </div>
        </div>
        <div v-if='!outflowRows.length && !inflowRows.length' class='flow-empty'>暂无资金流向数据</div>
      </div>

      <footer class='flow-footnote'>
        <span aria-hidden='true'>ⓘ</span>
        <p>{{ data?.methodology || '板块资金为上游当日聚合强弱指标，不代表板块之间的真实资金转移路径。' }}</p>
      </footer>
    </section>
    <section class='insight-panel'>
      <h2>解读</h2>
      <div class='insight-grid'>
        <article v-for='(item, index) in insights' :key='item.title'>
          <span class='insight-index' :class='item.tone'>{{ index + 1 }}</span>
          <div><strong>{{ item.title }}</strong><p>{{ item.body }}</p></div>
        </article>
      </div>
    </section>

    <section class='strength-panel'>
      <div class='strength-item'>
        <div class='strength-heading'><span>轮动广度</span><strong>{{ formatPct(summary.breadth_pct) }}</strong></div>
        <div class='meter'><i class='breadth-meter' :style='{ width: metricWidth(summary.breadth_pct) }'></i></div>
        <p>{{ Number(summary.breadth_pct) >= 50 ? '净流入板块占多数，市场扩散度较高。' : '净流出板块占多数，市场扩散度偏弱。' }}</p>
      </div>
      <div class='strength-item'>
        <div class='strength-heading'><span>拥挤程度</span><strong>{{ formatPct(summary.top_three_inflow_concentration_pct) }}</strong></div>
        <div class='meter'><i class='crowding-meter' :style='{ width: metricWidth(summary.top_three_inflow_concentration_pct) }'></i></div>
        <p>{{ Number(summary.top_three_inflow_concentration_pct) >= 65 ? '流入集中于少数主线，注意拥挤风险。' : '主线集中度适中，资金分布相对均衡。' }}</p>
      </div>
    </section>

    <section v-if='data?.divergences?.length' class='divergences'>
      <div class='section-title'><h2>价流背离</h2><span>{{ data.divergences.length }} 个板块</span></div>
      <div class='divergence-list'>
        <span v-for='row in data.divergences' :key='row.name'>
          {{ row.name }}
          <b :class='pctClass(row.net)'>{{ signedAmount(row.net) }}</b>
          <b :class='pctClass(row.change_pct)'>{{ formatPct(row.change_pct) }}</b>
        </span>
      </div>
    </section>
    <section class='table-card'>
      <div class='table-title'>
        <div><h2>{{ board === 'industry' ? '行业' : '概念' }}完整明细</h2><span>{{ pagination.total }} 条</span></div>
        <small>当日资金快照</small>
      </div>
      <div class='table-wrap'>
        <table>
          <thead><tr>
            <th>名称</th>
            <th><button type='button' @click='sortBy(`net`)'>净额 {{ sortMark('net') }}</button></th>
            <th><button type='button' @click='sortBy(`inflow`)'>流入 {{ sortMark('inflow') }}</button></th>
            <th><button type='button' @click='sortBy(`outflow`)'>流出 {{ sortMark('outflow') }}</button></th>
            <th><button type='button' @click='sortBy(`change_pct`)'>涨跌幅 {{ sortMark('change_pct') }}</button></th>
            <th>公司数</th><th>领涨股</th>
            <th><button type='button' @click='sortBy(`leader_pct`)'>领涨% {{ sortMark('leader_pct') }}</button></th>
          </tr></thead>
          <tbody><tr v-for='row in items' :key='row.name'>
            <td class='name'>{{ row.name }}</td>
            <td :class='pctClass(row.net)'>{{ signedAmount(row.net) }}</td>
            <td>{{ formatAmount(row.inflow) }}</td>
            <td>{{ formatAmount(row.outflow) }}</td>
            <td :class='pctClass(row.change_pct)'>{{ formatPct(row.change_pct) }}</td>
            <td>{{ row.company_count ?? '-' }}</td>
            <td>{{ row.leader || '-' }}</td>
            <td :class='pctClass(row.leader_pct)'>{{ formatPct(row.leader_pct) }}</td>
          </tr></tbody>
        </table>
        <div v-if='!items.length && !loading' class='empty'>暂无符合条件的板块</div>
      </div>
      <div class='pager'>
        <span>第 {{ pagination.page }} / {{ pagination.total_pages }} 页</span>
        <div>
          <button type='button' :disabled='pagination.page <= 1 || loading' @click='changePage(-1)'>上一页</button>
          <button type='button' :disabled='pagination.page >= pagination.total_pages || loading' @click='changePage(1)'>下一页</button>
        </div>
      </div>
    </section>
    <MarketDataStatus :meta='data?.meta' />
  </div>
</template>

<style scoped>
.page {
  color: #e7edf4;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 14px;
}

.title-row,
.header-meta,
.column-heading,
.strength-heading,
.section-title,
.table-title,
.pager {
  display: flex;
  align-items: center;
}

.title-row {
  gap: 10px;
}

.page-header h1 {
  margin: 0;
  font-size: 22px;
}

.page-header p {
  margin: 4px 0 0;
  color: #8592a2;
  font-size: 13px;
}

.live-badge,
.method-label {
  border: 1px solid #2e4251;
  border-radius: 4px;
  color: #8fc6d6;
  font-size: 11px;
  padding: 2px 7px;
}

.header-meta {
  gap: 12px;
  color: #71808f;
  font-size: 12px;
}

button {
  border: 1px solid #2b3947;
  border-radius: 5px;
  background: #121b24;
  color: #9eabb8;
  cursor: pointer;
  font: inherit;
}

button:hover:not(:disabled) {
  border-color: #497087;
  color: #e9f2f7;
}

button:disabled {
  cursor: not-allowed;
  opacity: .38;
}

.icon-button {
  display: grid;
  width: 34px;
  height: 34px;
  padding: 0;
  place-items: center;
  font-size: 18px;
}

.spinning {
  animation: spin .8s linear infinite;
}

.error-box {
  margin-bottom: 12px;
  border: 1px solid #6d3037;
  border-radius: 6px;
  background: #28171c;
  color: #ff9ca4;
  padding: 10px 12px;
}

.control-bar {
  display: grid;
  grid-template-columns: auto 1fr minmax(270px, 360px);
  gap: 18px;
  align-items: center;
  margin-bottom: 10px;
  border-top: 1px solid #26333e;
  border-bottom: 1px solid #26333e;
  padding: 10px 0;
}

.segmented,
.period-tabs,
.search-form {
  display: flex;
  gap: 5px;
}

.segmented button,
.period-tabs button {
  min-height: 30px;
  padding: 5px 11px;
}

.segmented button.active,
.period-tabs button.active {
  border-color: #327495;
  background: #163649;
  color: #e9f7ff;
}

.search-form {
  justify-self: end;
  width: 100%;
}

.search-form input {
  min-width: 0;
  flex: 1;
  border: 1px solid #2b3947;
  border-radius: 5px;
  outline: none;
  background: #0e161e;
  color: #e8eef4;
  padding: 7px 10px;
}

.search-form input:focus {
  border-color: #4680a0;
}

.search-form button {
  padding: 6px 14px;
}

.snapshot-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  margin-bottom: 10px;
  border: 1px solid #26343f;
  border-radius: 7px;
  background: #101820;
}

.snapshot-strip > div {
  padding: 10px 14px;
  border-right: 1px solid #26343f;
}

.snapshot-strip > div:last-child {
  border-right: 0;
}

.snapshot-strip span {
  color: #758391;
  font-size: 11px;
}

.snapshot-strip strong {
  display: block;
  margin-top: 2px;
  font-size: 15px;
}

.flow-shell,
.insight-panel,
.strength-panel,
.divergences,
.table-card {
  margin-bottom: 10px;
  border: 1px solid #26343f;
  border-radius: 8px;
  background: #0c141c;
}

.flow-shell-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid #25323c;
}

.eyebrow {
  display: block;
  margin-bottom: 2px;
  color: #70808e;
  font-size: 10px;
}

.flow-shell h2,
.insight-panel h2,
.section-title h2,
.table-title h2 {
  margin: 0;
  font-size: 14px;
}

.flow-stage {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 190px minmax(0, 1fr);
  min-height: 342px;
  padding: 12px 10px 14px;
  overflow: hidden;
}

.flow-lines {
  position: absolute;
  z-index: 0;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.flow-lines path {
  fill: none;
  stroke-width: 1.3;
  vector-effect: non-scaling-stroke;
}

.line-out {
  stroke: #347b63;
}

.line-in {
  stroke: #8a4248;
}

.flow-column,
.flow-core-wrap {
  position: relative;
  z-index: 1;
}

.flow-column {
  min-width: 0;
}

.column-heading {
  justify-content: space-between;
  min-height: 48px;
  padding: 0 8px;
}

.column-heading span,
.column-heading small {
  display: block;
}

.column-heading span {
  color: #dbe4eb;
  font-size: 12px;
  font-weight: 600;
}

.column-heading small {
  margin-top: 2px;
  color: #677581;
  font-size: 10px;
}

.column-heading > strong {
  font-size: 13px;
}

.flow-list {
  display: grid;
  gap: 4px;
}

.flow-row {
  display: grid;
  grid-template-columns: 28px minmax(68px, .7fr) minmax(80px, 1.25fr) 82px;
  gap: 8px;
  align-items: center;
  min-height: 48px;
  padding: 4px 8px;
}

.rank {
  display: grid;
  width: 27px;
  height: 23px;
  place-items: center;
  border: 1px solid #31424d;
  border-radius: 4px;
  color: #7f8d99;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 10px;
}

.rank-out {
  border-color: #285b4d;
  color: #6fc6a4;
}

.rank-in {
  border-color: #66363b;
  color: #e78990;
}

.flow-name {
  min-width: 0;
}

.flow-name b,
.flow-name small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.flow-name b {
  color: #dce5ec;
  font-size: 12px;
}

.flow-name small {
  margin-top: 2px;
  color: #687682;
  font-size: 9px;
}

.flow-track {
  height: 6px;
  overflow: hidden;
  border-radius: 3px;
  background: #1d2831;
}

.flow-fill {
  display: block;
  min-width: 3px;
  height: 100%;
  border-radius: inherit;
}

.flow-column-out .flow-fill {
  margin-left: auto;
  background: #64be9c;
}

.flow-column-in .flow-fill {
  background: #db666d;
}

.flow-value {
  text-align: right;
  font-size: 11px;
  white-space: nowrap;
}

.flow-core-wrap {
  display: grid;
  place-items: center;
}

.flow-core {
  display: grid;
  width: 150px;
  min-height: 112px;
  place-items: center;
  align-content: center;
  border: 1px solid #31526a;
  border-radius: 7px;
  background: #101b27;
  box-shadow: 0 0 0 5px rgba(23, 52, 69, .18);
}

.flow-symbol {
  color: #55a8d5;
  font-size: 23px;
  line-height: 1;
}

.flow-core small,
.flow-core > span:last-child {
  color: #738390;
  font-size: 10px;
}

.flow-core strong {
  margin: 3px 0;
  font-size: 21px;
}

.flow-empty,
.flow-loading {
  display: grid;
  min-height: 330px;
  place-items: center;
  color: #6d7a86;
  font-size: 12px;
}

.flow-empty {
  position: absolute;
  z-index: 3;
  inset: 0;
}

.flow-footnote {
  display: flex;
  gap: 7px;
  align-items: flex-start;
  border-top: 1px solid #25323c;
  color: #687681;
  padding: 9px 13px;
  font-size: 10px;
}

.flow-footnote p {
  margin: 0;
}

.insight-panel {
  display: grid;
  grid-template-columns: 74px 1fr;
  align-items: stretch;
}

.insight-panel > h2 {
  padding: 14px;
  border-right: 1px solid #25323c;
}

.insight-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
}

.insight-grid article {
  display: flex;
  gap: 10px;
  min-width: 0;
  padding: 12px 14px;
  border-right: 1px solid #25323c;
}

.insight-grid article:last-child {
  border-right: 0;
}

.insight-index {
  display: grid;
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  place-items: center;
  border-radius: 50%;
  font-size: 10px;
}

.insight-index.green {
  background: #173129;
  color: #6bc09f;
}

.insight-index.amber {
  background: #382a17;
  color: #e1a84b;
}

.insight-index.blue {
  background: #172c3b;
  color: #63acd3;
}

.insight-grid strong {
  display: block;
  color: #d7e0e7;
  font-size: 11px;
}

.insight-grid p,
.strength-item p {
  margin: 3px 0 0;
  color: #71808c;
  font-size: 10px;
  line-height: 1.45;
}

.strength-panel {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
}

.strength-item {
  padding: 12px 16px;
}

.strength-item:first-child {
  border-right: 1px solid #25323c;
}

.strength-heading {
  justify-content: space-between;
  margin-bottom: 7px;
  font-size: 11px;
}

.strength-heading strong {
  color: #dbe5ec;
  font-size: 12px;
}

.meter {
  height: 5px;
  overflow: hidden;
  border-radius: 3px;
  background: #1e2932;
}

.meter i {
  display: block;
  height: 100%;
  border-radius: inherit;
}

.breadth-meter {
  background: #4b9fc9;
}

.crowding-meter {
  background: #dfa13c;
}

.divergences {
  padding: 12px 14px;
}

.section-title,
.table-title,
.pager {
  justify-content: space-between;
}

.section-title > span,
.table-title span,
.table-title small {
  color: #71808c;
  font-size: 11px;
}

.divergence-list {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 9px;
}

.divergence-list > span {
  display: flex;
  gap: 6px;
  align-items: center;
  border-left: 2px solid #4a6070;
  background: #111b23;
  color: #aab5be;
  padding: 6px 9px;
  font-size: 10px;
}

.table-card {
  overflow: hidden;
}

.table-title {
  padding: 11px 13px;
  border-bottom: 1px solid #25323c;
}

.table-title > div {
  display: flex;
  gap: 8px;
  align-items: baseline;
}

.table-wrap {
  max-height: 540px;
  overflow: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

th {
  position: sticky;
  z-index: 2;
  top: 0;
  background: #101922;
  color: #75838f;
  font-weight: 500;
  text-align: right;
  white-space: nowrap;
}

th,
td {
  padding: 9px 10px;
  border-bottom: 1px solid #202c35;
}

th:first-child,
td:first-child {
  text-align: left;
}

th button {
  border: 0;
  background: transparent;
  color: inherit;
  padding: 0;
}

td {
  color: #aab4bd;
  text-align: right;
  white-space: nowrap;
}

tbody tr:hover {
  background: #111e27;
}

td.name {
  color: #e1e8ed;
  font-weight: 600;
}

.empty {
  color: #687681;
  padding: 36px;
  text-align: center;
}

.pager {
  color: #6d7a85;
  padding: 9px 12px;
  font-size: 11px;
}

.pager button {
  margin-left: 6px;
  padding: 5px 10px;
}

.up {
  color: #ec6c74;
}

.down {
  color: #68c29f;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1120px) {
  .control-bar {
    grid-template-columns: auto 1fr;
  }

  .search-form {
    grid-column: 1 / -1;
    justify-self: stretch;
  }

  .flow-stage {
    grid-template-columns: minmax(0, 1fr) 160px minmax(0, 1fr);
  }

  .flow-row {
    grid-template-columns: 26px minmax(62px, .8fr) minmax(56px, 1fr) 74px;
    gap: 6px;
    padding-inline: 5px;
  }

  .flow-core {
    width: 132px;
  }
}

@media (max-width: 900px) {
  .flow-stage {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px 18px;
  }

  .flow-lines {
    display: none;
  }

  .flow-core-wrap {
    grid-column: 1 / -1;
    grid-row: 1;
    padding: 8px 0;
  }

  .flow-column-out {
    grid-column: 1;
    grid-row: 2;
  }

  .flow-column-in {
    grid-column: 2;
    grid-row: 2;
  }

  .flow-core {
    width: 180px;
    min-height: 96px;
  }

  .insight-panel {
    grid-template-columns: 1fr;
  }

  .insight-panel > h2 {
    border-right: 0;
    border-bottom: 1px solid #25323c;
  }
}

@media (max-width: 680px) {
  .page-header {
    align-items: stretch;
  }

  .header-meta {
    flex-direction: column;
    align-items: flex-end;
  }

  .control-bar {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .period-tabs,
  .segmented {
    overflow-x: auto;
  }

  .search-form {
    grid-column: auto;
  }

  .snapshot-strip {
    grid-template-columns: repeat(2, 1fr);
  }

  .snapshot-strip > div:nth-child(2) {
    border-right: 0;
  }

  .snapshot-strip > div:nth-child(-n + 2) {
    border-bottom: 1px solid #26343f;
  }

  .flow-stage {
    grid-template-columns: 1fr;
  }

  .flow-core-wrap,
  .flow-column-out,
  .flow-column-in {
    grid-column: 1;
  }

  .flow-core-wrap { grid-row: 1; }
  .flow-column-out { grid-row: 2; }
  .flow-column-in { grid-row: 3; }

  .insight-grid,
  .strength-panel {
    grid-template-columns: 1fr;
  }

  .insight-grid article,
  .strength-item:first-child {
    border-right: 0;
    border-bottom: 1px solid #25323c;
  }

  .flow-row {
    grid-template-columns: 28px minmax(72px, .75fr) minmax(75px, 1.2fr) 78px;
  }

  .table-wrap {
    max-height: 480px;
  }
}

@media (max-width: 430px) {
  .page-header {
    flex-direction: column;
  }

  .header-meta {
    flex-direction: row;
    justify-content: space-between;
  }

  .flow-row {
    grid-template-columns: 25px 72px minmax(50px, 1fr) 72px;
    gap: 5px;
  }

  .flow-name small {
    display: none;
  }
}
</style>
