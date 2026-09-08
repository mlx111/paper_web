const STORAGE_PREFIX = 'mypaperweb';

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

function createId(prefix = 'id') {
  if (window.crypto?.randomUUID) {
    return `${prefix}_${window.crypto.randomUUID().replace(/-/g, '')}`;
  }

  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

function getHistoriesStorageKey(moduleName = 'chat') {
  return `${STORAGE_PREFIX}_${moduleName}_histories`;
}

export function createSessionId(prefix = 'session') {
  return createId(prefix);
}

export function createMessageId() {
  return createId('message');
}

export function normalizeMessage(message = {}) {
  const type = message.type || message.role || 'assistant';
  const content = message.content == null ? '' : String(message.content);
  const artifacts = message.artifacts && typeof message.artifacts === 'object' ? message.artifacts : {};

  return {
    id: message.id || createMessageId(),
    type,
    content,
    timestamp: message.timestamp || new Date().toISOString(),
    loading: Boolean(message.loading),
    streaming: Boolean(message.streaming),
    imageMap: message.imageMap || message.image_map || {},
    sources: Array.isArray(message.sources) ? message.sources : [],
    debugEntries: Array.isArray(message.debugEntries) ? message.debugEntries : [],
    artifacts,
    runId: message.runId || message.run_id || '',
    tracePath: message.tracePath || message.trace_path || '',
    traceMeta: message.traceMeta || message.trace_meta || {},
    traceStatus: message.traceStatus || message.trace_status || 'unknown',
    workflowRunId: message.workflowRunId || message.workflow_run_id || '',
    workflowName: message.workflowName || message.workflow_name || '',
    workflowStatus: message.workflowStatus || message.workflow_status || 'unknown',
    workflowSteps: Array.isArray(message.workflowSteps)
      ? message.workflowSteps
      : (Array.isArray(message.workflow_steps) ? message.workflow_steps : []),
    reportPath: message.reportPath || message.report_path || artifacts.report_path || '',
    researchSessionId:
      message.researchSessionId ||
      message.research_session_id ||
      artifacts.research_session_id ||
      artifacts.session_id ||
      '',
    researchStages: Array.isArray(message.researchStages) ? message.researchStages : [],
    researchCandidates: Array.isArray(message.researchCandidates) ? message.researchCandidates : [],
    clarificationCandidates: Array.isArray(message.clarificationCandidates) ? message.clarificationCandidates : [],
    clarificationStatus: message.clarificationStatus || '',
    clarificationSummary: message.clarificationSummary || '',
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
    const content = message?.content == null ? '' : String(message.content);
    return content.trim().length > 0;
  });
}

export function buildChatTitle(messages = []) {
  const normalized = normalizeMessages(messages);
  const userMessage =
    normalized.find((message) => message.type === 'user') ||
    normalized.find((message) => message.content?.trim());
  const seed = userMessage?.content?.trim() || 'New chat';
  const compact = seed.replace(/\s+/g, ' ');
  return compact.length > 24 ? `${compact.slice(0, 24)}...` : compact;
}

export function loadChatHistories(moduleName = 'chat') {
  const raw = window.localStorage.getItem(getHistoriesStorageKey(moduleName));
  const parsed = safeParseJSON(raw, []);

  if (!Array.isArray(parsed)) {
    return [];
  }

  return parsed
    .filter((item) => hasMeaningfulMessages(item?.messages || []))
    .map((item) => ({
      id: item?.id || createSessionId(),
      title: item?.title || 'New chat',
      messages: normalizeMessages(item?.messages || []),
      updatedAt: item?.updatedAt || new Date().toISOString()
    }));
}

export function saveChatHistories(histories = [], moduleName = 'chat') {
  window.localStorage.setItem(getHistoriesStorageKey(moduleName), JSON.stringify(histories));
}

export function upsertChatHistory(histories = [], sessionId, messages = []) {
  const normalizedMessages = normalizeMessages(messages);
  const nextHistory = {
    id: sessionId,
    title: buildChatTitle(normalizedMessages),
    messages: normalizedMessages,
    updatedAt: new Date().toISOString()
  };

  const index = histories.findIndex((history) => history.id === sessionId);
  if (index !== -1) {
    const nextHistories = [...histories];
    nextHistories[index] = nextHistory;
    return nextHistories;
  }
  return [nextHistory, ...histories];
}

export function removeChatHistory(histories = [], sessionId) {
  return histories.filter((history) => history.id !== sessionId);
}

export function buildModuleSessionId(moduleName = 'chat') {
  return createSessionId(`${moduleName}_session`);
}

export function findStoredHistory(histories = [], sessionId) {
  const found = histories.find((history) => history.id === sessionId);
  if (!found) {
    return null;
  }

  return {
    id: found.id,
    title: found.title || 'New chat',
    messages: normalizeMessages(found.messages || []),
    updatedAt: found.updatedAt || new Date().toISOString()
  };
}
