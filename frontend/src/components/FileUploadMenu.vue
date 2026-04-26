<template>
  <div class="tools-menu" :class="{ open }">
    <label class="tools-menu-item">
      <input
        type="file"
        accept=".txt,.md,.markdown,.pdf,.doc,.docx,.xls,.xlsx"
        hidden
        @change="handleChange"
      />
      <span>上传文件</span>
    </label>
  </div>
</template>

<script setup>
defineProps({
  open: {
    type: Boolean,
    default: false
  }
});

const emit = defineEmits(['upload']);

function handleChange(event) {
  const file = event.target.files?.[0];
  if (file) {
    emit('upload', file);
  }
  event.target.value = '';
}
</script>
