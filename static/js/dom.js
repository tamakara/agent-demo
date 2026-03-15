// =================DOM 节点缓存=================
export const $ = (id) => document.getElementById(id);

export const els = {
  userId: $("userIdInput"), btnUser: $("switchUserBtn"),
  chatLog: $("chatLog"), chatForm: $("chatForm"), msgInput: $("messageInput"),
  empSelect: $("employeeSelect"), btnNewEmp: $("newEmployeeBtn"), btnResetEmp: $("resetEmployeeBtn"),
  btnDeleteEmp: $("deleteEmployeeBtn"), btnReloadEmp: $("reloadEmployeeBtn"),
  btnUploadBrandLibrary: $("uploadBrandLibraryBtn"), uploadBrandLibraryInput: $("uploadBrandLibraryInput"),
  btnReloadFiles: $("reloadFilesBtn"),
  tree: $("directoryTree"), fileContent: $("fileContent"), fileName: $("activeFileName"),
  btnDeleteFile: $("deleteFileBtn"), btnSaveFile: $("saveFileBtn"),
  fileImagePreview: $("fileImagePreview"), fileImagePreviewImg: $("fileImagePreviewImg"), fileImagePreviewPath: $("fileImagePreviewPath"),
  modal: $("settingsModal"), btnSettings: $("openSettingsBtn"),
  tokenSum: $("tokenSummary"), resBar: $("residentBar"), diaBar: $("dialogueBar"), bufBar: $("bufferBar"),
  btnForceFlush: $("forceFlushBtn")
};

