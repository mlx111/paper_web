<template>
  <div class="message" :class="[message.type, { streaming: message.streaming }]">
    <div v-if="isAssistantLike" class="message-avatar">
      <span>AI</span>
    </div>

    <div ref="contentRoot" class="message-content">
      <template v-if="message.loading">
        <span>{{ message.content || "正在思考..." }}</span>
      </template>
      <template v-else-if="isAssistantLike">
        <div v-html="renderedHtml"></div>
      </template>
      <template v-else>
        <span style="white-space: pre-wrap">{{ message.content }}</span>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUpdated, ref } from "vue";
import { highlightCodeBlocks, renderMarkdown } from "../utils/markdown.js";

const props = defineProps({
  message: {
    type: Object,
    required: true
  }
});

const contentRoot = ref(null);
const isAssistantLike = computed(() => props.message.type === "assistant");
const renderedHtml = computed(() => renderMarkdown(props.message.content || ""));

function applyHighlight() {
  nextTick(() => {
    highlightCodeBlocks(contentRoot.value);
  });
}

onMounted(applyHighlight);
onUpdated(applyHighlight);
</script>
