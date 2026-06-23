<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { stockApi, dashboardApi } from '../api/stocks.js'
import StockTable from '../components/StockTable.vue'
import StockWatchlist from '../components/StockWatchlist.vue'

const router = useRouter()
const dashboardData = ref([])
const loading = ref(false)
const fetchLoading = ref(false)
let refreshTimer = null

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

async function fetchAllData() {
  fetchLoading.value = true
  try {
    await stockApi.fetchAll()
    setTimeout(loadDashboard, 2000) // 等2秒让数据入库
  } catch (e) {
    console.error('拉取数据失败', e)
  } finally {
    fetchLoading.value = false
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

// 每30秒自动刷新
onMounted(() => {
  loadDashboard()
  refreshTimer = setInterval(loadDashboard, 30000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<template>
  <div class="dashboard">
    <div class="dashboard-header">
      <h1>股票监控面板</h1>
      <div class="header-actions">
        <button
          class="btn btn-primary"
          @click="fetchAllData"
          :disabled="fetchLoading"
        >
          {{ fetchLoading ? '拉取中...' : '刷新数据' }}
        </button>
      </div>
    </div>

    <StockWatchlist @refresh="loadDashboard" />

    <StockTable
      :data="dashboardData"
      :loading="loading"
      @row-click="goToDetail"
      @delete="removeStock"
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
