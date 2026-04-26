<template>
  <div class="message" :class="[message.type, { streaming: message.streaming }]">
    <div v-if="isAssistantLike" class="message-avatar">
      <span>AI</span>
    </div>

    <div ref="contentRoot" class="message-content">
      <template v-if="message.loading">
        <span>{{ message.content || 'Thinking...' }}</span>
      </template>
      <template v-else-if="isAssistantLike">
        <div v-html="renderedHtml"></div>
        <div v-if="hasSources" class="message-sources">
          <div class="message-sources-title">来源</div>
          <div class="message-source-list">
            <div v-for="source in displaySources" :key="source.key" class="message-source-item">
              <div class="message-source-main">
                <span class="message-source-file">{{ source.filename }}</span>
                <span v-if="source.pageLabel" class="message-source-page">{{ source.pageLabel }}</span>
              </div>
              <div v-if="source.preview" class="message-source-preview">{{ source.preview }}</div>
            </div>
          </div>
        </div>
      </template>
      <template v-else>
        <span style="white-space: pre-wrap">{{ message.content }}</span>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUpdated, ref } from 'vue';
import { highlightCodeBlocks, renderMarkdown } from '../utils/markdown.js';

const props = defineProps({
  message: {
    type: Object,
    required: true
  }
});

const contentRoot = ref(null);
const isAssistantLike = computed(() => props.message.type === 'assistant');
const renderedHtml = computed(() => renderMarkdown(props.message.content || '', props.message.imageMap || {}));
const displaySources = computed(() => {
  const sources = Array.isArray(props.message.sources) ? props.message.sources : [];
  return sources.slice(0, 4).map((source, index) => {
    const pageNumber = Number(source.page_number);
    return {
      key: source.chunk_id || `${source.filename || 'source'}-${index}`,
      filename: source.filename || '未知文件',
      pageLabel: Number.isFinite(pageNumber) ? `第 ${pageNumber + 1} 页` : '',
      preview: source.preview || ''
    };
  });
});
const hasSources = computed(() => displaySources.value.length > 0);

function applyHighlight() {
  nextTick(() => {
    highlightCodeBlocks(contentRoot.value);
  });
}

onMounted(applyHighlight);
onUpdated(applyHighlight);
</script>
