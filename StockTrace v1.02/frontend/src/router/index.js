import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import StockDetail from '../views/StockDetail.vue'
import Market from '../views/Market.vue'
import MarketTrend from '../views/MarketTrend.vue'
import MarketSectors from '../views/MarketSectors.vue'
import MarketInstitutions from '../views/MarketInstitutions.vue'
import MarketNationalEtf from '../views/MarketNationalEtf.vue'
import MarketEtfRadar from '../views/MarketEtfRadar.vue'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: Dashboard,
  },
  {
    path: '/market',
    name: 'Market',
    component: Market,
  },
  {
    path: '/market/trend',
    name: 'MarketTrend',
    component: MarketTrend,
  },
  {
    path: '/market/sectors',
    name: 'MarketSectors',
    component: MarketSectors,
  },
  {
    path: '/market/institutions',
    name: 'MarketInstitutions',
    component: MarketInstitutions,
  },
  {
    path: '/market/national-etf',
    name: 'MarketNationalEtf',
    component: MarketNationalEtf,
  },
  {
    path: '/market/etf-radar',
    name: 'MarketEtfRadar',
    component: MarketEtfRadar,
  },
  {
    path: '/stock/:id',
    name: 'StockDetail',
    component: StockDetail,
    props: true,
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
