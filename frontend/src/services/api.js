const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

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

  if (typeof rawValue !== "string") {
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
    throw new Error("响应中没有可读取的数据流");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventName = "message";
  let dataLines = [];

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        if (dataLines.length > 0) {
          const rawData = dataLines.join("\n");
          const payload = parseMaybeJson(rawData);
          await onEvent?.({ event: eventName, rawData, data: payload });
        }
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const rawLine of lines) {
        const line = rawLine.replace(/\r$/, "");

        if (!line) {
          if (dataLines.length > 0) {
            const rawData = dataLines.join("\n");
            dataLines = [];
            const payload = parseMaybeJson(rawData);
            await onEvent?.({ event: eventName, rawData, data: payload });
          }
          eventName = "message";
          continue;
        }

        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim() || "message";
          continue;
        }

        if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trimStart());
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export async function sendQuickChat({ sessionId, question }) {
  try {
    const response = await fetch(buildUrl("/agent/chat"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        id: sessionId,
        question
      })
    });

    if (!response.ok) {
      throw new Error(`HTTP 错误: ${response.status}`);
    }

    const payload = await response.json();
    if (payload?.code !== 200) {
      throw new Error(payload?.message || "请求失败");
    }

    return payload?.data || {};
  } catch (error) {
    throw new Error(getErrorMessage(error, "快速对话失败"));
  }
}

export async function streamChat({ sessionId, question, onEvent }) {
  try {
    const response = await fetch(buildUrl("/agent/chat_stream"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream"
      },
      body: JSON.stringify({
        id: sessionId,
        question
      })
    });

    if (!response.ok) {
      throw new Error(`HTTP 错误: ${response.status}`);
    }

    await consumeSseResponse(response, async ({ data }) => {
      const payload = typeof data === "string" ? parseMaybeJson(data) : data;
      await onEvent?.(payload);
    });
  } catch (error) {
    throw new Error(getErrorMessage(error, "流式对话失败"));
  }
}

export async function loadSessionHistory(sessionId) {
  try {
    const response = await fetch(buildUrl(`/agent/chat/session/${encodeURIComponent(sessionId)}`));

    if (!response.ok) {
      throw new Error(`HTTP 错误: ${response.status}`);
    }

    return response.json();
  } catch (error) {
    throw new Error(getErrorMessage(error, "加载会话失败"));
  }
}

export async function clearChatSession(sessionId) {
  try {
    const response = await fetch(buildUrl("/agent/chat/clear"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        sessionId
      })
    });

    if (!response.ok) {
      throw new Error(`HTTP 错误: ${response.status}`);
    }

    return response.json();
  } catch (error) {
    throw new Error(getErrorMessage(error, "删除会话失败"));
  }
}

export async function uploadFile(file) {
  try {
    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(buildUrl("/file/upload"), {
      method: "POST",
      body: formData
    });

    if (!response.ok) {
      throw new Error(`HTTP 错误: ${response.status}`);
    }

    return response.json();
  } catch (error) {
    throw new Error(getErrorMessage(error, "文件上传失败"));
  }
}
