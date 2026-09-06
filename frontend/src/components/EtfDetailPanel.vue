<script setup>
import { computed, ref, watch } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { marketApi } from '../api/stocks.js'
import { formatNum, formatPct, pctClass } from '../utils/format.js'
import { formatAmount, formatShare } from '../utils/marketFormat.js'
import MarketDataStatus from './MarketDataStatus.vue'

use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, CanvasRenderer])

const props = defineProps({ code: { type: String, default: '' } })
const loading = ref(false)
const error = ref('')
const data = ref(null)
const range = ref('3m')

const RANGE_OPTIONS = [['1w', '1周'], ['1m', '1月'], ['3m', '3月'], ['6m', '半年'], ['1y', '1年'], ['custom', '自定义']]
const _today = new Date()
const _ago = days => {
  const d = new Date(_today)
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}
const customStart = ref(_ago(30))
const customEnd = ref(_today.toISOString().slice(0, 10))

const quote = computed(() => data.value?.quote || {})
const performance = computed(() => data.value?.price_performance || {})
const history = computed(() => data.value?.history?.items || [])
const stats = computed(() => data.value?.history?.stats || null)
const chartOption = computed(() => {
  if (!history.value.length) return {}
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', backgroundColor: '#101827', borderColor: '#33415f', textStyle: { color: '#ddd' } },
    legend: { data: ['收盘价', '成交额'], textStyle: { color: '#8490a8' }, top: 0 },
    grid: [{ left: 45, right: 14, top: 34, height: '54%' }, { left: 45, right: 14, top: '73%', height: '16%' }],
    xAxis: [
      { type: 'category', data: history.value.map(i => i.date), axisLabel: { color: '#6f7d96', hideOverlap: true, showMinLabel: true, showMaxLabel: true }, axisLine: { lineStyle: { color: '#2b3956' } } },
      { type: 'category', gridIndex: 1, data: history.value.map(i => i.date), axisLabel: { show: false }, axisLine: { lineStyle: { color: '#2b3956' } } },
    ],
    yAxis: [
      { type: 'value', scale: true, axisLabel: { color: '#6f7d96' }, splitLine: { lineStyle: { color: '#1b2943' } } },
      { type: 'value', gridIndex: 1, axisLabel: { show: false }, splitLine: { show: false } },
    ],
    series: [
      { name: '收盘价', type: 'line', showSymbol: false, smooth: true, data: history.value.map(i => i.close), itemStyle: { color: '#e94560' }, lineStyle: { width: 2 } },
      { name: '成交额', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: history.value.map(i => i.turnover), itemStyle: { color: '#315e8c' } },
    ],
  }
})

async function load() {
  if (!props.code) { data.value = null; return }
  loading.value = true
  error.value = ''
  try {
    const params = { range: range.value }
    if (range.value === 'custom') {
      if (!customStart.value || !customEnd.value) { loading.value = false; return }
      params.start_date = customStart.value
      params.end_date = customEnd.value
    }
    const res = await marketApi.getEtfDetail(props.code, params)
    data.value = res.data
  } catch (e) {
    error.value = e.response?.data?.detail || 'ETF 详情加载失败'
    data.value = null
  } finally { loading.value = false }
}

watch(() => props.code, load, { immediate: true })
watch(range, load)
</script>

<template>
  <aside class="detail-panel">
    <div v-if="!code" class="placeholder">选择左侧 ETF 查看行情与价格历史</div>
    <div v-else-if="loading" class="placeholder">详情加载中...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <template v-else-if="data">
      <header>
        <div><h2>{{ data.instrument?.name }}</h2><span>{{ data.instrument?.code }} · {{ data.instrument?.exchange || '-' }}</span></div>
        <div class="price"><strong>{{ formatNum(quote.price) }}</strong><span :class="pctClass(quote.change_pct)">{{ formatPct(quote.change_pct) }}</span></div>
      </header>
      <div class="metrics">
        <div><label>最新份额</label><b>{{ formatShare(quote.share) }}</b></div>
        <div><label>总市值</label><b>{{ formatAmount(quote.market_cap) }}</b></div>
        <div><label>成交额</label><b>{{ formatAmount(quote.turnover) }}</b></div>
        <div><label>主力净流入</label><b :class="pctClass(quote.main_net)">{{ formatAmount(quote.main_net) }}</b></div>
        <div><label>IOPV</label><b>{{ formatNum(quote.iopv) }}</b></div>
        <div><label>折溢价</label><b :class="pctClass(quote.discount_rate)">{{ formatPct(quote.discount_rate) }}</b></div>
      </div>
      <div class="range-tabs">
        <button v-for="r in RANGE_OPTIONS" :key="r[0]" :class="{ active: range === r[0] }" @click="range = r[0]">{{ r[1] }}</button>
      </div>
      <div v-if="range === 'custom'" class="custom-range">
        <input v-model="customStart" type="date" :max="customEnd" />
        <span>至</span>
        <input v-model="customEnd" type="date" :min="customStart" :max="customEnd" />
        <button class="apply" :disabled="!customStart || !customEnd || loading" @click="load">查询</button>
      </div>
      <v-chart v-if="history.length && chartOption.series" :option="chartOption" autoresize class="chart" />
      <p v-if="history.length" class="history-range">
        数据区间 {{ data.history.start_date }} ~ {{ data.history.end_date }} · {{ data.history.count }} 个交易日
      </p>
      <div v-else class="history-empty">
        <b>价格历史暂不可用</b>
        <p>当前行情仍可查看；历史数据源恢复后可重新刷新。</p>
      </div>
      <div v-if="stats" class="win-stats">
        <div><span>区间涨跌</span><b :class="pctClass(stats.change_pct)">{{ formatPct(stats.change_pct) }}</b></div>
        <div><span>区间最高</span><b>{{ formatNum(stats.high) }}</b></div>
        <div><span>区间最低</span><b>{{ formatNum(stats.low) }}</b></div>
        <div><span>日均成交额</span><b>{{ formatAmount(stats.avg_turnover) }}</b></div>
        <div><span>交易日</span><b>{{ stats.count }}</b></div>
      </div>
      <div class="returns">
        <div><span>5日</span><b :class="pctClass(performance.return_5d)">{{ formatPct(performance.return_5d) }}</b></div>
        <div><span>20日</span><b :class="pctClass(performance.return_20d)">{{ formatPct(performance.return_20d) }}</b></div>
        <div><span>60日</span><b :class="pctClass(performance.return_60d)">{{ formatPct(performance.return_60d) }}</b></div>
      </div>
      <div class="share-note">
        <b>份额变化{{ data.share_metrics?.availability === 'daily_snapshot' ? '（日度快照）' : '' }}</b>
        <p>{{ data.share_metrics?.message }}</p>
        <div v-if="data.share_metrics?.availability === 'daily_snapshot'" class="share-chgs">
          <span>1日 <b :class="pctClass(data.share_metrics.share_chg_1d)">{{ formatShare(data.share_metrics.share_chg_1d) }}</b></span>
          <span>5日 <b :class="pctClass(data.share_metrics.share_chg_5d)">{{ formatShare(data.share_metrics.share_chg_5d) }}</b></span>
          <span>20日 <b :class="pctClass(data.share_metrics.share_chg_20d)">{{ formatShare(data.share_metrics.share_chg_20d) }}</b></span>
        </div>
      </div>
      <MarketDataStatus v-if="data.history?.meta" :meta="data.history.meta" />
      <MarketDataStatus :meta="data.meta" />
    </template>
  </aside>
</template>

<style scoped>
.detail-panel { min-height: 520px; background: #111d34; border: 1px solid #213251; border-radius: 10px; padding: 14px; color: #dce4f2; }
.placeholder, .error { display: grid; place-items: center; min-height: 420px; color: #64718a; text-align: center; }
.error { color: #ff8796; }
header { display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid #213251; padding-bottom: 12px; }
h2 { margin: 0; font-size: 18px; } header span { color: #71809a; font-size: 12px; }
.price { text-align: right; }.price strong { display: block; font-size: 22px; }.price span { font-size: 14px; }
.metrics { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin: 12px 0; }
.metrics div { background: #0c172a; border-radius: 7px; padding: 9px; }.metrics label { display: block; color: #68758d; font-size: 11px; }.metrics b { display: block; margin-top: 4px; font-size: 13px; }
.range-tabs { display: flex; gap: 5px; }.range-tabs button { border: 1px solid #273a5c; background: #101a2c; color: #71809a; border-radius: 5px; padding: 4px 9px; cursor: pointer; }.range-tabs button.active { background: #174673; color: #fff; }
.custom-range { display: flex; align-items: center; gap: 6px; margin-top: 7px; color: #71809a; font-size: 12px; }
.custom-range input { background: #0c172a; border: 1px solid #273a5c; color: #dce4f2; border-radius: 5px; padding: 3px 6px; color-scheme: dark; font-size: 12px; }
.custom-range .apply { border: 1px solid #273a5c; background: #174673; color: #fff; border-radius: 5px; padding: 4px 10px; cursor: pointer; }
.custom-range .apply:disabled { opacity: .5; cursor: default; }
.win-stats { display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; margin: 10px 0; }
.win-stats div { background: #0c172a; padding: 8px 4px; text-align: center; border-radius: 6px; }
.win-stats span { color: #68758d; font-size: 11px; display: block; }
.win-stats b { font-size: 12px; }
.chart { width: 100%; height: 300px; }
.history-range { margin: 2px 0 8px; color: #68758d; font-size: 11px; text-align: center; }
.history-empty { min-height: 170px; margin: 10px 0; display: grid; place-content: center; text-align: center; border: 1px dashed #33445f; border-radius: 7px; color: #9ba8bd; }
.history-empty p { margin: 5px 0 0; color: #68758d; font-size: 12px; }
.returns { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }.returns div { background: #0c172a; padding: 8px; text-align: center; border-radius: 6px; }.returns span { color: #68758d; font-size: 11px; display: block; }
.share-note { margin: 12px 0; padding: 10px; border: 1px dashed #33445f; border-radius: 7px; color: #a8b3c7; font-size: 12px; }.share-note p { margin: 4px 0 0; color: #6e7b93; line-height: 1.5; }.share-chgs { display: flex; gap: 12px; margin-top: 8px; }.share-chgs span { color: #6e7b93; }.share-chgs b { margin-left: 4px; }
</style>
