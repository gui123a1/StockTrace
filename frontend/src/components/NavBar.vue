<script setup>
import { RouterLink } from 'vue-router'
</script>

<template>
  <nav class="navbar">
    <div class="nav-brand">
      <RouterLink to="/">StockTrace</RouterLink>
    </div>
    <div class="nav-links">
      <RouterLink to="/">监控面板</RouterLink>
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

.nav-links a {
  color: #ccc;
  text-decoration: none;
  margin-left: 24px;
  transition: color 0.2s;
}

.nav-links a:hover,
.nav-links a.router-link-active {
  color: #fff;
}
</style>
