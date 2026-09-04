import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 15000,
})

// 股票相关 API
export const stockApi = {
  // 获取关注列表
  getList() {
    return api.get('/stocks/')
  },

  // 单只关注详情
  get(id) {
    return api.get(`/stocks/${id}/`)
  },

  // 添加关注
  add(code, name = '') {
    return api.post('/stocks/', { code, name })
  },

  // 搜索股票（代码或名称）
  search(keyword) {
    return api.get('/stocks/search/', { params: { q: keyword } })
  },

  // 取消关注
  remove(id) {
    return api.delete(`/stocks/${id}/`)
  },

  // 获取日K数据
  getDaily(id, params = {}) {
    return api.get(`/stocks/${id}/daily/`, { params })
  },

  // 获取最新一天行情
  getDailyLatest(id) {
    return api.get(`/stocks/${id}/daily/latest/`)
  },

  // 获取分钟K线
  getMinutes(id, params = {}) {
    return api.get(`/stocks/${id}/minutes/`, { params })
  },

  // 手动拉取单只股票数据（后台任务，立即返回）
  fetchStock(id) {
    return api.post(`/stocks/${id}/fetch/`)
  },

  // 手动拉取所有股票数据（后台任务，立即返回）
  fetchAll() {
    return api.post('/stocks/fetch-all/')
  },

  // 后台拉取任务状态
  fetchStatus() {
    return api.get('/stocks/fetch-status/')
  },
}

// Dashboard
export const dashboardApi = {
  get() {
    return api.get('/dashboard/')
  },
}

// 市场数据（指数 / 资金 / ETF 等，外部源可能较慢）
const marketTimeout = { timeout: 60000 }

export const marketApi = {
  getOverview() {
    return api.get('/market/', marketTimeout)
  },
  getTrend(params = {}) {
    return api.get('/market/trend/', { ...marketTimeout, params })
  },
  getSectors(params = {}) {
    return api.get('/market/sectors/', { ...marketTimeout, params })
  },
  getNationalEtf() {
    return api.get('/market/national-etf/', marketTimeout)
  },
  // 区间资金流向需逐只拉取 18 只 ETF 的历史资金流，冷启动较慢；
  // params 传 { period } 或 { start, end }（自定义区间）
  getNationalEtfFlow(params = {}) {
    return api.get('/market/national-etf/flow/', { timeout: 180000, params })
  },
  getEtfRadar(params = {}) {
    return api.get('/market/etf-radar/', { ...marketTimeout, params })
  },
  getEtfDetail(code, params = {}) {
    return api.get(`/market/etfs/${code}/`, { ...marketTimeout, params })
  },
  // 大盘主力资金流区间聚合（上游仅约 120 个交易日，超出会标 truncated）
  getMarketFlow(params = {}) {
    return api.get('/market/market-flow/', { ...marketTimeout, params })
  },
  // 北向资金净买额区间聚合
  getNorthbound(params = {}) {
    return api.get('/market/northbound/', { ...marketTimeout, params })
  },
  getInstitutions(code) {
    const params = code ? { code } : {}
    return api.get('/market/institutions/', { ...marketTimeout, params })
  },
}

// AI 功能（LLM 调用较慢，单独放宽超时）
const aiTimeout = { timeout: 120000 }

export const aiApi = {
  // AI 服务商配置 CRUD
  listProviders() {
    return api.get('/ai-providers/')
  },
  createProvider(data) {
    return api.post('/ai-providers/', data)
  },
  updateProvider(id, data) {
    return api.patch(`/ai-providers/${id}/`, data)
  },
  deleteProvider(id) {
    return api.delete(`/ai-providers/${id}/`)
  },
  testProvider(id) {
    return api.post(`/ai-providers/${id}/test/`, {}, { timeout: 30000 })
  },

  // 个股 AI 分析（按需触发）
  analyzeStock(id) {
    return api.post(`/stocks/${id}/ai-analysis/`, {}, aiTimeout)
  },

  // 结构化条件选股（不调 LLM，快速）
  screener(spec) {
    return api.post('/screener/', spec, { timeout: 30000 })
  },

  // 自然语言选股：LLM 翻译成条件后执行
  screenerAi(query) {
    return api.post('/screener/ai/', { query }, aiTimeout)
  },

  // 对筛选结果做 AI 点评
  screenerComment(query, results) {
    return api.post('/screener/ai/comment/', { query, results }, aiTimeout)
  },
}

export default api
