import { $, els } from "./dom.js";
import {
  DEFAULT_TOKENIZER_MODEL,
  TOKENIZER_OPTIONS,
  fileNameFromPath,
  findEditableFile,
  isDeletableFilePath,
  state
} from "./state.js";

let onSelectFile = null;

export const setFileSelectHandler = (handler) => {
  onSelectFile = handler;
};

export const ui = {
  buildImagePreviewUrl(treePath, { bustCache = true } = {}) {
    const query = new URLSearchParams({
      user_id: String(state.userId || ""),
      path: String(treePath || "")
    });
    if (bustCache) query.set("ts", String(Date.now()));
    return `/storage/file-preview?${query.toString()}`;
  },

  notify(message, level = "info") {
    const text = String(message || "").trim();
    if (!text) return;
    const prefix = level === "error" ? "错误" : level === "success" ? "成功" : "提示";
    window.alert(`${prefix}：${text}`);
  },

  appendChat(type, content) {
    const tpl = $("chatItemTemplate").content.cloneNode(true);
    const item = tpl.querySelector(".chat-item");
    item.classList.add(type);

    const body = tpl.querySelector(".chat-body");
    const isString = typeof content === "string";
    const text = isString ? content : JSON.stringify(content, null, 2);

    if (["user", "assistant"].includes(type)) {
      tpl.querySelector(".chat-meta").textContent = type === "user" ? "👤 用户" : "🤖 助手";
      const pre = document.createElement("pre");
      pre.textContent = text;
      body.appendChild(pre);
    } else {
      item.innerHTML = `
        <details class="chat-collapsible">
          <summary>${type === "error" ? "❌ 错误" : `🔧 ${type}`}</summary>
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
    img.src = this.buildImagePreviewUrl(imageInfo.path, { bustCache: true });
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
    if (!status) return;
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
    const visibleTree = state.dataTree.filter((entry) => entry.path !== ".");
    if (!visibleTree.length) {
      els.tree.innerHTML = "<div class='text-muted text-center mt-2'>空目录</div>";
      return;
    }
    const pathSet = new Set(visibleTree.map((entry) => entry.path));
    const parentPath = (path) => {
      const idx = path.lastIndexOf("/");
      return idx === -1 ? "" : path.slice(0, idx);
    };

    const buildNode = (entry, depth = 0) => {
      const isExpanded = state.expandedDirs.has(entry.path);
      const parts = entry.path.split("/").filter(Boolean);
      const isRootFolder = entry.is_dir && entry.path.startsWith("/") && parts.length === 1;
      const isEmployeeMemberFolder = entry.is_dir && parts[0] === "employee" && parts.length === 2;
      let displayName = parts[parts.length - 1] || entry.path;
      if (isRootFolder) displayName = `${parts[0]}/`;
      else if (isEmployeeMemberFolder) displayName = `${parts[1]}/`;
      else if (entry.is_dir) displayName = `${displayName}/`;

      const row = document.createElement("div");
      row.className = `tree-row ${entry.is_dir ? "dir" : "file"} ${state.selectedFile?.path === entry.path ? "active" : ""}`;
      row.style.paddingLeft = `${depth * 12 + 8}px`;
      row.innerHTML = `<span>${entry.is_dir ? (isExpanded ? "📂" : "📁") : "📄"}</span> <span>${displayName}</span>`;

      row.onclick = () => {
        if (entry.is_dir) {
          if (isExpanded) state.expandedDirs.delete(entry.path);
          else state.expandedDirs.add(entry.path);
          this.renderTree();
          return;
        }
        if (typeof onSelectFile === "function") onSelectFile(entry.path);
      };
      els.tree.appendChild(row);

      if (entry.is_dir && isExpanded) {
        const children = visibleTree.filter(
          (child) => child.path.startsWith(`${entry.path}/`) && child.path.split("/").length === entry.path.split("/").length + 1
        );
        children.forEach((child) => buildNode(child, depth + 1));
      }
    };

    const roots = visibleTree.filter((entry) => !pathSet.has(parentPath(entry.path)));
    roots.forEach((entry) => buildNode(entry, 0));
  },

  updateEditor() {
    const selected = state.selectedFile;
    const activePath = String(selected?.path || "");
    const selectedKind = String(selected?.kind || "none");
    const file = findEditableFile(activePath);
    const cachedTextContent = state.textFileCache[activePath];
    const globallyLocked = !state.userId || state.isChatting;
    const canDelete = !!activePath && !globallyLocked && isDeletableFilePath(activePath);

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
      els.fileImagePreviewImg.src = this.buildImagePreviewUrl(activePath, { bustCache: true });
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
      els.empSelect, els.btnNewEmp, els.btnResetEmp, els.btnDeleteEmp, els.btnReloadEmp,
      els.btnUploadBrandLibrary, els.uploadBrandLibraryInput, els.btnReloadFiles,
      els.btnSettings, els.btnForceFlush, $("saveConfigBtn"), els.btnDeleteFile, els.btnSaveFile,
      els.msgInput, els.chatForm.querySelector("button")
    ].forEach((el) => {
      el.disabled = disabled;
    });
    if (!disabled) {
      const hasActiveEmployee = !!String(state.activeEmployeeId || "").trim();
      els.btnResetEmp.disabled = !hasActiveEmployee;
      els.btnDeleteEmp.disabled = !hasActiveEmployee;
    }
    if (!disabled) this.updateEditor();
    if (!state.userId) els.msgInput.placeholder = "请先配置并应用用户 ID...";
  }
};
