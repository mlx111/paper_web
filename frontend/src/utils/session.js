const STORAGE_KEY = "mypaperweb_chat_histories";

function safeParseJSON(value, fallback) {
  if (!value) {
    return fallback;
  }

  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function createId(prefix = "id") {
  if (window.crypto?.randomUUID) {
    return `${prefix}_${window.crypto.randomUUID().replace(/-/g, "")}`;
  }

  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

export function createSessionId() {
  return createId("session");
}

export function createMessageId() {
  return createId("message");
}

export function normalizeMessage(message = {}) {
  const type = message.type || message.role || "assistant";
  const content = message.content == null ? "" : String(message.content);

  return {
    id: message.id || createMessageId(),
    type,
    content,
    timestamp: message.timestamp || new Date().toISOString(),
    loading: Boolean(message.loading),
    streaming: Boolean(message.streaming)
  };
}

export function normalizeMessages(messages = []) {
  if (!Array.isArray(messages)) {
    return [];
  }

  return messages.map((message) => normalizeMessage(message));
}

export function hasMeaningfulMessages(messages = []) {
  if (!Array.isArray(messages)) {
    return false;
  }

  return messages.some((message) => {
    const content = message?.content == null ? "" : String(message.content);
    return content.trim().length > 0;
  });
}

export function buildChatTitle(messages = []) {
  const normalized = normalizeMessages(messages);
  const userMessage =
    normalized.find((message) => message.type === "user") ||
    normalized.find((message) => message.content?.trim());
  const seed = userMessage?.content?.trim() || "新对话";
  const compact = seed.replace(/\s+/g, " ");
  return compact.length > 24 ? `${compact.slice(0, 24)}...` : compact;
}

export function loadChatHistories() {
  const raw = window.localStorage.getItem(STORAGE_KEY);
  const parsed = safeParseJSON(raw, []);

  if (!Array.isArray(parsed)) {
    return [];
  }

  return parsed
    .filter((item) => hasMeaningfulMessages(item?.messages || []))
    .map((item) => ({
      id: item?.id || createSessionId(),
      title: item?.title || "新对话",
      messages: normalizeMessages(item?.messages || []),
      updatedAt: item?.updatedAt || new Date().toISOString()
    }))
    .sort((left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime());
}

export function saveChatHistories(histories = []) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(histories));
}

export function upsertChatHistory(histories = [], sessionId, messages = []) {
  const normalizedMessages = normalizeMessages(messages);
  const nextHistory = {
    id: sessionId,
    title: buildChatTitle(normalizedMessages),
    messages: normalizedMessages,
    updatedAt: new Date().toISOString()
  };

  const nextHistories = histories.filter((history) => history.id !== sessionId);
  nextHistories.unshift(nextHistory);
  return nextHistories;
}

export function removeChatHistory(histories = [], sessionId) {
  return histories.filter((history) => history.id !== sessionId);
}

export function findStoredHistory(histories = [], sessionId) {
  const found = histories.find((history) => history.id === sessionId);
  if (!found) {
    return null;
  }

  return {
    id: found.id,
    title: found.title || "新对话",
    messages: normalizeMessages(found.messages || []),
    updatedAt: found.updatedAt || new Date().toISOString()
  };
}