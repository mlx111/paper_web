<template>
  <aside v-if="visible" class="workflow-panel" aria-label="Workflow progress">
    <header class="workflow-panel-header">
      <div>
        <div class="workflow-panel-kicker">YAML Workflow</div>
        <h2 class="workflow-panel-title">工作流进度</h2>
        <p class="workflow-panel-subtitle">{{ workflowName || 'research_simple' }}</p>
      </div>
      <button type="button" class="workflow-icon-button" title="关闭" @click="$emit('close')">X</button>
    </header>

    <section class="workflow-panel-body">
      <div class="workflow-summary">
        <div>
          <span>状态</span>
          <strong :class="statusClass">{{ statusLabel }}</strong>
        </div>
        <div>
          <span>完成步骤</span>
          <strong>{{ completedCount }} / {{ totalCount }}</strong>
        </div>
      </div>

      <div v-if="question" class="workflow-question">
        <span>问题</span>
        <p>{{ question }}</p>
      </div>

      <div v-if="error" class="workflow-error">
        <span>失败原因</span>
        <p>{{ error }}</p>
      </div>

      <div class="workflow-actions">
        <button
          type="button"
          class="workflow-action-button"
          :disabled="running || !canResume"
          @click="$emit('resume')"
        >
          从失败步骤继续
        </button>
        <button type="button" class="workflow-action-button secondary" :disabled="running" @click="$emit('refresh')">
          刷新进度
        </button>
      </div>

      <div class="workflow-step-list">
        <div
          v-for="step in normalizedSteps"
          :key="step.key"
          class="workflow-step-card"
          :class="step.status"
        >
          <div class="workflow-step-index">{{ step.index + 1 }}</div>
          <div class="workflow-step-main">
            <div class="workflow-step-name">{{ step.name }}</div>
            <div class="workflow-step-meta">{{ stepStatusLabel(step.status) }}</div>
          </div>
        </div>
      </div>

      <div v-if="outputPreview" class="workflow-output">
        <span>输出摘要</span>
        <pre>{{ outputPreview }}</pre>
      </div>
    </section>
  </aside>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  visible: {
    type: Boolean,
    default: false,
  },
  workflowName: {
    type: String,
    default: '',
  },
  status: {
    type: String,
    default: 'not_started',
  },
  question: {
    type: String,
    default: '',
  },
  steps: {
    type: Array,
    default: () => [],
  },
  progress: {
    type: Object,
    default: null,
  },
  output: {
    type: Object,
    default: null,
  },
  error: {
    type: String,
    default: '',
  },
  running: {
    type: Boolean,
    default: false,
  },
});

defineEmits(['close', 'refresh', 'resume']);

const normalizedSteps = computed(() =>
  props.steps.map((step, index) => ({
    key: `${step.name || step.step || 'step'}-${step.index ?? index}`,
    index: Number.isFinite(Number(step.index)) ? Number(step.index) : index,
    name: step.name || step.step || `step_${index + 1}`,
    status: step.status || 'pending',
  })),
);

const completedCount = computed(() =>
  Number(props.progress?.completed_steps) ||
  normalizedSteps.value.filter((step) => step.status === 'completed').length,
);

const totalCount = computed(() =>
  Number(props.progress?.total_steps) ||
  Math.max(normalizedSteps.value.length, completedCount.value),
);

const canResume = computed(() => Boolean(props.progress?.can_resume || props.status === 'failed'));

const statusClass = computed(() => ({
  running: props.status === 'running',
  completed: props.status === 'completed',
  failed: props.status === 'failed',
}));

const statusLabel = computed(() => {
  if (props.status === 'running') return '运行中';
  if (props.status === 'completed') return '已完成';
  if (props.status === 'failed') return '失败';
  return '未开始';
});

const outputPreview = computed(() => {
  if (!props.output || typeof props.output !== 'object') {
    return '';
  }
  const value = props.output.output || props.output.answer || props.output;
  if (typeof value === 'string') {
    return value.slice(0, 1200);
  }
  return JSON.stringify(value, null, 2).slice(0, 1200);
});

function stepStatusLabel(status) {
  if (status === 'running') return '运行中';
  if (status === 'completed') return '已完成';
  if (status === 'failed') return '失败';
  return '等待中';
}
</script>

<style scoped>
.workflow-panel {
  position: fixed;
  right: 0;
  bottom: 0;
  z-index: 30;
  width: min(420px, 100vw);
  max-height: 72vh;
  display: flex;
  flex-direction: column;
  border: 1px solid #c9d6ea;
  border-right: 0;
  border-bottom: 0;
  border-radius: 10px 0 0 0;
  background: #f8fbff;
  color: #20324a;
  box-shadow: -18px -10px 44px rgba(15, 23, 42, 0.16);
}

.workflow-panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 16px 12px;
  border-bottom: 1px solid #dde7f5;
  background: #eef5ff;
}

.workflow-panel-kicker {
  color: #2f6ef2;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.workflow-panel-title {
  margin: 4px 0 0;
  color: #172033;
  font-size: 18px;
  line-height: 1.2;
}

.workflow-panel-subtitle {
  margin: 3px 0 0;
  color: #607089;
  font-size: 12px;
}

.workflow-icon-button,
.workflow-action-button {
  border: 1px solid #b9c8de;
  border-radius: 8px;
  background: #ffffff;
  color: #1e365d;
  cursor: pointer;
  font-size: 12px;
  font-weight: 800;
}

.workflow-icon-button {
  width: 32px;
  height: 32px;
}

.workflow-panel-body {
  min-height: 0;
  overflow-y: auto;
  padding: 14px 16px 18px;
}

.workflow-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.workflow-summary > div,
.workflow-question,
.workflow-error,
.workflow-output {
  border: 1px solid #d8e4f3;
  border-radius: 8px;
  background: #ffffff;
}

.workflow-summary > div {
  padding: 10px;
}

.workflow-summary span,
.workflow-question span,
.workflow-error span,
.workflow-output span {
  display: block;
  color: #6c7b90;
  font-size: 11px;
  font-weight: 800;
}

.workflow-summary strong {
  display: block;
  margin-top: 6px;
  font-size: 17px;
}

.workflow-summary strong.running {
  color: #0369a1;
}

.workflow-summary strong.completed {
  color: #15803d;
}

.workflow-summary strong.failed {
  color: #b91c1c;
}

.workflow-question,
.workflow-error,
.workflow-output {
  margin-top: 10px;
  padding: 10px;
}

.workflow-question p,
.workflow-error p {
  margin: 6px 0 0;
  color: #22334c;
  font-size: 13px;
  line-height: 1.5;
}

.workflow-error {
  border-color: #f1b8b8;
  background: #fff5f5;
}

.workflow-error p {
  color: #991b1b;
}

.workflow-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.workflow-action-button {
  min-height: 34px;
  padding: 0 12px;
  background: #17345f;
  color: #ffffff;
}

.workflow-action-button.secondary {
  background: #ffffff;
  color: #1e365d;
}

.workflow-action-button:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

.workflow-step-list {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}

.workflow-step-card {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 54px;
  padding: 10px;
  border: 1px solid #d8e4f3;
  border-radius: 8px;
  background: #ffffff;
}

.workflow-step-card.running {
  border-color: #7dd3fc;
  background: #eef9ff;
}

.workflow-step-card.completed {
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.workflow-step-card.failed {
  border-color: #fecaca;
  background: #fff1f2;
}

.workflow-step-index {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 999px;
  background: #e8eef8;
  color: #385174;
  font-size: 12px;
  font-weight: 800;
}

.workflow-step-main {
  min-width: 0;
}

.workflow-step-name {
  overflow: hidden;
  color: #172033;
  font-size: 13px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workflow-step-meta {
  margin-top: 3px;
  color: #64748b;
  font-size: 12px;
}

.workflow-output pre {
  max-height: 220px;
  margin: 8px 0 0;
  overflow: auto;
  color: #172033;
  font-size: 12px;
  white-space: pre-wrap;
}
</style>
