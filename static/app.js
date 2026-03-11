const elements = {
  model: document.getElementById("model"),
  apiKey: document.getElementById("apiKey"),
  baseUrl: document.getElementById("baseUrl"),
  maxToolRounds: document.getElementById("maxToolRounds"),
  totalTokenLimit: document.getElementById("totalTokenLimit"),
  currentUserId: document.getElementById("currentUserId"),
  switchUserBtn: document.getElementById("switchUserBtn"),

  openSettingsBtn: document.getElementById("openSettingsBtn"),
  settingsModal: document.getElementById("settingsModal"),
  closeSettingsBtn: document.getElementById("closeSettingsBtn"),

  saveConfigBtn: document.getElementById("saveConfigBtn"),
  forceFlushBtn: document.getElementById("forceFlushBtn"),
  tokenSummary: document.getElementById("tokenSummary"),
  residentBar: document.getElementById("residentBar"),
  dialogueBar: document.getElementById("dialogueBar"),
  bufferBar: document.getElementById("bufferBar"),
  chatLog: document.getElementById("chatLog"),
  chatForm: document.getElementById("chatForm"),
  messageInput: document.getElementById("messageInput"),
  sessionSelect: document.getElementById("sessionSelect"),
  newSessionBtn: document.getElementById("newSessionBtn"),
  reloadSessionBtn: document.getElementById("reloadSessionBtn"),
  fileTabs: document.getElementById("fileTabs"),
  fileContent: document.getElementById("fileContent"),
  activeFileName: document.getElementById("activeFileName"),
  saveFileBtn: document.getElementById("saveFileBtn"),
  reloadFilesBtn: document.getElementById("reloadFilesBtn"),
  resetMemoryBtn: document.getElementById("resetMemoryBtn"),
  chatItemTemplate: document.getElementById("chatItemTemplate"),
};

const state = {
  userId: "",
  sessions: [],
  activeSessionId: "",
  files: [],
  activeFile: null,
  isChatRunning: false,
};

const DEFAULT_LLM_MODEL = "agent-advoo";
const DEFAULT_LLM_API_KEY = "";
const DEFAULT_LLM_BASE_URL = "http://model-gateway.test.api.dotai.internal/v1";
const USER_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

function stringifyForDisplay(value) {
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch (err) {
    return String(value);
  }
}

function normalizeErrorPayload(error) {
  if (error && typeof error === "object") {
    const code = typeof error.code === "string" ? error.code : "request_error";
    const message = typeof error.message === "string" ? error.message : "请求失败";
    const details = Object.prototype.hasOwnProperty.call(error, "details") ? error.details : error;
    return {
      summary: `[${code}] ${message}`,
      detail: stringifyForDisplay(details),
    };
  }
  if (error instanceof Error) {
    return {
      summary: error.message || error.name || "请求失败",
      detail: error.stack || `${error.name}: ${error.message}`,
    };
  }
  if (typeof error === "string") {
    return { summary: error, detail: "" };
  }
  return { summary: "请求失败", detail: stringifyForDisplay(error) };
}

function reportError(error) {
  appendChatItem("error", normalizeErrorPayload(error));
}

function reportMeta(message) {
  appendChatItem("meta", message);
}

function getLLMConfigFromForm() {
  return {
    model: elements.model.value.trim() || DEFAULT_LLM_MODEL,
    api_key: elements.apiKey.value.trim() || DEFAULT_LLM_API_KEY,
    base_url: elements.baseUrl.value.trim() || DEFAULT_LLM_BASE_URL,
    max_tool_rounds: Number(elements.maxToolRounds.value || 6),
    total_token_limit: Number(elements.totalTokenLimit.value || 200000),
  };
}

function setFormFromConfig(config) {
  elements.model.value = config.model || DEFAULT_LLM_MODEL;
  elements.apiKey.value = config.api_key || DEFAULT_LLM_API_KEY;
  elements.baseUrl.value = config.base_url || DEFAULT_LLM_BASE_URL;
  elements.maxToolRounds.value = String(config.max_tool_rounds || 6);
  elements.totalTokenLimit.value = String(config.total_token_limit || 200000);
}

function setDefaultLLMConfig() {
  setFormFromConfig({
    model: DEFAULT_LLM_MODEL,
    api_key: DEFAULT_LLM_API_KEY,
    base_url: DEFAULT_LLM_BASE_URL,
    max_tool_rounds: 6,
    total_token_limit: 200000,
  });
}

function setActiveUserId(userId) {
  state.userId = userId;
  if (elements.currentUserId) {
    elements.currentUserId.textContent = userId;
  }
}

function requireUserId() {
  if (!state.userId) {
    throw new Error("user_id 未设置，请先输入用户ID。");
  }
  return state.userId;
}

function buildUserQuery(extra = {}) {
  const params = new URLSearchParams(extra);
  params.set("user_id", requireUserId());
  return params;
}

function promptForUserId() {
  const initial = state.userId || "";
  while (true) {
    const raw = window.prompt("请输入用户ID（字母/数字/._-，最长64位）", initial);
    if (raw === null) {
      continue;
    }
    const candidate = raw.trim();
    if (!candidate) {
      window.alert("用户ID不能为空。");
      continue;
    }
    if (!USER_ID_PATTERN.test(candidate)) {
      window.alert("用户ID仅允许字母、数字、点、下划线、短横线，且必须以字母或数字开头。");
      continue;
    }
    setActiveUserId(candidate);
    return;
  }
}

async function parseEnvelope(resp) {
  let payload = null;
  try {
    payload = await resp.json();
  } catch (err) {
    payload = null;
  }

  if (!payload || typeof payload !== "object") {
    throw { code: "invalid_response", message: `接口响应无法解析（HTTP ${resp.status}）`, details: payload };
  }

  if (!resp.ok) {
    if (payload.error && typeof payload.error === "object") {
      throw payload.error;
    }
    throw { code: "http_error", message: `HTTP ${resp.status}`, details: payload };
  }

  if (payload.error) {
    throw payload.error;
  }

  return payload.data;
}

async function apiGet(path, query = {}) {
  const params = new URLSearchParams(query);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const resp = await fetch(`${path}${suffix}`);
  return parseEnvelope(resp);
}

async function apiPost(path, body = null) {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body == null ? null : JSON.stringify(body),
  });
  return parseEnvelope(resp);
}

async function apiPut(path, body = null) {
  const resp = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: body == null ? null : JSON.stringify(body),
  });
  return parseEnvelope(resp);
}

function appendChatItem(type, content) {
  const node = elements.chatItemTemplate.content.cloneNode(true);
  const root = node.querySelector(".chat-item");
  const metaLabel = node.querySelector(".chat-meta");
  const bodyContainer = node.querySelector(".chat-body");

  root.classList.add(type);
  const isString = typeof content === "string";

  if (["user", "assistant"].includes(type)) {
    metaLabel.textContent = type === "user" ? "用户" : "助手";
    const pre = document.createElement("pre");
    pre.className = "chat-content";
    pre.textContent = isString ? content : stringifyForDisplay(content);
    bodyContainer.appendChild(pre);
  } else {
    metaLabel.style.display = "none";

    const details = document.createElement("details");
    details.className = "chat-collapsible";

    const summary = document.createElement("summary");
    let summaryText = type;
    let detailText = isString ? content : stringifyForDisplay(content);

    if (type === "tool_call") {
      summaryText = `工具调用：${content?.tool_name || "unknown"}`;
    } else if (type === "tool_result") {
      summaryText = `工具结果：${content?.tool_name || "unknown"}`;
    } else if (type === "meta") {
      summaryText = "系统元信息";
      if (isString && content.length < 60) {
        summaryText = `系统：${content}`;
        detailText = "";
      }
    } else if (type === "error") {
      if (content && typeof content === "object") {
        summaryText = content.summary || "请求失败";
        detailText = content.detail || "";
      } else {
        summaryText = "请求失败";
      }
    }

    summary.innerHTML = `<span class="summary-text">${summaryText}</span>`;
    if (detailText) {
      summary.innerHTML += `<svg class="fold-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>`;
      details.appendChild(summary);
      const pre = document.createElement("pre");
      pre.className = "chat-content";
      pre.textContent = detailText;
      details.appendChild(pre);
    } else {
      summary.style.cursor = "default";
      summary.addEventListener("click", (e) => e.preventDefault());
      details.appendChild(summary);
    }

    bodyContainer.appendChild(details);
  }

  elements.chatLog.appendChild(node);
  elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
}

function clearChatLog() {
  elements.chatLog.innerHTML = "";
}

function ensureSessionSelected() {
  if (!state.activeSessionId) {
    reportError("当前没有可用 session，请先创建 session。");
    return false;
  }
  return true;
}

function syncActiveFileSelection() {
  if (state.files.length === 0) {
    state.activeFile = null;
    return;
  }
  if (!state.activeFile || !state.files.some((f) => f.file_name === state.activeFile)) {
    state.activeFile = state.files[0].file_name;
  }
}

function tryParseJSON(raw) {
  if (typeof raw !== "string") {
    return raw;
  }
  try {
    return JSON.parse(raw);
  } catch (err) {
    return raw;
  }
}

function renderHistoryMessage(message) {
  const role = message.role || "";
  const zone = message.zone || "";
  const content = typeof message.content === "string" ? message.content : "";

  if (role === "user") {
    appendChatItem("user", content);
    return;
  }

  if (role === "assistant") {
    if (zone === "tool") {
      const parsed = tryParseJSON(content);
      if (parsed && typeof parsed === "object" && parsed.event === "tool_call") {
        appendChatItem("tool_call", parsed);
        return;
      }
    }
    appendChatItem("assistant", content);
    return;
  }

  if (role === "tool") {
    const parsed = tryParseJSON(content);
    if (parsed && typeof parsed === "object" && parsed.event === "tool_result") {
      appendChatItem("tool_result", parsed);
    } else {
      appendChatItem("tool_result", content);
    }
    return;
  }

  appendChatItem("meta", `${role || "unknown"}: ${content}`);
}

function formatSessionLabel(session) {
  const updatedAt = (session.updated_at || "").replace("T", " ").slice(0, 19);
  const messageCount = Number(session.message_count || 0);
  return `${session.session_id} · ${messageCount}条消息 · ${updatedAt || "未知时间"}`;
}

function renderSessionSelect() {
  elements.sessionSelect.innerHTML = "";
  for (const session of state.sessions) {
    const option = document.createElement("option");
    option.value = session.session_id;
    option.textContent = formatSessionLabel(session);
    if (session.session_id === state.activeSessionId) {
      option.selected = true;
    }
    elements.sessionSelect.appendChild(option);
  }
}

async function loadSessions() {
  const data = await apiGet("/sessions", { user_id: requireUserId() });
  state.sessions = data.sessions || [];
}

async function createSession() {
  const data = await apiPost("/sessions", { user_id: requireUserId() });
  return data.session;
}

async function loadSessionHistory(options = {}) {
  const announce = options.announce !== false;

  if (!state.activeSessionId) {
    clearChatLog();
    return;
  }

  const data = await apiGet("/session-messages", {
    user_id: requireUserId(),
    session_id: state.activeSessionId,
    limit: "2000",
  });

  const messages = data.messages || [];
  clearChatLog();
  for (const message of messages) {
    renderHistoryMessage(message);
  }

  if (announce) {
    appendChatItem("meta", `已切换到 session：${state.activeSessionId}（加载 ${messages.length} 条历史）`);
  }
}

async function loadGlobalLLMConfig() {
  const config = await apiGet("/settings", { user_id: requireUserId() });
  setFormFromConfig(config);
}

async function saveConfig() {
  const config = getLLMConfigFromForm();
  if (!config.model) {
    reportError("请先填写 model name。");
    return false;
  }
  if (!Number.isFinite(config.total_token_limit) || config.total_token_limit < 20000 || config.total_token_limit > 2000000) {
    reportError("Total Token Limit 必须在 20000 到 2000000 之间。");
    return false;
  }

  const latest = await apiPut("/settings", {
    user_id: requireUserId(),
    model: config.model,
    api_key: config.api_key,
    base_url: config.base_url,
    max_tool_rounds: Number.isFinite(config.max_tool_rounds) ? config.max_tool_rounds : 6,
    total_token_limit: Number.isFinite(config.total_token_limit) ? config.total_token_limit : 200000,
  });

  setFormFromConfig(latest);
  reportMeta("全局设置已保存。chat/flush 将按 DB 配置执行。");
  return true;
}

async function ensureActiveSession() {
  await loadSessions();
  if (state.sessions.length === 0) {
    await createSession();
    await loadSessions();
  }

  if (!state.activeSessionId || !state.sessions.some((s) => s.session_id === state.activeSessionId)) {
    state.activeSessionId = state.sessions[0]?.session_id || "";
  }

  renderSessionSelect();
}

async function refreshSessionsAndRender() {
  await loadSessions();
  renderSessionSelect();
}

async function switchUserContext(options = {}) {
  const announce = options.announce !== false;
  promptForUserId();
  state.activeSessionId = "";
  state.files = [];
  state.activeFile = null;
  clearChatLog();

  await ensureActiveSession();
  await loadGlobalLLMConfig();
  await loadSessionHistory({ announce: false });
  await loadMemoryFiles();
  await refreshStatus();

  if (announce) {
    reportMeta(`已切换用户：${state.userId}`);
  }
}

async function handleCreateSession() {
  const newSession = await createSession();
  await loadSessions();
  state.activeSessionId = newSession.session_id;
  renderSessionSelect();
  await loadSessionHistory();
  await refreshStatus();
}

async function readSSEStream(stream, onEvent) {
  const reader = stream.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";

    for (const block of blocks) {
      let dataLine = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("data:")) {
          dataLine += line.slice(5).trim();
        }
      }
      if (!dataLine) {
        continue;
      }

      let parsed = null;
      try {
        parsed = JSON.parse(dataLine);
      } catch (err) {
        continue;
      }
      onEvent(parsed);
    }
  }
}

async function sendChat(message) {
  if (state.isChatRunning) {
    reportMeta("已有请求在执行，请稍候。");
    return;
  }
  if (!ensureSessionSelected()) {
    return;
  }

  state.isChatRunning = true;
  appendChatItem("user", message);

  const config = getLLMConfigFromForm();
  const payload = {
    user_id: requireUserId(),
    message,
    session_id: state.activeSessionId,
    max_tool_rounds: config.max_tool_rounds,
  };

  try {
    const resp = await fetch("/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!resp.ok || !resp.body) {
      try {
        await parseEnvelope(resp);
      } catch (err) {
        reportError(err);
      }
      return;
    }

    await readSSEStream(resp.body, (eventEnvelope) => {
      const eventType = eventEnvelope?.type;
      const payloadData = eventEnvelope?.payload;

      if (eventType === "assistant_final") {
        appendChatItem("assistant", payloadData?.content || "");
      } else if (eventType === "memory_status") {
        updateTokenBoard(payloadData || {});
      } else if (eventType === "tool_call" || eventType === "tool_result") {
        appendChatItem(eventType, payloadData || {});
      } else if (eventType === "error") {
        reportError(payloadData || "请求失败");
      } else if (eventType === "meta") {
        appendChatItem("meta", payloadData || {});
      }
    });
  } catch (err) {
    reportError(err);
  } finally {
    state.isChatRunning = false;
    await refreshStatus();
    await refreshSessionsAndRender();
  }
}

function updateTokenBoard(status) {
  const thresholds = status.thresholds || {};
  const totalLimit = thresholds.total_limit || 200000;
  const systemPromptLimit = thresholds.system_prompt_limit || Math.floor(totalLimit * 0.1);
  const summaryLimit = thresholds.summary_limit || Math.floor(totalLimit * 0.01);
  const recentRawLimit = thresholds.recent_raw_limit || Math.floor(totalLimit * 0.09);
  const dialogueLimit = thresholds.dialogue_limit || Math.floor(totalLimit * 0.8);
  const flushTrigger = thresholds.flush_trigger || totalLimit;

  const resident = status.resident_tokens || 0;
  const dialogue = status.dialogue_tokens || 0;
  const buffer = status.buffer_tokens || 0;
  const total = status.total_tokens || 0;

  const residentPercent = Math.min(100, (resident / totalLimit) * 100);
  const dialoguePercent = Math.min(100, (dialogue / totalLimit) * 100);
  const bufferPercent = Math.min(100, (buffer / totalLimit) * 100);

  elements.residentBar.style.left = "0%";
  elements.residentBar.style.width = `${residentPercent}%`;
  elements.dialogueBar.style.left = `${residentPercent}%`;
  elements.dialogueBar.style.width = `${dialoguePercent}%`;
  elements.bufferBar.style.left = `${Math.min(100, residentPercent + dialoguePercent)}%`;
  elements.bufferBar.style.width = `${bufferPercent}%`;

  elements.tokenSummary.innerHTML =
    `user id：<b>${status.user_id || state.userId || "-"}</b><br>` +
    `session id：<b>${status.session_id || state.activeSessionId || "-"}</b><br>` +
    `total：<b>${total}</b> / ${totalLimit} token（刷盘阈值：${flushTrigger}）<br>` +
    `常驻区：${resident} | 对话区：${dialogue} | 缓冲区：${buffer}<br>` +
    `预算：系统提示词/记忆 ${systemPromptLimit} | 摘要 ${summaryLimit} | 最近原始对话 ${recentRawLimit} | 对话区 ${dialogueLimit}<br>` +
    `刷盘状态：<b>${status.is_flushing ? "进行中" : "空闲"}</b>`;
}

async function refreshStatus() {
  if (!state.activeSessionId) {
    return;
  }
  const config = getLLMConfigFromForm();
  try {
    const status = await apiGet("/memory/status", {
      user_id: requireUserId(),
      session_id: state.activeSessionId,
      model: config.model || DEFAULT_LLM_MODEL,
    });
    updateTokenBoard(status);
  } catch (err) {
    console.warn("状态刷新失败", err);
  }
}

function updateEditorByActiveFile() {
  if (!state.activeFile) {
    elements.activeFileName.textContent = "未选择文件";
    elements.fileContent.value = "";
    return;
  }

  const current = state.files.find((file) => file.file_name === state.activeFile);
  if (!current) {
    elements.activeFileName.textContent = "未选择文件";
    elements.fileContent.value = "";
    return;
  }

  elements.activeFileName.textContent = current.file_name;
  elements.fileContent.value = current.content || "";
}

function renderFileTabs() {
  elements.fileTabs.innerHTML = "";
  for (const file of state.files) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "file-tab";
    btn.textContent = file.file_name;
    if (state.activeFile === file.file_name) {
      btn.classList.add("active");
    }
    btn.addEventListener("click", () => {
      state.activeFile = file.file_name;
      updateEditorByActiveFile();
      renderFileTabs();
    });
    elements.fileTabs.appendChild(btn);
  }
}

async function loadMemoryFiles() {
  const data = await apiGet("/memory/files", { user_id: requireUserId() });
  state.files = data.files || [];
  syncActiveFileSelection();
  updateEditorByActiveFile();
  renderFileTabs();
}

async function resetMemoryFiles() {
  const confirmed = window.confirm("确认重置记忆文件吗？这会清空当前 memory 目录并用模板覆盖。");
  if (!confirmed) {
    return;
  }

  const data = await apiPost(`/memory/reset?${buildUserQuery().toString()}`);
  state.files = data.files || [];
  syncActiveFileSelection();
  updateEditorByActiveFile();
  renderFileTabs();
  const restoredCount = Array.isArray(data.restored_files) ? data.restored_files.length : 0;
  reportMeta(`记忆文件已重置，共恢复 ${restoredCount} 个模板文件。`);
  await refreshStatus();
}

async function saveActiveFile() {
  if (!state.activeFile) {
    reportError("当前没有可编辑的记忆文件。");
    return;
  }

  const content = elements.fileContent.value;
  const encoded = encodeURIComponent(state.activeFile);
  const data = await apiPut(`/memory/files/${encoded}?${buildUserQuery().toString()}`, {
    content,
    mode: "overwrite",
  });
  reportMeta(`文件保存成功：${data.file_name || state.activeFile}`);
  await loadMemoryFiles();
  await refreshStatus();
}

async function forceFlush() {
  if (!ensureSessionSelected()) {
    return;
  }
  const config = getLLMConfigFromForm();

  const data = await apiPost("/memory/flush", {
    user_id: requireUserId(),
    session_id: state.activeSessionId,
    max_tool_rounds: config.max_tool_rounds,
  });

  appendChatItem("meta", data);
  await refreshStatus();
  await refreshSessionsAndRender();
  elements.settingsModal.close();
}

function bindEvents() {
  if (elements.switchUserBtn) {
    elements.switchUserBtn.addEventListener("click", async () => {
      try {
        await switchUserContext();
      } catch (err) {
        reportError(err);
      }
    });
  }

  elements.openSettingsBtn.addEventListener("click", () => {
    elements.settingsModal.showModal();
  });

  elements.closeSettingsBtn.addEventListener("click", () => {
    elements.settingsModal.close();
  });

  elements.settingsModal.addEventListener("click", (e) => {
    const rect = elements.settingsModal.getBoundingClientRect();
    const isInDialog =
      rect.top <= e.clientY && e.clientY <= rect.top + rect.height &&
      rect.left <= e.clientX && e.clientX <= rect.left + rect.width;
    if (!isInDialog) {
      elements.settingsModal.close();
    }
  });

  elements.saveConfigBtn.addEventListener("click", async () => {
    try {
      const saved = await saveConfig();
      if (saved) {
        await refreshStatus();
        elements.settingsModal.close();
      }
    } catch (err) {
      reportError(err);
    }
  });

  elements.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      elements.chatForm.dispatchEvent(new Event("submit", { cancelable: true }));
    }
  });

  elements.chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = elements.messageInput.value.trim();
    if (!text) {
      return;
    }
    elements.messageInput.value = "";
    await sendChat(text);
  });

  elements.sessionSelect.addEventListener("change", async () => {
    state.activeSessionId = elements.sessionSelect.value;
    try {
      await loadSessionHistory();
      await refreshStatus();
    } catch (err) {
      reportError(err);
    }
  });

  elements.newSessionBtn.addEventListener("click", async () => {
    try {
      await handleCreateSession();
    } catch (err) {
      reportError(err);
    }
  });

  elements.reloadSessionBtn.addEventListener("click", async () => {
    try {
      await ensureActiveSession();
      await loadSessionHistory({ announce: false });
      await refreshStatus();
      reportMeta("session 列表已刷新。");
    } catch (err) {
      reportError(err);
    }
  });

  elements.reloadFilesBtn.addEventListener("click", async () => {
    try {
      await loadMemoryFiles();
    } catch (err) {
      reportError(err);
    }
  });

  elements.resetMemoryBtn.addEventListener("click", async () => {
    try {
      await resetMemoryFiles();
    } catch (err) {
      reportError(err);
    }
  });

  elements.saveFileBtn.addEventListener("click", async () => {
    try {
      await saveActiveFile();
    } catch (err) {
      reportError(err);
    }
  });

  elements.forceFlushBtn.addEventListener("click", async () => {
    try {
      await forceFlush();
    } catch (err) {
      reportError(err);
    }
  });
}

async function bootstrap() {
  bindEvents();
  setDefaultLLMConfig();
  promptForUserId();

  try {
    await ensureActiveSession();
    await loadGlobalLLMConfig();
    await loadSessionHistory({ announce: false });
    await loadMemoryFiles();
    await refreshStatus();
    setInterval(refreshStatus, 6000);
  } catch (err) {
    reportError(err);
  }
}

bootstrap();
