<template>
  <section class="chat-container" :class="{ centered }">
    <div v-if="!messages.length" class="welcome-greeting">
      <p>Hello, I am your AI assistant.</p>
    </div>

    <div ref="scrollRoot" class="chat-messages">
      <ChatMessage
        v-for="message in messages"
        :key="message.id"
        :message="message"
      />
    </div>

    <slot name="input"></slot>
  </section>
</template>

<script setup>
import { nextTick, onMounted, ref, watch } from 'vue';
import ChatMessage from './ChatMessage.vue';

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
