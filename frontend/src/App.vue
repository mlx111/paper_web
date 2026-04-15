<template>
  <div class="app-layout">
    <Sidebar
      :histories="chatHistories"
      :active-session-id="sessionId"
      @new-chat="startNewChat()"
      @select-history="selectHistory"
      @delete-history="deleteHistory"
    />

    <main class="main-content">
      <ChatWindow :messages="currentMessages" :centered="centered">
        <template #input>
          <ChatInput
            v-model="messageInput"
            :mode="currentMode"
            :disabled="isStreaming"
            :is-streaming="isStreaming"
            @send="sendMessage"
            @mode-change="setMode"
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
  loadSessionHistory,
  sendQuickChat,
  streamChat,
  uploadFile,
} from './services/api.js';
import {
  createMessageId,
  createSessionId,
  findStoredHistory,
  hasMeaningfulMessages,
  loadChatHistories,
  normalizeMessage,
  normalizeMessages,
  removeChatHistory,
  saveChatHistories,
  upsertChatHistory,
} from './utils/session.js';

const ALLOWED_FILE_EXTENSIONS = ['.txt', '.md', '.markdown', '.pdf', '.doc', '.docx', '.xls', '.xlsx'];
const MAX_FILE_SIZE = 50 * 1024 * 1024;

const sessionId = ref(createSessionId());
const currentMode = ref('quick');
const messageInput = ref('');
const currentMessages = ref([]);
const chatHistories = ref(loadChatHistories());
const isStreaming = ref(false);
const notifications = ref([]);
const overlay = reactive({
  visible: false,
  title: '正在处理...',
  subtitle: '请稍候...'
});

const centered = computed(() => currentMessages.value.length === 0);

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

function setOverlay(visible, title = '正在处理...', subtitle = '请稍候...') {
  overlay.visible = visible;
  overlay.title = title;
  overlay.subtitle = subtitle;
}

function persistCurrentConversation() {
  if (!hasMeaningfulMessages(currentMessages.value)) {
    return;
  }

  chatHistories.value = upsertChatHistory(chatHistories.value, sessionId.value, currentMessages.value);
  saveChatHistories(chatHistories.value);
}

function appendMessage(payload) {
  const message = normalizeMessage({
    id: payload?.id || createMessageId(),
    type: payload?.type || 'assistant',
    content: payload?.content || '',
    timestamp: payload?.timestamp || new Date().toISOString(),
    loading: Boolean(payload?.loading),
    streaming: Boolean(payload?.streaming),
  });
  currentMessages.value.push(message);
  return message.id;
}

function updateMessage(messageId, updater) {
  const index = currentMessages.value.findIndex((item) => item.id === messageId);
  if (index === -1) {
    return null;
  }

  const previous = currentMessages.value[index];
  const patch = typeof updater === 'function' ? updater({ ...previous }) : updater;
  const next = normalizeMessage({
    ...previous,
    ...(patch || {}),
    id: previous.id,
  });
  currentMessages.value[index] = next;
  return next;
}

function startNewChat({ preserveCurrent = true } = {}) {
  if (preserveCurrent) {
    persistCurrentConversation();
  }

  sessionId.value = createSessionId();
  messageInput.value = '';
  currentMessages.value = [];
}

function setMode(nextMode) {
  currentMode.value = nextMode;
}

async function selectHistory(historyId) {
  if (isStreaming.value || historyId === sessionId.value) {
    return;
  }

  const localHistory = findStoredHistory(chatHistories.value, historyId);
  if (!localHistory) {
    showNotification('未找到该会话记录', 'error');
    return;
  }

  persistCurrentConversation();

  try {
    const backendHistory = await loadSessionHistory(historyId);
    sessionId.value = historyId;

    const backendMessages = Array.isArray(backendHistory?.history) ? backendHistory.history : [];
    const nextMessages = hasMeaningfulMessages(backendMessages)
      ? backendMessages
      : (localHistory.messages || []);

    currentMessages.value = normalizeMessages(nextMessages);
  } catch (error) {
    sessionId.value = historyId;
    const fallbackMessages = hasMeaningfulMessages(localHistory.messages || []) ? localHistory.messages : [];
    currentMessages.value = normalizeMessages(fallbackMessages);
    showNotification(`已使用本地缓存加载会话：${error.message}`, 'warning');
  }
}

async function deleteHistory(historyId) {
  if (isStreaming.value) {
    showNotification('请等待当前操作完成后再删除会话', 'warning');
    return;
  }

  try {
    await clearChatSession(historyId);
    chatHistories.value = removeChatHistory(chatHistories.value, historyId);
    saveChatHistories(chatHistories.value);

    if (sessionId.value === historyId) {
      startNewChat({ preserveCurrent: false });
    }

    showNotification('会话已删除', 'success');
  } catch (error) {
    showNotification(`删除会话失败：${error.message}`, 'error');
  }
}

async function sendQuickMessage(question) {
  const loadingId = appendMessage({
    type: 'assistant',
    content: '正在思考...',
    loading: true,
  });

  try {
    const response = await sendQuickChat({
      sessionId: sessionId.value,
      question,
    });
    const answer = response?.answer || '（无回复内容）';
    updateMessage(loadingId, {
      content: answer,
      loading: false,
      streaming: false,
    });
    persistCurrentConversation();
  } catch (error) {
    updateMessage(loadingId, {
      content: `抱歉，快速对话失败：${error.message}`,
      loading: false,
      streaming: false,
    });
    persistCurrentConversation();
    showNotification(`快速对话失败：${error.message}`, 'error');
  }
}

async function sendStreamMessage(question) {
  const assistantId = appendMessage({
    type: 'assistant',
    content: '',
    streaming: true,
  });

  let fullResponse = '';

  try {
    await streamChat({
      sessionId: sessionId.value,
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

        if (payload.type === 'done') {
          const answer = payload.data?.answer || fullResponse || '（无回复内容）';
          fullResponse = answer;
          updateMessage(assistantId, {
            content: answer,
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
      content: fullResponse || '（无回复内容）',
      streaming: false,
    });
    persistCurrentConversation();
  } catch (error) {
    updateMessage(assistantId, {
      content: `抱歉，流式对话失败：${error.message}`,
      streaming: false,
    });
    persistCurrentConversation();
    showNotification(`流式对话失败：${error.message}`, 'error');
  }
}

async function sendMessage() {
  const question = messageInput.value.trim();
  if (!question || isStreaming.value) {
    return;
  }

  appendMessage({
    type: 'user',
    content: question,
  });
  persistCurrentConversation();
  messageInput.value = '';
  isStreaming.value = true;

  try {
    if (currentMode.value === 'quick') {
      await sendQuickMessage(question);
    } else {
      await sendStreamMessage(question);
    }
  } finally {
    isStreaming.value = false;
  }
}

async function uploadDocument(file) {
  if (!file) {
    return;
  }

  const fileName = file.name || '';
  const lowerName = fileName.toLowerCase();
  const validExtension = ALLOWED_FILE_EXTENSIONS.some((extension) => lowerName.endsWith(extension));
  if (!validExtension) {
    showNotification('只支持 TXT、Markdown、PDF、DOC、DOCX、XLS、XLSX 文件', 'error');
    return;
  }

  if (file.size > MAX_FILE_SIZE) {
    showNotification('文件大小不能超过 50MB', 'error');
    return;
  }

  isStreaming.value = true;
  setOverlay(true, '正在上传文件...', fileName ? `上传：${fileName}` : '请稍候...');

  try {
    const result = await uploadFile(file);
    if (result?.code === 200 || result?.message === 'success' || result?.data) {
      appendMessage({
        type: 'assistant',
        content: `${fileName} 上传到知识库成功。`,
      });
      persistCurrentConversation();
      showNotification('文件上传成功', 'success');
    } else {
      throw new Error(result?.message || '上传失败');
    }
  } catch (error) {
    showNotification(`文件上传失败：${error.message}`, 'error');
  } finally {
    isStreaming.value = false;
    setOverlay(false);
  }
}
</script>
