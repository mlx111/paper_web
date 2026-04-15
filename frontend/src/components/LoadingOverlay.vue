<template>
  <div v-if="visible" class="loading-overlay">
    <div class="loading-content">
      <div class="loading-spinner"></div>
      <div class="loading-text">{{ title }}</div>
      <div class="loading-subtext">{{ subtitle }}</div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  visible: {
    type: Boolean,
    default: false
  },
  title: {
    type: String,
    default: '正在处理...'
  },
  subtitle: {
    type: String,
    default: '请稍候'
  }
});
</script>
