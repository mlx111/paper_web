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
        <!-- Candidate research plans selection -->
        <div v-if="hasCandidates" class="message-candidates">
          <div class="message-candidates-title">请选择研究方向</div>
          <div
            v-for="candidate in candidates"
            :key="candidate.candidate_id"
            class="message-candidate-card"
            :class="{ selected: selectedCandidateId === candidate.candidate_id }"
            @click="selectCandidate(candidate.candidate_id)"
          >
            <div class="message-candidate-id">{{ candidate.candidate_id }}</div>
            <div class="message-candidate-body">
              <div class="message-candidate-title">{{ candidate.title }}</div>
              <div class="message-candidate-label">核心问题</div>
              <div class="message-candidate-text">{{ candidate.core_question }}</div>
              <div class="message-candidate-label">预期产出</div>
              <div class="message-candidate-text">{{ candidate.expected_output }}</div>
            </div>
          </div>
          <div v-if="selectedCandidateId" class="message-candidate-actions">
            <div class="message-candidate-modify">
              <label class="message-candidate-modify-label">或修改研究方向描述</label>
              <input
                v-model="modifiedQuery"
                type="text"
                class="message-candidate-modify-input"
                placeholder="输入修改后的研究方向..."
              />
            </div>
            <button
              type="button"
              class="message-action-button message-candidate-confirm"
              :disabled="!selectedCandidateId"
              @click="emitCandidateConfirm"
            >
              按此方向开始研究
            </button>
          </div>
        </div>

        <article class="message-markdown message-markdown-main" v-html="renderedHtml"></article>

        <!-- Research progress timeline -->
        <div v-if="hasResearchStages" class="message-timeline">
          <div class="message-timeline-title">研究进度</div>
          <div class="message-timeline-steps">
            <div
              v-for="stage in stageOrder"
              :key="stage.key"
              class="message-timeline-step"
              :class="stageClass(stage.key)"
            >
              <div class="message-timeline-dot"></div>
              <div class="message-timeline-label">{{ stage.label }}</div>
            </div>
          </div>
        </div>

        <div v-if="hasDebugEntries" class="message-debug">
          <div class="message-debug-title">研究过程</div>
          <div v-if="hasResearchStages" class="message-debug-hint">详细日志见下方可展开区域</div>
          <details>
            <summary class="message-debug-summary">查看详细日志</summary>
            <div class="message-debug-list">
              <div v-for="entry in debugEntries" :key="entry.key" class="message-debug-item">
                <div class="message-debug-node">{{ entry.nodeLabel }}</div>
                <div class="message-debug-text">{{ entry.text }}</div>
              </div>
            </div>
          </details>
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

        <div v-if="canManageResearchArtifacts" class="message-actions message-actions--artifact">
          <button type="button" class="message-action-button" @click="emitResearchQualityRequest">
            质量检查
          </button>
          <button type="button" class="message-action-button" @click="emitResearchRegenerateRequest">
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
  'request-research-quality',
  'request-research-regenerate',
  'candidate-selected',
]);

const props = defineProps({
  message: {
    type: Object,
    required: true
  }
});

const contentRoot = ref(null);
const isAssistantLike = computed(() => props.message.type === 'assistant');

// Candidate selection
const selectedCandidateId = ref('');
const modifiedQuery = ref('');

const candidates = computed(() => {
  const raw = props.message.clarificationCandidates || props.message.clarification_candidates || [];
  return Array.isArray(raw) ? raw : [];
});

const hasCandidates = computed(() => candidates.value.length > 0);

function selectCandidate(id) {
  selectedCandidateId.value = id;
}

function emitCandidateConfirm() {
  emit('candidate-selected', {
    candidateId: selectedCandidateId.value,
    modifiedQuery: modifiedQuery.value?.trim() || null,
  });
}

// Research timeline / stages
const stageOrder = [
  { key: 'clarify', label: '澄清' },
  { key: 'refine', label: '聚焦' },
  { key: 'branches', label: '分支' },
  { key: 'search', label: '搜索' },
  { key: 'synthesize', label: '综合' },
  { key: 'planning', label: '规划' },
  { key: 'report', label: '报告' },
  { key: 'judge', label: '检查' },
];

const researchStages = computed(() => {
  const stages = props.message.researchStages || props.message.research_stages || [];
  return Array.isArray(stages) ? stages : [];
});

const hasResearchStages = computed(() => researchStages.value.length > 0);

function stageClass(stageKey) {
  const stage = researchStages.value.find(s => s.stage === stageKey);
  if (!stage) return 'pending';
  return stage.status || 'pending';
}

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

const canManageResearchArtifacts = computed(() => {
  const artifacts = props.message.artifacts || {};
  return Boolean(
    artifacts.research_session_id ||
      artifacts.session_id ||
      props.message.researchSessionId ||
      hasQualityReport.value,
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

function emitResearchQualityRequest() {
  emit('request-research-quality', {
    content: props.message.content || '',
    artifacts: props.message.artifacts || {},
    sessionId: props.message.artifacts?.session_id || props.message.researchSessionId || '',
  });
}

function emitResearchRegenerateRequest() {
  emit('request-research-regenerate', {
    content: props.message.content || '',
    artifacts: props.message.artifacts || {},
    sessionId: props.message.artifacts?.session_id || props.message.researchSessionId || '',
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

/* Candidate selection cards */
.message-candidates {
  margin-bottom: 16px;
  padding: 14px;
  border: 1px solid #d0ddef;
  border-radius: 14px;
  background: linear-gradient(180deg, #f8fbff 0%, #f4f8ff 100%);
}

.message-candidates-title {
  margin-bottom: 10px;
  font-size: 14px;
  font-weight: 700;
  color: #173053;
}

.message-candidate-card {
  display: flex;
  gap: 10px;
  margin-bottom: 8px;
  padding: 10px 12px;
  border: 1.5px solid #d8e2f0;
  border-radius: 10px;
  background: #ffffff;
  cursor: pointer;
  transition: all 0.15s ease;
}

.message-candidate-card:hover {
  border-color: #8aabdd;
  background: #f6faff;
}

.message-candidate-card.selected {
  border-color: #2f6ef2;
  background: #eef5ff;
  box-shadow: 0 0 0 1px rgba(47, 110, 242, 0.15);
}

.message-candidate-id {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #2f6ef2;
  color: #ffffff;
  font-size: 13px;
  font-weight: 700;
}

.message-candidate-card.selected .message-candidate-id {
  background: #1a5bd6;
}

.message-candidate-body {
  flex: 1;
  min-width: 0;
}

.message-candidate-title {
  font-size: 13px;
  font-weight: 700;
  color: #173053;
  margin-bottom: 4px;
}

.message-candidate-label {
  font-size: 11px;
  font-weight: 600;
  color: #6a7f9c;
  margin-top: 4px;
}

.message-candidate-text {
  font-size: 12px;
  color: #334155;
  line-height: 1.5;
}

.message-candidate-actions {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.message-candidate-modify {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.message-candidate-modify-label {
  font-size: 12px;
  color: #536175;
}

.message-candidate-modify-input {
  padding: 8px 10px;
  border: 1px solid #c8d6ea;
  border-radius: 8px;
  font-size: 13px;
  color: #20324a;
  background: #ffffff;
}

.message-candidate-modify-input:focus {
  outline: none;
  border-color: #2f6ef2;
  box-shadow: 0 0 0 2px rgba(47, 110, 242, 0.12);
}

.message-candidate-confirm {
  align-self: flex-start;
  background: #2f6ef2;
  color: #ffffff;
  border-color: #2f6ef2;
}

.message-candidate-confirm:hover {
  background: #1a5bd6;
  border-color: #1a5bd6;
}

.message-candidate-confirm:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Research timeline stepper */
.message-timeline {
  margin-top: 14px;
  margin-bottom: 6px;
}

.message-timeline-title {
  font-size: 12px;
  font-weight: 700;
  color: #536175;
  margin-bottom: 8px;
}

.message-timeline-steps {
  display: flex;
  align-items: center;
  gap: 0;
  overflow-x: auto;
  padding: 4px 0;
}

.message-timeline-step {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.message-timeline-step + .message-timeline-step::before {
  content: '\2192';
  margin: 0 6px;
  color: #bcc9db;
  font-size: 12px;
}

.message-timeline-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #d8e2f0;
  flex-shrink: 0;
}

.message-timeline-step.running .message-timeline-dot {
  background: #2f6ef2;
  box-shadow: 0 0 0 3px rgba(47, 110, 242, 0.2);
  animation: pulse 1.5s ease-in-out infinite;
}

.message-timeline-step.done .message-timeline-dot {
  background: #22a06b;
}

.message-timeline-step.failed .message-timeline-dot {
  background: #e3493a;
}

@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 3px rgba(47, 110, 242, 0.2); }
  50% { box-shadow: 0 0 0 6px rgba(47, 110, 242, 0.08); }
}

.message-timeline-label {
  font-size: 11px;
  color: #6a7f9c;
  white-space: nowrap;
}

.message-timeline-step.running .message-timeline-label {
  color: #2f6ef2;
  font-weight: 600;
}

.message-timeline-step.done .message-timeline-label {
  color: #22a06b;
}

.message-timeline-step.failed .message-timeline-label {
  color: #e3493a;
}

.message-debug-hint {
  font-size: 11px;
  color: #8a9bb5;
  margin-bottom: 6px;
}

.message-debug-summary {
  cursor: pointer;
  font-size: 12px;
  color: #2f6ef2;
  font-weight: 600;
  margin-bottom: 6px;
}

.message-debug-summary::-webkit-details-marker {
  display: none;
}
</style>
