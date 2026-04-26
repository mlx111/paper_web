<template>
  <div class="chat-input-container">
    <div class="input-group-wrapper">
      <div class="input-wrapper">
        <div class="input-meta-row">
          <span class="input-module-badge">{{ moduleLabel }}</span>
          <span class="input-module-hint">{{ moduleHint }}</span>
        </div>

        <input
          class="message-input"
          type="text"
          maxlength="1000"
          :value="modelValue"
          :placeholder="placeholder"
          :disabled="disabled || isStreaming"
          @input="emit('update:modelValue', $event.target.value)"
          @keydown="onKeydown"
        />

        <div class="input-bottom-bar">
          <div class="left-actions">
            <div v-if="allowUpload" class="tools-btn-wrapper" :class="{ active: showToolsMenu }">
              <button class="tools-btn" type="button" title="更多操作" @click="showToolsMenu = !showToolsMenu">
                <svg class="tools-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                  <circle cx="12" cy="12" r="1.5" fill="currentColor" />
                  <circle cx="19" cy="12" r="1.5" fill="currentColor" />
                  <circle cx="5" cy="12" r="1.5" fill="currentColor" />
                </svg>
              </button>
              <FileUploadMenu :open="showToolsMenu" @upload="handleUpload" />
            </div>

            <div class="stream-mode-toggle" role="group" aria-label="输出模式">
              <button
                class="stream-mode-btn"
                :class="{ active: !useStreaming }"
                type="button"
                :disabled="disabled || isStreaming"
                @click="emit('update:useStreaming', false)"
              >
                普通
              </button>
              <button
                class="stream-mode-btn"
                :class="{ active: useStreaming }"
                type="button"
                :disabled="disabled || isStreaming"
                @click="emit('update:useStreaming', true)"
              >
                流式
              </button>
            </div>
          </div>

          <div class="right-actions">
            <button class="send-btn-circle" type="button" title="发送" :disabled="disabled || isStreaming" @click="emitSend">
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <path d="M22 2L11 13M22 2L15 22L11 13M22 2L2 9L11 13" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import FileUploadMenu from './FileUploadMenu.vue';

defineProps({
  modelValue: {
    type: String,
    default: ''
  },
  moduleLabel: {
    type: String,
    default: '对话'
  },
  moduleHint: {
    type: String,
    default: ''
  },
  placeholder: {
    type: String,
    default: '输入消息...'
  },
  allowUpload: {
    type: Boolean,
    default: false
  },
  disabled: {
    type: Boolean,
    default: false
  },
  isStreaming: {
    type: Boolean,
    default: false
  },
  useStreaming: {
    type: Boolean,
    default: false
  }
});

const emit = defineEmits(['update:modelValue', 'update:useStreaming', 'send', 'upload-file']);

const showToolsMenu = ref(false);

function emitSend() {
  emit('send');
}

function handleUpload(file) {
  showToolsMenu.value = false;
  emit('upload-file', file);
}

function onKeydown(event) {
  if (event.isComposing) {
    return;
  }

  if (event.key === 'Enter') {
    event.preventDefault();
    emitSend();
  }
}
</script>
