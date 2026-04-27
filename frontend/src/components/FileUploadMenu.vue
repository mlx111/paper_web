<template>
  <div class="tools-menu" :class="{ open }">
    <label class="tools-menu-item">
      <input
        type="file"
        accept=".txt,.md,.markdown,.pdf,.doc,.docx,.xls,.xlsx"
        hidden
        @change="handleKnowledgeChange"
      />
      <span>上传到知识库</span>
    </label>
    <label class="tools-menu-item">
      <input
        type="file"
        accept=".txt,.md,.markdown,.pdf,.docx,.html,.htm"
        hidden
        @change="handleTempChange"
      />
      <span>临时解析文件</span>
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

const emit = defineEmits(['upload', 'temp-upload']);

function handleKnowledgeChange(event) {
  const file = event.target.files?.[0];
  if (file) {
    emit('upload', file);
  }
  event.target.value = '';
}

function handleTempChange(event) {
  const file = event.target.files?.[0];
  if (file) {
    emit('temp-upload', file);
  }
  event.target.value = '';
}
</script>
