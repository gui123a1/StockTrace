<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { stockApi, dashboardApi } from '../api/stocks.js'
import StockTable from '../components/StockTable.vue'
import StockWatchlist from '../components/StockWatchlist.vue'
import AlertPanel from '../components/AlertPanel.vue'

const router = useRouter()
const dashboardData = ref([])
const loading = ref(false)
const fetchLoading = ref(false)
const fetchMessage = ref('')
let refreshTimer = null
let pollTimer = null

// 持仓汇总：只统计填了成本价的股票；数据来自看板真实行情
const portfolio = computed(() => {
  let cost = 0
  let value = 0
  let count = 0
  for (const item of dashboardData.value) {
    if (item.cost_price == null || item.quantity == null || item.close_price == null) continue
    cost += Number(item.cost_price) * Number(item.quantity)
    value += Number(item.close_price) * Number(item.quantity)
    count += 1
  }
  if (!count) return null
  return { cost, value, pnl: value - cost, count }
})

async function loadDashboard() {
  loading.value = true
  try {
    const res = await dashboardApi.get()
    dashboardData.value = res.data
  } catch (e) {
    console.error('加载面板数据失败', e)
  } finally {
    loading.value = false
  }
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function pollFetchStatus() {
  try {
    const res = await stockApi.fetchStatus()
    const st = res.data
    if (st.running) {
      fetchLoading.value = true
      fetchMessage.value = st.task === 'all' ? '正在拉取全部股票...' : `正在拉取 ${st.code || ''}...`
      return
    }
    // 任务已结束
    stopPoll()
    fetchLoading.value = false
    if (st.last_status === 'error') {
      fetchMessage.value = st.last_error || '拉取失败'
    } else if (st.last_status === 'success') {
      fetchMessage.value = '拉取完成'
      setTimeout(() => {
        if (fetchMessage.value === '拉取完成') fetchMessage.value = ''
      }, 3000)
    } else {
      fetchMessage.value = ''
    }
    await loadDashboard()
  } catch (e) {
    console.error('查询拉取状态失败', e)
  }
}

async function fetchAllData() {
  fetchLoading.value = true
  fetchMessage.value = '启动拉取...'
  try {
    await stockApi.fetchAll()
    stopPoll()
    pollTimer = setInterval(pollFetchStatus, 3000)
    await pollFetchStatus()
  } catch (e) {
    fetchLoading.value = false
    if (e.response?.status === 409) {
      fetchMessage.value = '已有拉取任务在执行'
      stopPoll()
      pollTimer = setInterval(pollFetchStatus, 3000)
      await pollFetchStatus()
    } else {
      console.error('拉取数据失败', e)
      fetchMessage.value = '启动拉取失败'
    }
  }
}

async function removeStock(item) {
  try {
    await stockApi.remove(item.id)
    loadDashboard()
  } catch (e) {
    console.error('删除失败', e)
    alert('取消关注失败，请重试')
  }
}

function goToDetail(item) {
  router.push(`/stock/${item.id}`)
}

function onWatchlistRefresh() {
  loadDashboard()
  // 添加后后端会后台拉行情，短时多刷几次
  setTimeout(loadDashboard, 3000)
  setTimeout(loadDashboard, 8000)
  setTimeout(loadDashboard, 15000)
}

// 低配 VPS：看板 60s 轮询即可（拉取任务另有独立轮询）
onMounted(() => {
  loadDashboard()
  refreshTimer = setInterval(loadDashboard, 60000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  stopPoll()
})
</script>

<template>
  <div class="dashboard">
    <div class="dashboard-header">
      <h1>股票监控面板</h1>
      <div class="header-actions">
        <span v-if="portfolio" class="portfolio" :class="portfolio.pnl >= 0 ? 'up' : 'down'">
          持仓{{ portfolio.count }}只 · 盈亏 {{ portfolio.pnl >= 0 ? '+' : '' }}{{ portfolio.pnl.toFixed(2) }}
        </span>
        <span v-if="fetchMessage" class="fetch-msg">{{ fetchMessage }}</span>
        <button
          class="btn btn-primary"
          @click="fetchAllData"
          :disabled="fetchLoading"
        >
          {{ fetchLoading ? '拉取中...' : '刷新数据' }}
        </button>
      </div>
    </div>

    <StockWatchlist @refresh="onWatchlistRefresh" />

    <AlertPanel :stocks="dashboardData" />

    <StockTable
      :data="dashboardData"
      :loading="loading"
      @row-click="goToDetail"
      @ai-click="goToDetail"
      @delete="removeStock"
      @refresh="onWatchlistRefresh"
    />
  </div>
</template>

<style scoped>
.dashboard-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.dashboard-header h1 {
  font-size: 24px;
  color: #eee;
}

.header-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.fetch-msg {
  color: #aaa;
  font-size: 13px;
}

.portfolio {
  font-size: 14px;
  font-weight: bold;
}

.portfolio.up {
  color: #e94560;
}

.portfolio.down {
  color: #00c853;
}

.btn {
  padding: 8px 20px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  transition: background 0.2s;
}

.btn-primary {
  background: #e94560;
  color: #fff;
}

.btn-primary:hover {
  background: #c73a52;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
