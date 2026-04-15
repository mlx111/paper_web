<template>
  <div class="chat-input-container">
    <div class="input-group-wrapper">
      <div class="input-wrapper">
        <input
          class="message-input"
          type="text"
          maxlength="1000"
          :value="modelValue"
          placeholder="询问智能论文助手"
          :disabled="disabled || isStreaming"
          @input="$emit('update:modelValue', $event.target.value)"
          @keydown="onKeydown"
        />

        <div class="input-bottom-bar">
          <div class="tools-btn-wrapper" :class="{ active: showToolsMenu }">
            <button class="tools-btn" type="button" :title="'更多选项'" @click="showToolsMenu = !showToolsMenu">
              <svg class="tools-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <circle cx="12" cy="12" r="1.5" fill="currentColor" />
                <circle cx="19" cy="12" r="1.5" fill="currentColor" />
                <circle cx="5" cy="12" r="1.5" fill="currentColor" />
              </svg>
            </button>
            <FileUploadMenu :open="showToolsMenu" @upload="handleUpload" />
          </div>

          <div class="right-actions">
            <div class="mode-selector-wrapper" :class="{ active: showModeMenu }">
              <button class="mode-selector-btn" type="button" @click="showModeMenu = !showModeMenu">
                <span>{{ currentModeLabel }}</span>
                <svg class="dropdown-arrow" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                  <path d="M6 9L12 15L18 9" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </button>

              <div class="mode-dropdown">
                <div class="dropdown-header">选择对话方式</div>
                <div class="dropdown-item" :class="{ active: mode === 'quick' }" @click="changeMode('quick')">
                  <div class="dropdown-item-main">
                    <span>快速</span>
                  </div>
                  <div class="dropdown-item-sub">快速问答</div>
                </div>
                <div class="dropdown-item" :class="{ active: mode === 'stream' }" @click="changeMode('stream')">
                  <div class="dropdown-item-main">
                    <span>流式</span>
                  </div>
                  <div class="dropdown-item-sub">流式对话</div>
                </div>
              </div>
            </div>

            <button class="send-btn-circle" type="button" :title="'发送'" :disabled="disabled || isStreaming" @click="emitSend">
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
import { computed, ref } from 'vue';
import FileUploadMenu from './FileUploadMenu.vue';

const props = defineProps({
  modelValue: {
    type: String,
    default: ''
  },
  mode: {
    type: String,
    default: 'quick'
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

const emit = defineEmits(['update:modelValue', 'send', 'mode-change', 'upload-file']);

const showToolsMenu = ref(false);
const showModeMenu = ref(false);

const currentModeLabel = computed(() => (props.mode === 'stream' ? '流式' : '快速'));

function emitSend() {
  if (props.disabled || props.isStreaming) {
    return;
  }
  emit('send');
}

function handleUpload(file) {
  showToolsMenu.value = false;
  emit('upload-file', file);
}

function changeMode(nextMode) {
  showModeMenu.value = false;
  emit('mode-change', nextMode);
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
