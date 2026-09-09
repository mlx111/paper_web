<template>
  <div class="model-settings-page">
    <header class="ms-header">
      <h2>模型设置</h2>
      <p>配置大模型的供应商、模型名称、API Key 与接口地址。保存后<strong>立即生效</strong>，无需重启服务。</p>
    </header>

    <div v-if="loading" class="ms-loading">加载中…</div>

    <form v-else class="ms-card" @submit.prevent="handleSave">
      <div class="ms-current" v-if="config">
        <span class="ms-badge">当前生效</span>
        <span>{{ currentProviderName }} · {{ config.model }}</span>
        <span class="ms-key-state" :class="{ ok: config.has_api_key }">
          {{ config.has_api_key ? `Key 已配置（${config.api_key_masked}）` : '未配置 API Key' }}
        </span>
      </div>

      <label class="ms-field">
        <span class="ms-label">模型供应商</span>
        <select v-model="form.provider" @change="handleProviderChange">
          <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </label>

      <label class="ms-field">
        <span class="ms-label">模型名称</span>
        <div class="ms-model-row" ref="modelFieldRef">
          <input
            v-model="form.model"
            type="text"
            placeholder="例如 qwen3.5-flash / deepseek-chat / gpt-4o-mini"
            @focus="showDropdown = !!availableModels.length"
            @input="showDropdown = !!availableModels.length"
            @keydown.esc="showDropdown = false"
          />
          <button
            type="button"
            class="ms-btn ghost"
            :disabled="fetchingModels"
            @click="handleFetchModels"
          >
            {{ fetchingModels ? '获取中…' : '获取模型列表' }}
          </button>
          <!-- 自定义可滚动下拉（替代原生 datalist，支持大量模型滚动） -->
          <div v-if="showDropdown && availableModels.length" class="ms-model-dropdown">
            <div class="ms-model-dropdown-list">
              <div
                v-for="m in filteredModels"
                :key="m"
                class="ms-model-option"
                @mousedown.prevent
                @click="selectModel(m)"
              >{{ m }}</div>
              <div v-if="!filteredModels.length" class="ms-model-empty">没有匹配的模型</div>
            </div>
            <div class="ms-model-dropdown-footer">共 {{ availableModels.length }} 个模型，显示 {{ filteredModels.length }} 个</div>
          </div>
        </div>
        <small v-if="availableModels.length" class="ms-hint">
          已拉取 {{ availableModels.length }} 个模型，点击输入框展开列表，可输入关键字过滤。
        </small>
      </label>

      <label class="ms-field">
        <span class="ms-label">接口地址（Base URL）</span>
        <input v-model="form.baseUrl" type="text" placeholder="https://.../v1" />
      </label>

      <label class="ms-field">
        <span class="ms-label">API Key</span>
        <input
          v-model="form.apiKey"
          type="password"
          autocomplete="new-password"
          :placeholder="keyPlaceholder"
        />
        <small class="ms-hint">
          所有供应商均通过 OpenAI 兼容接口调用；API Key 加密存储，留空表示不修改已保存的 Key。
        </small>
      </label>

      <div class="ms-actions">
        <button type="button" class="ms-btn secondary" :disabled="testing || saving" @click="handleTest">
          {{ testing ? '测试中…' : '测试连接' }}
        </button>
        <button type="submit" class="ms-btn primary" :disabled="saving">
          {{ saving ? '保存中…' : '保存并生效' }}
        </button>
      </div>

      <div v-if="testResult" class="ms-result" :class="testResult.ok ? 'ok' : 'fail'">
        <span>{{ testResult.ok ? '✓ ' : '✕ ' }}{{ testResult.message }}</span>
        <span v-if="testResult.latency_ms != null" class="ms-latency">{{ testResult.latency_ms }} ms</span>
      </div>

      <div v-if="saveMsg" class="ms-result ok">
        <span>✓ {{ saveMsg }}</span>
      </div>
      <div v-if="errorMsg" class="ms-result fail">
        <span>✕ {{ errorMsg }}</span>
      </div>
    </form>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, reactive, ref } from 'vue';
import { getLlmConfig, saveLlmConfig, testLlmConfig, fetchLlmModels } from '../services/api';

const loading = ref(true);
const testing = ref(false);
const saving = ref(false);
const fetchingModels = ref(false);
const providers = ref([]);
const config = ref(null);
const providerConfigs = ref({}); // 各供应商已保存的配置（脱敏）
const availableModels = ref([]);
const showDropdown = ref(false);
const modelFieldRef = ref(null);

const form = reactive({
  provider: 'dashscope',
  model: '',
  baseUrl: '',
  apiKey: ''
});

const testResult = ref(null);
const saveMsg = ref('');
const errorMsg = ref('');

const currentProviderName = computed(() => {
  const p = providers.value.find((x) => x.id === config.value?.provider);
  return p?.name || config.value?.provider || '';
});

// 当前选中供应商是否已保存 Key（反映表单所选，而非全局生效）
const selectedKeyConfig = computed(() => providerConfigs.value[form.provider] || null);

const keyPlaceholder = computed(() =>
  selectedKeyConfig.value?.has_api_key
    ? `已配置 ${selectedKeyConfig.value.api_key_masked}，留空则不修改`
    : '请输入 API Key'
);

// 根据输入框内容实时过滤模型列表（不区分大小写）
const filteredModels = computed(() => {
  const q = (form.model || '').trim().toLowerCase();
  if (!q) return availableModels.value;
  return availableModels.value.filter((m) => m.toLowerCase().includes(q));
});

function selectModel(m) {
  form.model = m;
  showDropdown.value = false;
}

function handleDocClick(e) {
  if (modelFieldRef.value && !modelFieldRef.value.contains(e.target)) {
    showDropdown.value = false;
  }
}

async function load() {
  loading.value = true;
  try {
    const data = await getLlmConfig();
    config.value = data;
    providers.value = data.providers || [];
    providerConfigs.value = data.provider_configs || {};
    form.provider = data.provider;
    form.model = data.model;
    form.baseUrl = data.base_url;
    form.apiKey = '';
  } catch (e) {
    errorMsg.value = e.message;
  } finally {
    loading.value = false;
  }
}

function handleProviderChange() {
  const p = providers.value.find((x) => x.id === form.provider);
  if (!p) return;
  // 切换供应商时：优先带出该供应商已保存的 model/base_url，否则用预设默认值
  const saved = providerConfigs.value[form.provider];
  form.baseUrl = (saved && saved.base_url) || p.base_url;
  form.model = (saved && saved.model) || p.default_model;
  // 换供应商后输入框留空，Key 状态由 placeholder 反映该供应商是否已配置
  form.apiKey = '';
  availableModels.value = [];
  showDropdown.value = false;
  testResult.value = null;
}

async function handleFetchModels() {
  fetchingModels.value = true;
  availableModels.value = [];
  // 清空模型名称输入，避免之前的输入过滤/影响新拉取的列表
  form.model = '';
  errorMsg.value = '';
  try {
    const data = await fetchLlmModels({
      provider: form.provider,
      baseUrl: form.baseUrl,
      apiKey: form.apiKey
    });
    if (data.ok && Array.isArray(data.models) && data.models.length) {
      availableModels.value = data.models;
      errorMsg.value = '';
      // 拉取成功后展开下拉，展示全部模型（输入框为空不过滤）
      showDropdown.value = true;
    } else {
      errorMsg.value = data.message || '未获取到模型列表，请确认供应商 / Base URL / API Key。';
    }
  } catch (e) {
    errorMsg.value = e.message;
  } finally {
    fetchingModels.value = false;
  }
}

async function handleTest() {
  testing.value = true;
  testResult.value = null;
  errorMsg.value = '';
  try {
    testResult.value = await testLlmConfig({
      provider: form.provider,
      model: form.model,
      baseUrl: form.baseUrl,
      apiKey: form.apiKey
    });
  } catch (e) {
    testResult.value = { ok: false, message: e.message };
  } finally {
    testing.value = false;
  }
}

async function handleSave() {
  saving.value = true;
  saveMsg.value = '';
  errorMsg.value = '';
  try {
    const data = await saveLlmConfig({
      provider: form.provider,
      model: form.model,
      baseUrl: form.baseUrl,
      apiKey: form.apiKey
    });
    config.value = data;
    providerConfigs.value = data.provider_configs || {};
    form.apiKey = '';
    saveMsg.value = '配置已保存，所有 Agent 已热重载，下一轮对话即使用新模型。';
  } catch (e) {
    errorMsg.value = e.message;
  } finally {
    saving.value = false;
  }
}

onMounted(() => {
  load();
  document.addEventListener('click', handleDocClick);
});
onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocClick);
});
</script>

<style scoped>
.model-settings-page {
  max-width: 720px;
  margin: 0 auto;
  padding: 32px 24px 64px;
}
.ms-header h2 {
  margin: 0 0 8px;
  font-size: 24px;
}
.ms-header p {
  margin: 0 0 24px;
  color: var(--color-text-2);
  line-height: 1.6;
}
.ms-loading {
  color: var(--color-text-2);
}
.ms-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 24px;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.ms-current {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  background: var(--color-primary-soft);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 12px 14px;
  font-size: 14px;
}
.ms-badge {
  background: var(--color-primary);
  color: #fff;
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 12px;
}
.ms-key-state {
  margin-left: auto;
  color: var(--color-warning);
}
.ms-key-state.ok {
  color: var(--color-success);
}
.ms-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ms-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}
.ms-field input,
.ms-field select {
  padding: 10px 12px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  font-size: 14px;
  outline: none;
}
.ms-model-row {
  position: relative;
  display: flex;
  gap: 8px;
  align-items: center;
}
.ms-model-row input {
  flex: 1;
}
.ms-model-dropdown {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  right: 0;
  z-index: 50;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}
.ms-model-dropdown-list {
  max-height: 320px;
  overflow-y: auto;
}
.ms-model-option {
  padding: 8px 12px;
  font-size: 13px;
  cursor: pointer;
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ms-model-option:hover {
  background: var(--color-primary-soft);
  color: var(--color-primary-hover);
}
.ms-model-empty {
  padding: 16px 12px;
  color: var(--color-text-3);
  font-size: 13px;
  text-align: center;
}
.ms-model-dropdown-footer {
  padding: 8px 12px;
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-2);
  font-size: 12px;
  color: var(--color-text-2);
}
.ms-btn.ghost {
  background: var(--color-surface-2);
  border: 1px solid var(--color-border);
  color: var(--color-text);
  white-space: nowrap;
  padding: 10px 14px;
}
.ms-btn.ghost:hover:not(:disabled) {
  background: var(--color-border);
}
.ms-field input:focus,
.ms-field select:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(47, 110, 242, 0.15);
}
.ms-hint {
  color: var(--color-text-3);
  font-size: 12px;
}
.ms-actions {
  display: flex;
  gap: 12px;
  margin-top: 4px;
}
.ms-btn {
  padding: 10px 20px;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  border: 1px solid transparent;
}
.ms-btn.primary {
  background: var(--color-primary);
  color: #fff;
}
.ms-btn.secondary {
  background: var(--color-surface);
  border-color: var(--color-border);
  color: var(--color-text);
}
.ms-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.ms-result {
  display: flex;
  align-items: center;
  gap: 12px;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 14px;
}
.ms-result.ok {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: var(--color-success);
}
.ms-result.fail {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: var(--color-error);
}
.ms-latency {
  margin-left: auto;
  color: var(--color-text-2);
}
</style>
