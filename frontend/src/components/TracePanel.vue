<template>
  <aside v-if="visible" class="trace-panel" aria-label="Agent run trace">
    <header class="trace-panel-header">
      <div>
        <div class="trace-panel-kicker">{{ t.kicker }}</div>
        <h2 class="trace-panel-title">{{ title }}</h2>
      </div>
      <div class="trace-panel-actions">
        <button type="button" class="trace-lang-button" :title="t.switchLanguage" @click="toggleLanguage">
          {{ isChinese ? 'EN' : '中文' }}
        </button>
        <button type="button" class="trace-icon-button" title="Refresh trace" @click="$emit('refresh')">
          {{ t.refreshShort }}
        </button>
        <button type="button" class="trace-icon-button" title="Close trace panel" @click="$emit('close')">
          {{ t.closeShort }}
        </button>
      </div>
    </header>

    <div v-if="loading" class="trace-panel-state">{{ t.loading }}</div>
    <div v-else-if="error" class="trace-panel-state error">{{ error }}</div>
    <div v-else-if="!trace" class="trace-panel-state">{{ t.noTrace }}</div>

    <section v-else class="trace-panel-body">
      <div v-if="trace.status === 'running'" class="trace-running-notice">
        {{ t.runningNotice }}
      </div>

      <div class="trace-summary-grid">
        <div class="trace-summary-item">
          <span>{{ t.status }}</span>
          <strong :class="statusClass">{{ statusLabel(trace.status) }}</strong>
        </div>
        <div class="trace-summary-item">
          <span>{{ t.route }}</span>
          <strong>{{ trace.route || '-' }}</strong>
        </div>
        <div class="trace-summary-item">
          <span>{{ t.steps }}</span>
          <strong>{{ steps.length }}</strong>
        </div>
        <div class="trace-summary-item">
          <span>{{ t.latency }}</span>
          <strong>{{ totalLatencyLabel }}</strong>
        </div>
        <div class="trace-summary-item">
          <span>{{ t.failedSteps }}</span>
          <strong>{{ summaryCount(runSummary.failed_steps) }}</strong>
        </div>
        <div class="trace-summary-item">
          <span>{{ t.toolCalls }}</span>
          <strong>{{ summaryCount(runSummary.tool_steps) }}</strong>
        </div>
        <div class="trace-summary-item">
          <span>{{ t.mcpTools }}</span>
          <strong>{{ summaryCount(runSummary.mcp_tool_steps) }}</strong>
        </div>
        <div class="trace-summary-item">
          <span>{{ t.errorCodes }}</span>
          <strong class="trace-summary-list">{{ summaryList(runSummary.tool_error_codes) }}</strong>
        </div>
      </div>

      <div class="trace-token-card">
        <div class="trace-token-card-head">
          <span>{{ t.tokenUsage }}</span>
          <strong>{{ formatToken(tokenUsage.total_tokens) }}</strong>
        </div>
        <div class="trace-token-grid">
          <div>
            <span>{{ t.promptTokens }}</span>
            <strong>{{ formatToken(tokenUsage.prompt_tokens) }}</strong>
          </div>
          <div>
            <span>{{ t.completionTokens }}</span>
            <strong>{{ formatToken(tokenUsage.completion_tokens) }}</strong>
          </div>
          <div>
            <span>{{ t.usageSource }}</span>
            <strong>{{ usageSourceLabel }}</strong>
          </div>
        </div>
      </div>

      <div class="trace-question">
        <span>{{ t.question }}</span>
        <p>{{ trace.question || '-' }}</p>
      </div>

      <div class="trace-run-meta">
        <div>
          <span>{{ t.runId }}</span>
          <code>{{ trace.run_id }}</code>
        </div>
        <div>
          <span>{{ t.sessionId }}</span>
          <code>{{ trace.session_id || '-' }}</code>
        </div>
      </div>

      <div class="trace-timeline">
        <div
          v-for="step in steps"
          :key="step.step_id"
          class="trace-step"
          :class="step.status || 'unknown'"
        >
          <div class="trace-step-rail">
            <span></span>
          </div>
          <div class="trace-step-card">
            <div class="trace-step-head">
              <div>
                <div class="trace-step-name">{{ stepNameLabel(step.step_name) }}</div>
                <div class="trace-step-type">{{ stepTypeLabel(step.step_type) }}</div>
              </div>
              <div class="trace-step-latency">{{ formatLatency(step.latency_ms) }}</div>
            </div>
            <div class="trace-step-status" :class="step.status || 'unknown'">
              {{ statusLabel(step.status) }}
            </div>
            <div v-if="isToolStep(step)" class="trace-tool-card">
              <div>
                <span>Tool</span>
                <strong>{{ step.input?.tool_name || step.step_name?.replace('tool:', '') || '-' }}</strong>
              </div>
              <div>
                <span>Summary</span>
                <strong>{{ toolSummary(step) }}</strong>
              </div>
              <div>
                <span>Error Code</span>
                <strong>{{ step.output?.error_code || '-' }}</strong>
              </div>
              <div>
                <span>Data Size</span>
                <strong>{{ formatDataSize(step.output?.data_size) }}</strong>
              </div>
            </div>
            <div v-if="step.error" class="trace-step-error">{{ step.error }}</div>
            <details class="trace-step-details">
              <summary>{{ t.payload }}</summary>
              <pre>{{ formatPayload({ input: step.input, output: step.output }) }}</pre>
            </details>
          </div>
        </div>
      </div>
    </section>
  </aside>
</template>

<script setup>
import { computed, ref } from 'vue';

const props = defineProps({
  visible: {
    type: Boolean,
    default: false,
  },
  trace: {
    type: Object,
    default: null,
  },
  loading: {
    type: Boolean,
    default: false,
  },
  error: {
    type: String,
    default: '',
  },
});

defineEmits(['close', 'refresh']);

const language = ref('zh');
const isChinese = computed(() => language.value === 'zh');
const steps = computed(() => (Array.isArray(props.trace?.steps) ? props.trace.steps : []));
const runSummary = computed(() => {
  const summary = props.trace ? props.trace.summary : null;
  return summary && typeof summary === 'object' ? summary : {};
});

const labels = {
  zh: {
    kicker: '运行追踪',
    switchLanguage: '切换到英文',
    refreshShort: '刷新',
    closeShort: '关闭',
    loading: '正在加载追踪...',
    noTrace: '未选择追踪记录。',
    status: '状态',
    route: '路由',
    steps: '步骤数',
    latency: '总耗时',
    tokenUsage: 'Token 消耗',
    promptTokens: '输入 Token',
    completionTokens: '输出 Token',
    usageSource: '来源',
    question: '问题',
    runId: '运行 ID',
    sessionId: '会话 ID',
    payload: '输入/输出详情',
    estimated: '估算',
    modelReturned: '模型返回',
    unknown: '未知',
    completed: '已完成',
    failed: '失败',
    running: '运行中',
    context: '上下文',
    model: '模型',
  },
  en: {
    kicker: 'Run Trace',
    switchLanguage: 'Switch to Chinese',
    refreshShort: 'R',
    closeShort: 'X',
    loading: 'Loading trace...',
    noTrace: 'No trace selected.',
    status: 'Status',
    route: 'Route',
    steps: 'Steps',
    latency: 'Latency',
    tokenUsage: 'Token Usage',
    promptTokens: 'Prompt Tokens',
    runningNotice: 'This run is still in progress. Full steps and token usage will appear after completion.',
    completionTokens: 'Completion Tokens',
    usageSource: 'Source',
    question: 'Question',
    runId: 'Run',
    sessionId: 'Session',
    payload: 'Payload',
    estimated: 'Estimated',
    modelReturned: 'Model returned',
    unknown: 'Unknown',
    completed: 'completed',
    failed: 'failed',
    running: 'running',
    context: 'context',
    model: 'model',
  },
};

const stepNameLabels = {
  zh: {
    context_build: '上下文构建',
    model_stream: '模型流式生成',
    model_invoke: '模型调用',
  },
  en: {
    context_build: 'context_build',
    model_stream: 'model_stream',
    model_invoke: 'model_invoke',
  },
};

const t = computed(() => ({
  runningNotice:
    language.value === 'zh'
      ? '当前运行中，完成后会显示完整步骤和 Token 消耗。'
      : 'This run is still in progress. Full steps and token usage will appear after completion.',
  ...labels[language.value],
  failedSteps: 'Failed Steps',
  toolCalls: 'Tool Calls',
  mcpTools: 'MCP Tools',
  errorCodes: 'Error Codes',
}));

const title = computed(() => {
  if (props.trace?.run_id) {
    return props.trace.run_id.slice(0, 10);
  }
  return 'Trace';
});

const statusClass = computed(() => ({
  completed: props.trace?.status === 'completed',
  failed: props.trace?.status === 'failed',
  running: props.trace?.status === 'running',
}));

const totalLatencyLabel = computed(() => {
  const total = steps.value.reduce((sum, step) => sum + (Number(step.latency_ms) || 0), 0);
  return formatLatency(total);
});

const tokenUsage = computed(() => {
  for (const step of [...steps.value].reverse()) {
    const usage = step?.output?.token_usage;
    if (usage && typeof usage === 'object') {
      return usage;
    }
  }
  return {
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    estimated: true,
    source: 'unavailable',
  };
});

const usageSourceLabel = computed(() => {
  if (!tokenUsage.value.total_tokens) {
    return t.value.unknown;
  }
  return tokenUsage.value.estimated ? t.value.estimated : t.value.modelReturned;
});

function toggleLanguage() {
  language.value = language.value === 'zh' ? 'en' : 'zh';
}

function formatLatency(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return '-';
  }
  if (number >= 1000) {
    return `${(number / 1000).toFixed(2)}s`;
  }
  return `${number}ms`;
}

function formatToken(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) {
    return '-';
  }
  return number.toLocaleString();
}

function summaryCount(value) {
  return Array.isArray(value) ? value.length : 0;
}

function summaryList(value) {
  if (!Array.isArray(value) || value.length === 0) {
    return '-';
  }
  return value.join(', ');
}

function statusLabel(status) {
  const key = status || 'unknown';
  return t.value[key] || key;
}

function stepNameLabel(name) {
  return stepNameLabels[language.value][name] || name || t.value.unknown;
}

function stepTypeLabel(type) {
  return t.value[type] || type || t.value.unknown;
}

function isToolStep(step) {
  return step?.step_type === 'tool' || String(step?.step_name || '').startsWith('tool:');
}

function toolSummary(step) {
  return step?.output?.summary || step?.output?.error || '-';
}

function formatDataSize(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) {
    return '-';
  }
  if (number >= 1024) {
    return `${(number / 1024).toFixed(1)} KB`;
  }
  return `${number} B`;
}

function formatPayload(value) {
  return JSON.stringify(value, null, 2);
}
</script>

<style scoped>
.trace-panel {
  position: fixed;
  top: 0;
  right: 0;
  z-index: 35;
  width: min(440px, 100vw);
  height: 100vh;
  display: flex;
  flex-direction: column;
  border-left: 1px solid #23324a;
  background: #0d1624;
  color: #dbe7f5;
  box-shadow: -20px 0 48px rgba(15, 23, 42, 0.24);
}

.trace-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 18px 14px;
  border-bottom: 1px solid #1e2b3f;
}

.trace-panel-kicker {
  color: #7dd3fc;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.trace-panel-title {
  margin: 4px 0 0;
  color: #f8fafc;
  font-size: 19px;
  line-height: 1.2;
}

.trace-panel-actions {
  display: flex;
  gap: 8px;
}

.trace-icon-button,
.trace-lang-button {
  min-width: 32px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid #31445f;
  border-radius: 8px;
  background: #121f32;
  color: #c6d6ea;
  cursor: pointer;
  font-size: 12px;
  font-weight: 800;
}

.trace-lang-button {
  min-width: 48px;
}

.trace-icon-button:hover,
.trace-lang-button:hover {
  border-color: #5aa7d6;
  color: #ffffff;
}

.trace-panel-state {
  margin: 18px;
  padding: 14px;
  border: 1px solid #26384f;
  border-radius: 8px;
  background: #111d2d;
  color: #a9bad0;
  font-size: 13px;
}

.trace-panel-state.error {
  border-color: #7f2d2d;
  background: #2a1518;
  color: #fecaca;
}

.trace-panel-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 18px 24px;
}

.trace-running-notice {
  margin-bottom: 12px;
  padding: 12px;
  border: 1px solid #315b7a;
  border-radius: 8px;
  background: #0b2235;
  color: #bae6fd;
  font-size: 13px;
  line-height: 1.5;
}

.trace-summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.trace-summary-item,
.trace-token-card,
.trace-question,
.trace-run-meta > div {
  border: 1px solid #243550;
  border-radius: 8px;
  background: #101b2b;
}

.trace-summary-item {
  min-height: 76px;
  padding: 12px;
}

.trace-summary-item span,
.trace-question span,
.trace-run-meta span {
  display: block;
  color: #8395ad;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}

.trace-summary-item strong {
  display: block;
  margin-top: 8px;
  color: #f8fafc;
  font-size: 18px;
  line-height: 1.2;
}

.trace-summary-item .trace-summary-list {
  overflow-wrap: anywhere;
  font-size: 13px;
}

.trace-token-card {
  margin-top: 12px;
  padding: 12px;
}

.trace-token-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.trace-token-card-head span,
.trace-token-grid span {
  color: #8395ad;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}

.trace-token-card-head strong {
  color: #f8fafc;
  font-size: 20px;
}

.trace-token-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.trace-token-grid div {
  min-width: 0;
  padding: 10px;
  border-radius: 8px;
  background: #08111f;
}

.trace-token-grid strong {
  display: block;
  margin-top: 6px;
  overflow: hidden;
  color: #dbeafe;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-summary-item strong.completed {
  color: #86efac;
}

.trace-summary-item strong.failed {
  color: #fca5a5;
}

.trace-summary-item strong.running {
  color: #93c5fd;
}

.trace-question {
  margin-top: 12px;
  padding: 12px;
}

.trace-question p {
  margin: 8px 0 0;
  color: #dbe7f5;
  font-size: 13px;
  line-height: 1.55;
}

.trace-run-meta {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}

.trace-run-meta > div {
  min-width: 0;
  padding: 12px;
}

.trace-run-meta code {
  display: block;
  margin-top: 7px;
  overflow: hidden;
  color: #bae6fd;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-timeline {
  display: grid;
  gap: 0;
  margin-top: 18px;
}

.trace-step {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
}

.trace-step-rail {
  position: relative;
}

.trace-step-rail::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 10px;
  width: 1px;
  background: #26384f;
}

.trace-step-rail span {
  position: relative;
  z-index: 1;
  display: block;
  width: 11px;
  height: 11px;
  margin-top: 17px;
  border-radius: 50%;
  background: #64748b;
}

.trace-step.completed .trace-step-rail span {
  background: #22c55e;
}

.trace-step.failed .trace-step-rail span {
  background: #ef4444;
}

.trace-step-card {
  margin-bottom: 12px;
  padding: 12px;
  border: 1px solid #243550;
  border-radius: 8px;
  background: #101b2b;
}

.trace-step-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.trace-step-name {
  color: #f8fafc;
  font-size: 14px;
  font-weight: 800;
}

.trace-step-type,
.trace-step-latency {
  color: #8395ad;
  font-size: 12px;
}

.trace-step-status {
  display: inline-flex;
  margin-top: 10px;
  padding: 3px 8px;
  border-radius: 999px;
  background: #1f2f45;
  color: #cbd5e1;
  font-size: 11px;
  font-weight: 800;
}

.trace-step-status.completed {
  background: #12351f;
  color: #86efac;
}

.trace-step-status.failed {
  background: #3b171b;
  color: #fca5a5;
}

.trace-step-error {
  margin-top: 10px;
  color: #fecaca;
  font-size: 12px;
  line-height: 1.45;
}

.trace-tool-card {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
  padding: 10px;
  border: 1px solid #315b7a;
  border-radius: 8px;
  background: #081827;
}

.trace-tool-card span {
  display: block;
  color: #7aa7c7;
  font-size: 10px;
  font-weight: 800;
  text-transform: uppercase;
}

.trace-tool-card strong {
  display: block;
  margin-top: 4px;
  overflow: hidden;
  color: #dbeafe;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-step-details {
  margin-top: 10px;
}

.trace-step-details summary {
  cursor: pointer;
  color: #7dd3fc;
  font-size: 12px;
  font-weight: 700;
}

.trace-step-details pre {
  max-height: 260px;
  margin: 9px 0 0;
  overflow: auto;
  padding: 10px;
  border: 1px solid #243550;
  border-radius: 8px;
  background: #08111f;
  color: #dbeafe;
  font-size: 11px;
  line-height: 1.55;
}

@media (max-width: 720px) {
  .trace-panel {
    width: 100vw;
  }
}
</style>
