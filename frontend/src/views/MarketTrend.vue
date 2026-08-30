<script setup>
import { ref, computed, onMounted } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  TooltipComponent,
  GridComponent,
  LegendComponent,
  DataZoomComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import MarketSubNav from '../components/MarketSubNav.vue'
import { marketApi } from '../api/stocks.js'
import { formatPct, pctClass } from '../utils/format.js'

use([
  LineChart,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  DataZoomComponent,
  CanvasRenderer,
])

const COLORS = ['#e94560', '#4fc3f7', '#ffb74d', '#81c784', '#ba68c8']

const DAYS_OPTIONS = [30, 60, 120, 250]

const loading = ref(false)
const error = ref('')
const data = ref(null)
const days = ref(120)

const seriesList = computed(() => data.value?.series || [])

const chartOption = computed(() => {
  const list = seriesList.value
  if (!list.length) return {}

  // 对齐日期并集
  const dateSet = new Set()
  list.forEach(s => (s.items || []).forEach(i => dateSet.add(i.date)))
  const dates = Array.from(dateSet).sort()

  const chartSeries = list.map((s, idx) => {
    const map = Object.fromEntries((s.items || []).map(i => [i.date, i.norm_pct]))
    return {
      name: s.name,
      type: 'line',
      showSymbol: false,
      smooth: true,
      data: dates.map(d => map[d] ?? null),
      itemStyle: { color: COLORS[idx % COLORS.length] },
      lineStyle: { width: 2 },
    }
  })

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1a1a2e',
      borderColor: '#333',
      textStyle: { color: '#ddd', fontSize: 12 },
      valueFormatter: (v) => (v == null ? '-' : `${Number(v).toFixed(2)}%`),
    },
    legend: {
      data: list.map(s => s.name),
      textStyle: { color: '#ccc', fontSize: 12 },
      top: 0,
    },
    grid: { left: '8%', right: '4%', top: 48, bottom: 60 },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', start: 0, end: 100, height: 18, bottom: 8, textStyle: { color: '#888' } },
    ],
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { color: '#888', fontSize: 11 },
      axisLine: { lineStyle: { color: '#444' } },
    },
    yAxis: {
      type: 'value',
      name: '相对涨跌%',
      nameTextStyle: { color: '#888', fontSize: 11 },
      axisLabel: {
        color: '#888',
        fontSize: 11,
        formatter: (v) => `${v}%`,
      },
      splitLine: { lineStyle: { color: '#1a2744' } },
    },
    series: chartSeries,
  }
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await marketApi.getTrend({ days: days.value })
    data.value = res.data
  } catch (e) {
    console.error(e)
    error.value = e.response?.data?.detail || '加载走势失败'
  } finally {
    loading.value = false
  }
}

function setDays(value) {
  if (days.value === value) return
  days.value = value
  load()
}

onMounted(load)
</script>

<template>
  <div class="page">
    <MarketSubNav />
    <div class="page-header">
      <div>
        <h1>全市场走势</h1>
        <p class="sub">
          近 {{ data?.days || days }} 交易日归一化对比（首日=0%）
          <span v-if="data?.updated_at"> · {{ data.updated_at }}</span>
        </p>
      </div>
      <button class="btn" @click="load" :disabled="loading">
        {{ loading ? '加载中...' : '刷新' }}
      </button>
    </div>

    <div v-if="error" class="error-box">{{ error }}</div>

    <div class="range-bar">
      <span class="range-label">时间范围</span>
      <button
        v-for="d in DAYS_OPTIONS"
        :key="d"
        class="range-btn"
        :class="{ active: days === d }"
        :disabled="loading"
        @click="setDays(d)"
      >{{ d }}日</button>
    </div>

    <section class="section">
      <v-chart
        v-if="chartOption.series?.length"
        :option="chartOption"
        autoresize
        style="height: 420px; width: 100%"
      />
      <div v-else-if="!loading" class="empty">
        {{ data?.message || '暂无走势数据' }}
      </div>
    </section>

    <section class="section" v-if="seriesList.length">
      <h2>区间涨跌幅</h2>
      <div class="stat-grid">
        <div v-for="s in seriesList" :key="s.code" class="stat-card">
          <div class="name">{{ s.name }}</div>
          <div class="code">{{ s.code }}</div>
          <div class="pct" :class="pctClass(s.period_change_pct)">
            {{ formatPct(s.period_change_pct) }}
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page { color: #ddd; }
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 16px;
}
.page-header h1 { margin: 0; font-size: 22px; color: #eee; }
.sub { color: #888; font-size: 13px; margin-top: 4px; }
.btn {
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  background: #e94560;
  color: #fff;
  cursor: pointer;
}
.btn:disabled { opacity: 0.6; }
.range-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
}
.range-label { color: #888; font-size: 12px; margin-right: 4px; }
.range-btn {
  padding: 5px 12px;
  border: 1px solid #2b3947;
  border-radius: 5px;
  background: #121b24;
  color: #9eabb8;
  cursor: pointer;
  font-size: 12px;
}
.range-btn.active { border-color: #327495; background: #163649; color: #e9f7ff; }
.range-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.error-box {
  background: #3a1520;
  color: #ff8a9a;
  padding: 12px;
  border-radius: 8px;
  margin-bottom: 12px;
}
.section {
  background: #16213e;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}
.section h2 {
  margin: 0 0 12px;
  font-size: 15px;
  color: #eee;
}
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
}
.stat-card {
  background: #1a1a2e;
  border-radius: 8px;
  padding: 12px;
  border: 1px solid #1a2744;
}
.name { font-weight: 600; color: #eee; font-size: 14px; }
.code { color: #666; font-size: 12px; margin: 2px 0 8px; }
.pct { font-size: 20px; font-weight: 700; }
.empty {
  text-align: center;
  color: #666;
  padding: 40px;
}
@media (max-width: 640px) {
  .page-header h1 { font-size: 18px; }
}
</style>
