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
          <div v-if="allowUpload" class="tools-btn-wrapper" :class="{ active: showToolsMenu }">
            <button class="tools-btn" type="button" title="More options" @click="showToolsMenu = !showToolsMenu">
              <svg class="tools-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <circle cx="12" cy="12" r="1.5" fill="currentColor" />
                <circle cx="19" cy="12" r="1.5" fill="currentColor" />
                <circle cx="5" cy="12" r="1.5" fill="currentColor" />
              </svg>
            </button>
            <FileUploadMenu :open="showToolsMenu" @upload="handleUpload" />
          </div>

          <div class="right-actions">
            <button class="send-btn-circle" type="button" title="Send" :disabled="disabled || isStreaming" @click="emitSend">
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
    default: 'Chat'
  },
  moduleHint: {
    type: String,
    default: ''
  },
  placeholder: {
    type: String,
    default: 'Type a message...'
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
  }
});

const emit = defineEmits(['update:modelValue', 'send', 'upload-file']);

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
