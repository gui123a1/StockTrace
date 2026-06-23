<script setup>
import { ref } from 'vue'

const props = defineProps({
  data: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['row-click', 'delete'])

const expandedRows = ref(new Set())

function toggleRow(code) {
  if (expandedRows.value.has(code)) {
    expandedRows.value.delete(code)
  } else {
    expandedRows.value.add(code)
  }
}

function isExpanded(code) {
  return expandedRows.value.has(code)
}

function formatPct(val) {
  if (val == null) return '-'
  const num = Number(val)
  const sign = num > 0 ? '+' : ''
  return `${sign}${num.toFixed(2)}%`
}

function pctClass(val) {
  if (val == null) return ''
  if (Number(val) > 0) return 'up'
  if (Number(val) < 0) return 'down'
  return ''
}

function formatNum(val) {
  if (val == null) return '-'
  return Number(val).toFixed(2)
}

function handleGoDetail(e, item) {
  e.stopPropagation()
  emit('row-click', item)
}

async function handleDelete(e, item) {
  e.stopPropagation()
  if (!confirm(`确认取消关注 ${item.name || item.code}？`)) return
  emit('delete', item)
}
</script>

<template>
  <div class="stock-table-wrapper">
    <div v-if="loading" class="loading">加载中...</div>
    <table v-else class="stock-table">
      <thead>
        <tr>
          <th class="th-expand"></th>
          <th>代码</th>
          <th>名称</th>
          <th>日期</th>
          <th>现价</th>
          <th>涨跌幅</th>
          <th>涨跌价</th>
          <th class="th-actions">操作</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="item in data" :key="item.code">
          <!-- 折叠行（默认显示） -->
          <tr
            class="stock-row"
            :class="{ expanded: isExpanded(item.code) }"
            @click="toggleRow(item.code)"
          >
            <td class="expand-icon" @click.stop="toggleRow(item.code)">
              <span :class="isExpanded(item.code) ? 'arrow-down' : 'arrow-right'"></span>
            </td>
            <td class="code">{{ item.code }}</td>
            <td class="name">{{ item.name }}</td>
            <td>{{ item.trade_date || '-' }}</td>
            <td :class="pctClass(item.open_close_pct)">{{ formatNum(item.close_price) }}</td>
            <td :class="pctClass(item.open_close_pct)">
              {{ formatPct(item.open_close_pct) }}
            </td>
            <td :class="pctClass(item.open_close_diff)">
              {{ formatPct(item.open_close_diff) }}
            </td>
            <td class="actions">
              <button class="btn-kline" @click="handleGoDetail($event, item)" title="查看K线图">K线</button>
              <button class="btn-delete" @click="handleDelete($event, item)" title="取消关注">✕</button>
            </td>
          </tr>
          <!-- 展开行 -->
          <tr v-if="isExpanded(item.code)" class="expand-row">
            <td colspan="8">
              <div class="expand-content">
                <div class="expand-grid">
                  <div class="expand-item">
                    <span class="elabel">振幅</span>
                    <span :class="pctClass(item.high_low_pct)">{{ formatPct(item.high_low_pct) }}</span>
                  </div>
                  <div class="expand-item">
                    <span class="elabel">开盘价</span>
                    <span>{{ formatNum(item.open_price) }}</span>
                  </div>
                  <div class="expand-item">
                    <span class="elabel">收盘价</span>
                    <span>{{ formatNum(item.close_price) }}</span>
                  </div>
                  <div class="expand-item">
                    <span class="elabel">最高价</span>
                    <span class="up">{{ formatNum(item.high_price) }}</span>
                  </div>
                  <div class="expand-item">
                    <span class="elabel">最低价</span>
                    <span class="down">{{ formatNum(item.low_price) }}</span>
                  </div>
                </div>
                <div class="expand-actions">
                  <button class="btn-kline-lg" @click="handleGoDetail($event, item)">查看K线图 →</button>
                </div>
              </div>
            </td>
          </tr>
        </template>
        <tr v-if="!data.length">
          <td colspan="8" class="empty">暂无数据，请先添加关注的股票并点击"刷新数据"</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.stock-table-wrapper {
  background: #16213e;
  border-radius: 8px;
  overflow-x: auto;
}

.loading {
  text-align: center;
  padding: 40px;
  color: #888;
}

.stock-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.stock-table th {
  background: #0f3460;
  color: #ccc;
  padding: 12px 16px;
  text-align: left;
  white-space: nowrap;
  font-weight: normal;
}

.th-expand {
  width: 36px;
}

.th-actions {
  width: 100px;
}

.stock-table td {
  padding: 12px 16px;
  color: #ddd;
  white-space: nowrap;
  border-bottom: 1px solid #1a1a2e;
}

.stock-row {
  cursor: pointer;
  transition: background 0.15s;
}

.stock-row:hover {
  background: #1a2744;
}

.stock-row.expanded {
  background: #1a2744;
}

.expand-icon {
  text-align: center;
  cursor: pointer;
}

.arrow-right::before {
  content: '▶';
  font-size: 10px;
  color: #888;
}

.arrow-down::before {
  content: '▼';
  font-size: 10px;
  color: #888;
}

.code {
  color: #e94560;
  font-weight: bold;
}

.name {
  color: #eee;
}

.actions {
  white-space: nowrap;
}

.up {
  color: #e94560;
  font-weight: bold;
}

.down {
  color: #00c853;
  font-weight: bold;
}

.empty {
  text-align: center;
  color: #666;
  padding: 40px !important;
}

/* 展开行 */
.expand-row td {
  padding: 0 16px 16px 52px;
  border-bottom: 1px solid #1a1a2e;
}

.expand-content {
  background: #1a1a2e;
  border-radius: 6px;
  padding: 14px 16px;
}

.expand-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 12px 20px;
}

.expand-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.elabel {
  color: #888;
  font-size: 12px;
}

.expand-item span:last-child {
  font-size: 15px;
  font-weight: bold;
  color: #ddd;
}

.expand-actions {
  margin-top: 12px;
}

/* K线按钮（折叠行内） */
.btn-kline {
  background: transparent;
  border: 1px solid #3a7bd5;
  color: #3a7bd5;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  margin-right: 6px;
}

.btn-kline:hover {
  background: #3a7bd5;
  color: #fff;
}

/* K线按钮（展开行） */
.btn-kline-lg {
  background: #0f3460;
  border: 1px solid #3a7bd5;
  color: #3a7bd5;
  border-radius: 4px;
  padding: 6px 16px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-kline-lg:hover {
  background: #3a7bd5;
  color: #fff;
}

/* 删除按钮 */
.btn-delete {
  background: transparent;
  border: 1px solid #e94560;
  color: #e94560;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-delete:hover {
  background: #e94560;
  color: #fff;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .stock-table th,
  .stock-table td {
    padding: 8px 10px;
    font-size: 13px;
  }

  .expand-row td {
    padding: 0 10px 12px 46px;
  }

  .expand-grid {
    grid-template-columns: repeat(3, 1fr);
    gap: 8px 12px;
  }
}

@media (max-width: 500px) {
  .expand-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
