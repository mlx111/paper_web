<template>
  <section class="materials-panel">
    <header class="materials-panel__header">
      <div>
        <h3>素材</h3>
        <p>{{ materials.length }} 项</p>
      </div>
      <button class="ghost-button" type="button" :disabled="loading" @click="refreshMaterials">刷新</button>
    </header>

    <div class="materials-panel__grid">
      <div class="materials-panel__card">
        <label>
          来源
          <select v-model="sourceType">
            <option value="paste">粘贴</option>
            <option value="link">链接</option>
          </select>
        </label>

        <label>
          类型
          <select v-model="materialType">
            <option value="text">文本</option>
            <option value="link">链接</option>
          </select>
        </label>

        <label>
          标题
          <input v-model="title" type="text" placeholder="可选" />
        </label>

        <label>
          内容
          <textarea v-model="content" rows="4" placeholder="粘贴要点或摘要"></textarea>
        </label>

        <label>
          URL
          <input v-model="url" type="url" placeholder="https://..." />
        </label>

        <label>
          标签
          <input v-model="tags" type="text" placeholder="逗号分隔" />
        </label>

        <div class="materials-panel__actions">
          <button class="primary-button" type="button" :disabled="saving || loading" @click="saveTextMaterial">
            保存
          </button>
        </div>
      </div>

      <div class="materials-panel__card">
        <label>
          文件
          <input type="file" :disabled="uploading || loading" @change="handleFileSelect" />
        </label>

        <div class="materials-panel__upload-meta">
          <span>{{ selectedFileName || '未选择文件' }}</span>
          <button class="primary-button" type="button" :disabled="uploading || !selectedFile" @click="uploadSelectedFile">
            上传
          </button>
        </div>

        <div class="materials-panel__list">
          <article v-for="material in materials" :key="material.material_id" class="materials-panel__item">
            <strong>{{ material.title || material.url || '未命名素材' }}</strong>
            <span>{{ material.material_type }} · {{ material.source_type }}</span>
            <p>{{ material.content || material.url || material.file_path || ' ' }}</p>
          </article>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import {
  loadPresentationMaterials,
  savePresentationMaterials,
  uploadPresentationMaterial,
} from '../services/api.js';

const props = defineProps({
  sessionId: {
    type: String,
    required: true,
  },
});

const materials = ref([]);
const loading = ref(false);
const saving = ref(false);
const uploading = ref(false);
const sourceType = ref('paste');
const materialType = ref('text');
const title = ref('');
const content = ref('');
const url = ref('');
const tags = ref('');
const selectedFile = ref(null);

const selectedFileName = computed(() => selectedFile.value?.name || '');

function normalizeMaterials(payload) {
  if (!payload || typeof payload !== 'object') {
    return [];
  }
  if (Array.isArray(payload.materials)) {
    return payload.materials;
  }
  return [];
}

async function refreshMaterials() {
  if (!props.sessionId) {
    materials.value = [];
    return;
  }
  loading.value = true;
  try {
    const result = await loadPresentationMaterials(props.sessionId);
    materials.value = normalizeMaterials(result?.data || result);
  } catch {
    materials.value = [];
  } finally {
    loading.value = false;
  }
}

async function saveTextMaterial() {
  if (!props.sessionId) {
    return;
  }
  saving.value = true;
  try {
    const payload = {
      sourceType: sourceType.value,
      materialType: materialType.value,
      title: title.value.trim() || undefined,
      content: content.value.trim() || undefined,
      url: url.value.trim() || undefined,
      tags: tags.value
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
    };
    await savePresentationMaterials({
      sessionId: props.sessionId,
      materials: [payload],
    });
    title.value = '';
    content.value = '';
    url.value = '';
    tags.value = '';
    await refreshMaterials();
  } finally {
    saving.value = false;
  }
}

function handleFileSelect(event) {
  selectedFile.value = event?.target?.files?.[0] || null;
}

async function uploadSelectedFile() {
  if (!props.sessionId || !selectedFile.value) {
    return;
  }
  uploading.value = true;
  try {
    await uploadPresentationMaterial(selectedFile.value, props.sessionId);
    selectedFile.value = null;
    await refreshMaterials();
  } finally {
    uploading.value = false;
  }
}

watch(
  () => props.sessionId,
  () => {
    refreshMaterials();
  },
  { immediate: true },
);
</script>

<style scoped>
.materials-panel {
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.92);
  padding: 16px;
  display: grid;
  gap: 14px;
}

.materials-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.materials-panel__header h3 {
  margin: 0;
  font-size: 15px;
  line-height: 1.2;
}

.materials-panel__header p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 12px;
}

.materials-panel__grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
}

.materials-panel__card {
  display: grid;
  gap: 10px;
  padding: 14px;
  border-radius: 12px;
  background: #ffffff;
  border: 1px solid rgba(148, 163, 184, 0.22);
}

.materials-panel__card label {
  display: grid;
  gap: 6px;
  font-size: 12px;
  color: #334155;
}

.materials-panel__card input,
.materials-panel__card textarea,
.materials-panel__card select {
  width: 100%;
  border: 1px solid rgba(148, 163, 184, 0.38);
  border-radius: 10px;
  padding: 10px 12px;
  font: inherit;
  background: #fff;
  color: #0f172a;
}

.materials-panel__card textarea {
  resize: vertical;
  min-height: 92px;
}

.materials-panel__actions,
.materials-panel__upload-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.materials-panel__list {
  display: grid;
  gap: 10px;
  max-height: 240px;
  overflow: auto;
}

.materials-panel__item {
  border-radius: 10px;
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid rgba(148, 163, 184, 0.2);
  display: grid;
  gap: 4px;
}

.materials-panel__item strong {
  font-size: 13px;
  color: #0f172a;
}

.materials-panel__item span,
.materials-panel__item p {
  margin: 0;
  font-size: 12px;
  color: #64748b;
  word-break: break-word;
}

.ghost-button,
.primary-button {
  border-radius: 10px;
  border: 1px solid transparent;
  padding: 9px 14px;
  font: inherit;
  cursor: pointer;
}

.ghost-button {
  background: #ffffff;
  border-color: rgba(148, 163, 184, 0.4);
  color: #334155;
}

.primary-button {
  background: #1d4ed8;
  color: #ffffff;
}

.ghost-button:disabled,
.primary-button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

@media (max-width: 1100px) {
  .materials-panel__grid {
    grid-template-columns: 1fr;
  }
}
</style>
