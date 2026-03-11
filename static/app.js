// =================配置与状态=================
const CONFIG = {
  storageKey: "agent_demo_user_id"
};

const state = {
  userId: localStorage.getItem(CONFIG.storageKey) || "",
  employees: [],
  activeEmployeeId: "",
  settings: null,
  files: [],
  dataTree: [],
  activeFile: null,
  expandedDirs: new Set(),
  isChatting: false,
};

// =================DOM 节点缓存=================
const $ = (id) => document.getElementById(id);
const els = {
  userId: $("userIdInput"), btnUser: $("switchUserBtn"),
  chatLog: $("chatLog"), chatForm: $("chatForm"), msgInput: $("messageInput"),
  empSelect: $("employeeSelect"), btnNewEmp: $("newEmployeeBtn"), btnReloadEmp: $("reloadEmployeeBtn"),
  btnResetMemory: $("resetMemoryBtn"), btnReloadFiles: $("reloadFilesBtn"),
  tree: $("directoryTree"), fileContent: $("fileContent"), fileName: $("activeFileName"), btnSaveFile: $("saveFileBtn"),
  modal: $("settingsModal"), btnSettings: $("openSettingsBtn"),
  tokenSum: $("tokenSummary"), resBar: $("residentBar"), diaBar: $("dialogueBar"), bufBar: $("bufferBar"),
  btnForceFlush: $("forceFlushBtn")
};

const toEditableRelativePath = (path) => {
  const raw = String(path || "").trim();
  if (!raw) return "";
  if (raw.startsWith("/employee/")) return raw.slice("/employee/".length);
  if (raw.startsWith("employee/")) return raw.slice("employee/".length);
  return raw;
};

const findEditableFile = (path) => {
  const normalized = toEditableRelativePath(path);
  if (!normalized) return null;
  return state.files.find(f => f.relative_path === normalized || f.file_name === normalized) || null;
};

// =================API 封装库=================
const api = {
  async req(method, path, body = null, query = {}) {
    if (state.userId) query.user_id = state.userId;
    if (state.activeEmployeeId) query.employee_id = state.activeEmployeeId;
    
    const qs = new URLSearchParams(query).toString();
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
  get: (path, q) => api.req("GET", path, null, q),
  post: (path, b, q) => api.req("POST", path, b, q),
  put: (path, b, q) => api.req("PUT", path, b, q)
};

// =================UI 渲染中心=================
const ui = {
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
      const isRootFolder = entry.path.startsWith('/') && parts.length === 1;
      const isEmployeeSecondDir = entry.is_dir && parts[0] === "employee" && parts.length === 2;
      const displayName = isRootFolder
        ? entry.path
        : (isEmployeeSecondDir ? `/${parts[1]}` : (parts[parts.length - 1] || entry.path));
      const row = document.createElement("div");
      row.className = `tree-row ${entry.is_dir ? 'dir' : 'file'} ${state.activeFile === entry.path ? 'active' : ''}`;
      row.style.paddingLeft = `${depth * 12 + 8}px`;
      row.innerHTML = `<span>${entry.is_dir ? (isExpanded ? '📂' : '📁') : '📄'}</span> <span>${displayName}</span>`;
      
      row.onclick = () => {
        if (entry.is_dir) {
          isExpanded ? state.expandedDirs.delete(entry.path) : state.expandedDirs.add(entry.path);
          ui.renderTree();
        } else {
          state.activeFile = entry.path;
          ui.updateEditor();
          ui.renderTree();
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
    const file = findEditableFile(state.activeFile);
    els.fileName.textContent = file ? file.file_name : "未选择文件";
    els.fileContent.value = file ? file.content : "";
  },

  applySettings(settings) {
    if (!settings) return;
    $("model").value = settings.model || "";
    $("apiKey").value = settings.api_key || "";
    $("baseUrl").value = settings.base_url || "";
    $("maxToolRounds").value = settings.max_tool_rounds != null ? String(settings.max_tool_rounds) : "";
    $("totalTokenLimit").value = settings.total_token_limit != null ? String(settings.total_token_limit) : "";
  },

  lockUI(locked) {
    const disabled = !state.userId || locked;
    [els.empSelect, els.btnNewEmp, els.btnReloadEmp, els.btnResetMemory, els.btnReloadFiles, els.btnSettings, els.btnForceFlush, $("saveConfigBtn"), $("saveFileBtn"), els.msgInput, els.chatForm.querySelector("button")].forEach(el => el.disabled = disabled);
    if (!state.userId) els.msgInput.placeholder = "请先配置并应用用户 ID...";
  }
};

// =================核心业务逻辑=================
const logic = {
  parseIntOrNull(value) {
    const parsed = parseInt(String(value ?? "").trim(), 10);
    return Number.isFinite(parsed) ? parsed : null;
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
      this.renderEmpSelect();
      await this.loadContext();
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
    const maxToolRounds = this.parseIntOrNull($("maxToolRounds").value);
    const totalTokenLimit = this.parseIntOrNull($("totalTokenLimit").value);

    if (maxToolRounds == null || totalTokenLimit == null) {
      return ui.appendChat('error', "请填写合法的 Max Tool Rounds 和 Total Token Limit");
    }

    const latest = await api.put("/settings", {
      user_id: state.userId,
      model,
      api_key: apiKey,
      base_url: baseUrl,
      max_tool_rounds: maxToolRounds,
      total_token_limit: totalTokenLimit
    });
    state.settings = latest || null;
    ui.applySettings(state.settings);
    ui.appendChat('meta', "用户配置已更新");
  },

  async manualFlush() {
    if (!state.userId || !state.activeEmployeeId) return ui.appendChat('error', "请先选择用户与员工");
    const maxToolRounds = this.parseIntOrNull($("maxToolRounds").value);
    const body = { user_id: state.userId, employee_id: state.activeEmployeeId };
    if (maxToolRounds != null) body.max_tool_rounds = maxToolRounds;
    const data = await api.post("/memory/flush", body);
    const accepted = !!data?.accepted;
    ui.appendChat("meta", accepted ? "已触发手动刷盘" : "当前已有刷盘任务在执行");
    await this.refreshStatus();
  },

  async resetMemory() {
    if (!state.userId || !state.activeEmployeeId) return ui.appendChat('error', "请先选择用户与员工");
    const confirmed = window.confirm("确认重置记忆吗？将重置 memory.md 与 notebook 下的记忆文件。");
    if (!confirmed) return;
    await api.post("/memory/reset");
    await this.refreshFiles();
    await this.refreshStatus();
    ui.appendChat("meta", "记忆已重置（memory.md 与 notebook 下文件）");
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

  async loadContext() {
    if(!state.activeEmployeeId) return;
    try {
      state.expandedDirs = new Set();
      const history = await api.get("/employee-messages", { limit: "50" });
      els.chatLog.innerHTML = "";
      (history.messages || []).forEach(m => ui.appendChat(m.role, m.content));

      await this.refreshFiles();
      
      await this.refreshStatus();
    } catch (err) {
      console.warn("上下文加载失败", err);
    }
  },

  async refreshFiles() {
    const currentActive = state.activeFile;
    const mem = await api.get("/memory/files");
    state.files = mem.files || [];
    state.dataTree = mem.tree || [];
    if (state.expandedDirs.size === 0) {
      state.expandedDirs = new Set(
        state.dataTree
          .filter(entry => entry.is_dir && entry.path !== ".")
          .map(entry => entry.path)
      );
    }
    if (currentActive) {
      const stillExists = state.dataTree.some(entry => entry.path === currentActive && !entry.is_dir);
      state.activeFile = stillExists ? currentActive : null;
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
      const maxToolRounds = this.parseIntOrNull($("maxToolRounds").value);
      const payload = { user_id: state.userId, employee_id: state.activeEmployeeId, message: msg };
      if (maxToolRounds != null) payload.max_tool_rounds = maxToolRounds;
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
            else if (ev.type === 'tool_call' || ev.type === 'tool_result') ui.appendChat(ev.type, ev.payload);
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
    els.btnNewEmp.onclick = async () => { await this.createEmployee(); await this.loadContext(); };
    els.btnReloadEmp.onclick = () => this.switchUser();
    els.btnReloadFiles.onclick = async () => {
      try {
        await this.refreshFiles();
      } catch (err) {
        ui.appendChat('error', "刷新目录失败: " + err.message);
      }
    };
    els.btnResetMemory.onclick = async () => {
      try {
        await this.resetMemory();
      } catch (err) {
        ui.appendChat('error', "重置记忆失败: " + err.message);
      }
    };

    els.btnSaveFile.onclick = async () => {
      try {
        if(!state.activeFile) return ui.appendChat("error", "未选择文件");
        const file = findEditableFile(state.activeFile);
        if (!file) return ui.appendChat("error", "该文件不支持直接编辑");

        const content = els.fileContent.value;
        const result = await api.put(`/memory/files/${encodeURIComponent(file.file_name)}`, { content, mode: "overwrite" });
        file.content = typeof result?.content === "string" ? result.content : content;
        await this.refreshFiles();
        ui.appendChat("meta", `保存成功：${file.file_name}`);
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
