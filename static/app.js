// =================配置与状态=================
const CONFIG = {
  storageKey: "agent_demo_user_id"
};
const TOKENIZER_OPTIONS = ["gemini-3-flash", "gemini-3.1-pro"];
const DEFAULT_TOKENIZER_MODEL = "gemini-3-flash";
const IMAGE_FILE_EXT_PATTERN = /\.(png|jpe?g|webp|gif|bmp|svg)$/i;
const EDITABLE_TEXT_EXT_PATTERN = /\.(md|txt)$/i;
const DELETABLE_ROOT_NAMES = new Set(["brand_library", "skill_library"]);

const state = {
  userId: localStorage.getItem(CONFIG.storageKey) || "",
  employees: [],
  activeEmployeeId: "",
  settings: null,
  files: [],
  dataTree: [],
  activeFile: null,
  selectedFile: null,
  textFileCache: {},
  loadingTextFilePath: "",
  expandedDirs: new Set(),
  isChatting: false,
};

// =================DOM 节点缓存=================
const $ = (id) => document.getElementById(id);
const els = {
  userId: $("userIdInput"), btnUser: $("switchUserBtn"),
  chatLog: $("chatLog"), chatForm: $("chatForm"), msgInput: $("messageInput"),
  empSelect: $("employeeSelect"), btnNewEmp: $("newEmployeeBtn"), btnReloadEmp: $("reloadEmployeeBtn"),
  btnUploadBrandLibrary: $("uploadBrandLibraryBtn"), uploadBrandLibraryInput: $("uploadBrandLibraryInput"),
  btnResetMemory: $("resetMemoryBtn"), btnReloadFiles: $("reloadFilesBtn"),
  tree: $("directoryTree"), fileContent: $("fileContent"), fileName: $("activeFileName"),
  btnDeleteFile: $("deleteFileBtn"), btnSaveFile: $("saveFileBtn"),
  fileImagePreview: $("fileImagePreview"), fileImagePreviewImg: $("fileImagePreviewImg"), fileImagePreviewPath: $("fileImagePreviewPath"),
  modal: $("settingsModal"), btnSettings: $("openSettingsBtn"),
  tokenSum: $("tokenSummary"), resBar: $("residentBar"), diaBar: $("dialogueBar"), bufBar: $("bufferBar"),
  btnForceFlush: $("forceFlushBtn")
};

const toEditableRelativePath = (path) => {
  const raw = String(path || "").trim();
  if (!raw) return "";
  return raw.startsWith("/") ? raw.slice(1) : raw;
};

const extractEmployeeIdFromTreePath = (path) => {
  const normalized = toEditableRelativePath(path);
  if (!normalized) return "";
  const parts = normalized.split("/").filter(Boolean);
  if (parts.length < 2 || parts[0] !== "employee") return "";
  const candidate = String(parts[1] || "").trim();
  return /^[0-9]+$/.test(candidate) ? candidate : "";
};

const findEditableFile = (path) => {
  const normalized = toEditableRelativePath(path);
  if (!normalized) return null;
  return state.files.find(f => String(f.relative_path || "").trim() === normalized) || null;
};

const fileNameFromPath = (path) => {
  const raw = String(path || "").trim();
  if (!raw) return "";
  const parts = raw.split("/").filter(Boolean);
  return parts[parts.length - 1] || raw;
};

const isImageTreePath = (path) => IMAGE_FILE_EXT_PATTERN.test(String(path || ""));
const isEditableTextTreePath = (path) => EDITABLE_TEXT_EXT_PATTERN.test(String(path || "").trim());
const fileKindFromTreePath = (path) => {
  if (isImageTreePath(path)) return "image";
  if (isEditableTextTreePath(path)) return "text";
  return "other";
};

const dataRootNameFromPath = (path) => {
  const normalized = toEditableRelativePath(path);
  const parts = normalized.split("/").filter(Boolean);
  return parts[0] || "";
};

const isDeletableFilePath = (path) => DELETABLE_ROOT_NAMES.has(dataRootNameFromPath(path));

const buildSelectedFile = (path) => {
  const normalized = String(path || "").trim();
  if (!normalized) return null;
  return {
    path: normalized,
    kind: fileKindFromTreePath(normalized),
    name: fileNameFromPath(normalized),
  };
};

// =================API 封装库=================
const api = {
  async req(method, path, body = null, query = {}) {
    const requestQuery = { ...(query || {}) };
    if (state.userId && !requestQuery.user_id) requestQuery.user_id = state.userId;
    if (state.activeEmployeeId && !requestQuery.employee_id) requestQuery.employee_id = state.activeEmployeeId;
    
    const qs = new URLSearchParams(requestQuery).toString();
    const url = `${path}${qs ? '?' + qs : ''}`;
    
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : null
    });
    
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.error) throw payload.error || new Error(`HTTP ${res.status}`);
    return payload.data;
  },
  async upload(path, files, query = {}) {
    const requestQuery = { ...(query || {}) };
    if (state.userId && !requestQuery.user_id) requestQuery.user_id = state.userId;
    const qs = new URLSearchParams(requestQuery).toString();
    const url = `${path}${qs ? '?' + qs : ''}`;

    const form = new FormData();
    Array.from(files || []).forEach((file) => form.append("files", file));

    const res = await fetch(url, { method: "POST", body: form });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.error) throw payload.error || new Error(`HTTP ${res.status}`);
    return payload.data;
  },
  get: (path, q) => api.req("GET", path, null, q),
  post: (path, b, q) => api.req("POST", path, b, q),
  put: (path, b, q) => api.req("PUT", path, b, q),
  del: (path, q) => api.req("DELETE", path, null, q)
};

// =================UI 渲染中心=================
const ui = {
  buildImagePreviewUrl(treePath, { bustCache = true } = {}) {
    const query = new URLSearchParams({ user_id: state.userId, path: String(treePath || "") });
    if (bustCache) query.set("ts", String(Date.now()));
    return `/memory/file-preview?${query.toString()}`;
  },

  appendChat(type, content) {
    const tpl = $("chatItemTemplate").content.cloneNode(true);
    const item = tpl.querySelector(".chat-item");
    item.classList.add(type);
    
    const body = tpl.querySelector(".chat-body");
    const isString = typeof content === "string";
    const text = isString ? content : JSON.stringify(content, null, 2);

    if (['user', 'assistant'].includes(type)) {
      tpl.querySelector(".chat-meta").textContent = type === 'user' ? '👤 用户' : '🤖 助手';
      const pre = document.createElement("pre");
      pre.textContent = text;
      body.appendChild(pre);
    } else {
      item.innerHTML = `
        <details class="chat-collapsible">
          <summary>${type === 'error' ? '❌ 错误' : '🔧 ' + type}</summary>
          <pre>${text}</pre>
        </details>`;
    }
    
    els.chatLog.appendChild(item);
    els.chatLog.scrollTop = els.chatLog.scrollHeight;
  },

  appendImageToChat(imageInfo) {
    if (!imageInfo?.path || !state.userId) return;
    const tpl = $("chatItemTemplate").content.cloneNode(true);
    const item = tpl.querySelector(".chat-item");
    item.classList.add("assistant");
    tpl.querySelector(".chat-meta").textContent = "🖼️ 图片结果";

    const body = tpl.querySelector(".chat-body");
    const card = document.createElement("div");
    card.className = "chat-image-card";

    const img = document.createElement("img");
    img.src = ui.buildImagePreviewUrl(imageInfo.path, { bustCache: true });
    img.alt = imageInfo.fileName || "生成图片";
    img.loading = "lazy";

    const meta = document.createElement("div");
    meta.className = "chat-image-meta";
    const metaParts = [];
    if (imageInfo.fileName) metaParts.push(imageInfo.fileName);
    if (imageInfo.model) metaParts.push(imageInfo.model);
    if (imageInfo.aspectRatio) metaParts.push(`比例 ${imageInfo.aspectRatio}`);
    if (imageInfo.resolution) metaParts.push(imageInfo.resolution);
    meta.textContent = metaParts.join(" · ");

    card.appendChild(img);
    if (meta.textContent) card.appendChild(meta);
    body.appendChild(card);

    els.chatLog.appendChild(item);
    els.chatLog.scrollTop = els.chatLog.scrollHeight;
  },
  
  updateTokenBoard(status) {
    if(!status) return;
    const {
      thresholds = {},
      resident_tokens = 0,
      dialogue_tokens = 0,
      buffer_tokens = 0,
      total_tokens = 0,
      is_flushing = false
    } = status;
    const limit = thresholds.total_limit || 200000;
    const residentBudget = thresholds.resident_limit || 0;
    const dialogueBudget = thresholds.dialogue_limit || Math.max(0, limit - residentBudget);
    const bufferSharedRemaining = Math.max(0, dialogueBudget - dialogue_tokens);
    const fmt = (n) => Number(n || 0).toLocaleString("zh-CN");
    
    const getPct = (val) => Math.min(100, (val / limit) * 100);
    els.resBar.style.width = `${getPct(resident_tokens)}%`;
    els.diaBar.style.left = `${getPct(resident_tokens)}%`;
    els.diaBar.style.width = `${getPct(dialogue_tokens)}%`;
    els.bufBar.style.left = `${Math.min(100, getPct(resident_tokens) + getPct(dialogue_tokens))}%`;
    els.bufBar.style.width = `${getPct(buffer_tokens)}%`;
    
    els.tokenSum.innerHTML = [
      `刷盘状态: <b>${is_flushing ? "刷盘中" : "空闲"}</b>`,
      `常驻区: <b>${fmt(resident_tokens)} token</b> / <b>${fmt(residentBudget)} token</b>`,
      `对话区: <b>${fmt(dialogue_tokens)} token</b> / <b>${fmt(dialogueBudget)} token</b>`,
      `缓冲区: <b>${fmt(buffer_tokens)} token</b> / 共享上限 <b>${fmt(dialogueBudget)} token</b> (剩余 ${fmt(bufferSharedRemaining)} token)`,
      `总计: <b>${fmt(total_tokens)} token</b> / <b>${fmt(limit)} token</b>`
    ].join("<br>");
  },

  renderTree() {
    els.tree.innerHTML = "";
    const visibleTree = state.dataTree.filter(entry => entry.path !== '.');
    if (!visibleTree.length) return els.tree.innerHTML = "<div class='text-muted text-center mt-2'>空目录</div>";
    const pathSet = new Set(visibleTree.map(entry => entry.path));
    const parentPath = (path) => {
      const idx = path.lastIndexOf('/');
      return idx === -1 ? '' : path.slice(0, idx);
    };
    
    const buildNode = (entry, depth = 0) => {
      const isExpanded = state.expandedDirs.has(entry.path);
      const parts = entry.path.split('/').filter(Boolean);
      const isRootFolder = entry.is_dir && entry.path.startsWith('/') && parts.length === 1;
      const isEmployeeMemberFolder = entry.is_dir && parts[0] === "employee" && parts.length === 2;
      let displayName = parts[parts.length - 1] || entry.path;
      if (isRootFolder) displayName = `${parts[0]}/`;
      else if (isEmployeeMemberFolder) displayName = `${parts[1]}/`;
      else if (entry.is_dir) displayName = `${displayName}/`;
      const row = document.createElement("div");
      row.className = `tree-row ${entry.is_dir ? 'dir' : 'file'} ${state.selectedFile?.path === entry.path ? 'active' : ''}`;
      row.style.paddingLeft = `${depth * 12 + 8}px`;
      row.innerHTML = `<span>${entry.is_dir ? (isExpanded ? '📂' : '📁') : '📄'}</span> <span>${displayName}</span>`;
      
      row.onclick = () => {
        if (entry.is_dir) {
          isExpanded ? state.expandedDirs.delete(entry.path) : state.expandedDirs.add(entry.path);
          ui.renderTree();
        } else {
          logic.selectFile(entry.path);
        }
      };
      els.tree.appendChild(row);
      
      if (entry.is_dir && isExpanded) {
        const children = visibleTree.filter(c => c.path.startsWith(entry.path + '/') && c.path.split('/').length === entry.path.split('/').length + 1);
        children.forEach(c => buildNode(c, depth + 1));
      }
    };

    const roots = visibleTree.filter(c => !pathSet.has(parentPath(c.path)));
    roots.forEach(r => buildNode(r, 0));
  },

  updateEditor() {
    const selected = state.selectedFile;
    const activePath = String(selected?.path || "");
    const selectedKind = String(selected?.kind || "none");
    const file = findEditableFile(activePath);
    const cachedTextContent = state.textFileCache[activePath];
    const globallyLocked = !state.userId || state.isChatting;
    const canDelete = !!activePath && !globallyLocked && isDeletableFilePath(activePath);

    // 每次更新编辑区先回到“文本模式”，仅在明确是图片文件时再切换到预览模式。
    els.fileImagePreview.hidden = true;
    els.fileImagePreview.style.display = "none";
    els.fileImagePreviewImg.removeAttribute("src");
    els.fileImagePreviewImg.alt = "";
    els.fileImagePreviewPath.textContent = "";
    els.fileContent.style.display = "";

    if (selectedKind === "image" && state.userId) {
      const displayName = fileNameFromPath(activePath) || "图片文件";
      els.fileName.textContent = displayName;
      els.fileImagePreview.hidden = false;
      els.fileImagePreview.style.display = "flex";
      els.fileImagePreviewImg.src = ui.buildImagePreviewUrl(activePath, { bustCache: true });
      els.fileImagePreviewPath.textContent = activePath;
      els.fileContent.style.display = "none";
      els.fileContent.value = "";
      els.btnDeleteFile.disabled = !canDelete;
      els.btnSaveFile.disabled = true;
      return;
    }

    if (selectedKind === "text") {
      els.fileName.textContent = fileNameFromPath(activePath) || "未选择文件";
      els.btnDeleteFile.disabled = !canDelete;
      if (file && typeof file.content === "string") {
        els.fileContent.value = file.content;
        els.btnSaveFile.disabled = globallyLocked;
        return;
      }
      if (state.loadingTextFilePath === activePath) {
        els.fileContent.value = "正在加载文件内容...";
        els.btnSaveFile.disabled = true;
        return;
      }
      if (typeof cachedTextContent === "string") {
        els.fileContent.value = cachedTextContent;
        els.btnSaveFile.disabled = globallyLocked;
        return;
      }
      els.fileContent.value = "文本文件加载失败，请重试。";
      els.btnSaveFile.disabled = true;
      return;
    }

    if (activePath) {
      els.fileName.textContent = fileNameFromPath(activePath) || "未选择文件";
      els.fileContent.value = "不支持该文件预览和编辑。";
      els.btnDeleteFile.disabled = !canDelete;
      els.btnSaveFile.disabled = true;
      return;
    }

    els.fileName.textContent = "未选择文件";
    els.fileContent.value = "";
    els.btnDeleteFile.disabled = true;
    els.btnSaveFile.disabled = true;
  },

  applySettings(settings) {
    if (!settings) return;
    $("model").value = settings.model || "";
    $("apiKey").value = settings.api_key || "";
    $("baseUrl").value = settings.base_url || "";
    $("totalTokenLimit").value = settings.total_token_limit != null ? String(settings.total_token_limit) : "";
    const tokenizerModel = String(settings.tokenizer_model || "").trim().toLowerCase();
    $("tokenizerModel").value = TOKENIZER_OPTIONS.includes(tokenizerModel) ? tokenizerModel : DEFAULT_TOKENIZER_MODEL;
  },

  lockUI(locked) {
    const disabled = !state.userId || locked;
    [
      els.empSelect, els.btnNewEmp, els.btnReloadEmp, els.btnUploadBrandLibrary, els.uploadBrandLibraryInput,
      els.btnResetMemory, els.btnReloadFiles,
      els.btnSettings, els.btnForceFlush, $("saveConfigBtn"), els.btnDeleteFile, els.btnSaveFile,
      els.msgInput, els.chatForm.querySelector("button")
    ].forEach(el => el.disabled = disabled);
    if (!disabled) ui.updateEditor();
    if (!state.userId) els.msgInput.placeholder = "请先配置并应用用户 ID...";
  }
};

// =================核心业务逻辑=================
const logic = {
  parseJsonObject(value) {
    if (value && typeof value === "object") return value;
    if (typeof value !== "string") return null;
    const text = value.trim();
    if (!text) return null;
    try {
      const parsed = JSON.parse(text);
      return parsed && typeof parsed === "object" ? parsed : null;
    } catch {
      return null;
    }
  },

  extractGeneratedImage(payload) {
    if (!payload || payload.tool_name !== "image_gen_edit") return null;
    const resultEnvelope = payload.result;
    if (!resultEnvelope || typeof resultEnvelope !== "object" || resultEnvelope.error) return null;
    const data = this.parseJsonObject(resultEnvelope.result);
    if (!data) return null;

    const path = String(data.workspace_relative_path || data.brand_relative_path || "").trim();
    if (!path || !isImageTreePath(path)) return null;
    return {
      path,
      fileName: String(data.workspace_file_name || data.brand_file_name || fileNameFromPath(path)),
      model: String(data.model || ""),
      aspectRatio: String(data.aspect_ratio || ""),
      resolution: String(data.resolution || ""),
    };
  },

  normalizeHistoryMessage(message) {
    if (!message || typeof message !== "object") {
      return { type: "assistant", payload: "" };
    }
    const role = String(message.role || "assistant");
    const zone = String(message.zone || "");
    const content = message.content;
    const parsedPayload = this.parseJsonObject(content);

    // 工具区历史消息需要恢复为 tool_call/tool_result 事件视图，
    // 避免被当作 assistant 普通文本渲染。
    if (zone === "tool") {
      if (parsedPayload) {
        return { type: "tool_result", payload: parsedPayload };
      }
      return { type: role || "tool_result", payload: String(content || "") };
    }

    return { type: role, payload: content };
  },

  parseIntOrNull(value) {
    const parsed = parseInt(String(value ?? "").trim(), 10);
    return Number.isFinite(parsed) ? parsed : null;
  },

  async ensureTextFileLoaded(path) {
    const targetPath = String(path || "").trim();
    if (!targetPath || !isEditableTextTreePath(targetPath)) return;
    const editableFile = findEditableFile(targetPath);
    if (editableFile && typeof editableFile.content === "string") {
      state.textFileCache[targetPath] = editableFile.content;
      return;
    }
    if (typeof state.textFileCache[targetPath] === "string") return;

    state.loadingTextFilePath = targetPath;
    ui.updateEditor();
    try {
      const data = await api.get("/memory/file-content", { path: targetPath });
      state.textFileCache[targetPath] = String(data?.content ?? "");
    } catch (err) {
      ui.appendChat("error", "读取文件失败: " + err.message);
    } finally {
      if (state.loadingTextFilePath === targetPath) state.loadingTextFilePath = "";
      ui.updateEditor();
    }
  },

  async selectFile(path) {
    const selected = buildSelectedFile(path);
    if (!selected) return;
    state.activeFile = selected.path;
    state.selectedFile = selected;
    ui.renderTree();
    ui.updateEditor();
    if (selected.kind === "text") {
      await this.ensureTextFileLoaded(selected.path);
    }
  },

  async init() {
    els.userId.value = state.userId;
    ui.lockUI(false);
    if (state.userId) await logic.switchUser();
    
    setInterval(() => state.activeEmployeeId && logic.refreshStatus(), 8000);
    this.bindEvents();
  },

  async switchUser() {
    const id = els.userId.value.trim();
    if (!id) return ui.appendChat('error', "用户ID不能为空");
    
    state.userId = id;
    localStorage.setItem(CONFIG.storageKey, id);
    ui.lockUI(false);
    els.chatLog.innerHTML = "";
    
    try {
      await this.loadSettings();
      const data = await api.get("/employees");
      state.employees = data.employees || [];
      if(!state.employees.length) await logic.createEmployee();
      
      state.activeEmployeeId = state.employees[0]?.employee_id || "";
      state.activeFile = null;
      state.selectedFile = null;
      state.files = [];
      state.dataTree = [];
      state.textFileCache = {};
      state.loadingTextFilePath = "";
      this.renderEmpSelect();
      await this.loadContext({ refreshFiles: true, resetExpandedDirs: true });
    } catch (err) {
      ui.appendChat('error', "用户切换失败: " + err.message);
    }
  },

  async loadSettings() {
    if (!state.userId) return;
    const settings = await api.get("/settings");
    state.settings = settings || null;
    ui.applySettings(state.settings);
  },

  async saveSettings() {
    if (!state.userId) return ui.appendChat('error', "请先配置用户 ID");
    const model = $("model").value.trim();
    const apiKey = $("apiKey").value.trim();
    const baseUrl = $("baseUrl").value.trim();
    const totalTokenLimit = this.parseIntOrNull($("totalTokenLimit").value);
    const tokenizerModel = String($("tokenizerModel").value || "").trim().toLowerCase();

    if (totalTokenLimit == null) {
      return ui.appendChat('error', "请填写合法的 Total Token Limit");
    }
    if (!TOKENIZER_OPTIONS.includes(tokenizerModel)) {
      return ui.appendChat('error', "请选择合法的 Tokenizer");
    }

    const latest = await api.put("/settings", {
      user_id: state.userId,
      model,
      api_key: apiKey,
      base_url: baseUrl,
      total_token_limit: totalTokenLimit,
      tokenizer_model: tokenizerModel
    });
    state.settings = latest || null;
    ui.applySettings(state.settings);
    ui.appendChat('meta', "用户配置已更新");
  },

  async manualFlush() {
    if (!state.userId || !state.activeEmployeeId) return ui.appendChat('error', "请先选择用户与员工");
    const body = { user_id: state.userId, employee_id: state.activeEmployeeId };
    const data = await api.post("/memory/flush", body);
    const accepted = !!data?.accepted;
    ui.appendChat("meta", accepted ? "已触发手动刷盘" : "当前已有刷盘任务在执行");
    await this.refreshStatus();
  },

  async resetMemory() {
    const selectedEmployeeId = extractEmployeeIdFromTreePath(state.selectedFile?.path);
    const targetEmployeeId = selectedEmployeeId || state.activeEmployeeId;
    if (!state.userId || !targetEmployeeId) return ui.appendChat('error', "请先选择用户与员工");
    const confirmed = window.confirm("确认重置记忆吗？将重置 memory.md 与 notebook 下的记忆文件。");
    if (!confirmed) return;
    await api.post("/memory/reset", null, { employee_id: targetEmployeeId });
    await this.refreshFiles();
    await this.refreshStatus();
    ui.appendChat("meta", `员工 #${targetEmployeeId} 记忆已重置（memory.md 与 notebook 下文件）`);
  },

  async deleteSelectedFile() {
    const selected = state.selectedFile;
    if (!selected?.path) return ui.appendChat("error", "未选择文件");
    if (!isDeletableFilePath(selected.path)) {
      return ui.appendChat("error", "仅允许删除 brand_library 与 skill_library 下的文件");
    }
    const confirmed = window.confirm(`确认删除文件吗？\n${selected.path}`);
    if (!confirmed) return;
    await api.del("/memory/file", { path: selected.path });
    if (state.loadingTextFilePath === selected.path) {
      state.loadingTextFilePath = "";
    }
    delete state.textFileCache[selected.path];
    state.activeFile = null;
    state.selectedFile = null;
    await this.refreshFiles();
    ui.appendChat("meta", `已删除文件：${selected.path}`);
  },

  async uploadBrandLibraryFiles(fileList) {
    if (!state.userId) return ui.appendChat("error", "请先配置并应用用户 ID");
    const files = Array.from(fileList || []).filter(Boolean);
    if (!files.length) return;
    const result = await api.upload("/memory/brand-library/upload", files);
    await this.refreshFiles();
    const uploaded = Array.isArray(result?.uploaded) ? result.uploaded : [];
    if (!uploaded.length) {
      ui.appendChat("meta", "素材上传完成");
      return;
    }
    const renamedCount = uploaded.filter(item => !!item?.renamed).length;
    const previewNames = uploaded.slice(0, 5).map(item => String(item.file_name || "")).filter(Boolean);
    const previewText = previewNames.join("、");
    const suffix = uploaded.length > 5 ? ` 等 ${uploaded.length} 个文件` : `：${previewText}`;
    const detailParts = [];
    if (renamedCount > 0) detailParts.push(`${renamedCount} 个同名文件已自动重命名`);
    const detail = detailParts.length ? `（${detailParts.join("，")}）` : "";
    ui.appendChat("meta", `素材上传成功${suffix}${detail}`);
  },

  async createEmployee() {
    const data = await api.post("/employees", { user_id: state.userId });
    state.employees.push(data.employee);
    state.activeEmployeeId = data.employee.employee_id;
    this.renderEmpSelect();
  },

  renderEmpSelect() {
    els.empSelect.innerHTML = state.employees.map(e => 
      `<option value="${e.employee_id}" ${e.employee_id === state.activeEmployeeId ? 'selected' : ''}>员工 #${e.employee_id}</option>`
    ).join('');
  },

  async loadContext({ refreshFiles = false, resetExpandedDirs = false } = {}) {
    if(!state.activeEmployeeId) return;
    try {
      const history = await api.get("/employee-messages", { limit: "50" });
      els.chatLog.innerHTML = "";
      (history.messages || []).forEach(m => {
        const normalized = this.normalizeHistoryMessage(m);
        ui.appendChat(normalized.type, normalized.payload);
        const imageInfo = this.extractGeneratedImage(
          normalized && normalized.type === "tool_result" ? normalized.payload : null
        );
        if (imageInfo) ui.appendImageToChat(imageInfo);
      });

      if (refreshFiles) {
        await this.refreshFiles({ resetExpandedDirs });
      }
      
      await this.refreshStatus();
    } catch (err) {
      console.warn("上下文加载失败", err);
    }
  },

  async refreshFiles({ resetExpandedDirs = false } = {}) {
    if (resetExpandedDirs) state.expandedDirs = new Set();
    const currentSelectedPath = String(state.selectedFile?.path || "");
    const mem = await api.get("/memory/files");
    state.files = mem.files || [];
    state.dataTree = mem.tree || [];
    const currentPaths = new Set(
      state.dataTree
        .filter(entry => !entry.is_dir)
        .map(entry => String(entry.path || ""))
    );
    Object.keys(state.textFileCache).forEach((path) => {
      if (!currentPaths.has(path)) delete state.textFileCache[path];
    });
    if (state.loadingTextFilePath && !currentPaths.has(state.loadingTextFilePath)) {
      state.loadingTextFilePath = "";
    }
    if (state.expandedDirs.size === 0) {
      state.expandedDirs = new Set(
        state.dataTree
          .filter(entry => entry.is_dir && entry.path !== ".")
          .map(entry => entry.path)
      );
    }
    if (currentSelectedPath) {
      const stillExists = state.dataTree.some(entry => entry.path === currentSelectedPath && !entry.is_dir);
      if (stillExists) {
        state.activeFile = currentSelectedPath;
        state.selectedFile = buildSelectedFile(currentSelectedPath);
      } else {
        state.activeFile = null;
        state.selectedFile = null;
      }
    }
    ui.renderTree();
    ui.updateEditor();
  },

  async refreshStatus() {
    const model = $("model").value.trim();
    const query = model ? { model } : {};
    const status = await api.get("/memory/status", query).catch(()=>null);
    ui.updateTokenBoard(status);
  },

  async sendMessage(msg) {
    if (state.isChatting || !state.activeEmployeeId) return;
    state.isChatting = true;
    ui.lockUI(true);
    ui.appendChat('user', msg);
    
    try {
      const payload = { user_id: state.userId, employee_id: state.activeEmployeeId, message: msg };
      const res = await fetch("/chat/stream", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value);
        const matches = [...chunk.matchAll(/data:\s*({.*})/g)];
        matches.forEach(m => {
          try {
            const ev = JSON.parse(m[1]);
            if (ev.type === 'assistant_final') ui.appendChat('assistant', ev.payload.content);
            else if (ev.type === 'tool_call') ui.appendChat(ev.type, ev.payload);
            else if (ev.type === 'tool_result') {
              ui.appendChat(ev.type, ev.payload);
              const imageInfo = this.extractGeneratedImage(ev.payload);
              if (imageInfo) ui.appendImageToChat(imageInfo);
            }
            else if (ev.type === 'memory_status') ui.updateTokenBoard(ev.payload);
          } catch(e) {}
        });
      }
    } catch (err) {
      ui.appendChat('error', err.message);
    } finally {
      state.isChatting = false;
      ui.lockUI(false);
      await this.refreshStatus();
    }
  },

  bindEvents() {
    els.btnUser.onclick = () => this.switchUser();
    
    els.chatForm.onsubmit = (e) => {
      e.preventDefault();
      const text = els.msgInput.value.trim();
      if (!text) return;
      els.msgInput.value = "";
      this.sendMessage(text);
    };
    
    els.msgInput.onkeydown = (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); els.chatForm.requestSubmit(); }
    };

    els.empSelect.onchange = (e) => { state.activeEmployeeId = e.target.value; this.loadContext(); };
    els.btnNewEmp.onclick = async () => { await this.createEmployee(); await this.loadContext({ refreshFiles: true }); };
    els.btnReloadEmp.onclick = () => this.switchUser();
    els.btnReloadFiles.onclick = async () => {
      try {
        await this.refreshFiles();
      } catch (err) {
        ui.appendChat('error', "刷新目录失败: " + err.message);
      }
    };
    els.btnUploadBrandLibrary.onclick = () => {
      if (!state.userId || state.isChatting) return;
      els.uploadBrandLibraryInput.click();
    };
    els.uploadBrandLibraryInput.onchange = async (e) => {
      const selectedFiles = e.target.files;
      if (!selectedFiles || selectedFiles.length === 0) return;
      try {
        await this.uploadBrandLibraryFiles(selectedFiles);
      } catch (err) {
        ui.appendChat("error", "上传素材失败: " + err.message);
      } finally {
        e.target.value = "";
      }
    };
    els.btnResetMemory.onclick = async () => {
      try {
        await this.resetMemory();
      } catch (err) {
        ui.appendChat('error', "重置记忆失败: " + err.message);
      }
    };

    els.btnDeleteFile.onclick = async () => {
      try {
        await this.deleteSelectedFile();
      } catch (err) {
        ui.appendChat("error", "删除文件失败: " + err.message);
      }
    };

    els.btnSaveFile.onclick = async () => {
      try {
        const selected = state.selectedFile;
        if(!selected?.path) return ui.appendChat("error", "未选择文件");
        if (selected.kind !== "text") {
          return ui.appendChat("error", "当前文件不可编辑");
        }

        const content = els.fileContent.value;
        const result = await api.put(
          "/memory/file-content",
          { content, mode: "overwrite" },
          { path: selected.path }
        );
        const latestContent = typeof result?.content === "string" ? result.content : content;
        const file = findEditableFile(selected.path);
        if (file) file.content = latestContent;
        state.textFileCache[selected.path] = latestContent;
        await this.refreshFiles();
        ui.appendChat("meta", `保存成功：${selected.path}`);
      } catch (err) {
        ui.appendChat("error", "保存修改失败: " + err.message);
      }
    };

    els.btnForceFlush.onclick = async () => {
      try {
        await this.manualFlush();
      } catch (err) {
        ui.appendChat('error', "手动刷盘失败: " + err.message);
      }
    };

    els.btnSettings.onclick = async () => {
      try {
        await this.loadSettings();
      } catch (err) {
        ui.appendChat('error', "加载用户配置失败: " + err.message);
      }
      els.modal.showModal();
    };
    $("closeSettingsBtn").onclick = () => els.modal.close();
    $("saveConfigBtn").onclick = async () => {
      try {
        await this.saveSettings();
        els.modal.close();
      } catch (err) {
        ui.appendChat('error', "保存用户配置失败: " + err.message);
      }
    };
  }
};

// 启动
document.addEventListener('DOMContentLoaded', () => logic.init());
