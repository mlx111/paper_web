<template>
  <section class="chat-container" :class="{ centered }">
    <div v-if="!messages.length" class="welcome-greeting">
      <p>你好，我是你的智能论文助手。</p>
    </div>

    <div ref="scrollRoot" class="chat-messages">
      <ChatMessage
        v-for="message in messages"
        :key="message.id"
        :message="message"
        @request-presentation="emit('request-presentation', $event)"
        @request-presentation-quality="emit('request-presentation-quality', $event)"
        @request-presentation-regenerate="emit('request-presentation-regenerate', $event)"
      />
    </div>

    <slot name="input"></slot>
  </section>
</template>

<script setup>
import { nextTick, onMounted, ref, watch } from 'vue';
import ChatMessage from './ChatMessage.vue';

const emit = defineEmits(['request-presentation', 'request-presentation-quality', 'request-presentation-regenerate']);

const props = defineProps({
  messages: {
    type: Array,
    default: () => []
  },
  centered: {
    type: Boolean,
    default: false
  }
});

const scrollRoot = ref(null);

function scrollToBottom() {
  nextTick(() => {
    if (scrollRoot.value) {
      scrollRoot.value.scrollTop = scrollRoot.value.scrollHeight;
    }
  });
}

watch(
  () => props.messages,
  () => scrollToBottom(),
  { deep: true }
);

onMounted(scrollToBottom);
</script>
