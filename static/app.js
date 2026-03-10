const elements = {
  model: document.getElementById("model"),
  apiKey: document.getElementById("apiKey"),
  baseUrl: document.getElementById("baseUrl"),
  maxToolRounds: document.getElementById("maxToolRounds"),
  totalTokenLimit: document.getElementById("totalTokenLimit"),
  currentUserId: document.getElementById("currentUserId"),
  switchUserBtn: document.getElementById("switchUserBtn"),
  
  // 弹窗控制节点
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
const DEFAULT_LLM_API_KEY = "sk-RtSmDDQfUbbrNczdVajJqoozIR8AYolUOWwSTgpc2s7rZq6F";
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

function deriveSummaryFromValidationDetail(detail) {
  if (!Array.isArray(detail) || detail.length === 0) {
    return "";
  }
  const messages = detail.map((item) => {
    if (!item || typeof item !== "object") {
      return typeof item === "string" ? item : null;
    }
    const loc = Array.isArray(item.loc) ? item.loc.join(".") : "";
    const msg = typeof item.msg === "string" ? item.msg : stringifyForDisplay(item);
    return loc ? `${loc}: ${msg}` : msg;
  }).filter(Boolean);
  return messages.join("；");
}

function normalizeErrorPayload(error) {
  if (error && typeof error === "object" && !Array.isArray(error) && "summary" in error) {
    return {
      summary: String(error.summary || "请求失败"),
      detail: typeof error.detail === "string" ? error.detail : stringifyForDisplay(error.detail),
    };
  }

  if (error instanceof Error) {
    const summary = error.message || error.name || "请求失败";
    const detail = error.stack || `${error.name}: ${error.message}`;
    return { summary, detail };
  }

  if (typeof error === "string") {
    return { summary: error, detail: "" };
  }

  if (Array.isArray(error)) {
    const summary = deriveSummaryFromValidationDetail(error) || "请求失败";
    return { summary, detail: stringifyForDisplay(error) };
  }

  if (error && typeof error === "object") {
    const detailText = stringifyForDisplay(error);
    const summaryCandidates = [
      typeof error.message === "string" ? error.message : "",
      typeof error.error === "string" ? error.error : "",
      typeof error.title === "string" ? error.title : "",
      typeof error.detail === "string" ? error.detail : "",
      deriveSummaryFromValidationDetail(error.detail),
    ];
    const summary = summaryCandidates.find((item) => item && item.trim()) || "请求失败，请展开查看详情";
    return { summary, detail: detailText };
  }

  return { summary: String(error), detail: "" };
}

function reportError(error) {
  appendChatItem("error", normalizeErrorPayload(error));
}

function reportMeta(message) {
  appendChatItem("meta", message);
}

function formatEventLabel(type) {
  const mapping = {
    meta: "系统元信息",
    user: "用户",
    assistant: "助手",
    tool_call: "工具调用",
    tool_result: "工具结果",
    error: "错误",
    message: "消息",
  };
  return mapping[type] || type;
}

function getLLMConfigFromForm() {
  return {
    model: elements.model.value.trim(),
    api_key: elements.apiKey.value.trim(),
    base_url: elements.baseUrl.value.trim() || null,
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

// === 更新后的节点追加渲染函数，包含折叠逻辑 ===
function appendChatItem(type, content) {
  const node = elements.chatItemTemplate.content.cloneNode(true);
  const root = node.querySelector(".chat-item");
  const metaLabel = node.querySelector(".chat-meta");
  const bodyContainer = node.querySelector(".chat-body");

  root.classList.add(type);
  const isString = typeof content === "string";

  // 用户、助手信息保持直接展示
  if (["user", "assistant"].includes(type)) {
    metaLabel.textContent = formatEventLabel(type);
    const pre = document.createElement("pre");
    pre.className = "chat-content";
    pre.textContent = isString ? content : stringifyForDisplay(content);
    bodyContainer.appendChild(pre);
  } else {
    // 隐藏默认的 Label
    metaLabel.style.display = "none"; 

    // 构建折叠面板 (details/summary)
    const details = document.createElement("details");
    details.className = "chat-collapsible";

    const summary = document.createElement("summary");
    let summaryText = formatEventLabel(type);
    let detailText = isString ? content : stringifyForDisplay(content);

    // 根据不同类型提取友好的摘要
    if (type === "tool_call" && content && content.function) {
      summaryText = `🔧 工具调用：${content.function.name}`;
      try {
        detailText = typeof content.function.arguments === "string" 
          ? stringifyForDisplay(JSON.parse(content.function.arguments))
          : stringifyForDisplay(content.function.arguments);
      } catch (e) {}
    } else if (type === "tool_result") {
      summaryText = `⚡ 工具执行完毕并返回结果`;
    } else if (type === "error") {
      if (content && typeof content === "object") {
        const summary = typeof content.summary === "string" ? content.summary.trim() : "";
        const detail = typeof content.detail === "string" ? content.detail.trim() : "";
        summaryText = summary ? `❌ ${summary}` : "❌ 请求失败";
        detailText = detail;
      } else {
        const fallback = isString ? content : stringifyForDisplay(content);
        summaryText = fallback ? `❌ ${fallback}` : "❌ 请求失败";
        detailText = "";
      }
    } else if (type === "meta") {
      // 较短的 meta 文本直接显示，不提供折叠展开
      if (isString && content.length < 50) {
        summaryText = `⚙️ ${content}`;
        detailText = ""; 
      } else if (content && typeof content === "object") {
        if (content.type === "state_refresh") {
          const round = Number(content.round);
          const roundText = Number.isFinite(round) ? `第${round}轮` : "本轮";
          const fileName = content.file_name ? ` · ${content.file_name}` : "";
          summaryText = `♻️ 记忆状态刷新（${roundText}${fileName}）`;
        } else if (content.type === "llm_request") {
          const round = Number(content.round);
          const roundText = Number.isFinite(round) ? `第${round}轮` : "本轮";
          const model = content.request_body?.model;
          summaryText = model
            ? `🧠 LLM 调用信息（${roundText} · ${model}）`
            : `🧠 LLM 调用信息（${roundText}）`;
        } else if (
          Object.prototype.hasOwnProperty.call(content, "session_id") &&
          Object.prototype.hasOwnProperty.call(content, "model") &&
          Object.prototype.hasOwnProperty.call(content, "max_tool_rounds")
        ) {
          summaryText = `⚙️ 会话元信息`;
        } else if (content.flush_scheduled) {
          summaryText = `⚙️ 刷盘调度信息`;
        } else {
          summaryText = `⚙️ 系统元信息`;
        }
      } else {
        summaryText = `⚙️ 系统元信息`;
      }
    }

    summary.innerHTML = `<span class="summary-text">${summaryText}</span>`;
    
    // 如果存在需要折叠的长文本，则加上箭头图标和展开内容
    if (detailText) {
      summary.innerHTML += `<svg class="fold-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>`;
      details.appendChild(summary);
      
      const pre = document.createElement("pre");
      pre.className = "chat-content";
      pre.textContent = detailText;
      details.appendChild(pre);
    } else {
      // 如果没有详情，禁用点击事件和光标
      summary.style.cursor = "default";
      summary.addEventListener('click', (e) => e.preventDefault());
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

function validateLLMConfig(config) {
  if (!config.model || !config.api_key) {
    return "请先填写 model name 和 api key。";
  }
  if (!Number.isFinite(config.total_token_limit) || config.total_token_limit < 20000 || config.total_token_limit > 2000000) {
    return "Total Token Limit 必须在 20000 到 2000000 之间。";
  }
  return null;
}

function formatApiErrorMessage(status, data) {
  if (!data) {
    return `请求失败：${status}`;
  }

  const detail = data.detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail.trim();
  }

  if (Array.isArray(detail) && detail.length > 0) {
    const messages = detail.map((item) => {
      if (!item || typeof item !== "object") {
        return null;
      }
      const loc = Array.isArray(item.loc) ? item.loc.join(".") : "body";
      const msg = typeof item.msg === "string" ? item.msg : JSON.stringify(item);
      if (loc.endsWith("total_token_limit")) {
        return `Total Token Limit 不合法：${msg}`;
      }
      return `${loc}: ${msg}`;
    }).filter(Boolean);

    if (messages.length > 0) {
      return messages.join("；");
    }
  }

  return typeof data === "object" ? JSON.stringify(data) : String(data);
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

async function refreshSessionsAndRender() {
  await loadSessions();
  renderSessionSelect();
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

async function loadSessionHistory(options = {}) {
  const announce = options.announce !== false;

  if (!state.activeSessionId) {
    clearChatLog();
    return;
  }

  const params = buildUserQuery({
    session_id: state.activeSessionId,
    limit: "2000",
  });

  const resp = await fetch(`/api/session-messages?${params.toString()}`);
  if (!resp.ok) {
    throw new Error(`加载历史记录失败：${resp.status}`);
  }

  const data = await resp.json();
  const messages = data.messages || [];

  clearChatLog();
  for (const message of messages) {
    renderHistoryMessage(message);
  }

  if (announce) {
    appendChatItem("meta", `已切换到 session：${state.activeSessionId}（加载 ${messages.length} 条历史）`);
  }
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
  const params = buildUserQuery();
  const resp = await fetch(`/api/sessions?${params.toString()}`);
  if (!resp.ok) {
    throw new Error(`加载 session 列表失败：${resp.status}`);
  }
  const data = await resp.json();
  state.sessions = data.sessions || [];
}

async function createSession() {
  const resp = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: requireUserId() }),
  });
  if (!resp.ok) {
    throw new Error(`创建 session 失败：${resp.status}`);
  }
  const data = await resp.json();
  return data.session;
}

async function loadGlobalLLMConfig() {
  const params = buildUserQuery();
  const resp = await fetch(`/api/settings?${params.toString()}`);
  if (!resp.ok) {
    throw new Error(`加载全局设置失败：${resp.status}`);
  }
  const config = await resp.json();
  setFormFromConfig(config);
}

async function saveConfig() {
  const config = getLLMConfigFromForm();
  const configError = validateLLMConfig(config);
  if (configError) {
    reportError(configError);
    return false;
  }

  const payload = {
    model: config.model || DEFAULT_LLM_MODEL,
    api_key: config.api_key || DEFAULT_LLM_API_KEY,
    base_url: config.base_url,
    max_tool_rounds: Number.isFinite(config.max_tool_rounds) ? config.max_tool_rounds : 6,
    total_token_limit: Number.isFinite(config.total_token_limit) ? config.total_token_limit : 200000,
  };

  try {
    const params = buildUserQuery();
    const resp = await fetch(`/api/settings?${params.toString()}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    let data = null;
    try {
      data = await resp.json();
    } catch (err) {
      data = null;
    }

    if (!resp.ok) {
      reportError({
        summary: formatApiErrorMessage(resp.status, data),
        detail: data || { status: resp.status },
      });
      return false;
    }
    setFormFromConfig(data);
    reportMeta("全局设置已保存到数据库。");
    return true;
  } catch (err) {
    reportError(err);
    return false;
  }
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
  try {
    const newSession = await createSession();
    await loadSessions();
    state.activeSessionId = newSession.session_id;
    renderSessionSelect();
    await loadSessionHistory();
    await refreshStatus();
  } catch (err) {
    reportError(err);
  }
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
      const event = { event: "message", data: "" };
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) {
          event.event = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          event.data += line.slice(5).trim();
        }
      }
      if (!event.data) {
        continue;
      }

      let parsed = event.data;
      try {
        parsed = JSON.parse(event.data);
      } catch (err) {
        // 允许后端返回纯文本 data。
      }
      onEvent(event.event, parsed);
    }
  }
}

async function sendChat(message) {
  const config = getLLMConfigFromForm();
  const configError = validateLLMConfig(config);
  if (configError) {
    reportError(configError);
    elements.settingsModal.showModal(); // 自动弹窗
    return;
  }
  if (state.isChatRunning) {
    reportMeta("已有请求在执行，请稍候。");
    return;
  }
  if (!ensureSessionSelected()) {
    return;
  }

  state.isChatRunning = true;
  appendChatItem("user", message);

  const payload = {
    user_id: requireUserId(),
    message,
    session_id: state.activeSessionId,
    max_tool_rounds: config.max_tool_rounds,
    llm_config: {
      model: config.model,
      api_key: config.api_key,
      base_url: config.base_url,
    },
  };

  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!resp.ok || !resp.body) {
      const text = await resp.text();
      reportError({
        summary: `请求失败：${resp.status}`,
        detail: text || { status: resp.status },
      });
      return;
    }

    await readSSEStream(resp.body, (eventName, data) => {
      if (eventName === "assistant_final") {
        appendChatItem("assistant", data.content || "");
      } else if (eventName === "memory_status") {
        updateTokenBoard(data);
      } else if (eventName === "tool_call" || eventName === "tool_result") {
        appendChatItem(eventName, data);
      } else if (eventName === "error") {
        reportError({
          summary: data?.message || "请求执行失败",
          detail: data || "后端未返回错误详情",
        });
      } else if (eventName === "meta") {
        appendChatItem("meta", data);
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
  const totalLimit = status.thresholds?.total_limit || 200000;
  const systemPromptLimit = status.thresholds?.system_prompt_limit || Math.floor(totalLimit * 0.1);
  const summaryLimit = status.thresholds?.summary_limit || Math.floor(totalLimit * 0.01);
  const recentRawLimit = status.thresholds?.recent_raw_limit || Math.floor(totalLimit * 0.09);
  const dialogueLimit = status.thresholds?.dialogue_limit || Math.floor(totalLimit * 0.8);
  const flushTrigger = status.thresholds?.flush_trigger || totalLimit;
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
    `session id：<b>${status.session_id}</b><br>` +
    `total：<b>${total}</b> / ${totalLimit} token（刷盘阈值：${flushTrigger}）<br>` +
    `常驻区：${resident} | 对话区：${dialogue} | 缓冲区：${buffer}<br>` +
    `预算：系统提示词/记忆 ${systemPromptLimit} | 摘要 ${summaryLimit} | 最近原始对话 ${recentRawLimit} | 对话区 ${dialogueLimit}<br>` +
    `刷盘状态：<b>${status.is_flushing ? "进行中" : "空闲"}</b>`;
}

async function refreshStatus() {
  const config = getLLMConfigFromForm();
  if (!state.activeSessionId) {
    return;
  }

  const params = buildUserQuery({
    session_id: state.activeSessionId,
    model: config.model || DEFAULT_LLM_MODEL,
  });

  try {
    const resp = await fetch(`/api/memory/status?${params.toString()}`);
    if (!resp.ok) {
      return;
    }
    const status = await resp.json();
    updateTokenBoard(status);
  } catch (err) {
    console.warn("状态刷新失败：", err);
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
  try {
    const params = buildUserQuery();
    const resp = await fetch(`/api/memory/files?${params.toString()}`);
    if (!resp.ok) {
      reportError(`加载文件失败：${resp.status}`);
      return;
    }
    const data = await resp.json();
    state.files = data.files || [];
    syncActiveFileSelection();
    updateEditorByActiveFile();
    renderFileTabs();
  } catch (err) {
    reportError(err);
  }
}

async function resetMemoryFiles() {
  const confirmed = window.confirm("确认重置记忆文件吗？这会清空当前 memory 目录并用模板覆盖。");
  if (!confirmed) {
    return;
  }

  try {
    const params = buildUserQuery();
    const resp = await fetch(`/api/memory/reset?${params.toString()}`, {
      method: "POST",
    });
    const data = await resp.json();
    if (!resp.ok) {
      reportError({
        summary: typeof data?.detail === "string" ? data.detail : "重置记忆文件失败",
        detail: data || { status: resp.status },
      });
      return;
    }

    state.files = data.files || [];
    syncActiveFileSelection();
    updateEditorByActiveFile();
    renderFileTabs();
    const restoredCount = Array.isArray(data.restored_files) ? data.restored_files.length : 0;
    reportMeta(`记忆文件已重置，共恢复 ${restoredCount} 个模板文件。`);
    await refreshStatus();
  } catch (err) {
    reportError(err);
  }
}

async function saveActiveFile() {
  if (!state.activeFile) {
    reportError("当前没有可编辑的记忆文件。");
    return;
  }

  const content = elements.fileContent.value;
  const encoded = encodeURIComponent(state.activeFile);

  try {
    const params = buildUserQuery();
    const resp = await fetch(`/api/memory/files/${encoded}?${params.toString()}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, mode: "overwrite" }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      reportError({
        summary: typeof data?.detail === "string" ? data.detail : "保存文件失败",
        detail: data || { status: resp.status },
      });
      return;
    }
    reportMeta(`文件保存成功：${state.activeFile}`);
    await loadMemoryFiles();
    await refreshStatus();
  } catch (err) {
    reportError(err);
  }
}

async function forceFlush() {
  const config = getLLMConfigFromForm();
  const configError = validateLLMConfig(config);
  if (configError) {
    reportError(configError);
    elements.settingsModal.showModal(); // 自动弹窗
    return;
  }
  if (!ensureSessionSelected()) {
    return;
  }

  try {
    const resp = await fetch("/api/memory/flush", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: requireUserId(),
        session_id: state.activeSessionId,
        max_tool_rounds: config.max_tool_rounds,
        llm_config: {
          model: config.model,
          api_key: config.api_key,
          base_url: config.base_url,
        },
      }),
    });
    const data = await resp.json();
    appendChatItem("meta", data);
  } catch (err) {
    reportError(err);
  } finally {
    await refreshStatus();
    await refreshSessionsAndRender();
    elements.settingsModal.close(); // 刷盘后关闭配置框
  }
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

  // === 弹窗 Modal 控制 ===
  elements.openSettingsBtn.addEventListener("click", () => {
    elements.settingsModal.showModal();
  });
  
  elements.closeSettingsBtn.addEventListener("click", () => {
    elements.settingsModal.close();
  });

  // 点击背景自动关闭
  elements.settingsModal.addEventListener("click", (e) => {
    const rect = elements.settingsModal.getBoundingClientRect();
    const isInDialog = rect.top <= e.clientY && e.clientY <= rect.top + rect.height &&
                       rect.left <= e.clientX && e.clientX <= rect.left + rect.width;
    if (!isInDialog) {
      elements.settingsModal.close();
    }
  });

  elements.saveConfigBtn.addEventListener("click", async () => {
    const saved = await saveConfig();
    if (!saved) {
      return;
    }
    await refreshStatus();
    elements.settingsModal.close(); // 保存成功后自动关闭弹窗
  });

  // === 聊天快捷键与提交逻辑 ===
  elements.messageInput.addEventListener("keydown", (event) => {
    // 按 Enter 键且没按 Shift 键时发送
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

  // === 其他事件绑定 ===
  elements.sessionSelect.addEventListener("change", async () => {
    state.activeSessionId = elements.sessionSelect.value;
    try {
      await loadSessionHistory();
      await refreshStatus();
    } catch (err) {
      reportError(err);
    }
  });

  elements.newSessionBtn.addEventListener("click", handleCreateSession);
  
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

  elements.reloadFilesBtn.addEventListener("click", loadMemoryFiles);
  elements.resetMemoryBtn.addEventListener("click", resetMemoryFiles);
  elements.saveFileBtn.addEventListener("click", saveActiveFile);
  elements.forceFlushBtn.addEventListener("click", forceFlush);
}

async function bootstrap() {
  bindEvents();
  setDefaultLLMConfig();
  promptForUserId();
  try {
    await ensureActiveSession();
    await loadGlobalLLMConfig(); // 加载全局配置
    await loadSessionHistory({ announce: false });
  } catch (err) {
    reportError(err);
  }
  await loadMemoryFiles();
  await refreshStatus();
  setInterval(refreshStatus, 6000);
}

bootstrap();
