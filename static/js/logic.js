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

const normalizedUserId = () => String(state.userId || "").trim();
const normalizedEmployeeId = (employeeId = state.activeEmployeeId) =>
  String(employeeId || "").trim() || "1";
const userBasePath = () => `/users/${encodeURIComponent(normalizedUserId())}`;
const employeeBasePath = (employeeId = state.activeEmployeeId) =>
  `${userBasePath()}/employees/${encodeURIComponent(normalizedEmployeeId(employeeId))}`;
const sessionIdForEmployee = (employeeId = state.activeEmployeeId) => {
  const normalizedEmployee = normalizedEmployeeId(employeeId);
  const matchedEmployee = state.employees.find(
    (item) => String(item?.employee_id || "").trim() === normalizedEmployee
  );
  const sessionId = String(matchedEmployee?.session_id || "").trim();
  return sessionId || `employee-${normalizedEmployee}`;
};
const sessionBasePath = (employeeId = state.activeEmployeeId) =>
  `${employeeBasePath(employeeId)}/sessions/${encodeURIComponent(sessionIdForEmployee(employeeId))}`;

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
    const rawMessageKind = String(message.message_kind || "").trim().toLowerCase();
    const messageKind = rawMessageKind || "chat";
    const content = message.content;
    const parsedPayload = this.parseJsonObject(content);

    if (messageKind === "meta") {
      if (parsedPayload) {
        const eventType = String(parsedPayload.event || "").trim().toLowerCase();
        if (eventType.startsWith("graph_")) {
          return { type: eventType, payload: parsedPayload };
        }
        return { type: "system_event", payload: parsedPayload };
      }
      return { type: "system_event", payload: String(content || "") };
    }

    return { type: role, payload: content };
  },

  handleSseEvent(event) {
    if (!event || typeof event !== "object") return;
    const eventType = String(event.type || "").trim();
    const payload = event.payload;

    if (eventType === "assistant_final") {
      ui.appendChat("assistant", payload?.content || "");
      return;
    }
    if (eventType === "graph_tool_start") {
      ui.appendChat("graph_tool_start", payload);
      return;
    }
    if (eventType === "graph_tool_end") {
      ui.appendChat("graph_tool_end", payload);
      const imageInfo = this.extractGeneratedImage(payload);
      if (imageInfo) ui.appendImageToChat(imageInfo);
      return;
    }
    if (["graph_reasoning_start", "graph_reasoning_end", "graph_error", "system_event"].includes(eventType)) {
      ui.appendChat(eventType, payload);
      return;
    }
    if (eventType === "memory_status") {
      ui.updateTokenBoard(payload);
      return;
    }
    if (eventType === "error") {
      const message = payload && typeof payload === "object" ? String(payload.message || "") : String(payload || "");
      ui.appendChat("error", message || "请求处理失败");
    }
  },

  consumeSseBuffer(buffer, onEvent) {
    const frames = buffer.split("\n\n");
    const remainder = frames.pop() || "";
    frames.forEach((frame) => {
      const lines = frame.split("\n");
      const dataLines = lines.filter((line) => line.startsWith("data:"));
      if (!dataLines.length) return;
      const dataText = dataLines.map((line) => line.replace(/^data:\s*/, "")).join("\n").trim();
      if (!dataText) return;
      try {
        const event = JSON.parse(dataText);
        onEvent(event);
      } catch (_) {
        // 忽略格式损坏的 SSE 事件片段，继续消费后续帧，避免整条流中断。
      }
    });
    return remainder;
  },

  parseIntOrNull(value) {
    const parsed = parseInt(String(value ?? "").trim(), 10);
    return Number.isFinite(parsed) ? parsed : null;
  },

  parseFloatOrNull(value) {
    const parsed = parseFloat(String(value ?? "").trim());
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
      const data = await api.get(`${userBasePath()}/files/content`, { path: targetPath });
      state.textFileCache[targetPath] = String(data?.content ?? "");
    } catch (err) {
      ui.notify(`读取文件失败: ${err.message}`, "error");
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
      ui.notify("用户ID不能为空", "error");
      return;
    }

    state.userId = id;
    localStorage.setItem(CONFIG.storageKey, id);
    ui.lockUI(false);
    els.chatLog.innerHTML = "";

    try {
      await this.loadSettings();
      const data = await api.get(`${userBasePath()}/employees`);
      state.employees = data.employees || [];
      if (!state.employees.length) await this.createEmployee();

      state.activeEmployeeId = String(state.employees[0]?.employee_id || "");
      state.activeFile = null;
      state.selectedFile = null;
      state.files = [];
      state.dataTree = [];
      state.textFileCache = {};
      state.loadingTextFilePath = "";
      this.renderEmpSelect();
      await this.loadContext({ refreshFiles: true, resetExpandedDirs: true });
    } catch (err) {
      ui.notify(`用户切换失败: ${err.message}`, "error");
    }
  },

  async loadSettings() {
    if (!state.userId) return;
    const settings = await api.get(`${userBasePath()}/settings`);
    state.settings = settings || null;
    ui.applySettings(state.settings);
  },

  async saveSettings() {
    if (!state.userId) {
      ui.notify("请先配置用户 ID", "error");
      return;
    }
    const model = $("model").value.trim();
    const apiKey = $("apiKey").value.trim();
    const baseUrl = $("baseUrl").value.trim();
    const totalTokenLimit = this.parseIntOrNull($("totalTokenLimit").value);
    const tokenizerModel = String($("tokenizerModel").value || "").trim().toLowerCase();
    const memoryCapacityRatio = this.parseFloatOrNull($("memoryCapacityRatio").value);
    const notebookCapacityRatio = this.parseFloatOrNull($("notebookCapacityRatio").value);
    const dialogueSummaryRatio = this.parseFloatOrNull($("dialogueSummaryRatio").value);
    const retentionRatio = this.parseFloatOrNull($("retentionRatio").value);
    const deepThinkingEnabled = !!$("deepThinkingEnabled").checked;

    if (totalTokenLimit == null) {
      ui.notify("请填写合法的 Total Token Limit", "error");
      return;
    }
    if (!TOKENIZER_OPTIONS.includes(tokenizerModel)) {
      ui.notify("请选择合法的 Tokenizer", "error");
      return;
    }
    if (memoryCapacityRatio == null || memoryCapacityRatio < 0.01 || memoryCapacityRatio > 1) {
      ui.notify("Memory Capacity Ratio 必须在 0.01 到 1 之间", "error");
      return;
    }
    if (notebookCapacityRatio == null || notebookCapacityRatio < 0.01 || notebookCapacityRatio > 1) {
      ui.notify("Notebook Capacity Ratio 必须在 0.01 到 1 之间", "error");
      return;
    }
    if (dialogueSummaryRatio == null || dialogueSummaryRatio < 0.01 || dialogueSummaryRatio > 1) {
      ui.notify("Dialogue Summary Ratio 必须在 0.01 到 1 之间", "error");
      return;
    }
    if (retentionRatio == null || retentionRatio < 0.01 || retentionRatio > 1) {
      ui.notify("Retention Ratio 必须在 0.01 到 1 之间", "error");
      return;
    }

    const latest = await api.put(`${userBasePath()}/settings`, {
      model,
      api_key: apiKey,
      base_url: baseUrl,
      total_token_limit: totalTokenLimit,
      tokenizer_model: tokenizerModel,
      memory_capacity_ratio: memoryCapacityRatio,
      notebook_capacity_ratio: notebookCapacityRatio,
      dialogue_summary_ratio: dialogueSummaryRatio,
      retention_ratio: retentionRatio,
      deep_thinking_enabled: deepThinkingEnabled
    });
    state.settings = latest || null;
    ui.applySettings(state.settings);
    ui.notify("用户配置已更新", "success");
  },

  async manualCompression() {
    if (!state.userId || !state.activeEmployeeId) {
      ui.notify("请先选择用户与员工", "error");
      return;
    }
    const data = await api.post(`${sessionBasePath()}/compressions`);
    const accepted = !!data?.accepted;
    ui.notify(accepted ? "已触发手动压缩" : "当前已有压缩任务在执行", "success");
    await this.refreshStatus();
  },

  async resetEmployee() {
    const targetEmployeeId = String(state.activeEmployeeId || "").trim();
    if (!state.userId || !targetEmployeeId) {
      ui.notify("请先选择用户与员工", "error");
      return;
    }
    const confirmed = window.confirm("确认重置员工吗？将重置该员工全部数据（记忆、workspace、skills 等），效果等同删除后同编号重建。");
    if (!confirmed) return;
    await api.post(`${employeeBasePath(targetEmployeeId)}/reset`);
    const employeesData = await api.get(`${userBasePath()}/employees`);
    state.employees = employeesData.employees || [];
    const exists = state.employees.some(
      (item) => String(item?.employee_id || "").trim() === targetEmployeeId
    );
    state.activeEmployeeId = exists ? targetEmployeeId : String(state.employees[0]?.employee_id || "");
    this.renderEmpSelect();
    await this.loadContext({ refreshFiles: true, resetExpandedDirs: true });
    ui.notify(`员工 #${targetEmployeeId} 已重置（同编号重建）`, "success");
  },

  async deleteEmployee() {
    const targetEmployeeId = String(state.activeEmployeeId || "").trim();
    if (!state.userId || !targetEmployeeId) {
      ui.notify("请先选择要删除的员工", "error");
      return;
    }
    const confirmed = window.confirm(`确认删除员工 #${targetEmployeeId} 吗？该员工的消息与 employee/${targetEmployeeId} 目录数据将被删除。`);
    if (!confirmed) return;
    await api.del(`${employeeBasePath(targetEmployeeId)}`);

    const employeesData = await api.get(`${userBasePath()}/employees`);
    state.employees = employeesData.employees || [];
    state.activeEmployeeId = String(state.employees[0]?.employee_id || "");
    state.activeFile = null;
    state.selectedFile = null;
    state.textFileCache = {};
    state.loadingTextFilePath = "";
    this.renderEmpSelect();

    if (!state.activeEmployeeId) {
      els.chatLog.innerHTML = "";
      await this.refreshFiles({ resetExpandedDirs: true });
      ui.notify(`员工 #${targetEmployeeId} 已删除`, "success");
      return;
    }

    await this.loadContext({ refreshFiles: true, resetExpandedDirs: true });
    ui.notify(`员工 #${targetEmployeeId} 已删除`, "success");
  },

  async deleteSelectedFile() {
    const selected = state.selectedFile;
    if (!selected?.path) {
      ui.notify("未选择文件", "error");
      return;
    }
    if (!isDeletableFilePath(selected.path)) {
      ui.notify("仅允许删除 brand_library 与 skill_library 下的文件", "error");
      return;
    }
    const confirmed = window.confirm(`确认删除文件吗？\n${selected.path}`);
    if (!confirmed) return;
    await api.del(`${userBasePath()}/files/content`, { path: selected.path });
    if (state.loadingTextFilePath === selected.path) {
      state.loadingTextFilePath = "";
    }
    delete state.textFileCache[selected.path];
    state.activeFile = null;
    state.selectedFile = null;
    await this.refreshFiles();
    ui.notify(`已删除文件：${selected.path}`, "success");
  },

  async uploadBrandLibraryFiles(fileList) {
    if (!state.userId) {
      ui.notify("请先配置并应用用户 ID", "error");
      return;
    }
    const files = Array.from(fileList || []).filter(Boolean);
    if (!files.length) return;
    const result = await api.upload(`${userBasePath()}/files/brand-library`, files);
    await this.refreshFiles();
    const uploaded = Array.isArray(result?.uploaded) ? result.uploaded : [];
    if (!uploaded.length) {
      ui.notify("素材上传完成", "success");
      return;
    }
    const renamedCount = uploaded.filter((item) => !!item?.renamed).length;
    const previewNames = uploaded.slice(0, 5).map((item) => String(item.file_name || "")).filter(Boolean);
    const previewText = previewNames.join("、");
    const suffix = uploaded.length > 5 ? ` 等 ${uploaded.length} 个文件` : `：${previewText}`;
    const detailParts = [];
    if (renamedCount > 0) detailParts.push(`${renamedCount} 个同名文件已自动重命名`);
    const detail = detailParts.length ? `（${detailParts.join("，")}）` : "";
    ui.notify(`素材上传成功${suffix}${detail}`, "success");
  },

  async createEmployee() {
    const data = await api.post(`${userBasePath()}/employees`);
    state.employees.push(data.employee);
    state.activeEmployeeId = String(data?.employee?.employee_id || "");
    this.renderEmpSelect();
  },

  renderEmpSelect() {
    const selectedEmployeeId = String(state.activeEmployeeId || "").trim();
    els.empSelect.innerHTML = state.employees.map((entry) => {
      const employeeId = String(entry?.employee_id || "").trim();
      const selected = employeeId === selectedEmployeeId ? "selected" : "";
      return `<option value="${employeeId}" ${selected}>员工 #${employeeId}</option>`;
    }).join("");
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
      const history = await api.get(`${employeeBasePath()}/messages`, { limit: "50" });
      els.chatLog.innerHTML = "";
      (history.messages || []).forEach((message) => {
        const normalized = this.normalizeHistoryMessage(message);
        ui.appendChat(normalized.type, normalized.payload);
        const imageInfo = this.extractGeneratedImage(
          normalized && normalized.type === "graph_tool_end" ? normalized.payload : null
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
    const mem = await api.get(`${userBasePath()}/files/tree`);
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
    const status = await api.get(`${sessionBasePath()}/memory`, query).catch(() => null);
    ui.updateTokenBoard(status);
  },

  async sendMessage(msg) {
    if (state.isChatting || !state.activeEmployeeId) return;
    state.isChatting = true;
    ui.lockUI(true);
    ui.appendChat("user", msg);

    try {
      const payload = { message: msg };
      const res = await fetch(`${sessionBasePath()}/messages/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        let errorMessage = `HTTP ${res.status}`;
        try {
          const payload = await res.json();
          const detail = payload && typeof payload === "object" ? payload.error : null;
          if (detail && typeof detail.message === "string" && detail.message.trim()) {
            errorMessage = detail.message;
          }
        } catch {
          // 非 JSON 错误体保持默认 HTTP 状态提示，避免二次解析抛错覆盖根因。
        }
        throw new Error(errorMessage);
      }
      if (!res.body) {
        throw new Error("流式响应为空");
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let sseBuffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (value) {
          sseBuffer += decoder.decode(value, { stream: true });
          sseBuffer = this.consumeSseBuffer(sseBuffer, (event) => this.handleSseEvent(event));
        }
        if (done) break;
      }
      sseBuffer += decoder.decode();
      sseBuffer = this.consumeSseBuffer(sseBuffer, (event) => this.handleSseEvent(event));
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
        ui.notify(`重置员工失败: ${err.message}`, "error");
      }
    };
    els.btnDeleteEmp.onclick = async () => {
      try {
        await this.deleteEmployee();
      } catch (err) {
        ui.notify(`删除员工失败: ${err.message}`, "error");
      }
    };
    els.btnReloadEmp.onclick = () => this.switchUser();
    els.btnReloadFiles.onclick = async () => {
      try {
        await this.refreshFiles();
      } catch (err) {
        ui.notify(`刷新目录失败: ${err.message}`, "error");
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
        ui.notify(`上传素材失败: ${err.message}`, "error");
      } finally {
        event.target.value = "";
      }
    };
    els.btnDeleteFile.onclick = async () => {
      try {
        await this.deleteSelectedFile();
      } catch (err) {
        ui.notify(`删除文件失败: ${err.message}`, "error");
      }
    };

    els.btnSaveFile.onclick = async () => {
      try {
        const selected = state.selectedFile;
        if (!selected?.path) {
          ui.notify("未选择文件", "error");
          return;
        }
        if (selected.kind !== "text") {
          ui.notify("当前文件不可编辑", "error");
          return;
        }
        const treeEntry = state.dataTree.find((entry) => String(entry.path || "") === selected.path);
        if (treeEntry && treeEntry.can_write === false) {
          ui.notify("当前为只读文件（其他员工目录）", "error");
          return;
        }

        const content = els.fileContent.value;
        const result = await api.put(
          `${userBasePath()}/files/content`,
          { content, mode: "overwrite" },
          { path: selected.path }
        );
        const latestContent = typeof result?.content === "string" ? result.content : content;
        const file = findEditableFile(selected.path);
        if (file) file.content = latestContent;
        state.textFileCache[selected.path] = latestContent;
        await this.refreshFiles();
        ui.notify(`保存成功：${selected.path}`, "success");
      } catch (err) {
        ui.notify(`保存修改失败: ${err.message}`, "error");
      }
    };

    els.btnForceCompression.onclick = async () => {
      try {
        await this.manualCompression();
      } catch (err) {
        ui.notify(`手动压缩失败: ${err.message}`, "error");
      }
    };

    els.btnSettings.onclick = async () => {
      try {
        await this.loadSettings();
      } catch (err) {
        ui.notify(`加载用户配置失败: ${err.message}`, "error");
      }
      els.modal.showModal();
    };
    $("closeSettingsBtn").onclick = () => els.modal.close();
    $("saveConfigBtn").onclick = async () => {
      try {
        await this.saveSettings();
        els.modal.close();
      } catch (err) {
        ui.notify(`保存用户配置失败: ${err.message}`, "error");
      }
    };
  }
};

