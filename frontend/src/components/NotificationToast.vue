<template>
  <div class="toast-stack">
    <div
      v-for="item in notifications"
      :key="item.id"
      class="toast"
      :class="item.type"
    >
      {{ item.message }}
    </div>
  </div>
</template>

<script setup>
defineProps({
  notifications: {
    type: Array,
    default: () => []
  }
});
</script>
