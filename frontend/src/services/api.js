const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

function buildUrl(path) {
  return `${API_BASE}${path}`;
}

function getErrorMessage(error, fallback) {
  return error?.message || fallback;
}

function parseMaybeJson(rawValue) {
  if (rawValue == null) {
    return rawValue;
  }

  if (typeof rawValue !== 'string') {
    return rawValue;
  }

  try {
    return JSON.parse(rawValue);
  } catch {
    return rawValue;
  }
}

async function consumeSseResponse(response, onEvent) {
  if (!response.body) {
    throw new Error('Response does not include a readable stream.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let eventName = 'message';
  let dataLines = [];

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        if (dataLines.length > 0) {
          const rawData = dataLines.join('\n');
          const payload = parseMaybeJson(rawData);
          await onEvent?.({ event: eventName, rawData, data: payload });
        }
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const rawLine of lines) {
        const line = rawLine.replace(/\r$/, '');

        if (!line) {
          if (dataLines.length > 0) {
            const rawData = dataLines.join('\n');
            dataLines = [];
            const payload = parseMaybeJson(rawData);
            await onEvent?.({ event: eventName, rawData, data: payload });
          }
          eventName = 'message';
          continue;
        }

        if (line.startsWith('event:')) {
          eventName = line.slice(6).trim() || 'message';
          continue;
        }

        if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trimStart());
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

async function postJson(path, body) {
  const response = await fetch(buildUrl(path), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    throw new Error(`HTTP error: ${response.status}`);
  }

  const payload = await response.json();
  if (payload?.code !== 200) {
    throw new Error(payload?.message || 'Request failed');
  }

  return payload?.data || {};
}

async function postStream(path, body, onEvent) {
  const response = await fetch(buildUrl(path), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream'
    },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    throw new Error(`HTTP error: ${response.status}`);
  }

  await consumeSseResponse(response, async ({ data }) => {
    const payload = typeof data === 'string' ? parseMaybeJson(data) : data;
    await onEvent?.(payload);
  });
}

async function getJson(path) {
  const response = await fetch(buildUrl(path));

  if (!response.ok) {
    throw new Error(`HTTP error: ${response.status}`);
  }

  return response.json();
}

async function postFormData(path, formData) {
  const response = await fetch(buildUrl(path), {
    method: 'POST',
    body: formData
  });

  if (!response.ok) {
    throw new Error(`HTTP error: ${response.status}`);
  }

  return response.json();
}

export async function sendQuickChat({ sessionId, question }) {
  try {
    return await postJson('/agent/chat', {
      id: sessionId,
      question
    });
  } catch (error) {
    throw new Error(getErrorMessage(error, 'Quick chat failed.'));
  }
}

export async function streamChat({ sessionId, question, onEvent }) {
  try {
    await postStream('/agent/chat_stream', {
      id: sessionId,
      question
    }, onEvent);
  } catch (error) {
    throw new Error(getErrorMessage(error, 'Quick chat streaming failed.'));
  }
}

export async function loadSessionHistory(sessionId) {
  try {
    return await getJson(`/agent/chat/session/${encodeURIComponent(sessionId)}`);
  } catch (error) {
    throw new Error(getErrorMessage(error, 'Failed to load chat session history.'));
  }
}

export async function clearChatSession(sessionId) {
  try {
    return await postJson('/agent/chat/clear', {
      sessionId
    });
  } catch (error) {
    throw new Error(getErrorMessage(error, 'Failed to clear chat session.'));
  }
}

export async function sendResearchChat({ sessionId, question }) {
  try {
    return await postJson('/research/chat', {
      id: sessionId,
      question
    });
  } catch (error) {
    throw new Error(getErrorMessage(error, 'Research chat failed.'));
  }
}

export async function streamResearchChat({ sessionId, question, onEvent }) {
  try {
    await postStream('/research/chat_stream', {
      id: sessionId,
      question
    }, onEvent);
  } catch (error) {
    throw new Error(getErrorMessage(error, 'Research streaming failed.'));
  }
}

export async function loadResearchSessionHistory(sessionId) {
  try {
    return await getJson(`/research/session/${encodeURIComponent(sessionId)}`);
  } catch (error) {
    throw new Error(getErrorMessage(error, 'Failed to load research session history.'));
  }
}

export async function clearResearchSession(sessionId) {
  try {
    return await postJson('/research/clear', {
      sessionId
    });
  } catch (error) {
    throw new Error(getErrorMessage(error, 'Failed to clear research session.'));
  }
}

export async function sendFileChat({ sessionId, question }) {
  try {
    return await postJson('/file/chat', {
      id: sessionId,
      question
    });
  } catch (error) {
    throw new Error(getErrorMessage(error, 'File chat failed.'));
  }
}

export async function streamFileChat({ sessionId, question, onEvent }) {
  try {
    await postStream('/file/chat_stream', {
      id: sessionId,
      question
    }, onEvent);
  } catch (error) {
    throw new Error(getErrorMessage(error, 'File streaming failed.'));
  }
}

export async function loadFileSessionHistory(sessionId) {
  try {
    return await getJson(`/file/session/${encodeURIComponent(sessionId)}`);
  } catch (error) {
    throw new Error(getErrorMessage(error, 'Failed to load file session history.'));
  }
}

export async function clearFileSession(sessionId) {
  try {
    return await postJson('/file/clear', {
      sessionId
    });
  } catch (error) {
    throw new Error(getErrorMessage(error, 'Failed to clear file session.'));
  }
}

export async function uploadFile(file) {
  try {
    const formData = new FormData();
    formData.append('file', file);
    return await postFormData('/file/upload', formData);
  } catch (error) {
    throw new Error(getErrorMessage(error, 'File upload failed.'));
  }
}
