<template>
  <aside class="sidebar">
    <div class="sidebar-header">
      <h2 class="sidebar-title">智能论文助手</h2>
    </div>

    <div class="sidebar-content">
      <button class="new-chat-btn" type="button" @click="$emit('new-chat')">
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path d="M12 5V19M5 12H19" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
        </svg>
        <span>新建对话</span>
      </button>

      <div class="chat-history-section">
        <div class="history-header">
          <span>近期对话</span>
        </div>

        <div class="chat-history-list">
          <div
            v-for="history in histories"
            :key="history.id"
            class="history-item"
            :class="{ active: history.id === activeSessionId }"
            @click="$emit('select-history', history.id)"
          >
            <div class="history-item-content">
              <span class="history-item-title">{{ history.title || '新对话' }}</span>
            </div>

            <button
              class="history-item-delete"
              type="button"
              title="删除"
              @click.stop="$emit('delete-history', history.id)"
            >
              ×
            </button>
          </div>

          <div v-if="!histories.length" class="history-empty">
            暂无对话记录
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup>
defineProps({
  histories: {
    type: Array,
    default: () => []
  },
  activeSessionId: {
    type: String,
    default: ''
  }
});

defineEmits(['new-chat', 'select-history', 'delete-history']);
</script>
