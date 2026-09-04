<script setup>
import { RouterView } from 'vue-router'
import NavBar from './components/NavBar.vue'
</script>

<template>
  <NavBar />
  <main class="main-content">
    <!-- include 按路由 name 缓存页面组件：切走不销毁，回来免白屏重拉 -->
    <RouterView v-slot="{ Component }">
      <KeepAlive :include="['Market', 'MarketTrend', 'MarketSectors', 'MarketInstitutions', 'MarketNationalEtf', 'MarketEtfRadar']">
        <component :is="Component" />
      </KeepAlive>
    </RouterView>
  </main>
</template>

<style scoped>
.main-content {
  max-width: 1400px;
  margin: 0 auto;
  padding: 20px;
}
</style>
