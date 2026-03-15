// =================配置与状态=================
export const CONFIG = {
  storageKey: "agent_demo_user_id"
};

export const TOKENIZER_OPTIONS = ["kimi-k2.5"];
export const DEFAULT_TOKENIZER_MODEL = "kimi-k2.5";
export const IMAGE_FILE_EXT_PATTERN = /\.(png|jpe?g|webp|gif|bmp|svg)$/i;
export const EDITABLE_TEXT_EXT_PATTERN = /\.(md|txt)$/i;
export const DELETABLE_ROOT_NAMES = new Set(["brand_library", "skill_library"]);

export const state = {
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
  isChatting: false
};

export const toEditableRelativePath = (path) => {
  const raw = String(path || "").trim();
  if (!raw) return "";
  return raw.startsWith("/") ? raw.slice(1) : raw;
};

export const findEditableFile = (path) => {
  const normalized = toEditableRelativePath(path);
  if (!normalized) return null;
  return state.files.find((f) => String(f.relative_path || "").trim() === normalized) || null;
};

export const fileNameFromPath = (path) => {
  const raw = String(path || "").trim();
  if (!raw) return "";
  const parts = raw.split("/").filter(Boolean);
  return parts[parts.length - 1] || raw;
};

export const isImageTreePath = (path) => IMAGE_FILE_EXT_PATTERN.test(String(path || ""));
export const isEditableTextTreePath = (path) => EDITABLE_TEXT_EXT_PATTERN.test(String(path || "").trim());

export const fileKindFromTreePath = (path) => {
  if (isImageTreePath(path)) return "image";
  if (isEditableTextTreePath(path)) return "text";
  return "other";
};

export const dataRootNameFromPath = (path) => {
  const normalized = toEditableRelativePath(path);
  const parts = normalized.split("/").filter(Boolean);
  return parts[0] || "";
};

export const isDeletableFilePath = (path) => DELETABLE_ROOT_NAMES.has(dataRootNameFromPath(path));

export const buildSelectedFile = (path) => {
  const normalized = String(path || "").trim();
  if (!normalized) return null;
  return {
    path: normalized,
    kind: fileKindFromTreePath(normalized),
    name: fileNameFromPath(normalized)
  };
};

