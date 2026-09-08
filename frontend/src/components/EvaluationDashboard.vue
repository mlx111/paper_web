<template>
  <section class="evaluation-dashboard" aria-label="Evaluation dashboard">
    <header class="evaluation-dashboard-header">
      <div>
        <div class="evaluation-kicker">AgentOps Benchmark</div>
        <h2>评测面板</h2>
        <p>查看 Benchmark 报告、失败归因、Token 消耗，并跳转到对应 Trace。</p>
      </div>
      <div class="evaluation-actions">
        <button type="button" :disabled="loading || running" @click="loadReports">刷新</button>
        <button type="button" class="primary" :disabled="running" @click="runBenchmark">
          {{ running ? '运行中...' : '运行 Benchmark' }}
        </button>
      </div>
    </header>

    <div v-if="error" class="evaluation-state error">{{ error }}</div>
    <div v-else-if="loading" class="evaluation-state">正在加载评测报告...</div>
    <div v-else-if="!selectedReport" class="evaluation-state">暂无评测报告，点击“运行 Benchmark”生成第一份报告。</div>

    <template v-else>
      <div class="evaluation-report-bar">
        <label>
          <span>报告</span>
          <select v-model="selectedReportName" :disabled="running" @change="loadSelectedReport">
            <option v-for="report in reports" :key="report.name" :value="report.name">
              {{ report.name }}
            </option>
          </select>
        </label>
        <div class="evaluation-report-meta">
          <span>{{ selectedReportInfo?.updated_at || '-' }}</span>
          <span>{{ formatBytes(selectedReportInfo?.size_bytes) }}</span>
        </div>
      </div>

      <div class="evaluation-summary-grid">
        <div class="evaluation-summary-card"><span>总 Case</span><strong>{{ summary.total_cases ?? '-' }}</strong></div>
        <div class="evaluation-summary-card"><span>通过</span><strong>{{ summary.passed_cases ?? '-' }}</strong></div>
        <div class="evaluation-summary-card"><span>平均分</span><strong>{{ formatScore(summary.avg_score) }}</strong></div>
        <div class="evaluation-summary-card"><span>平均延迟</span><strong>{{ formatLatency(summary.avg_latency_ms) }}</strong></div>
        <div class="evaluation-summary-card"><span>总 Token</span><strong>{{ formatNumber(totalTokens) }}</strong></div>
      </div>

      <section class="evaluation-section">
        <div class="evaluation-section-head">
          <h3>失败类别</h3>
          <span>{{ failureCategories.length }} 类</span>
        </div>
        <div v-if="!failureCategories.length" class="evaluation-empty">当前报告没有失败 case。</div>
        <div v-else class="failure-category-list">
          <div v-for="item in failureCategories" :key="item.category" class="failure-category-item">
            <span>{{ item.category }}</span>
            <strong>{{ item.count }}</strong>
          </div>
        </div>
      </section>

      <section class="evaluation-section">
        <div class="evaluation-section-head">
          <h3>Failed Cases</h3>
          <span>{{ failedCases.length }} 条</span>
        </div>
        <div v-if="!failedCases.length" class="evaluation-empty">没有失败样本，可以查看全部结果确认成本和延迟。</div>
        <div v-else class="evaluation-table-wrap">
          <table class="evaluation-table">
            <thead>
              <tr>
                <th>Case</th>
                <th>Score</th>
                <th>Category</th>
                <th>Reason</th>
                <th>Tools</th>
                <th>Token</th>
                <th>Latency</th>
                <th>Trace</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in failedCases" :key="item.case_id">
                <td><code>{{ item.case_id }}</code></td>
                <td>{{ formatScore(item.score) }}</td>
                <td>{{ item.failure_category || '-' }}</td>
                <td>{{ item.failure_reason || item.error || '-' }}</td>
                <td>{{ formatTools(item.actual_tools) }}</td>
                <td>{{ formatNumber(item.token_usage) }}</td>
                <td>{{ formatLatency(item.latency_ms) }}</td>
                <td>
                  <button type="button" class="trace-link-button" :disabled="!item.run_id" @click="openTrace(item)">
                    查看 Trace
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { getEvaluationReport, listEvaluationReports, runEvaluation } from '../services/api.js';

const emit = defineEmits(['open-trace']);

const loading = ref(false);
const running = ref(false);
const error = ref('');
const reports = ref([]);
const selectedReportName = ref('');
const selectedReport = ref(null);

const selectedReportInfo = computed(() => reports.value.find((item) => item.name === selectedReportName.value) || null);
const summary = computed(() => selectedReport.value?.summary || {});
const results = computed(() => (Array.isArray(selectedReport.value?.results) ? selectedReport.value.results : []));
const failedCases = computed(() => {
  const explicit = selectedReport.value?.failed_cases;
  if (Array.isArray(explicit) && explicit.length) {
    return explicit;
  }
  return results.value.filter((item) => Number(item.score) < 0.75);
});
const totalTokens = computed(() => results.value.reduce((sum, item) => sum + (Number(item.token_usage) || 0), 0));
const failureCategories = computed(() => {
  const categories = summary.value.failure_categories || {};
  return Object.entries(categories)
    .map(([category, count]) => ({ category, count }))
    .filter((item) => Number(item.count) > 0);
});

async function loadReports() {
  loading.value = true;
  error.value = '';
  try {
    const data = await listEvaluationReports();
    reports.value = Array.isArray(data.reports) ? data.reports : [];
    if (!selectedReportName.value && reports.value[0]?.name) {
      selectedReportName.value = reports.value[0].name;
    }
    if (selectedReportName.value) {
      await loadSelectedReport();
    } else {
      selectedReport.value = null;
    }
  } catch (err) {
    error.value = err.message || '评测报告加载失败。';
  } finally {
    loading.value = false;
  }
}

async function loadSelectedReport() {
  if (!selectedReportName.value) {
    selectedReport.value = null;
    return;
  }
  error.value = '';
  try {
    selectedReport.value = await getEvaluationReport(selectedReportName.value);
  } catch (err) {
    selectedReport.value = null;
    error.value = err.message || '评测报告读取失败。';
  }
}

async function runBenchmark() {
  running.value = true;
  error.value = '';
  try {
    const result = await runEvaluation();
    selectedReportName.value = result.report_name || '';
    await loadReports();
  } catch (err) {
    error.value = err.message || 'Benchmark 运行失败。';
  } finally {
    running.value = false;
  }
}

function openTrace(item) {
  if (!item?.run_id) {
    return;
  }
  emit('open-trace', { runId: item.run_id, run_id: item.run_id });
}

function formatScore(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(2) : '-';
}

function formatLatency(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return '-';
  }
  return number >= 1000 ? `${(number / 1000).toFixed(2)}s` : `${number.toFixed(0)}ms`;
}

function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString() : '-';
}

function formatBytes(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return '-';
  }
  return number >= 1024 ? `${(number / 1024).toFixed(1)} KB` : `${number} B`;
}

function formatTools(tools) {
  return Array.isArray(tools) && tools.length ? tools.join(', ') : '-';
}

onMounted(loadReports);
</script>

<style scoped>
.evaluation-dashboard {
  min-height: 100%;
  overflow-y: auto;
  padding: 28px;
  background: #0f1720;
  color: #dce7f3;
}

.evaluation-dashboard-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding-bottom: 20px;
  border-bottom: 1px solid #253345;
}

.evaluation-kicker {
  color: #7dd3fc;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.evaluation-dashboard h2 {
  margin: 6px 0 8px;
  color: #f8fafc;
  font-size: 28px;
  line-height: 1.2;
}

.evaluation-dashboard p {
  margin: 0;
  color: #9fb0c5;
  font-size: 14px;
}

.evaluation-actions,
.evaluation-report-meta {
  display: flex;
  gap: 10px;
}

.evaluation-actions button,
.trace-link-button {
  height: 36px;
  padding: 0 13px;
  border: 1px solid #36506b;
  border-radius: 8px;
  background: #142235;
  color: #dbeafe;
  cursor: pointer;
  font-weight: 800;
}

.evaluation-actions button.primary {
  border-color: #0ea5e9;
  background: #075985;
  color: #f0f9ff;
}

.evaluation-actions button:disabled,
.trace-link-button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.evaluation-state,
.evaluation-report-bar,
.evaluation-summary-card,
.evaluation-section {
  border: 1px solid #26384f;
  border-radius: 8px;
  background: #111d2d;
}

.evaluation-state {
  margin-top: 18px;
  padding: 16px;
  color: #b5c6dc;
}

.evaluation-state.error {
  border-color: #7f2d2d;
  background: #2a1518;
  color: #fecaca;
}

.evaluation-report-bar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  margin-top: 20px;
  padding: 14px;
}

.evaluation-report-bar label {
  display: grid;
  gap: 7px;
}

.evaluation-report-bar span,
.evaluation-summary-card span {
  color: #8395ad;
  font-size: 12px;
  font-weight: 800;
}

.evaluation-report-bar select {
  min-width: min(420px, 72vw);
  height: 36px;
  border: 1px solid #36506b;
  border-radius: 8px;
  background: #0a1320;
  color: #f8fafc;
}

.evaluation-summary-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.evaluation-summary-card {
  min-height: 86px;
  padding: 14px;
}

.evaluation-summary-card span {
  font-size: 11px;
  text-transform: uppercase;
}

.evaluation-summary-card strong {
  display: block;
  margin-top: 10px;
  color: #f8fafc;
  font-size: 22px;
}

.evaluation-section {
  margin-top: 16px;
  padding: 16px;
}

.evaluation-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.evaluation-section-head h3 {
  margin: 0;
  color: #f8fafc;
  font-size: 17px;
}

.evaluation-section-head span,
.evaluation-empty {
  color: #8ca0b8;
  font-size: 13px;
}

.failure-category-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.failure-category-item {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 38px;
  padding: 0 12px;
  border: 1px solid #334966;
  border-radius: 8px;
  background: #0a1320;
}

.failure-category-item strong {
  color: #fca5a5;
}

.evaluation-table-wrap {
  overflow-x: auto;
}

.evaluation-table {
  width: 100%;
  min-width: 980px;
  border-collapse: collapse;
}

.evaluation-table th,
.evaluation-table td {
  padding: 11px 10px;
  border-bottom: 1px solid #26384f;
  text-align: left;
  vertical-align: top;
  font-size: 13px;
}

.evaluation-table th {
  color: #8ca0b8;
  font-size: 11px;
  text-transform: uppercase;
}

.evaluation-table code {
  color: #bae6fd;
}

.trace-link-button {
  height: 30px;
  font-size: 12px;
}

@media (max-width: 980px) {
  .evaluation-dashboard {
    padding: 18px;
  }

  .evaluation-dashboard-header,
  .evaluation-report-bar {
    align-items: stretch;
    flex-direction: column;
  }

  .evaluation-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
