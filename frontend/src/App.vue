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
      <ChatWindow :messages="currentMessages" :centered="centered">
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
import Sidebar from './components/Sidebar.vue';
import {
  clearChatSession,
  clearFileSession,
  clearResearchSession,
  loadFileSessionHistory,
  loadResearchSessionHistory,
  loadSessionHistory,
  sendFileChat,
  sendQuickChat,
  sendResearchChat,
  streamChat,
  streamFileChat,
  streamResearchChat,
  uploadFile,
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
const MAX_FILE_SIZE = 50 * 1024 * 1024;

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

async function sendStreamingMessage(question) {
  const assistantId = appendMessage({
    type: 'assistant',
    content: '',
    streaming: true,
  });

  let fullResponse = '';
  let imageMap = {};
  let sources = [];

  try {
    await currentModule.value.sendStream({
      sessionId: currentSessionId.value,
      question,
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

        if (payload.type === 'done' || payload.type === 'complete') {
          const answer = payload.data?.answer || fullResponse || '(no answer)';
          imageMap = payload.data?.image_map || payload.data?.imageMap || imageMap;
          sources = payload.data?.sources || sources;
          fullResponse = answer;
          updateMessage(assistantId, {
            content: answer,
            imageMap,
            sources,
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
</script>
