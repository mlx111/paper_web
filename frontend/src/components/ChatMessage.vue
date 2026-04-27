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
        <div v-if="hasDebugEntries" class="message-debug">
          <div class="message-debug-title">研究过程</div>
          <div class="message-debug-list">
            <div v-for="entry in debugEntries" :key="entry.key" class="message-debug-item">
              <div class="message-debug-node">{{ entry.nodeLabel }}</div>
              <div class="message-debug-text">{{ entry.text }}</div>
            </div>
          </div>
        </div>
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
const debugEntries = computed(() => {
  const entries = Array.isArray(props.message.debugEntries) ? props.message.debugEntries : [];
  return entries
    .map((entry, index) => ({
      key: entry.id || `${entry.node || 'debug'}-${index}`,
      nodeLabel: entry.nodeLabel || entry.node || '阶段',
      text: entry.text || ''
    }))
    .filter((entry) => entry.text);
});
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
const hasDebugEntries = computed(() => debugEntries.value.length > 0);
const hasSources = computed(() => displaySources.value.length > 0);

function applyHighlight() {
  nextTick(() => {
    highlightCodeBlocks(contentRoot.value);
  });
}

onMounted(applyHighlight);
onUpdated(applyHighlight);
</script>
