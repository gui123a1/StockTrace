<script setup>
import { RouterView } from 'vue-router'
import NavBar from './components/NavBar.vue'
</script>

<template>
  <NavBar />
  <main class="main-content">
    <RouterView />
  </main>
</template>

<style scoped>
.main-content {
  max-width: 1400px;
  margin: 0 auto;
  padding: 20px;
}
</style>
