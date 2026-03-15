import { api } from "./api_client.js";
import { $, els } from "./dom.js";
import {
  CONFIG,
  TOKENIZER_OPTIONS,
  buildSelectedFile,
  fileNameFromPath,
  findEditableFile,
  isDeletableFilePath,
  isEditableTextTreePath,
  isImageTreePath,
  state
} from "./state.js";
import { setFileSelectHandler, ui } from "./ui.js";

const userQuery = () => ({ user_id: state.userId });
const employeeQuery = (employeeId = state.activeEmployeeId) => ({
  user_id: state.userId,
  employee_id: String(employeeId || "").trim() || "1"
});

export const logic = {
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
      resolution: String(data.resolution || "")
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
      const data = await api.get("/storage/file-content", { ...userQuery(), path: targetPath });
      state.textFileCache[targetPath] = String(data?.content ?? "");
    } catch (err) {
      ui.appendChat("error", `读取文件失败: ${err.message}`);
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
    setFileSelectHandler((path) => this.selectFile(path));
    if (state.userId) await this.switchUser();

    setInterval(() => state.activeEmployeeId && this.refreshStatus(), 8000);
    this.bindEvents();
  },

  async switchUser() {
    const id = els.userId.value.trim();
    if (!id) {
      ui.appendChat("error", "用户ID不能为空");
      return;
    }

    state.userId = id;
    localStorage.setItem(CONFIG.storageKey, id);
    ui.lockUI(false);
    els.chatLog.innerHTML = "";

    try {
      await this.loadSettings();
      const data = await api.get("/user/employees", userQuery());
      state.employees = data.employees || [];
      if (!state.employees.length) await this.createEmployee();

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
      ui.appendChat("error", `用户切换失败: ${err.message}`);
    }
  },

  async loadSettings() {
    if (!state.userId) return;
    const settings = await api.get("/user/settings", userQuery());
    state.settings = settings || null;
    ui.applySettings(state.settings);
  },

  async saveSettings() {
    if (!state.userId) {
      ui.appendChat("error", "请先配置用户 ID");
      return;
    }
    const model = $("model").value.trim();
    const apiKey = $("apiKey").value.trim();
    const baseUrl = $("baseUrl").value.trim();
    const totalTokenLimit = this.parseIntOrNull($("totalTokenLimit").value);
    const tokenizerModel = String($("tokenizerModel").value || "").trim().toLowerCase();

    if (totalTokenLimit == null) {
      ui.appendChat("error", "请填写合法的 Total Token Limit");
      return;
    }
    if (!TOKENIZER_OPTIONS.includes(tokenizerModel)) {
      ui.appendChat("error", "请选择合法的 Tokenizer");
      return;
    }

    const latest = await api.put("/user/settings", {
      user_id: state.userId,
      model,
      api_key: apiKey,
      base_url: baseUrl,
      total_token_limit: totalTokenLimit,
      tokenizer_model: tokenizerModel
    });
    state.settings = latest || null;
    ui.applySettings(state.settings);
    ui.appendChat("meta", "用户配置已更新");
  },

  async manualFlush() {
    if (!state.userId || !state.activeEmployeeId) {
      ui.appendChat("error", "请先选择用户与员工");
      return;
    }
    const data = await api.post("/chat/memory/flush", employeeQuery());
    const accepted = !!data?.accepted;
    ui.appendChat("meta", accepted ? "已触发手动刷盘" : "当前已有刷盘任务在执行");
    await this.refreshStatus();
  },

  async resetEmployee() {
    const targetEmployeeId = String(state.activeEmployeeId || "").trim();
    if (!state.userId || !targetEmployeeId) {
      ui.appendChat("error", "请先选择用户与员工");
      return;
    }
    const confirmed = window.confirm("确认重置员工吗？将重置该员工全部数据（记忆、workspace、skills 等），效果等同删除后同编号重建。");
    if (!confirmed) return;
    await api.post(`/user/employees/${encodeURIComponent(targetEmployeeId)}/reset`, null, userQuery());
    const employeesData = await api.get("/user/employees", userQuery());
    state.employees = employeesData.employees || [];
    const exists = state.employees.some((item) => item.employee_id === targetEmployeeId);
    state.activeEmployeeId = exists ? targetEmployeeId : (state.employees[0]?.employee_id || "");
    this.renderEmpSelect();
    await this.loadContext({ refreshFiles: true, resetExpandedDirs: true });
    ui.appendChat("meta", `员工 #${targetEmployeeId} 已重置（同编号重建）`);
  },

  async deleteEmployee() {
    const targetEmployeeId = String(state.activeEmployeeId || "").trim();
    if (!state.userId || !targetEmployeeId) {
      ui.appendChat("error", "请先选择要删除的员工");
      return;
    }
    const confirmed = window.confirm(`确认删除员工 #${targetEmployeeId} 吗？该员工的消息与 employee/${targetEmployeeId} 目录数据将被删除。`);
    if (!confirmed) return;
    await api.del(`/user/employees/${encodeURIComponent(targetEmployeeId)}`, userQuery());

    const employeesData = await api.get("/user/employees", userQuery());
    state.employees = employeesData.employees || [];
    state.activeEmployeeId = state.employees[0]?.employee_id || "";
    state.activeFile = null;
    state.selectedFile = null;
    state.textFileCache = {};
    state.loadingTextFilePath = "";
    this.renderEmpSelect();

    if (!state.activeEmployeeId) {
      els.chatLog.innerHTML = "";
      await this.refreshFiles({ resetExpandedDirs: true });
      ui.appendChat("meta", `员工 #${targetEmployeeId} 已删除`);
      return;
    }

    await this.loadContext({ refreshFiles: true, resetExpandedDirs: true });
    ui.appendChat("meta", `员工 #${targetEmployeeId} 已删除`);
  },

  async deleteSelectedFile() {
    const selected = state.selectedFile;
    if (!selected?.path) {
      ui.appendChat("error", "未选择文件");
      return;
    }
    if (!isDeletableFilePath(selected.path)) {
      ui.appendChat("error", "仅允许删除 brand_library 与 skill_library 下的文件");
      return;
    }
    const confirmed = window.confirm(`确认删除文件吗？\n${selected.path}`);
    if (!confirmed) return;
    await api.del("/storage/file", { ...userQuery(), path: selected.path });
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
    if (!state.userId) {
      ui.appendChat("error", "请先配置并应用用户 ID");
      return;
    }
    const files = Array.from(fileList || []).filter(Boolean);
    if (!files.length) return;
    const result = await api.upload("/storage/brand-library/upload", files, userQuery());
    await this.refreshFiles();
    const uploaded = Array.isArray(result?.uploaded) ? result.uploaded : [];
    if (!uploaded.length) {
      ui.appendChat("meta", "素材上传完成");
      return;
    }
    const renamedCount = uploaded.filter((item) => !!item?.renamed).length;
    const previewNames = uploaded.slice(0, 5).map((item) => String(item.file_name || "")).filter(Boolean);
    const previewText = previewNames.join("、");
    const suffix = uploaded.length > 5 ? ` 等 ${uploaded.length} 个文件` : `：${previewText}`;
    const detailParts = [];
    if (renamedCount > 0) detailParts.push(`${renamedCount} 个同名文件已自动重命名`);
    const detail = detailParts.length ? `（${detailParts.join("，")}）` : "";
    ui.appendChat("meta", `素材上传成功${suffix}${detail}`);
  },

  async createEmployee() {
    const data = await api.post("/user/employees", { user_id: state.userId });
    state.employees.push(data.employee);
    state.activeEmployeeId = data.employee.employee_id;
    this.renderEmpSelect();
  },

  renderEmpSelect() {
    els.empSelect.innerHTML = state.employees.map((entry) =>
      `<option value="${entry.employee_id}" ${entry.employee_id === state.activeEmployeeId ? "selected" : ""}>员工 #${entry.employee_id}</option>`
    ).join("");
    const disabled = !state.userId || state.isChatting;
    const hasEmployees = state.employees.length > 0;
    const hasActiveEmployee = !!String(state.activeEmployeeId || "").trim();
    els.empSelect.disabled = disabled || !hasEmployees;
    els.btnResetEmp.disabled = disabled || !hasActiveEmployee;
    els.btnDeleteEmp.disabled = disabled || !hasActiveEmployee;
  },

  async loadContext({ refreshFiles = false, resetExpandedDirs = false } = {}) {
    if (!state.activeEmployeeId) return;
    try {
      const history = await api.get("/user/employee-messages", { ...employeeQuery(), limit: "50" });
      els.chatLog.innerHTML = "";
      (history.messages || []).forEach((message) => {
        const normalized = this.normalizeHistoryMessage(message);
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
    const mem = await api.get("/storage/tree", userQuery());
    state.files = mem.files || [];
    state.dataTree = mem.tree || [];
    const currentPaths = new Set(
      state.dataTree
        .filter((entry) => !entry.is_dir)
        .map((entry) => String(entry.path || ""))
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
          .filter((entry) => entry.is_dir && entry.path !== ".")
          .map((entry) => entry.path)
      );
    }
    if (currentSelectedPath) {
      const stillExists = state.dataTree.some((entry) => entry.path === currentSelectedPath && !entry.is_dir);
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
    const status = await api.get("/chat/memory/status", { ...employeeQuery(), ...query }).catch(() => null);
    ui.updateTokenBoard(status);
  },

  async sendMessage(msg) {
    if (state.isChatting || !state.activeEmployeeId) return;
    state.isChatting = true;
    ui.lockUI(true);
    ui.appendChat("user", msg);

    try {
      const payload = { ...employeeQuery(), message: msg };
      const res = await fetch("/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value);
        const matches = [...chunk.matchAll(/data:\s*({.*})/g)];
        matches.forEach((match) => {
          try {
            const event = JSON.parse(match[1]);
            if (event.type === "assistant_final") ui.appendChat("assistant", event.payload.content);
            else if (event.type === "tool_call") ui.appendChat(event.type, event.payload);
            else if (event.type === "tool_result") {
              ui.appendChat(event.type, event.payload);
              const imageInfo = this.extractGeneratedImage(event.payload);
              if (imageInfo) ui.appendImageToChat(imageInfo);
            } else if (event.type === "memory_status") ui.updateTokenBoard(event.payload);
          } catch (_) {
            // ignore parse errors from incomplete chunks
          }
        });
      }
    } catch (err) {
      ui.appendChat("error", err.message);
    } finally {
      state.isChatting = false;
      ui.lockUI(false);
      await this.refreshStatus();
    }
  },

  bindEvents() {
    els.btnUser.onclick = () => this.switchUser();

    els.chatForm.onsubmit = (event) => {
      event.preventDefault();
      const text = els.msgInput.value.trim();
      if (!text) return;
      els.msgInput.value = "";
      this.sendMessage(text);
    };

    els.msgInput.onkeydown = (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        els.chatForm.requestSubmit();
      }
    };

    els.empSelect.onchange = (event) => {
      state.activeEmployeeId = event.target.value;
      this.loadContext();
    };
    els.btnNewEmp.onclick = async () => {
      await this.createEmployee();
      await this.loadContext({ refreshFiles: true });
    };
    els.btnResetEmp.onclick = async () => {
      try {
        await this.resetEmployee();
      } catch (err) {
        ui.appendChat("error", `重置员工失败: ${err.message}`);
      }
    };
    els.btnDeleteEmp.onclick = async () => {
      try {
        await this.deleteEmployee();
      } catch (err) {
        ui.appendChat("error", `删除员工失败: ${err.message}`);
      }
    };
    els.btnReloadEmp.onclick = () => this.switchUser();
    els.btnReloadFiles.onclick = async () => {
      try {
        await this.refreshFiles();
      } catch (err) {
        ui.appendChat("error", `刷新目录失败: ${err.message}`);
      }
    };
    els.btnUploadBrandLibrary.onclick = () => {
      if (!state.userId || state.isChatting) return;
      els.uploadBrandLibraryInput.click();
    };
    els.uploadBrandLibraryInput.onchange = async (event) => {
      const selectedFiles = event.target.files;
      if (!selectedFiles || selectedFiles.length === 0) return;
      try {
        await this.uploadBrandLibraryFiles(selectedFiles);
      } catch (err) {
        ui.appendChat("error", `上传素材失败: ${err.message}`);
      } finally {
        event.target.value = "";
      }
    };
    els.btnDeleteFile.onclick = async () => {
      try {
        await this.deleteSelectedFile();
      } catch (err) {
        ui.appendChat("error", `删除文件失败: ${err.message}`);
      }
    };

    els.btnSaveFile.onclick = async () => {
      try {
        const selected = state.selectedFile;
        if (!selected?.path) {
          ui.appendChat("error", "未选择文件");
          return;
        }
        if (selected.kind !== "text") {
          ui.appendChat("error", "当前文件不可编辑");
          return;
        }

        const content = els.fileContent.value;
        const result = await api.put(
          "/storage/file-content",
          { content, mode: "overwrite" },
          { ...userQuery(), path: selected.path }
        );
        const latestContent = typeof result?.content === "string" ? result.content : content;
        const file = findEditableFile(selected.path);
        if (file) file.content = latestContent;
        state.textFileCache[selected.path] = latestContent;
        await this.refreshFiles();
        ui.appendChat("meta", `保存成功：${selected.path}`);
      } catch (err) {
        ui.appendChat("error", `保存修改失败: ${err.message}`);
      }
    };

    els.btnForceFlush.onclick = async () => {
      try {
        await this.manualFlush();
      } catch (err) {
        ui.appendChat("error", `手动刷盘失败: ${err.message}`);
      }
    };

    els.btnSettings.onclick = async () => {
      try {
        await this.loadSettings();
      } catch (err) {
        ui.appendChat("error", `加载用户配置失败: ${err.message}`);
      }
      els.modal.showModal();
    };
    $("closeSettingsBtn").onclick = () => els.modal.close();
    $("saveConfigBtn").onclick = async () => {
      try {
        await this.saveSettings();
        els.modal.close();
      } catch (err) {
        ui.appendChat("error", `保存用户配置失败: ${err.message}`);
      }
    };
  }
};
