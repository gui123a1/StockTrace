<script setup>
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

const route = useRoute()
const isWatchlist = computed(() => route.path === '/' || route.path.startsWith('/stock/'))
const isMarket = computed(() => route.path.startsWith('/market'))
</script>

<template>
  <nav class="navbar">
    <div class="nav-brand">
      <RouterLink to="/">StockTrace</RouterLink>
    </div>
    <div class="nav-links">
      <RouterLink to="/" :class="{ active: isWatchlist }">自选</RouterLink>
      <RouterLink to="/market" :class="{ active: isMarket }">数据</RouterLink>
    </div>
  </nav>
</template>

<style scoped>
.navbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  background: #1a1a2e;
  color: #fff;
  box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}

.nav-brand a {
  font-size: 20px;
  font-weight: bold;
  color: #e94560;
  text-decoration: none;
}

.nav-links {
  display: flex;
  align-items: center;
  gap: 8px;
}

.nav-links a {
  color: #ccc;
  text-decoration: none;
  margin-left: 8px;
  padding: 6px 12px;
  border-radius: 6px;
  transition: color 0.2s, background 0.2s;
}

.nav-links a:hover {
  color: #fff;
  background: #1a2744;
}

.nav-links a.active {
  color: #fff;
  background: #0f3460;
}
</style>
