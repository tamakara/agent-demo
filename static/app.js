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

  employeeSelect: document.getElementById("employeeSelect"),
  newEmployeeBtn: document.getElementById("newEmployeeBtn"),
  reloadEmployeeBtn: document.getElementById("reloadEmployeeBtn"),

  fileTabs: document.getElementById("fileTabs"),
  fileContent: document.getElementById("fileContent"),
  activeFileName: document.getElementById("activeFileName"),
  saveFileBtn: document.getElementById("saveFileBtn"),
  reloadFilesBtn: document.getElementById("reloadFilesBtn"),
  resetMemoryBtn: document.getElementById("resetMemoryBtn"),
  directoryTree: document.getElementById("directoryTree"),
  dataDirPath: document.getElementById("dataDirPath"),

  chatItemTemplate: document.getElementById("chatItemTemplate"),
};

const state = {
  userId: "",
  employees: [],
  activeEmployeeId: "",
  activeSessionId: "",
  files: [],
  dataTree: [],
  dataDir: "",
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

function requireEmployeeId() {
  if (!state.activeEmployeeId) {
    throw new Error("当前没有可用数字员工，请先创建员工。");
  }
  return state.activeEmployeeId;
}

function buildUserQuery(extra = {}, includeEmployee = false) {
  const params = new URLSearchParams(extra);
  params.set("user_id", requireUserId());
  if (includeEmployee) {
    params.set("employee_id", requireEmployeeId());
  }
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

function ensureEmployeeSelected() {
  if (!state.activeEmployeeId) {
    reportError("当前没有可用数字员工，请先创建员工。");
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

function syncActiveEmployeeSession() {
  const current = state.employees.find((employee) => employee.employee_id === state.activeEmployeeId);
  state.activeSessionId = current?.session_id || "";
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

function formatEmployeeLabel(employee) {
  const updatedAt = (employee.updated_at || "").replace("T", " ").slice(0, 19);
  const messageCount = Number(employee.message_count || 0);
  return `员工 #${employee.employee_id} · ${messageCount}条消息 · ${updatedAt || "未知时间"}`;
}

function renderEmployeeSelect() {
  elements.employeeSelect.innerHTML = "";
  for (const employee of state.employees) {
    const option = document.createElement("option");
    option.value = employee.employee_id;
    option.textContent = formatEmployeeLabel(employee);
    if (employee.employee_id === state.activeEmployeeId) {
      option.selected = true;
    }
    elements.employeeSelect.appendChild(option);
  }
}

async function loadEmployees() {
  const data = await apiGet("/employees", { user_id: requireUserId() });
  state.employees = data.employees || [];
}

async function createEmployee() {
  const data = await apiPost("/employees", { user_id: requireUserId() });
  return data.employee;
}

async function loadEmployeeHistory(options = {}) {
  const announce = options.announce !== false;

  if (!state.activeEmployeeId) {
    clearChatLog();
    return;
  }

  const data = await apiGet("/employee-messages", {
    user_id: requireUserId(),
    employee_id: state.activeEmployeeId,
    limit: "2000",
  });

  state.activeSessionId = data.session_id || state.activeSessionId;

  const messages = data.messages || [];
  clearChatLog();
  for (const message of messages) {
    renderHistoryMessage(message);
  }

  if (announce) {
    appendChatItem("meta", `已切换到员工 #${state.activeEmployeeId}（加载 ${messages.length} 条历史）`);
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

async function ensureActiveEmployee() {
  await loadEmployees();
  if (state.employees.length === 0) {
    await createEmployee();
    await loadEmployees();
  }

  if (!state.activeEmployeeId || !state.employees.some((e) => e.employee_id === state.activeEmployeeId)) {
    state.activeEmployeeId = state.employees[0]?.employee_id || "";
  }

  syncActiveEmployeeSession();
  renderEmployeeSelect();
}

async function refreshEmployeesAndRender() {
  await loadEmployees();
  if (!state.activeEmployeeId || !state.employees.some((e) => e.employee_id === state.activeEmployeeId)) {
    state.activeEmployeeId = state.employees[0]?.employee_id || "";
  }
  syncActiveEmployeeSession();
  renderEmployeeSelect();
}

function resetMemoryView() {
  state.files = [];
  state.dataTree = [];
  state.dataDir = "";
  state.activeFile = null;
  updateEditorByActiveFile();
  renderFileTabs();
  renderDirectoryTree();
  updateDataDirPath();
}

async function switchUserContext(options = {}) {
  const announce = options.announce !== false;
  promptForUserId();
  state.activeEmployeeId = "";
  state.activeSessionId = "";
  resetMemoryView();
  clearChatLog();

  await ensureActiveEmployee();
  await loadGlobalLLMConfig();
  await loadEmployeeHistory({ announce: false });
  await loadMemoryFiles();
  await refreshStatus();

  if (announce) {
    reportMeta(`已切换用户：${state.userId}`);
  }
}

async function handleCreateEmployee() {
  const newEmployee = await createEmployee();
  await loadEmployees();
  state.activeEmployeeId = newEmployee.employee_id;
  syncActiveEmployeeSession();
  renderEmployeeSelect();
  await loadEmployeeHistory();
  await loadMemoryFiles();
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
  if (!ensureEmployeeSelected()) {
    return;
  }

  state.isChatRunning = true;
  appendChatItem("user", message);

  const config = getLLMConfigFromForm();
  const payload = {
    user_id: requireUserId(),
    employee_id: state.activeEmployeeId,
    message,
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
    await refreshEmployeesAndRender();
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
    `employee id：<b>${status.employee_id || state.activeEmployeeId || "-"}</b><br>` +
    `session id：<b>${status.session_id || state.activeSessionId || "-"}</b><br>` +
    `total：<b>${total}</b> / ${totalLimit} token（刷盘阈值：${flushTrigger}）<br>` +
    `常驻区：${resident} | 对话区：${dialogue} | 缓冲区：${buffer}<br>` +
    `预算：系统提示词/记忆 ${systemPromptLimit} | 摘要 ${summaryLimit} | 最近原始对话 ${recentRawLimit} | 对话区 ${dialogueLimit}<br>` +
    `刷盘状态：<b>${status.is_flushing ? "进行中" : "空闲"}</b>`;
}

async function refreshStatus() {
  if (!state.activeEmployeeId) {
    return;
  }
  const config = getLLMConfigFromForm();
  try {
    const status = await apiGet("/memory/status", {
      user_id: requireUserId(),
      employee_id: state.activeEmployeeId,
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

  elements.activeFileName.textContent = `${current.file_name} (${current.relative_path || current.file_name})`;
  elements.fileContent.value = current.content || "";
}

function renderFileTabs() {
  elements.fileTabs.innerHTML = "";
  for (const file of state.files) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "file-tab";
    btn.textContent = file.file_name;
    btn.title = file.relative_path || file.file_name;
    if (state.activeFile === file.file_name) {
      btn.classList.add("active");
    }
    btn.addEventListener("click", () => {
      state.activeFile = file.file_name;
      updateEditorByActiveFile();
      renderFileTabs();
      renderDirectoryTree();
    });
    elements.fileTabs.appendChild(btn);
  }
}

function updateDataDirPath() {
  elements.dataDirPath.textContent = state.dataDir || "-";
}

function renderDirectoryTree() {
  elements.directoryTree.innerHTML = "";

  const tree = Array.isArray(state.dataTree) ? state.dataTree : [];
  if (tree.length === 0) {
    const empty = document.createElement("div");
    empty.className = "tree-item dir";
    empty.textContent = "[DIR] .";
    elements.directoryTree.appendChild(empty);
    return;
  }

  for (const entry of tree) {
    const relativePath = String(entry?.path || "");
    if (!relativePath) {
      continue;
    }
    const isDir = Boolean(entry?.is_dir);
    const depth = relativePath === "." ? 0 : Math.max(0, relativePath.split("/").length - 1);
    const displayName = relativePath === "." ? "." : (relativePath.split("/").pop() || relativePath);

    const button = document.createElement("button");
    button.type = "button";
    button.className = `tree-item ${isDir ? "dir" : "file"}`;
    button.style.paddingLeft = `${8 + depth * 14}px`;
    button.title = relativePath;
    button.textContent = `${isDir ? "[DIR]" : "[FILE]"} ${displayName}`;

    if (isDir) {
      button.disabled = true;
      elements.directoryTree.appendChild(button);
      continue;
    }

    const editable = state.files.find((file) => file.relative_path === relativePath);
    if (!editable) {
      button.disabled = true;
      elements.directoryTree.appendChild(button);
      continue;
    }

    button.classList.add("selectable");
    if (state.activeFile === editable.file_name) {
      button.classList.add("active");
    }
    button.addEventListener("click", () => {
      state.activeFile = editable.file_name;
      updateEditorByActiveFile();
      renderFileTabs();
      renderDirectoryTree();
    });
    elements.directoryTree.appendChild(button);
  }
}

async function loadMemoryFiles() {
  if (!ensureEmployeeSelected()) {
    resetMemoryView();
    return;
  }

  const data = await apiGet("/memory/files", {
    user_id: requireUserId(),
    employee_id: state.activeEmployeeId,
  });

  state.activeSessionId = data.session_id || state.activeSessionId;
  state.files = data.files || [];
  state.dataTree = data.tree || [];
  state.dataDir = data.data_dir || "";

  syncActiveFileSelection();
  updateEditorByActiveFile();
  renderFileTabs();
  renderDirectoryTree();
  updateDataDirPath();
}

async function resetMemoryFiles() {
  if (!ensureEmployeeSelected()) {
    return;
  }

  const confirmed = window.confirm(`确认重置员工 #${state.activeEmployeeId} 的记忆文件吗？这会清空该员工目录下的记忆模板文件并覆盖为初始内容。`);
  if (!confirmed) {
    return;
  }

  const data = await apiPost(`/memory/reset?${buildUserQuery({}, true).toString()}`);
  state.activeSessionId = data.session_id || state.activeSessionId;
  state.files = data.files || [];
  state.dataTree = data.tree || [];
  syncActiveFileSelection();
  updateEditorByActiveFile();
  renderFileTabs();
  renderDirectoryTree();

  const restoredCount = Array.isArray(data.restored_files) ? data.restored_files.length : 0;
  reportMeta(`员工 #${state.activeEmployeeId} 记忆文件已重置，共恢复 ${restoredCount} 个模板文件。`);
  await refreshStatus();
}

async function saveActiveFile() {
  if (!state.activeFile) {
    reportError("当前没有可编辑的记忆文件。");
    return;
  }

  const content = elements.fileContent.value;
  const encoded = encodeURIComponent(state.activeFile);
  const data = await apiPut(`/memory/files/${encoded}?${buildUserQuery({}, true).toString()}`, {
    content,
    mode: "overwrite",
  });
  reportMeta(`文件保存成功：${data.file_name || state.activeFile}`);
  await loadMemoryFiles();
  await refreshStatus();
}

async function forceFlush() {
  if (!ensureEmployeeSelected()) {
    return;
  }
  const config = getLLMConfigFromForm();

  const data = await apiPost("/memory/flush", {
    user_id: requireUserId(),
    employee_id: state.activeEmployeeId,
    max_tool_rounds: config.max_tool_rounds,
  });

  appendChatItem("meta", data);
  await refreshStatus();
  await refreshEmployeesAndRender();
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

  elements.employeeSelect.addEventListener("change", async () => {
    state.activeEmployeeId = elements.employeeSelect.value;
    syncActiveEmployeeSession();
    try {
      await loadEmployeeHistory();
      await loadMemoryFiles();
      await refreshStatus();
    } catch (err) {
      reportError(err);
    }
  });

  elements.newEmployeeBtn.addEventListener("click", async () => {
    try {
      await handleCreateEmployee();
    } catch (err) {
      reportError(err);
    }
  });

  elements.reloadEmployeeBtn.addEventListener("click", async () => {
    try {
      await ensureActiveEmployee();
      await loadEmployeeHistory({ announce: false });
      await loadMemoryFiles();
      await refreshStatus();
      reportMeta("数字员工列表已刷新。");
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
    await ensureActiveEmployee();
    await loadGlobalLLMConfig();
    await loadEmployeeHistory({ announce: false });
    await loadMemoryFiles();
    await refreshStatus();
    setInterval(refreshStatus, 6000);
  } catch (err) {
    reportError(err);
  }
}

bootstrap();
