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
        <article class="message-markdown message-markdown-main" v-html="renderedHtml"></article>

        <div v-if="hasDebugEntries" class="message-debug">
          <div class="message-debug-title">研究过程</div>
          <div class="message-debug-list">
            <div v-for="entry in debugEntries" :key="entry.key" class="message-debug-item">
              <div class="message-debug-node">{{ entry.nodeLabel }}</div>
              <div class="message-debug-text">{{ entry.text }}</div>
            </div>
          </div>
        </div>

        <details v-if="hasResearchPlan" class="message-plan">
          <summary>详细计划</summary>
          <article class="message-markdown message-plan-body" v-html="renderedPlanHtml"></article>
        </details>

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

        <div v-if="hasArtifactDownloads" class="message-downloads">
          <div class="message-downloads-title">文件下载</div>
          <div class="message-download-list">
            <a
              v-if="artifactDownloads.pptx"
              class="message-download-link"
              :href="artifactDownloads.pptx"
              target="_blank"
              rel="noopener"
            >
              下载 PPTX
            </a>
            <a
              v-if="artifactDownloads.plan"
              class="message-download-link"
              :href="artifactDownloads.plan"
              target="_blank"
              rel="noopener"
            >
              下载计划
            </a>
            <a
              v-if="artifactDownloads.manuscript"
              class="message-download-link"
              :href="artifactDownloads.manuscript"
              target="_blank"
              rel="noopener"
            >
              下载讲稿
            </a>
            <a
              v-if="artifactDownloads.quality"
              class="message-download-link"
              :href="artifactDownloads.quality"
              target="_blank"
              rel="noopener"
            >
              下载质量报告
            </a>
          </div>
        </div>

        <details v-if="hasQualityReport" class="message-quality">
          <summary>质量检查结果</summary>
          <div class="message-quality-body">
            <div class="message-quality-badges">
              <span class="message-quality-badge" :class="{ passed: qualityPassed, failed: !qualityPassed }">
                {{ qualityPassed ? '通过' : '未通过' }}
              </span>
              <span class="message-quality-badge">问题 {{ qualityIssueCount }}</span>
              <span class="message-quality-badge">警告 {{ qualityWarningCount }}</span>
            </div>
            <div v-if="qualityReport.issues?.length" class="message-quality-list">
              <div v-for="(issue, index) in qualityReport.issues" :key="`issue-${index}`" class="message-quality-item">
                {{ issue }}
              </div>
            </div>
            <div v-else class="message-quality-empty">未发现明显问题。</div>
            <div v-if="qualityReport.warnings?.length" class="message-quality-list">
              <div
                v-for="(warning, index) in qualityReport.warnings"
                :key="`warning-${index}`"
                class="message-quality-item warning"
              >
                {{ warning }}
              </div>
            </div>
          </div>
        </details>

        <div v-if="canGeneratePresentation" class="message-actions">
          <button type="button" class="message-action-button" @click="emitPresentationRequest">
            基于本研究生成 PPT
          </button>
        </div>

        <div v-if="canManagePresentationArtifacts" class="message-actions message-actions--artifact">
          <button type="button" class="message-action-button" @click="emitPresentationQualityRequest">
            质量检查
          </button>
          <button type="button" class="message-action-button" @click="emitPresentationRegenerateRequest">
            重新生成
          </button>
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

const emit = defineEmits([
  'request-presentation',
  'request-presentation-quality',
  'request-presentation-regenerate',
]);

const props = defineProps({
  message: {
    type: Object,
    required: true
  }
});

const contentRoot = ref(null);
const isAssistantLike = computed(() => props.message.type === 'assistant');

function splitResearchPlan(content) {
  const source = String(content || '');
  const planPattern = /(^##\s*(?:研究计划|详细计划).*$)([\s\S]*?)(?=^##\s+|\s*$)/mi;
  const match = source.match(planPattern);
  if (!match) {
    return { main: source, plan: '' };
  }

  const plan = `${match[1]}\n${match[2]}`.trim();
  const main = source.replace(planPattern, '\n').trim();
  return { main, plan };
}

const extractedPlan = computed(() => splitResearchPlan(props.message.content || ''));
const renderedHtml = computed(() => renderMarkdown(extractedPlan.value.main || '', props.message.imageMap || {}));
const renderedPlanHtml = computed(() => renderMarkdown(extractedPlan.value.plan || '', props.message.imageMap || {}));

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
      filename: source.filename || '未知来源',
      pageLabel: Number.isFinite(pageNumber) ? `第 ${pageNumber + 1} 页` : '',
      preview: source.preview || ''
    };
  });
});

const artifactDownloads = computed(() => props.message.artifacts?.download_urls || props.message.artifacts?.downloadUrls || {});
const hasArtifactDownloads = computed(() =>
  Boolean(
    artifactDownloads.value.pptx ||
      artifactDownloads.value.plan ||
      artifactDownloads.value.manuscript ||
      artifactDownloads.value.quality,
  ),
);

const qualityReport = computed(
  () => props.message.artifacts?.quality_report || props.message.artifacts?.qualityReport || null,
);
const hasQualityReport = computed(() => Boolean(qualityReport.value));

const canManagePresentationArtifacts = computed(() => {
  const artifacts = props.message.artifacts || {};
  return Boolean(artifacts.session_id || artifacts.pptx_path || artifacts.manifest_path || hasQualityReport.value);
});

const hasDebugEntries = computed(() => debugEntries.value.length > 0);
const hasSources = computed(() => displaySources.value.length > 0);
const hasResearchPlan = computed(() => Boolean(extractedPlan.value.plan));

const canGeneratePresentation = computed(() => {
  const artifacts = props.message.artifacts || {};
  return Boolean(
    artifacts.can_generate_ppt ||
      artifacts.research_session_id ||
      artifacts.session_id ||
      props.message.researchSessionId,
  );
});

const qualityIssueCount = computed(() => {
  const issues = qualityReport.value?.issues;
  return Array.isArray(issues) ? issues.length : 0;
});

const qualityWarningCount = computed(() => {
  const warnings = qualityReport.value?.warnings;
  return Array.isArray(warnings) ? warnings.length : 0;
});

const qualityPassed = computed(() => Boolean(qualityReport.value?.passed));

function applyHighlight() {
  nextTick(() => {
    highlightCodeBlocks(contentRoot.value);
  });
}

function emitPresentationRequest() {
  emit('request-presentation', {
    content: props.message.content || '',
    artifacts: props.message.artifacts || {},
    researchSessionId:
      props.message.researchSessionId ||
      props.message.research_session_id ||
      props.message.artifacts?.research_session_id ||
      props.message.artifacts?.session_id ||
      '',
    topic: props.message.artifacts?.question || props.message.content || '',
  });
}

function emitPresentationQualityRequest() {
  emit('request-presentation-quality', {
    content: props.message.content || '',
    artifacts: props.message.artifacts || {},
    sessionId: props.message.artifacts?.session_id || props.message.researchSessionId || '',
    topic: props.message.artifacts?.topic || props.message.content || '',
  });
}

function emitPresentationRegenerateRequest() {
  emit('request-presentation-regenerate', {
    content: props.message.content || '',
    artifacts: props.message.artifacts || {},
    sessionId: props.message.artifacts?.session_id || props.message.researchSessionId || '',
    topic: props.message.artifacts?.topic || props.message.content || '',
  });
}

onMounted(applyHighlight);
onUpdated(applyHighlight);
</script>

<style scoped>
.message-markdown {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  color: #20324a;
  font-size: 14px;
  line-height: 1.78;
  letter-spacing: 0;
}

.message-markdown :deep(p) {
  margin: 0;
}

.message-markdown :deep(p + p) {
  margin-top: 0.15rem;
}

.message-markdown :deep(h1),
.message-markdown :deep(h2),
.message-markdown :deep(h3),
.message-markdown :deep(h4),
.message-markdown :deep(h5),
.message-markdown :deep(h6) {
  margin: 0.75rem 0 0;
  color: #173053;
  line-height: 1.35;
}

.message-markdown :deep(h1) {
  font-size: 1.35rem;
}

.message-markdown :deep(h2) {
  font-size: 1.15rem;
}

.message-markdown :deep(h3) {
  font-size: 1.02rem;
}

.message-markdown :deep(ul),
.message-markdown :deep(ol) {
  margin: 0.25rem 0 0;
  padding-left: 1.4rem;
}

.message-markdown :deep(li + li) {
  margin-top: 0.25rem;
}

.message-markdown :deep(blockquote) {
  margin: 0.3rem 0 0;
  padding: 0.75rem 0.95rem;
  border-left: 4px solid #84aef8;
  background: #f5f8ff;
  color: #41526e;
  border-radius: 10px;
}

.message-markdown :deep(code:not(pre code)) {
  padding: 0.14rem 0.36rem;
  border-radius: 6px;
  background: #eef4ff;
  color: #21406a;
  font-size: 0.93em;
}

.message-markdown :deep(pre) {
  margin: 0.35rem 0 0;
  padding: 14px 16px;
  border: 1px solid #dbe5f3;
  border-radius: 14px;
  background: #0f172a;
  color: #e8eef8;
  overflow-x: auto;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.message-markdown :deep(pre code) {
  padding: 0;
  background: transparent;
  color: inherit;
  font-size: 0.93rem;
  line-height: 1.7;
}

.message-markdown :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin-top: 0.4rem;
  overflow: hidden;
  border: 1px solid #dfe7f2;
  border-radius: 12px;
  background: #fff;
}

.message-markdown :deep(th),
.message-markdown :deep(td) {
  padding: 10px 12px;
  border-bottom: 1px solid #e6edf6;
  border-right: 1px solid #e6edf6;
  text-align: left;
  vertical-align: top;
}

.message-markdown :deep(th) {
  background: #f5f8ff;
  font-weight: 700;
  color: #20324a;
}

.message-markdown :deep(tr:last-child td) {
  border-bottom: none;
}

.message-markdown :deep(td:last-child),
.message-markdown :deep(th:last-child) {
  border-right: none;
}

.message-markdown :deep(hr) {
  border: 0;
  height: 1px;
  margin: 0.9rem 0;
  background: linear-gradient(90deg, transparent, #d9e3f0, transparent);
}

.message-markdown :deep(a) {
  color: #2f6ef2;
  text-decoration: none;
}

.message-markdown :deep(a:hover) {
  text-decoration: underline;
}

.message-markdown :deep(img) {
  border-radius: 12px;
}

.message-actions {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.message-actions--artifact {
  margin-top: 10px;
}

.message-downloads {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid #e2e9f3;
}

.message-downloads-title {
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 700;
  color: #536175;
}

.message-download-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.message-download-link {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid #c8d6ea;
  border-radius: 8px;
  background: #ffffff;
  color: #21406a;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}

.message-download-link:hover {
  background: #f4f8fd;
  border-color: #99b4d6;
}

.message-quality {
  margin-top: 14px;
  padding: 10px 12px 12px;
  border: 1px solid #dfe7f2;
  border-radius: 14px;
  background: linear-gradient(180deg, #fcfdff 0%, #f8fbff 100%);
}

.message-quality > summary {
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  list-style: none;
  font-size: 13px;
  font-weight: 700;
  color: #23406c;
}

.message-quality > summary::-webkit-details-marker {
  display: none;
}

.message-quality > summary::before {
  content: '▸';
  color: #5f86d6;
  transition: transform 0.18s ease;
}

.message-quality[open] > summary::before {
  transform: rotate(90deg);
}

.message-quality-body {
  margin-top: 10px;
  display: grid;
  gap: 10px;
}

.message-quality-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.message-quality-badge {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid #d3def0;
  background: #ffffff;
  color: #36506f;
  font-size: 12px;
  font-weight: 700;
}

.message-quality-badge.passed {
  border-color: #bfe7ce;
  background: #effaf3;
  color: #12724d;
}

.message-quality-badge.failed {
  border-color: #f4c7c7;
  background: #fff1f1;
  color: #a93030;
}

.message-quality-list {
  display: grid;
  gap: 8px;
}

.message-quality-item {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid #dfe7f2;
  background: #ffffff;
  color: #334155;
  font-size: 12px;
  line-height: 1.55;
}

.message-quality-item.warning {
  background: #fff8eb;
  border-color: #f1deba;
  color: #8a6108;
}

.message-quality-empty {
  padding: 10px 12px;
  border-radius: 10px;
  background: #f7fafc;
  color: #64748b;
  font-size: 12px;
}

.message-plan {
  margin-top: 14px;
  padding: 10px 12px 12px;
  border: 1px solid #dfe7f2;
  border-radius: 14px;
  background: linear-gradient(180deg, #fbfdff 0%, #f8fbff 100%);
}

.message-plan > summary {
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  list-style: none;
  font-size: 13px;
  font-weight: 700;
  color: #23406c;
}

.message-plan > summary::-webkit-details-marker {
  display: none;
}

.message-plan > summary::before {
  content: '▸';
  color: #5f86d6;
  transition: transform 0.18s ease;
}

.message-plan[open] > summary::before {
  transform: rotate(90deg);
}

.message-plan-body {
  margin-top: 10px;
  padding: 12px 14px;
  border: 1px solid #e2eaf4;
  border-radius: 12px;
  background: #ffffff;
}

.message-action-button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid #c8d6ea;
  border-radius: 8px;
  background: #ffffff;
  color: #21406a;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.message-action-button:hover {
  background: #f4f8fd;
  border-color: #99b4d6;
}
</style>
