<template>
  <div class="app-layout">
    <Sidebar
      :modules="MODULES"
      :active-module="activeModule"
      :histories="currentHistories"
      :active-session-id="currentSessionId"
      @select-module="switchModule"
      @new-chat="startNewChat()"
      @select-history="selectHistory"
      @delete-history="deleteHistory"
    />

    <main class="main-content">
      <details v-if="activeModule === 'presentation'" class="presentation-materials-accordion">
        <summary class="presentation-materials-summary">
          <span class="presentation-materials-summary-title">素材</span>
          <span class="presentation-materials-summary-hint">上传文件、粘贴要点或链接，默认折叠，不打断对话</span>
        </summary>
        <PresentationMaterialsPanel
          :session-id="currentSessionId"
        />
      </details>

      <ChatWindow
        :messages="currentMessages"
        :centered="centered"
        @request-presentation="generatePresentationFromResearch"
        @request-research-quality="checkResearchQuality"
        @request-research-regenerate="regenerateResearchReport"
        @candidate-selected="handleCandidateSelected"
      >
        <template #input>
          <ChatInput
            v-model="messageInput"
            :module-label="currentModule.label"
            :module-hint="currentModule.hint"
            :placeholder="currentModule.placeholder"
            :allow-upload="currentModule.allowUpload"
            :use-streaming="currentUseStreaming"
            :disabled="isStreaming"
            :is-streaming="isStreaming"
            @update:use-streaming="currentUseStreaming = $event"
            @send="sendMessage"
            @upload-file="uploadDocument"
            @upload-temp-file="uploadTempDocument"
          />
        </template>
      </ChatWindow>
    </main>

    <LoadingOverlay
      :visible="overlay.visible"
      :title="overlay.title"
      :subtitle="overlay.subtitle"
    />

    <NotificationToast :notifications="notifications" />
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue';
import ChatInput from './components/ChatInput.vue';
import ChatWindow from './components/ChatWindow.vue';
import LoadingOverlay from './components/LoadingOverlay.vue';
import NotificationToast from './components/NotificationToast.vue';
import PresentationMaterialsPanel from './components/PresentationMaterialsPanel.vue';
import Sidebar from './components/Sidebar.vue';
import {
  clearChatSession,
  clearFileSession,
  clearPresentationSession,
  clearResearchSession,
  checkPresentationQuality as requestPresentationQuality,
  confirmResearchCandidate,
  loadFileSessionHistory,
  loadPresentationSessionHistory,
  loadResearchSessionHistory,
  loadSessionHistory,
  checkResearchQuality as requestResearchQuality,
  regenerateResearchReport as requestResearchReportRegeneration,
  prepareResearchRerun,
  sendFileChat,
  sendPresentationChat,
  sendQuickChat,
  sendResearchChat,
  streamChat,
  streamFileChat,
  streamPresentationChat,
  streamResearchChat,
  uploadFile,
  uploadTempFile,
} from './services/api.js';
import {
  buildModuleSessionId,
  createMessageId,
  findStoredHistory,
  hasMeaningfulMessages,
  loadChatHistories as loadLocalHistories,
  normalizeMessage,
  normalizeMessages,
  removeChatHistory,
  saveChatHistories,
  upsertChatHistory,
} from './utils/session.js';

const ALLOWED_FILE_EXTENSIONS = ['.txt', '.md', '.markdown', '.pdf', '.doc', '.docx', '.xls', '.xlsx'];
const ALLOWED_TEMP_FILE_EXTENSIONS = ['.txt', '.md', '.markdown', '.pdf', '.docx', '.html', '.htm'];
const MAX_FILE_SIZE = 50 * 1024 * 1024;
const MAX_TEMP_FILE_SIZE = 20 * 1024 * 1024;

const MODULES = [
  {
    key: 'chat',
    label: '智能问答',
    description: '日常问题与快速回答',
    hint: '快速回答',
    placeholder: '请输入你的问题',
    allowUpload: false,
    loadHistory: loadSessionHistory,
    clearSession: clearChatSession,
    sendSingle: sendQuickChat,
    sendStream: streamChat,
    defaultStreaming: false,
  },
  {
    key: 'file',
    label: '文档问答',
    description: '基于上传文件提问',
    hint: 'RAG 检索增强',
    placeholder: '询问上传文档中的内容',
    allowUpload: true,
    loadHistory: loadFileSessionHistory,
    clearSession: clearFileSession,
    sendSingle: sendFileChat,
    sendStream: streamFileChat,
    defaultStreaming: true,
  },
  {
    key: 'research',
    label: '论文研究',
    description: '论文检索与综述分析',
    hint: '研究工作流',
    placeholder: '输入研究问题，例如：机械臂抓取相关论文',
    allowUpload: false,
    loadHistory: loadResearchSessionHistory,
    clearSession: clearResearchSession,
    sendSingle: sendResearchChat,
    sendStream: streamResearchChat,
    defaultStreaming: true,
  },
  {
    key: 'presentation',
    label: 'PPT生成',
    description: '通用主题演示文稿生成',
    hint: '规划 + 讲稿 + 导出',
    placeholder: '输入一个演示主题，例如：企业RAG方案分享',
    allowUpload: false,
    loadHistory: loadPresentationSessionHistory,
    clearSession: clearPresentationSession,
    sendSingle: sendPresentationChat,
    sendStream: streamPresentationChat,
    defaultStreaming: true,
  },
];

const MODULE_MAP = Object.fromEntries(MODULES.map((item) => [item.key, item]));

function createModuleState(moduleKey) {
  const moduleConfig = MODULES.find((item) => item.key === moduleKey);
  return {
    sessionId: buildModuleSessionId(moduleKey),
    messageInput: '',
    currentMessages: [],
    histories: loadLocalHistories(moduleKey),
    isStreaming: false,
    useStreaming: moduleConfig?.defaultStreaming ?? true,
  };
}

const moduleStates = reactive(
  Object.fromEntries(MODULES.map((item) => [item.key, createModuleState(item.key)])),
);

const activeModule = ref('chat');
const notifications = ref([]);
const overlay = reactive({
  visible: false,
  title: '处理中...',
  subtitle: '请稍候...',
});

const currentState = computed(() => moduleStates[activeModule.value]);
const currentModule = computed(() => MODULE_MAP[activeModule.value]);
const currentHistories = computed(() => currentState.value.histories);
const currentMessages = computed(() => currentState.value.currentMessages);
const currentSessionId = computed(() => currentState.value.sessionId);
const isStreaming = computed(() => currentState.value.isStreaming);
const centered = computed(() => currentMessages.value.length === 0);
const currentUseStreaming = computed({
  get() {
    return currentState.value.useStreaming;
  },
  set(value) {
    currentState.value.useStreaming = Boolean(value);
  },
});
const messageInput = computed({
  get() {
    return currentState.value.messageInput;
  },
  set(value) {
    currentState.value.messageInput = value;
  },
});

function createNotification(message, type = 'info') {
  return {
    id: createMessageId(),
    message,
    type,
  };
}

function showNotification(message, type = 'info') {
  const notification = createNotification(message, type);
  notifications.value = [...notifications.value, notification];

  window.setTimeout(() => {
    notifications.value = notifications.value.filter((item) => item.id !== notification.id);
  }, 3000);
}

function setOverlay(visible, title = '处理中...', subtitle = '请稍候...') {
  overlay.visible = visible;
  overlay.title = title;
  overlay.subtitle = subtitle;
}

function persistConversation(moduleKey = activeModule.value) {
  const state = moduleStates[moduleKey];
  if (!state || !hasMeaningfulMessages(state.currentMessages)) {
    return;
  }

  state.histories = upsertChatHistory(state.histories, state.sessionId, state.currentMessages);
  saveChatHistories(state.histories, moduleKey);
}

function appendMessage(payload, moduleKey = activeModule.value) {
  const state = moduleStates[moduleKey];
  const message = normalizeMessage({
    id: payload?.id || createMessageId(),
    type: payload?.type || 'assistant',
    content: payload?.content || '',
    timestamp: payload?.timestamp || new Date().toISOString(),
    loading: Boolean(payload?.loading),
    streaming: Boolean(payload?.streaming),
    imageMap: payload?.imageMap || payload?.image_map || {},
    sources: Array.isArray(payload?.sources) ? payload.sources : [],
    debugEntries: Array.isArray(payload?.debugEntries) ? payload.debugEntries : [],
    artifacts: payload?.artifacts || {},
    reportPath: payload?.reportPath || payload?.report_path || '',
    researchSessionId: payload?.researchSessionId || payload?.research_session_id || '',
  });
  state.currentMessages.push(message);
  return message.id;
}

function updateMessage(messageId, updater, moduleKey = activeModule.value) {
  const state = moduleStates[moduleKey];
  const index = state.currentMessages.findIndex((item) => item.id === messageId);
  if (index === -1) {
    return null;
  }

  const previous = state.currentMessages[index];
  const patch = typeof updater === 'function' ? updater({ ...previous }) : updater;
  const next = normalizeMessage({
    ...previous,
    ...(patch || {}),
    id: previous.id,
  });
  state.currentMessages[index] = next;
  return next;
}

function switchModule(moduleKey) {
  if (!MODULE_MAP[moduleKey] || moduleKey === activeModule.value || isStreaming.value) {
    return;
  }

  persistConversation();
  activeModule.value = moduleKey;
}

function startNewChat({ preserveCurrent = true } = {}) {
  const state = currentState.value;

  if (preserveCurrent) {
    persistConversation();
  }

  state.sessionId = buildModuleSessionId(activeModule.value);
  state.messageInput = '';
  state.currentMessages = [];
}

async function selectHistory(historyId) {
  const state = currentState.value;
  const moduleConfig = currentModule.value;

  if (state.isStreaming || historyId === state.sessionId) {
    return;
  }

  const localHistory = findStoredHistory(state.histories, historyId);
  if (!localHistory) {
    showNotification('未找到该会话。', 'error');
    return;
  }

  persistConversation();

  try {
    const backendHistory = await moduleConfig.loadHistory(historyId);
    state.sessionId = historyId;

    const backendMessages = Array.isArray(backendHistory?.history) ? backendHistory.history : [];
    const nextMessages = hasMeaningfulMessages(backendMessages)
      ? backendMessages
      : (localHistory.messages || []);

    state.currentMessages = normalizeMessages(nextMessages);
  } catch (error) {
    state.sessionId = historyId;
    const fallbackMessages = hasMeaningfulMessages(localHistory.messages || []) ? localHistory.messages : [];
    state.currentMessages = normalizeMessages(fallbackMessages);
    showNotification(`已从本地缓存加载：${error.message}`, 'warning');
  }
}

async function deleteHistory(historyId) {
  const state = currentState.value;
  const moduleConfig = currentModule.value;

  if (state.isStreaming) {
    showNotification('请等待当前操作完成后再删除会话。', 'warning');
    return;
  }

  try {
    await moduleConfig.clearSession(historyId);
    state.histories = removeChatHistory(state.histories, historyId);
    saveChatHistories(state.histories, activeModule.value);

    if (state.sessionId === historyId) {
      startNewChat({ preserveCurrent: false });
    }

    showNotification('会话已删除。', 'success');
  } catch (error) {
    showNotification(`删除会话失败：${error.message}`, 'error');
  }
}

async function sendQuickMessage(question) {
  const loadingId = appendMessage({
    type: 'assistant',
    content: 'Thinking...',
    loading: true,
  });

  try {
    const response = await currentModule.value.sendSingle({
      sessionId: currentSessionId.value,
      question,
    });

    const answer = response?.answer || '(no answer)';
    updateMessage(loadingId, {
      content: answer,
      imageMap: response?.image_map || response?.imageMap || {},
      sources: response?.sources || [],
      loading: false,
      streaming: false,
    });
    persistConversation();
  } catch (error) {
    updateMessage(loadingId, {
      content: `抱歉，请求失败：${error.message}`,
      loading: false,
      streaming: false,
    });
    persistConversation();
    showNotification(`对话失败：${error.message}`, 'error');
  }
}

async function sendStreamingMessage(question, extraRequest = {}) {
  const assistantId = appendMessage({
    type: 'assistant',
    content: '',
    streaming: true,
    debugEntries: [],
  });

  let fullResponse = '';
  let imageMap = {};
  let sources = [];
  let artifacts = {};
  let researchStages = [];

  function formatDebugNodeLabel(nodeName) {
    const mapping = {
      decision_making: '研究判断',
      clarify: '范围澄清',
      refine_query: '目标聚焦',
      expand: '研究分支',
      branch_gather: '分支检索',
      branch_synthesize: '发现汇总',
      planning: '研究计划',
      agent: '研究生成',
      tools: '工具调用',
      judge: '质量检查'
    };
    return mapping[nodeName] || nodeName || '研究阶段';
  }

  function appendDebugEntry(payload) {
    const text = typeof payload?.data === 'string' ? payload.data.trim() : '';
    if (!text) {
      return;
    }

    updateMessage(assistantId, (previous) => {
      const existing = Array.isArray(previous.debugEntries) ? previous.debugEntries : [];
      return {
        debugEntries: [
          ...existing,
          {
            id: `${payload?.node || 'debug'}-${existing.length + 1}`,
            node: payload?.node || 'debug',
            nodeLabel: formatDebugNodeLabel(payload?.node),
            text
          }
        ],
        streaming: true
      };
    });
  }

  try {
    await currentModule.value.sendStream({
      sessionId: currentSessionId.value,
      question,
      ...extraRequest,
      onEvent(payload) {
        if (!payload || typeof payload !== 'object') {
          return;
        }

        if (payload.type === 'content') {
          fullResponse += payload.data || '';
          updateMessage(assistantId, {
            content: fullResponse,
            streaming: true,
          });
          return;
        }

        if (payload.type === 'stage') {
          const stageEntry = { stage: payload.stage, status: payload.status };
          const updatedStages = [...researchStages.filter(s => s.stage !== payload.stage), stageEntry];
          researchStages = updatedStages;
          updateMessage(assistantId, {
            researchStages: updatedStages,
            streaming: true,
          });
          return;
        }

        if (payload.type === 'candidates') {
          const data = payload.data || {};
          const candidates = Array.isArray(data.candidates) ? data.candidates : [];
          updateMessage(assistantId, {
            clarificationCandidates: candidates,
            clarificationSummary: data.clarification_summary || data.clarificationSummary || '',
            streaming: false,
          });
          return;
        }

        if (payload.type === 'debug') {
          appendDebugEntry(payload);
          return;
        }

        if (payload.type === 'done' || payload.type === 'complete') {
          const answer = payload.data?.answer || fullResponse || '(no answer)';
          imageMap = payload.data?.image_map || payload.data?.imageMap || imageMap;
          sources = payload.data?.sources || sources;
          artifacts = payload.data?.artifacts || payload.data?.artifact || artifacts;
          researchStages = Array.isArray(payload.data?.research_stages) ? payload.data.research_stages : researchStages;
          fullResponse = answer;
          updateMessage(assistantId, {
            content: answer,
            imageMap,
            sources,
            artifacts,
            researchStages,
            researchCandidates: Array.isArray(payload.data?.research_candidates) ? payload.data.research_candidates : [],
            clarificationStatus: payload.data?.clarification_status || payload.data?.clarificationStatus || '',
            reportPath: payload.data?.report_path || payload.data?.reportPath || artifacts?.report_path || '',
            researchSessionId:
              payload.data?.research_session_id ||
              payload.data?.researchSessionId ||
              artifacts?.research_session_id ||
              artifacts?.session_id ||
              '',
            streaming: false,
          });
          return;
        }

        if (payload.type === 'error') {
          throw new Error(payload.data || payload.message || '流式请求失败');
        }
      },
    });

    updateMessage(assistantId, {
      content: fullResponse || '(no answer)',
      imageMap,
      sources,
      artifacts,
      streaming: false,
    });
    persistConversation();
  } catch (error) {
    updateMessage(assistantId, {
      content: `抱歉，流式响应失败：${error.message}`,
      streaming: false,
    });
    persistConversation();
    showNotification(`流式响应失败：${error.message}`, 'error');
  }
}

async function handleCandidateSelected(payload) {
  const state = currentState.value;
  if (state.isStreaming) {
    return;
  }

  state.isStreaming = true;

  try {
    const result = await confirmResearchCandidate({
      sessionId: currentSessionId.value,
      candidateId: payload.candidateId,
      modifiedQuery: payload.modifiedQuery || null,
    });

    if (!result) {
      showNotification('确认研究方向失败', 'error');
      return;
    }

    appendMessage({
      type: 'user',
      content: `按「${payload.candidateId}」方向进行研究`,
    });
    persistConversation();

    await sendStreamingMessage('按确认方向进行研究');
    showNotification('研究方向已确认，开始研究...', 'success');
  } catch (error) {
    showNotification(`确认研究方向失败：${error.message}`, 'error');
  } finally {
    state.isStreaming = false;
  }
}

async function checkResearchQuality(payload = {}) {
  const artifacts = payload?.artifacts || {};
  const sessionId = payload?.sessionId || artifacts?.session_id || currentSessionId.value;

  if (!sessionId) {
    showNotification('未找到可检查的研究会话。', 'warning');
    return;
  }

  try {
    const report = await requestResearchQuality(sessionId);
    const passed = Boolean(report?.passed);
    const issues = Array.isArray(report?.issues) ? report.issues : [];
    const warnings = Array.isArray(report?.warnings) ? report.warnings : [];
    const summary = passed ? '通过' : '未通过';
    const content = `研究报告质量检查已完成，结果：${summary}。问题 ${issues.length} 项，警告 ${warnings.length} 项。`;
    appendMessage({ type: 'assistant', content, artifacts: { session_id: sessionId, quality_report: report } });
    persistConversation();
    showNotification(`质量检查${passed ? '通过' : '完成'}`, passed ? 'success' : 'warning');
  } catch (error) {
    showNotification(`质量检查失败：${error.message}`, 'error');
  }
}

async function regenerateResearchReport(payload = {}) {
  const artifacts = payload?.artifacts || {};
  const sessionId = payload?.sessionId || artifacts?.session_id || currentSessionId.value;

  if (!sessionId) {
    showNotification('未找到可重新生成的研究会话。', 'warning');
    return;
  }

  const state = currentState.value;
  if (state.isStreaming) {
    return;
  }

  state.isStreaming = true;

  try {
    const prepResult = await prepareResearchRerun(sessionId);
    const question = prepResult?.question || '';

    if (!question) {
      showNotification('未找到原始研究问题。', 'error');
      return;
    }

    appendMessage({ type: 'user', content: '重新生成研究报告' });
    persistConversation();

    await sendStreamingMessage(question);
    showNotification('研究报告已重新生成。', 'success');
  } catch (error) {
    showNotification(`研究报告重新生成失败：${error.message}`, 'error');
  } finally {
    state.isStreaming = false;
  }
}

async function generatePresentationFromResearch(payload = {}) {
  const artifacts = payload?.artifacts || {};
  const researchSessionId =
    payload?.researchSessionId ||
    payload?.research_session_id ||
    artifacts?.research_session_id ||
    artifacts?.session_id ||
    '';

  if (!researchSessionId) {
    showNotification('未找到可用于生成 PPT 的研究会话。', 'warning');
    return;
  }

  const topic =
    payload?.topic ||
    payload?.content ||
    artifacts?.question ||
    '基于本研究生成 PPT';

  activeModule.value = 'presentation';
  const state = currentState.value;

  if (state.isStreaming) {
    return;
  }

  appendMessage(
    {
      type: 'user',
      content: '基于本研究生成 PPT',
    },
    'presentation',
  );
  persistConversation('presentation');
  state.isStreaming = true;

  try {
    await sendStreamingMessage('', {
      researchSessionId,
      topic,
    });
    showNotification('已切换到 PPT 生成。', 'success');
  } finally {
    state.isStreaming = false;
  }
}

async function checkPresentationQuality(payload = {}) {
  const artifacts = payload?.artifacts || {};
  const sessionId = payload?.sessionId || artifacts?.session_id || currentSessionId.value;

  if (!sessionId) {
    showNotification('未找到可检查的 PPT 会话。', 'warning');
    return;
  }

  activeModule.value = 'presentation';
  const state = currentState.value;
  if (state.isStreaming) {
    return;
  }

  const actionLabel = '检查当前 PPT 质量';
  const loadingMessageId = appendMessage(
    {
      type: 'assistant',
      content: '正在检查 PPT 质量...',
      loading: true,
      streaming: true,
      artifacts: {
        session_id: sessionId,
      },
    },
    'presentation',
  );

  persistConversation('presentation');
  state.isStreaming = true;

  try {
    const report = await requestPresentationQuality(sessionId);
    const passed = Boolean(report?.passed);
    const issues = Array.isArray(report?.issues) ? report.issues : [];
    const warnings = Array.isArray(report?.warnings) ? report.warnings : [];
    const summary = passed ? '通过' : '未通过';
    const qualityContent = `PPT 质量检查已完成，结果：${summary}。问题 ${issues.length} 项，警告 ${warnings.length} 项。`;

    updateMessage(loadingMessageId, {
      content: qualityContent,
      loading: false,
      streaming: false,
      artifacts: {
        session_id: sessionId,
        quality_report: report,
        download_urls: {
          quality: `/presentation/download/${encodeURIComponent(sessionId)}/quality`,
          ...(artifacts?.download_urls || artifacts?.downloadUrls || {}),
        },
      },
    }, 'presentation');
    persistConversation('presentation');
    showNotification(actionLabel, 'success');
  } catch (error) {
    updateMessage(
      loadingMessageId,
      {
        content: `PPT 质量检查失败：${error.message}`,
        loading: false,
        streaming: false,
      },
      'presentation',
    );
    persistConversation('presentation');
    showNotification(`PPT 质量检查失败：${error.message}`, 'error');
  } finally {
    state.isStreaming = false;
  }
}

async function regeneratePresentationFromArtifacts(payload = {}) {
  const artifacts = payload?.artifacts || {};
  const sessionId = payload?.sessionId || artifacts?.session_id || currentSessionId.value;

  if (!sessionId) {
    showNotification('未找到可重新生成的 PPT 会话。', 'warning');
    return;
  }

  activeModule.value = 'presentation';
  const state = currentState.value;
  if (state.isStreaming) {
    return;
  }

  const loadingMessageId = appendMessage(
    {
      type: 'assistant',
      content: '正在基于已保存工件重新生成 PPT...',
      loading: true,
      streaming: true,
      artifacts: {
        session_id: sessionId,
      },
    },
    'presentation',
  );

  persistConversation('presentation');
  state.isStreaming = true;

  try {
    const result = await requestPresentationRegeneration(sessionId);
    const responseArtifacts = result?.artifacts || {};
    updateMessage(
      loadingMessageId,
      {
        content: result?.answer || 'PPT 已重新生成。',
        loading: false,
        streaming: false,
        artifacts: {
          ...artifacts,
          ...responseArtifacts,
          session_id: sessionId,
        },
      },
      'presentation',
    );
    persistConversation('presentation');
    showNotification('PPT 已重新生成。', 'success');
  } catch (error) {
    updateMessage(
      loadingMessageId,
      {
        content: `PPT 重新生成失败：${error.message}`,
        loading: false,
        streaming: false,
      },
      'presentation',
    );
    persistConversation('presentation');
    showNotification(`PPT 重新生成失败：${error.message}`, 'error');
  } finally {
    state.isStreaming = false;
  }
}

async function sendMessage() {
  const state = currentState.value;
  const question = state.messageInput.trim();
  if (!question || state.isStreaming) {
    return;
  }

  appendMessage({
    type: 'user',
    content: question,
  });
  persistConversation();
  state.messageInput = '';
  state.isStreaming = true;

  try {
    if (state.useStreaming) {
      await sendStreamingMessage(question);
    } else {
      await sendQuickMessage(question);
    }
  } finally {
    state.isStreaming = false;
  }
}

async function uploadDocument(file) {
  if (!file) {
    return;
  }

  if (activeModule.value !== 'file') {
    showNotification('文件上传仅在“文档问答”模块可用。', 'warning');
    return;
  }

  const fileName = file.name || '';
  const lowerName = fileName.toLowerCase();
  const validExtension = ALLOWED_FILE_EXTENSIONS.some((extension) => lowerName.endsWith(extension));
  if (!validExtension) {
    showNotification('仅支持 TXT、Markdown、PDF、DOC、DOCX、XLS、XLSX 文件。', 'error');
    return;
  }

  if (file.size > MAX_FILE_SIZE) {
    showNotification('文件大小不能超过 50MB。', 'error');
    return;
  }

  currentState.value.isStreaming = true;
  setOverlay(true, '正在上传文件...', fileName ? `正在上传：${fileName}` : '请稍候...');

  try {
    const result = await uploadFile(file);
    if (result?.code === 200 || result?.message === 'success' || result?.data) {
      appendMessage({
        type: 'assistant',
        content: `${fileName} 上传成功。`,
      });
      persistConversation();
      showNotification('文件上传成功。', 'success');
    } else {
      throw new Error(result?.message || '上传失败');
    }
  } catch (error) {
    showNotification(`文件上传失败：${error.message}`, 'error');
  } finally {
    currentState.value.isStreaming = false;
    setOverlay(false);
  }
}

async function uploadTempDocument(file) {
  if (!file) {
    return;
  }

  if (activeModule.value !== 'file') {
    showNotification('临时文件仅在“文档问答”模块可用。', 'warning');
    return;
  }

  const fileName = file.name || '';
  const lowerName = fileName.toLowerCase();
  const validExtension = ALLOWED_TEMP_FILE_EXTENSIONS.some((extension) => lowerName.endsWith(extension));
  if (!validExtension) {
    showNotification('临时解析仅支持 TXT、Markdown、PDF、DOCX、HTML 文件。', 'error');
    return;
  }

  if (file.size > MAX_TEMP_FILE_SIZE) {
    showNotification('临时文件大小不能超过 20MB。', 'error');
    return;
  }

  currentState.value.isStreaming = true;
  setOverlay(true, '正在上传临时文件...', fileName ? `正在上传：${fileName}` : '请稍候...');

  try {
    const result = await uploadTempFile(file, currentSessionId.value);
    if (result?.code === 200 || result?.message === 'success' || result?.data) {
      appendMessage({
        type: 'assistant',
        content: `${fileName} 已作为临时文件上传，可直接让助手解析。`,
      });
      persistConversation();
      showNotification('临时文件上传成功。', 'success');
    } else {
      throw new Error(result?.message || '临时上传失败');
    }
  } catch (error) {
    showNotification(`临时文件上传失败：${error.message}`, 'error');
  } finally {
    currentState.value.isStreaming = false;
    setOverlay(false);
  }
}
</script>
