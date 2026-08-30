import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 股票相关 API
export const stockApi = {
  // 获取关注列表
  getList() {
    return api.get('/stocks/')
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

  // 手动拉取单只股票数据
  fetchStock(id) {
    return api.post(`/stocks/${id}/fetch/`)
  },

  // 手动拉取所有股票数据
  fetchAll() {
    return api.post('/stocks/fetch-all/')
  },
}

// Dashboard
export const dashboardApi = {
  get() {
    return api.get('/dashboard/')
  },
}

export default api
