<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MarketSubNav from '../components/MarketSubNav.vue'
import MarketDataStatus from '../components/MarketDataStatus.vue'
import EtfDetailPanel from '../components/EtfDetailPanel.vue'
import { marketApi } from '../api/stocks.js'
import { formatPct, formatNum, pctClass } from '../utils/format.js'
import { formatAmount, formatShare } from '../utils/marketFormat.js'

const route = useRoute(), router = useRouter()
const loading = ref(false), error = ref(''), data = ref(null)
const selectedCode = ref(route.query.code || '')
const items = computed(() => data.value?.items || [])
const summary = computed(() => data.value?.summary || {})

async function load() {
  loading.value = true; error.value = ''
  try { data.value = (await marketApi.getNationalEtf()).data }
  catch (e) { error.value = e.response?.data?.detail || '加载观察名单失败' }
  finally { loading.value = false }
}
function select(row) { selectedCode.value = row.code; router.replace({ query: { code: row.code } }) }
onMounted(load)
</script>

<template>
  <div class="page">
    <MarketSubNav />
    <div class="page-header">
      <div><div class="title-line"><h1>国家队相关 ETF 观察</h1><span>观察名单 · 非官方持仓</span></div><p>宽基与政策相关 ETF 的行情、份额与资金快照</p></div>
      <button class="primary" @click="load" :disabled="loading">{{ loading ? '加载中...' : '刷新' }}</button>
    </div>
    <div v-if="error" class="error-box">{{ error }}</div>
    <div class="warning"><b>数据边界</b> {{ data?.disclaimer || '该页面是研究观察名单，不代表任何机构的官方持仓。' }}</div>
    <div v-if="data?.watchlist_definition" class="definition">
      <span><b>名单维护：</b>{{ data.watchlist_definition.maintained_by }}</span>
      <span><b>筛选依据：</b>{{ data.watchlist_definition.basis }}</span>
      <span><b>官方持仓：</b>{{ data.watchlist_definition.is_official_holding ? '是' : '否' }}</span>
    </div>
    <div class="summary-grid">
      <div><label>有行情标的</label><b>{{ summary.count ?? '-' }} 只</b></div>
      <div><label>合计主力净流入</label><b :class="pctClass(summary.total_main_net)">{{ formatAmount(summary.total_main_net) }}</b></div>
      <div><label>合计最新份额</label><b>{{ formatShare(summary.total_share) }}</b></div>
      <div><label>合计市场规模</label><b>{{ formatAmount(summary.total_market_cap) }}</b></div>
    </div>
    <div class="workbench">
      <section class="table-card"><div class="table-wrap"><table>
        <thead><tr><th>#</th><th>代码</th><th>ETF 名称</th><th>最新价</th><th>涨跌幅</th><th>主力净流入</th><th>最新份额</th><th>总市值</th><th>换手</th><th>折溢价</th></tr></thead>
        <tbody><tr v-for="(row,i) in items" :key="row.code" :class="{ selected:selectedCode===row.code, muted:!row.listed }" :tabindex="row.listed ? 0 : -1" @click="row.listed && select(row)" @keyup.enter="row.listed && select(row)">
          <td>{{ i+1 }}</td><td class="code">{{ row.code }}</td><td class="name">{{ row.name }} <small v-if="!row.listed">暂无行情</small></td><td>{{ formatNum(row.price) }}</td>
          <td :class="pctClass(row.change_pct)">{{ formatPct(row.change_pct) }}</td><td :class="pctClass(row.main_net)">{{ formatAmount(row.main_net) }}</td>
          <td>{{ formatShare(row.share) }}</td><td>{{ formatAmount(row.market_cap) }}</td><td>{{ formatPct(row.turnover_rate) }}</td><td :class="pctClass(row.discount_rate)">{{ formatPct(row.discount_rate) }}</td>
        </tr></tbody>
      </table><div v-if="!items.length&&!loading" class="empty">暂无观察数据</div></div></section>
      <EtfDetailPanel :code="selectedCode" />
    </div>
    <MarketDataStatus :meta="data?.meta" :fallback="data?.disclaimer" />
  </div>
</template>

<style scoped>
.page{color:#dce4f2}.page-header{display:flex;justify-content:space-between;gap:12px;margin-bottom:11px}.page-header h1{margin:0;font-size:22px}.page-header p{margin:4px 0 0;color:#71809a;font-size:13px}.title-line{display:flex;align-items:center;gap:9px;flex-wrap:wrap}.title-line span{color:#ffbd6b;background:#382711;border:1px solid #694718;border-radius:5px;padding:3px 7px;font-size:11px}.primary{cursor:pointer;border:1px solid #286391;background:#174673;color:#fff;border-radius:6px;padding:7px 13px}.primary:disabled{opacity:.5}.error-box{background:#3a1520;color:#ff8796;padding:10px;border-radius:7px;margin-bottom:10px}.warning{background:#211b15;border:1px solid #584126;color:#cbb892;padding:10px 12px;border-radius:8px;font-size:12px;margin-bottom:10px;line-height:1.5}.warning b{color:#f0bd71;margin-right:6px}.definition{display:flex;flex-wrap:wrap;gap:8px 18px;background:#0d1729;border:1px solid #293b5b;border-radius:8px;padding:9px 11px;margin-bottom:10px;color:#7e8ca4;font-size:12px}.definition b{color:#aeb9cb}.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-bottom:10px}.summary-grid>div{background:#111d34;border:1px solid #213251;border-radius:8px;padding:11px}.summary-grid label{display:block;color:#68758d;font-size:11px}.summary-grid b{display:block;margin-top:5px;font-size:17px}.workbench{display:grid;grid-template-columns:minmax(0,1.8fr) minmax(320px,.9fr);gap:10px;margin-bottom:10px;align-items:start}.table-card{min-width:0;background:#111d34;border:1px solid #213251;border-radius:10px;overflow:hidden}.table-wrap{overflow:auto;max-height:720px}table{width:100%;border-collapse:collapse;font-size:12px}th{position:sticky;top:0;background:#0d192d;color:#7887a1;font-weight:500;text-align:right;padding:9px 8px;white-space:nowrap}td{padding:8px;border-bottom:1px solid #1d2a43;text-align:right;white-space:nowrap}th:nth-child(-n+3),td:nth-child(-n+3){text-align:left}tbody tr{cursor:pointer}tbody tr:hover,tbody tr.selected{background:#162b49}tr.muted{opacity:.5;cursor:not-allowed}.code{color:#7eb8e8}.name{color:#e0e7f1}.name small{color:#80736a;font-size:10px;margin-left:4px}.empty{text-align:center;padding:40px;color:#64718a}@media(max-width:1000px){.workbench{grid-template-columns:1fr}.summary-grid{grid-template-columns:repeat(2,1fr)}}
</style>
