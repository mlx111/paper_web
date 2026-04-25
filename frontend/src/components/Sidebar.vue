<template>
  <aside class="sidebar">
    <div class="sidebar-header">
      <h1 class="sidebar-title">My Paper Web</h1>
      <p class="sidebar-subtitle">Separate modules, separate sessions</p>
    </div>

    <div class="sidebar-content">
      <div class="module-switcher">
        <button
          v-for="module in modules"
          :key="module.key"
          class="module-switcher-item"
          :class="{ active: module.key === activeModule }"
          type="button"
          @click="emit('select-module', module.key)"
        >
          <span class="module-switcher-label">{{ module.label }}</span>
          <span class="module-switcher-desc">{{ module.description }}</span>
        </button>
      </div>

      <button class="new-chat-btn" type="button" @click="emit('new-chat')">
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
        </svg>
        <span>New session</span>
      </button>

      <section class="chat-history-section">
        <div class="history-header">Sessions</div>
        <div v-if="!histories.length" class="history-empty">No sessions yet.</div>
        <div v-else class="chat-history-list">
          <div
            v-for="history in histories"
            :key="history.id"
            class="history-item"
            :class="{ active: history.id === activeSessionId }"
            @click="emit('select-history', history.id)"
          >
            <div class="history-item-content">
              <span class="history-item-title">{{ history.title }}</span>
            </div>
            <button
              class="history-item-delete"
              type="button"
              title="Delete session"
              @click.stop="emit('delete-history', history.id)"
            >
              ×
            </button>
          </div>
        </div>
      </section>
    </div>
  </aside>
</template>

<script setup>
const emit = defineEmits(['select-module', 'new-chat', 'select-history', 'delete-history']);

defineProps({
  modules: {
    type: Array,
    default: () => []
  },
  activeModule: {
    type: String,
    default: 'chat'
  },
  histories: {
    type: Array,
    default: () => []
  },
  activeSessionId: {
    type: String,
    default: ''
  }
});
</script>
