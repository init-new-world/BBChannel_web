import { createPresetTeamEditor } from "./preset-team.js";
import { createPresetAssistEditor } from "./preset-assist.js";

const TERMINAL_JOB_STATES = new Set(["cancelled", "succeeded", "failed"]);
const ACTIVE_JOB_STATES = new Set(["queued", "running", "paused", "cancelling"]);

const state = {
  connected: false,
  backends: [],
  devices: [],
  settings: [],
  strategies: [],
  equipTemplates: [],
  equipCandidates: [],
  equipFullCandidate: null,
  equipNonFullCandidate: null,
  equipTemplateBusy: false,
  assistTags: [],
  assistTagMode: "assist",
  assistTagGeneration: 0,
  assistTagListSequence: 0,
  assistTagBusy: false,
  assistTagCandidates: [],
  assistTagScreenshotBase64: "",
  assistTagImage: null,
  assistTagCropBounds: null,
  assistTagDragStart: null,
  materialCatalog: null,
  materialQuerySequence: 0,
  notebookSavedContent: "",
  notebookBusy: false,
  screenshotUrl: null,
  screenshotBase64: "",
  debugOverlayDataUrl: null,
  screenMode: "source",
  screenshotNaturalSize: null,
  latestMatch: null,
  selectedSettingPlan: null,
  selectedSettingProgram: null,
  selectedStrategy: null,
  presetEditor: null,
  jobs: [],
  activeJob: null,
  jobEvents: [],
  jobEventSource: null,
};

const els = {
  backendSelect: document.querySelector("#backend-select"),
  deviceList: document.querySelector("#device-list"),
  manualAdbEndpoint: document.querySelector("#manual-adb-endpoint"),
  addAdbEndpoint: document.querySelector("#add-adb-endpoint"),
  refreshDevices: document.querySelector("#refresh-devices"),
  connectDevice: document.querySelector("#connect-device"),
  disconnectDevice: document.querySelector("#disconnect-device"),
  connectionState: document.querySelector("#connection-state"),
  settingSelect: document.querySelector("#setting-select"),
  settingValidation: document.querySelector("#setting-validation"),
  settingPlan: document.querySelector("#setting-plan"),
  newSetting: document.querySelector("#new-setting"),
  editSetting: document.querySelector("#edit-setting"),
  deleteSetting: document.querySelector("#delete-setting"),
  refreshSettings: document.querySelector("#refresh-settings"),
  importSetting: document.querySelector("#import-setting"),
  exportSetting: document.querySelector("#export-setting"),
  settingFileInput: document.querySelector("#setting-file-input"),
  strategySelect: document.querySelector("#strategy-select"),
  strategySummary: document.querySelector("#strategy-summary"),
  newStrategy: document.querySelector("#new-strategy"),
  editStrategy: document.querySelector("#edit-strategy"),
  deleteStrategy: document.querySelector("#delete-strategy"),
  presetDialog: document.querySelector("#preset-dialog"),
  presetForm: document.querySelector("#preset-form"),
  presetDialogTitle: document.querySelector("#preset-dialog-title"),
  presetName: document.querySelector("#preset-name"),
  presetJson: document.querySelector("#preset-json"),
  presetWaves: document.querySelector("#preset-waves"),
  presetWaveControls: document.querySelector("#preset-wave-controls"),
  presetWaveCount: document.querySelector("#preset-wave-count"),
  presetWaveList: document.querySelector("#preset-wave-list"),
  presetWaveStatus: document.querySelector("#preset-wave-status"),
  addScriptWave: document.querySelector("#add-script-wave"),
  presetRunOptions: document.querySelector("#preset-run-options"),
  presetRunControls: document.querySelector("#preset-run-controls"),
  presetRunInputs: [...document.querySelectorAll("[data-run-option]")],
  presetAssistSkills: document.querySelector("#preset-assist-skills"),
  presetScriptStrategy: document.querySelector("#preset-script-strategy"),
  presetStrategyTarget: document.querySelector("#preset-strategy-target"),
  presetStrategySource: document.querySelector("#preset-strategy-source"),
  presetTurnStrategyStatus: document.querySelector("#preset-turn-strategy-status"),
  applyTurnStrategy: document.querySelector("#apply-turn-strategy"),
  clearTurnStrategy: document.querySelector("#clear-turn-strategy"),
  presetTurnNps: document.querySelector("#preset-turn-nps"),
  presetTurnNpStatus: document.querySelector("#preset-turn-np-status"),
  presetTurnNpInputs: [...document.querySelectorAll("[data-turn-np-index]")],
  clearTurnNps: document.querySelector("#clear-turn-nps"),
  presetSkillInputs: [...document.querySelectorAll("[data-assist-skill-index]")],
  presetStrategyRules: document.querySelector("#preset-strategy-rules"),
  presetStrategyEntry: document.querySelector("#preset-strategy-entry"),
  presetStrategyTag: document.querySelector("#preset-strategy-tag"),
  addStrategyEntry: document.querySelector("#add-strategy-entry"),
  duplicateStrategyEntry: document.querySelector("#duplicate-strategy-entry"),
  deleteStrategyEntry: document.querySelector("#delete-strategy-entry"),
  moveStrategyEntryUp: document.querySelector("#move-strategy-entry-up"),
  moveStrategyEntryDown: document.querySelector("#move-strategy-entry-down"),
  presetStrategyBreakpoints: [...document.querySelectorAll("[data-strategy-breakpoint]")],
  presetStrategyColorFirst: document.querySelector("#preset-strategy-color-first"),
  presetStrategyCards: [...document.querySelectorAll("[data-strategy-card]")],
  presetError: document.querySelector("#preset-error"),
  closePreset: document.querySelector("#close-preset"),
  cancelPreset: document.querySelector("#cancel-preset"),
  savePreset: document.querySelector("#save-preset"),
  snapshotButton: document.querySelector("#snapshot-button"),
  clearScreenshot: document.querySelector("#clear-screenshot"),
  templateSelect: document.querySelector("#template-select"),
  thresholdInput: document.querySelector("#threshold-input"),
  recognitionScales: document.querySelector("#recognition-scales"),
  recognitionRoiEnabled: document.querySelector("#recognition-roi-enabled"),
  recognitionRoiControls: document.querySelector("#recognition-roi-controls"),
  recognitionRoiX: document.querySelector("#recognition-roi-x"),
  recognitionRoiY: document.querySelector("#recognition-roi-y"),
  recognitionRoiWidth: document.querySelector("#recognition-roi-width"),
  recognitionRoiHeight: document.querySelector("#recognition-roi-height"),
  matchButton: document.querySelector("#match-button"),
  matchResult: document.querySelector("#match-result"),
  tapX: document.querySelector("#tap-x"),
  tapY: document.querySelector("#tap-y"),
  tapButton: document.querySelector("#tap-button"),
  swipeX1: document.querySelector("#swipe-x1"),
  swipeY1: document.querySelector("#swipe-y1"),
  swipeX2: document.querySelector("#swipe-x2"),
  swipeY2: document.querySelector("#swipe-y2"),
  swipeDuration: document.querySelector("#swipe-duration"),
  swipeButton: document.querySelector("#swipe-button"),
  screenMeta: document.querySelector("#screen-meta"),
  screenStage: document.querySelector("#screen-stage"),
  screenshot: document.querySelector("#screenshot"),
  screenEmpty: document.querySelector("#screen-empty"),
  matchOverlay: document.querySelector("#match-overlay"),
  screenSourceMode: document.querySelector("#screen-source-mode"),
  screenDebugMode: document.querySelector("#screen-debug-mode"),
  fitScreen: document.querySelector("#fit-screen"),
  actualScreen: document.querySelector("#actual-screen"),
  refreshEvents: document.querySelector("#refresh-events"),
  eventLog: document.querySelector("#event-log"),
  logCount: document.querySelector("#log-count"),
  diagnosticVerifyTemplate: document.querySelector("#diagnostic-verify-template"),
  diagnosticTimeout: document.querySelector("#diagnostic-timeout"),
  diagnosticTap: document.querySelector("#diagnostic-tap"),
  startDiagnostic: document.querySelector("#start-diagnostic"),
  battleScriptName: document.querySelector("#battle-script-name"),
  battleProgramStatus: document.querySelector("#battle-program-status"),
  battleActionDelay: document.querySelector("#battle-action-delay"),
  fullRunEntryMode: document.querySelector("#full-run-entry-mode"),
  fullRunCount: document.querySelector("#full-run-count"),
  fullRunRestartLimit: document.querySelector("#full-run-restart-limit"),
  fullRunMapSwipes: document.querySelector("#full-run-map-swipes"),
  fullRunApple: document.querySelector("#full-run-apple"),
  fullRunTeamCheck: document.querySelector("#full-run-team-check"),
  fullRunAssistFilter: document.querySelector("#full-run-assist-filter"),
  startFullRun: document.querySelector("#start-full-run"),
  restartGame: document.querySelector("#restart-game"),
  inspectChocolate: document.querySelector("#inspect-chocolate"),
  runChocolate: document.querySelector("#run-chocolate"),
  inspectDigdig: document.querySelector("#inspect-digdig"),
  executeDigdig: document.querySelector("#execute-digdig"),
  inspectLottery: document.querySelector("#inspect-lottery"),
  runLottery: document.querySelector("#run-lottery"),
  lotteryPaySlot: document.querySelector("#lottery-pay-slot"),
  lotteryStar3: document.querySelector("#lottery-star-3"),
  lotteryStar4: document.querySelector("#lottery-star-4"),
  lotteryStar5: document.querySelector("#lottery-star-5"),
  inspectExpball: document.querySelector("#inspect-expball"),
  expballDestination: document.querySelector("#expball-destination"),
  navigateExpball: document.querySelector("#navigate-expball"),
  inspectExpballGrid: document.querySelector("#inspect-expball-grid"),
  fpSummonBatches: document.querySelector("#fp-summon-batches"),
  runExpballSummon: document.querySelector("#run-expball-summon"),
  runExpballStorage: document.querySelector("#run-expball-storage"),
  runExpballSell: document.querySelector("#run-expball-sell"),
  equipTemplateName: document.querySelector("#equip-template-name"),
  captureEquipCandidates: document.querySelector("#capture-equip-candidates"),
  equipCandidateList: document.querySelector("#equip-candidate-list"),
  equipCandidatePreview: document.querySelector("#equip-candidate-preview"),
  equipCandidatePreviewStatus: document.querySelector("#equip-candidate-preview-status"),
  useEquipFull: document.querySelector("#use-equip-full"),
  useEquipNonFull: document.querySelector("#use-equip-non-full"),
  equipFullImage: document.querySelector("#equip-full-image"),
  equipNonFullImage: document.querySelector("#equip-non-full-image"),
  equipFullSource: document.querySelector("#equip-full-source"),
  equipNonFullSource: document.querySelector("#equip-non-full-source"),
  buildEquipTemplate: document.querySelector("#build-equip-template"),
  equipTemplateList: document.querySelector("#equip-template-list"),
  equipTemplatePreview: document.querySelector("#equip-template-preview"),
  equipTemplatePreviewStatus: document.querySelector("#equip-template-preview-status"),
  testEquipTemplate: document.querySelector("#test-equip-template"),
  equipTestStatus: document.querySelector("#equip-test-status"),
  activateEquipTemplate: document.querySelector("#activate-equip-template"),
  archiveEquipTemplate: document.querySelector("#archive-equip-template"),
  openAssistTags: document.querySelector("#open-assist-tags"),
  assistTagDialog: document.querySelector("#assist-tag-dialog"),
  assistTagModes: document.querySelectorAll("[data-tag-mode]"),
  assistTagModeLabel: document.querySelector("#assist-tag-mode-label"),
  assistTagWorkspace: document.querySelector("#assist-tag-workspace"),
  assistTagCaptureLabel: document.querySelector("#assist-tag-capture-label"),
  assistTagCandidateLabel: document.querySelector("#assist-tag-candidate-label"),
  assistTagBindingStatus: document.querySelector("#assist-tag-binding-status"),
  closeAssistTags: document.querySelector("#close-assist-tags"),
  captureAssistTagScreen: document.querySelector("#capture-assist-tag-screen"),
  assistTagCandidate: document.querySelector("#assist-tag-candidate"),
  assistTagCanvas: document.querySelector("#assist-tag-canvas"),
  assistTagCanvasEmpty: document.querySelector("#assist-tag-canvas-empty"),
  assistTagLabel: document.querySelector("#assist-tag-label"),
  assistTagThreshold: document.querySelector("#assist-tag-threshold"),
  assistTagCropStatus: document.querySelector("#assist-tag-crop-status"),
  assistTagMakerStatus: document.querySelector("#assist-tag-maker-status"),
  saveAssistTag: document.querySelector("#save-assist-tag"),
  assistTagList: document.querySelector("#assist-tag-list"),
  assistTagPreview: document.querySelector("#assist-tag-preview"),
  assistTagPreviewEmpty: document.querySelector("#assist-tag-preview-empty"),
  assistTagMetadata: document.querySelector("#assist-tag-metadata"),
  assistTagFile: document.querySelector("#assist-tag-file"),
  importAssistTag: document.querySelector("#import-assist-tag"),
  bindAssistTag: document.querySelector("#bind-assist-tag"),
  deleteAssistTag: document.querySelector("#delete-assist-tag"),
  assistTagLibraryStatus: document.querySelector("#assist-tag-library-status"),
  openMaterialDrops: document.querySelector("#open-material-drops"),
  materialDialog: document.querySelector("#material-dialog"),
  materialForm: document.querySelector("#material-form"),
  closeMaterialDialog: document.querySelector("#close-material-dialog"),
  materialServer: document.querySelector("#material-server"),
  materialQuality: document.querySelector("#material-quality"),
  materialName: document.querySelector("#material-name"),
  materialResultStatus: document.querySelector("#material-result-status"),
  materialResults: document.querySelector("#material-results"),
  openNotebook: document.querySelector("#open-notebook"),
  notebookDialog: document.querySelector("#notebook-dialog"),
  notebookForm: document.querySelector("#notebook-form"),
  closeNotebookDialog: document.querySelector("#close-notebook-dialog"),
  notebookContent: document.querySelector("#notebook-content"),
  notebookStatus: document.querySelector("#notebook-status"),
  saveNotebook: document.querySelector("#save-notebook"),
  startBattleDryRun: document.querySelector("#start-battle-dry-run"),
  startBattlePlan: document.querySelector("#start-battle-plan"),
  jobHistory: document.querySelector("#job-history"),
  jobStatus: document.querySelector("#job-status"),
  jobKind: document.querySelector("#job-kind"),
  jobProgress: document.querySelector("#job-progress"),
  jobStep: document.querySelector("#job-step"),
  jobResult: document.querySelector("#job-result"),
  pauseJob: document.querySelector("#pause-job"),
  resumeJob: document.querySelector("#resume-job"),
  cancelJob: document.querySelector("#cancel-job"),
  jobError: document.querySelector("#job-error"),
  jobEvents: document.querySelector("#job-events"),
  jobEventCount: document.querySelector("#job-event-count"),
};

const presetTeam = createPresetTeamEditor({
  getEditor: () => state.presetEditor,
  source: els.presetJson,
  request: api,
  onChange: () => {
    renderPresetScriptStrategy();
    setPresetError("");
  },
  onError: setPresetError,
});

const presetAssist = createPresetAssistEditor({
  getEditor: () => state.presetEditor,
  source: els.presetJson,
  onChange: () => {
    renderPresetScriptStrategy();
    setPresetError("");
  },
  onError: setPresetError,
});

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    const message = payload?.error?.message
      || payload?.detail?.message
      || payload?.detail?.code
      || `${response.status} ${response.statusText}`;
    const error = new Error(message);
    error.payload = payload;
    throw error;
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response;
}

async function init() {
  bindEvents();
  await Promise.allSettled([
    loadCapabilities(),
    loadDevices(),
    loadSettings(),
    loadStrategies(),
    loadTemplates(),
    loadEquipTemplates(),
    loadAssistTags(),
    loadEvents(),
    loadJobs(),
  ]);
  await loadConnectionState();
  updateControls();
}

function bindEvents() {
  els.backendSelect.addEventListener("change", () => renderDevices());
  els.refreshDevices.addEventListener("click", () => loadDevices());
  els.addAdbEndpoint.addEventListener("click", addManualAdbEndpoint);
  els.manualAdbEndpoint.addEventListener("input", updateControls);
  els.manualAdbEndpoint.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addManualAdbEndpoint();
    }
  });
  els.connectDevice.addEventListener("click", connect);
  els.disconnectDevice.addEventListener("click", disconnect);
  els.settingSelect.addEventListener("change", loadSelectedSettingPlan);
  els.strategySelect.addEventListener("change", loadSelectedStrategy);
  els.newSetting.addEventListener("click", () => openPresetEditor("settings", false));
  els.editSetting.addEventListener("click", () => openPresetEditor("settings", true));
  els.deleteSetting.addEventListener("click", () => deletePreset("settings"));
  els.refreshSettings.addEventListener("click", () => loadSettings());
  els.importSetting.addEventListener("click", () => els.settingFileInput.click());
  els.settingFileInput.addEventListener("change", handleSettingImport);
  els.exportSetting.addEventListener("click", exportSelectedSetting);
  els.newStrategy.addEventListener("click", () => openPresetEditor("strategies", false));
  els.editStrategy.addEventListener("click", () => openPresetEditor("strategies", true));
  els.deleteStrategy.addEventListener("click", () => deletePreset("strategies"));
  els.presetForm.addEventListener("submit", savePreset);
  els.presetDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closePresetEditor();
  });
  els.presetJson.addEventListener("input", () => {
    if (state.presetEditor) {
      state.presetEditor.strategyDrafts = {};
      state.presetEditor.runOptionDrafts = {};
    }
    renderPresetFields();
    setPresetError("");
  });
  els.presetSkillInputs.forEach((input) => input.addEventListener("change", updatePresetSkills));
  els.presetRunInputs.forEach((input) => {
    input.addEventListener("change", updatePresetRunOption);
    if (input.type === "number") input.addEventListener("input", (event) => updatePresetRunOption(event, true));
    input.addEventListener("invalid", () => { els.presetRunOptions.open = true; });
  });
  els.addScriptWave.addEventListener("click", () => changeScriptWaves("add-wave"));
  els.presetWaveList.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-wave-action]");
    if (!button || button.disabled) return;
    changeScriptWaves(button.dataset.waveAction, Number(button.closest("[data-script-wave]").dataset.scriptWave));
  });
  els.presetStrategyTarget.addEventListener("change", () => {
    if (state.presetEditor?.kind !== "settings") return;
    state.presetEditor.strategyTarget = els.presetStrategyTarget.value;
    renderPresetScriptStrategy();
  });
  els.presetStrategySource.addEventListener("change", () => {
    if (state.presetEditor?.kind !== "settings") return;
    state.presetEditor.strategySource = els.presetStrategySource.value;
    renderPresetScriptStrategy();
  });
  els.applyTurnStrategy.addEventListener("click", applyPresetToTurn);
  els.clearTurnStrategy.addEventListener("click", clearTurnStrategy);
  els.presetTurnNpInputs.forEach((input) => input.addEventListener("change", updateTurnNps));
  els.clearTurnNps.addEventListener("click", () => updateTurnNps(null));
  els.presetStrategyEntry.addEventListener("change", () => {
    if (state.presetEditor?.kind === "strategies") {
      state.presetEditor.strategyIndex = Number(els.presetStrategyEntry.value);
      renderPresetStrategyRules();
    }
  });
  els.presetStrategyTag.addEventListener("change", updatePresetStrategyTag);
  els.addStrategyEntry.addEventListener("click", () => changePresetStrategyEntries("add"));
  els.duplicateStrategyEntry.addEventListener("click", () => changePresetStrategyEntries("duplicate"));
  els.deleteStrategyEntry.addEventListener("click", () => changePresetStrategyEntries("delete"));
  els.moveStrategyEntryUp.addEventListener("click", () => changePresetStrategyEntries("up"));
  els.moveStrategyEntryDown.addEventListener("click", () => changePresetStrategyEntries("down"));
  [...els.presetStrategyBreakpoints, els.presetStrategyColorFirst].forEach((input) => {
    input.addEventListener("change", updatePresetStrategyRule);
  });
  els.presetStrategyCards.forEach((row) => row.addEventListener("change", updatePresetStrategyCard));
  els.closePreset.addEventListener("click", closePresetEditor);
  els.cancelPreset.addEventListener("click", closePresetEditor);
  els.snapshotButton.addEventListener("click", captureScreenshot);
  els.clearScreenshot.addEventListener("click", clearScreenshot);
  els.matchButton.addEventListener("click", matchTemplate);
  els.recognitionRoiEnabled.addEventListener("change", () => {
    els.recognitionRoiControls.hidden = !els.recognitionRoiEnabled.checked;
  });
  els.tapButton.addEventListener("click", sendTap);
  els.swipeButton.addEventListener("click", sendSwipe);
  els.fitScreen.addEventListener("click", () => setScreenScale("fit"));
  els.actualScreen.addEventListener("click", () => setScreenScale("actual"));
  els.screenSourceMode.addEventListener("click", () => setScreenMode("source"));
  els.screenDebugMode.addEventListener("click", () => setScreenMode("debug"));
  els.refreshEvents.addEventListener("click", loadEvents);
  els.screenshot.addEventListener("load", onScreenshotLoaded);
  els.screenStage.addEventListener("click", populateTapFromClick);
  els.startDiagnostic.addEventListener("click", startDiagnosticJob);
  els.startBattleDryRun.addEventListener("click", startBattleDryRun);
  els.startBattlePlan.addEventListener("click", startBattlePlan);
  els.fullRunEntryMode.addEventListener("change", updateControls);
  els.startFullRun.addEventListener("click", startFullRun);
  els.restartGame.addEventListener("click", restartGame);
  els.inspectChocolate.addEventListener("click", inspectChocolate);
  els.runChocolate.addEventListener("click", runChocolate);
  els.inspectDigdig.addEventListener("click", inspectDigdig);
  els.executeDigdig.addEventListener("click", executeDigdig);
  els.inspectLottery.addEventListener("click", inspectLottery);
  els.runLottery.addEventListener("click", runLottery);
  els.lotteryStar3.addEventListener("change", updateControls);
  els.lotteryStar4.addEventListener("change", updateControls);
  els.lotteryStar5.addEventListener("change", updateControls);
  els.inspectExpball.addEventListener("click", inspectExpball);
  els.navigateExpball.addEventListener("click", navigateExpball);
  els.inspectExpballGrid.addEventListener("click", inspectExpballGrid);
  els.runExpballSummon.addEventListener("click", runExpballSummon);
  els.runExpballStorage.addEventListener("click", runExpballStorage);
  els.runExpballSell.addEventListener("click", runExpballSell);
  els.equipTemplateName.addEventListener("input", updateControls);
  els.captureEquipCandidates.addEventListener("click", captureEquipCandidates);
  els.equipCandidateList.addEventListener("change", renderSelectedEquipCandidate);
  els.equipCandidatePreview.addEventListener("error", handleEquipCandidatePreviewError);
  els.useEquipFull.addEventListener("click", () => assignEquipCandidate("full"));
  els.useEquipNonFull.addEventListener("click", () => assignEquipCandidate("non-full"));
  els.equipFullImage.addEventListener("change", () => handleEquipFileChange("full"));
  els.equipNonFullImage.addEventListener("change", () => handleEquipFileChange("non-full"));
  els.buildEquipTemplate.addEventListener("click", buildEquipTemplate);
  els.equipTemplateList.addEventListener("change", renderSelectedEquipTemplate);
  els.equipTemplatePreview.addEventListener("error", handleEquipTemplatePreviewError);
  els.testEquipTemplate.addEventListener("click", testEquipTemplate);
  els.activateEquipTemplate.addEventListener("click", () => moveEquipTemplate("activate"));
  els.archiveEquipTemplate.addEventListener("click", () => moveEquipTemplate("archive"));
  els.openAssistTags.addEventListener("click", openAssistTagMaker);
  els.closeAssistTags.addEventListener("click", () => els.assistTagDialog.close());
  els.assistTagDialog.addEventListener("close", resetAssistTagMaker);
  els.assistTagModes.forEach((tab) => {
    tab.addEventListener("click", () => changeAssistTagMode(tab.dataset.tagMode));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const tabs = [...els.assistTagModes];
      const next = event.key === "Home" ? tabs[0] : event.key === "End" ? tabs.at(-1)
        : tabs[(tabs.indexOf(tab) + 1) % tabs.length];
      next.focus();
      changeAssistTagMode(next.dataset.tagMode);
    });
  });
  els.captureAssistTagScreen.addEventListener("click", captureAssistTagScreen);
  els.assistTagCandidate.addEventListener("change", () => {
    state.assistTagCropBounds = null;
    state.assistTagDragStart = null;
    updateAssistTagCropStatus();
    drawAssistTagCanvas();
    updateControls();
  });
  els.assistTagCanvas.addEventListener("pointerdown", beginAssistTagCrop);
  els.assistTagCanvas.addEventListener("pointermove", moveAssistTagCrop);
  els.assistTagCanvas.addEventListener("pointerup", finishAssistTagCrop);
  els.assistTagCanvas.addEventListener("pointercancel", finishAssistTagCrop);
  els.assistTagLabel.addEventListener("input", updateControls);
  els.assistTagThreshold.addEventListener("input", updateControls);
  els.saveAssistTag.addEventListener("click", saveAssistTag);
  els.assistTagList.addEventListener("change", renderSelectedAssistTag);
  els.assistTagPreview.addEventListener("error", () => {
    els.assistTagPreview.hidden = true;
    els.assistTagPreviewEmpty.hidden = false;
    els.assistTagPreviewEmpty.textContent = "Preview unavailable";
  });
  els.assistTagFile.addEventListener("change", updateControls);
  els.importAssistTag.addEventListener("click", importAssistTag);
  els.bindAssistTag.addEventListener("click", toggleAssistTagBinding);
  els.deleteAssistTag.addEventListener("click", deleteAssistTag);
  els.openMaterialDrops.addEventListener("click", openMaterialDrops);
  els.closeMaterialDialog.addEventListener("click", () => els.materialDialog.close());
  els.materialForm.addEventListener("submit", queryMaterialDrops);
  els.materialServer.addEventListener("change", queryMaterialDrops);
  els.materialQuality.addEventListener("change", () => {
    updateMaterialNames();
    queryMaterialDrops();
  });
  els.materialName.addEventListener("change", queryMaterialDrops);
  els.openNotebook.addEventListener("click", openNotebook);
  els.notebookForm.addEventListener("submit", saveNotebook);
  els.closeNotebookDialog.addEventListener("click", closeNotebook);
  els.notebookDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeNotebook();
  });
  els.notebookContent.addEventListener("input", () => {
    els.notebookStatus.textContent = els.notebookContent.value === state.notebookSavedContent
      ? "Saved"
      : "Unsaved changes";
  });
  els.jobHistory.addEventListener("change", () => selectJob(els.jobHistory.value));
  els.pauseJob.addEventListener("click", () => controlJob("pause"));
  els.resumeJob.addEventListener("click", () => controlJob("resume"));
  els.cancelJob.addEventListener("click", () => controlJob("cancel"));
}

async function loadCapabilities() {
  const payload = await api("/api/capabilities");
  state.backends = payload.capabilities || [];
  els.backendSelect.replaceChildren(
    ...state.backends.map((backend) => {
      const option = document.createElement("option");
      option.value = backend.name;
      option.textContent = backend.available ? backend.name : `${backend.name} unavailable`;
      option.disabled = !backend.available;
      return option;
    }),
  );
}

async function loadConnectionState() {
  try {
    const payload = await api("/api/state");
    state.connected = Boolean(payload.connected);
    setConnectionLabel(payload);
  } catch {
    state.connected = false;
    setConnectionLabel({ connected: false });
  }
}

async function loadTemplates() {
  try {
    const payload = await api("/api/templates");
    const templates = payload.templates || [];
    els.templateSelect.replaceChildren(
      ...templates.map((template) => {
        const option = document.createElement("option");
        option.value = template;
        option.textContent = template;
        return option;
      }),
    );
    const emptyOption = document.createElement("option");
    emptyOption.value = "";
    emptyOption.textContent = "No verification";
    els.diagnosticVerifyTemplate.replaceChildren(
      emptyOption,
      ...templates.map((template) => {
        const option = document.createElement("option");
        option.value = template;
        option.textContent = template;
        return option;
      }),
    );
    updateControls();
  } catch (error) {
    showError(error);
  }
}

async function loadEquipTemplates(preferredName = "", preferredLocation = "") {
  try {
    const selectedKey = preferredName
      ? equipTemplateKey({ name: preferredName, location: preferredLocation })
      : els.equipTemplateList.value;
    const payload = await api("/api/equip-templates");
    state.equipTemplates = payload.templates || [];
    if (!state.equipTemplates.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No templates";
      els.equipTemplateList.replaceChildren(option);
    } else {
      els.equipTemplateList.replaceChildren(
        ...state.equipTemplates.map((template) => {
          const option = document.createElement("option");
          option.value = equipTemplateKey(template);
          const location = template.location === "active" ? "Active" : "Archive";
          const mode = template.precise ? "precise" : "simple";
          option.textContent = `${location} | ${template.name} | ${mode}`;
          return option;
        }),
      );
      if (state.equipTemplates.some((template) => equipTemplateKey(template) === selectedKey)) {
        els.equipTemplateList.value = selectedKey;
      }
    }
    renderSelectedEquipTemplate();
  } catch (error) {
    state.equipTemplates = [];
    els.equipTemplateList.replaceChildren();
    renderSelectedEquipTemplate();
    showError(error);
  }
}

function equipTemplateKey(template) {
  return `${template.location}:${template.name}`;
}

function selectedEquipTemplate() {
  return state.equipTemplates.find(
    (template) => equipTemplateKey(template) === els.equipTemplateList.value,
  ) || null;
}

function renderSelectedEquipTemplate() {
  const template = selectedEquipTemplate();
  if (!template) {
    els.equipTemplatePreview.hidden = true;
    els.equipTemplatePreview.removeAttribute("src");
    els.equipTemplatePreviewStatus.hidden = false;
    els.equipTemplatePreviewStatus.textContent = "No templates";
    els.equipTestStatus.textContent = "Not tested";
    updateControls();
    return;
  }
  els.equipTemplatePreviewStatus.hidden = false;
  els.equipTemplatePreviewStatus.textContent = template.precise ? "Precise" : "Simple";
  els.equipTemplatePreview.hidden = false;
  els.equipTemplatePreview.src = `/api/equip-templates/${encodeURIComponent(template.name)}/image?location=${template.location}`;
  els.equipTestStatus.textContent = "Not tested";
  updateControls();
}

function handleEquipTemplatePreviewError() {
  els.equipTemplatePreview.hidden = true;
  els.equipTemplatePreviewStatus.hidden = false;
  els.equipTemplatePreviewStatus.textContent = "Preview unavailable";
}

async function testEquipTemplate() {
  const template = selectedEquipTemplate();
  if (!template || (!state.connected && !state.screenshotBase64)) {
    return;
  }
  state.equipTemplateBusy = true;
  els.equipTestStatus.textContent = "Testing...";
  updateControls();
  try {
    const result = await api(
      `/api/equip-templates/${encodeURIComponent(template.name)}/test`,
      {
        method: "POST",
        body: JSON.stringify({
          location: template.location,
          screenshot_base64: state.screenshotBase64 || null,
        }),
      },
    );
    const fullCount = result.matches.filter((match) => match.full_limit_break === true).length;
    const nonFullCount = result.matches.filter((match) => match.full_limit_break === false).length;
    const unknownCount = result.match_count - fullCount - nonFullCount;
    els.equipTestStatus.textContent = `${result.match_count} matches | ${fullCount} full | ${nonFullCount} non-full | ${unknownCount} unknown`;
  } catch (error) {
    els.equipTestStatus.textContent = "Test failed";
    showError(error);
  } finally {
    state.equipTemplateBusy = false;
    updateControls();
  }
}

async function captureEquipCandidates() {
  if (!els.settingSelect.value || (!state.connected && !state.screenshotBase64)) {
    return;
  }
  state.equipTemplateBusy = true;
  updateControls();
  try {
    const payload = await api("/api/equip-templates/candidates", {
      method: "POST",
      body: JSON.stringify({
        setting_name: els.settingSelect.value,
        screenshot_base64: state.screenshotBase64 || null,
      }),
    });
    state.equipCandidates = payload.candidates || [];
    if (!state.equipCandidates.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No candidates";
      els.equipCandidateList.replaceChildren(option);
    } else {
      els.equipCandidateList.replaceChildren(
        ...state.equipCandidates.map((candidate) => {
          const option = document.createElement("option");
          option.value = candidate.id;
          option.textContent = `Row ${candidate.row} | ${formatEquipCandidateKind(candidate.kind)}`;
          return option;
        }),
      );
    }
    renderSelectedEquipCandidate();
  } catch (error) {
    state.equipCandidates = [];
    els.equipCandidateList.replaceChildren();
    renderSelectedEquipCandidate();
    showError(error);
  } finally {
    state.equipTemplateBusy = false;
    updateControls();
  }
}

function selectedEquipCandidate() {
  return state.equipCandidates.find(
    (candidate) => candidate.id === els.equipCandidateList.value,
  ) || null;
}

function renderSelectedEquipCandidate() {
  const candidate = selectedEquipCandidate();
  if (!candidate) {
    els.equipCandidatePreview.hidden = true;
    els.equipCandidatePreview.removeAttribute("src");
    els.equipCandidatePreviewStatus.hidden = false;
    els.equipCandidatePreviewStatus.textContent = "No candidates";
    updateControls();
    return;
  }
  els.equipCandidatePreview.hidden = false;
  els.equipCandidatePreview.src = `data:image/png;base64,${candidate.image_base64}`;
  els.equipCandidatePreviewStatus.hidden = false;
  els.equipCandidatePreviewStatus.textContent = `Row ${candidate.row}`;
  updateControls();
}

function handleEquipCandidatePreviewError() {
  els.equipCandidatePreview.hidden = true;
  els.equipCandidatePreviewStatus.hidden = false;
  els.equipCandidatePreviewStatus.textContent = "Preview unavailable";
}

function assignEquipCandidate(target) {
  const candidate = selectedEquipCandidate();
  if (!candidate) {
    return;
  }
  if (target === "full") {
    state.equipFullCandidate = candidate;
    els.equipFullImage.value = "";
  } else {
    state.equipNonFullCandidate = candidate;
    els.equipNonFullImage.value = "";
  }
  renderEquipInputSources();
  updateControls();
}

function handleEquipFileChange(target) {
  if (target === "full" && els.equipFullImage.files[0]) {
    state.equipFullCandidate = null;
  }
  if (target === "non-full" && els.equipNonFullImage.files[0]) {
    state.equipNonFullCandidate = null;
  }
  renderEquipInputSources();
  updateControls();
}

function renderEquipInputSources() {
  els.equipFullSource.textContent = formatEquipInputSource(
    "Full",
    els.equipFullImage.files[0],
    state.equipFullCandidate,
  );
  els.equipNonFullSource.textContent = formatEquipInputSource(
    "Non-full",
    els.equipNonFullImage.files[0],
    state.equipNonFullCandidate,
  );
}

function formatEquipInputSource(label, file, candidate) {
  if (file) {
    return `${label}: ${file.name}`;
  }
  if (candidate) {
    return `${label}: row ${candidate.row} ${formatEquipCandidateKind(candidate.kind)}`;
  }
  return `${label}: not set`;
}

function formatEquipCandidateKind(kind) {
  if (kind === "equip") {
    return "Equip";
  }
  return String(kind || "candidate").replace("_", " ");
}

async function buildEquipTemplate() {
  const name = els.equipTemplateName.value.trim();
  const fullImage = els.equipFullImage.files[0] || null;
  const nonFullImage = els.equipNonFullImage.files[0] || null;
  const hasFullSource = fullImage || state.equipFullCandidate;
  const hasNonFullSource = nonFullImage || state.equipNonFullCandidate;
  if (!name || (!hasFullSource && !hasNonFullSource)) {
    return;
  }

  state.equipTemplateBusy = true;
  updateControls();
  try {
    const [fullImageBase64, nonFullImageBase64] = await Promise.all([
      fullImage
        ? blobToDataUrl(fullImage)
        : equipCandidateDataUrl(state.equipFullCandidate),
      nonFullImage
        ? blobToDataUrl(nonFullImage)
        : equipCandidateDataUrl(state.equipNonFullCandidate),
    ]);
    const request = {
      full_image_base64: fullImageBase64,
      non_full_image_base64: nonFullImageBase64,
      overwrite: false,
    };
    let template;
    try {
      template = await saveEquipTemplate(name, request);
    } catch (error) {
      const conflict = error?.payload?.error?.code === "data_file_conflict";
      if (!conflict || !window.confirm(`Replace archived template ${name}?`)) {
        throw error;
      }
      template = await saveEquipTemplate(name, { ...request, overwrite: true });
    }
    els.equipFullImage.value = "";
    els.equipNonFullImage.value = "";
    state.equipFullCandidate = null;
    state.equipNonFullCandidate = null;
    renderEquipInputSources();
    await Promise.all([
      loadEquipTemplates(template.name, template.location),
      loadTemplates(),
    ]);
  } catch (error) {
    showError(error);
  } finally {
    state.equipTemplateBusy = false;
    updateControls();
  }
}

function equipCandidateDataUrl(candidate) {
  return candidate ? `data:image/png;base64,${candidate.image_base64}` : null;
}

function saveEquipTemplate(name, request) {
  return api(`/api/equip-templates/${encodeURIComponent(name)}`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

async function moveEquipTemplate(action) {
  const template = selectedEquipTemplate();
  if (!template) {
    return;
  }
  state.equipTemplateBusy = true;
  updateControls();
  try {
    let moved;
    try {
      moved = await requestEquipTemplateMove(template, action, false);
    } catch (error) {
      const conflict = error?.payload?.error?.code === "data_file_conflict";
      const destination = action === "activate" ? "active" : "archive";
      if (!conflict || !window.confirm(`Replace ${destination} template ${template.name}?`)) {
        throw error;
      }
      moved = await requestEquipTemplateMove(template, action, true);
    }
    await Promise.all([
      loadEquipTemplates(moved.name, moved.location),
      loadTemplates(),
    ]);
  } catch (error) {
    showError(error);
  } finally {
    state.equipTemplateBusy = false;
    updateControls();
  }
}

function requestEquipTemplateMove(template, action, overwrite) {
  return api(`/api/equip-templates/${encodeURIComponent(template.name)}/${action}`, {
    method: "POST",
    body: JSON.stringify({ overwrite }),
  });
}

async function openAssistTagMaker() {
  els.assistTagDialog.showModal();
  const request = assistTagRequest();
  try {
    await loadAssistTags();
  } catch (error) {
    if (isCurrentAssistTagRequest(request)) {
      els.assistTagLibraryStatus.textContent = error.message || "Tags unavailable";
    }
  }
}

function assistTagRequest() {
  return {
    generation: state.assistTagGeneration,
    mode: state.assistTagMode,
    endpoint: `/api/${state.assistTagMode}-tags`,
  };
}

function isCurrentAssistTagRequest(request) {
  return request.generation === state.assistTagGeneration;
}

function resetAssistTagCapture() {
  state.assistTagCandidates = [];
  state.assistTagScreenshotBase64 = "";
  state.assistTagImage = null;
  state.assistTagCropBounds = null;
  state.assistTagDragStart = null;
  els.assistTagCandidate.replaceChildren();
  els.assistTagCanvasEmpty.hidden = false;
  updateAssistTagCropStatus();
  drawAssistTagCanvas();
}

function resetAssistTagMaker() {
  // Invalidate every outstanding operation, including a round trip to the same mode.
  state.assistTagGeneration += 1;
  state.assistTagBusy = false;
  state.assistTags = [];
  els.assistTagList.replaceChildren();
  els.assistTagFile.value = "";
  els.assistTagLabel.value = "Custom";
  els.assistTagThreshold.value = "0.80";
  els.assistTagMakerStatus.textContent = "Idle";
  els.assistTagLibraryStatus.textContent = "Ready";
  resetAssistTagCapture();
  renderSelectedAssistTag();
}

async function changeAssistTagMode(mode) {
  if (mode === state.assistTagMode) return;
  state.assistTagMode = mode;
  resetAssistTagMaker();
  const command = mode === "command";
  els.assistTagModes.forEach((tab) => {
    const selected = tab.dataset.tagMode === mode;
    tab.classList.toggle("active", selected);
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
  });
  els.assistTagWorkspace.setAttribute("aria-labelledby", `assist-tag-mode-${mode}`);
  els.assistTagModeLabel.textContent = command ? "Command Card Tags" : "Assist Tags";
  els.assistTagCaptureLabel.textContent = command ? "Capture Cards" : "Capture & Match";
  els.assistTagCandidateLabel.textContent = command ? "Card slot" : "Support";
  els.assistTagCandidate.setAttribute("aria-label", command ? "Command card slot" : "Matched support");
  els.assistTagCanvas.setAttribute("aria-label", command ? "Command card tag crop canvas" : "Assist tag crop canvas");
  els.assistTagList.setAttribute("aria-label", command ? "Command card tag" : "Assist tag");
  els.assistTagPreview.alt = command ? "Selected command card tag" : "Selected assist tag";
  const request = assistTagRequest();
  try {
    await loadAssistTags();
  } catch (error) {
    if (isCurrentAssistTagRequest(request)) {
      els.assistTagLibraryStatus.textContent = error.message || "Tags unavailable";
    }
  }
}

async function loadAssistTags(preferredName = "") {
  const request = assistTagRequest();
  const sequence = ++state.assistTagListSequence;
  const current = () => isCurrentAssistTagRequest(request) && sequence === state.assistTagListSequence;
  const selectedName = preferredName || els.assistTagList.value;
  try {
    const payload = await api(request.endpoint);
    if (!current()) return;
    state.assistTags = payload.tags || [];
    els.assistTagList.replaceChildren(
      ...state.assistTags.map((tag) => {
        const option = document.createElement("option");
        option.value = tag.name;
        option.textContent = assistTagDisplayName(tag.name);
        return option;
      }),
    );
    if (state.assistTags.some((tag) => tag.name === selectedName)) {
      els.assistTagList.value = selectedName;
    }
    renderSelectedAssistTag();
  } catch (error) {
    if (!current()) return;
    state.assistTags = [];
    els.assistTagList.replaceChildren();
    renderSelectedAssistTag();
    throw error;
  }
}

function selectedAssistTag() {
  return state.assistTags.find((tag) => tag.name === els.assistTagList.value) || null;
}

function assistTagDisplayName(name) {
  const marker = name.lastIndexOf("]W");
  return marker > 0 ? name.slice(1, marker) : name;
}

function assistTagConfigName(path) {
  const value = Array.isArray(path) ? path[0] : path;
  const normalized = String(value || "").replaceAll("\\", "/");
  return normalized.slice(normalized.lastIndexOf("/") + 1);
}

function isAssistTagBound(tag) {
  const configured = state.assistTagMode === "command"
    ? state.selectedSettingPlan?.special_keys || []
    : state.selectedSettingPlan?.assist?.tags || [];
  return configured.some((entry) => entry.template_name === tag?.name);
}

function renderSelectedAssistTag() {
  const tag = selectedAssistTag();
  if (!tag) {
    els.assistTagPreview.hidden = true;
    els.assistTagPreview.removeAttribute("src");
    els.assistTagPreviewEmpty.hidden = false;
    els.assistTagPreviewEmpty.textContent = "No tags";
    els.assistTagMetadata.textContent = "No tag selected";
    els.bindAssistTag.textContent = "Bind to Script";
    updateControls();
    return;
  }
  els.assistTagPreviewEmpty.hidden = true;
  els.assistTagPreview.hidden = false;
  els.assistTagPreview.src = `${assistTagRequest().endpoint}/${encodeURIComponent(tag.name)}/image?v=${Date.now()}`;
  const [sourceWidth, sourceHeight] = tag.source_size;
  const [left, top, right, bottom] = tag.offsets;
  els.assistTagMetadata.textContent = [
    `${sourceWidth}x${sourceHeight} | ${tag.image_size[0]}x${tag.image_size[1]}`,
    `offset ${left},${top} -> ${right},${bottom}`,
    `threshold ${Number(tag.threshold)}`,
  ].join("\n");
  els.bindAssistTag.textContent = isAssistTagBound(tag)
    ? "Unbind from Script"
    : "Bind to Script";
  updateControls();
}

async function captureAssistTagScreen() {
  const settingName = els.settingSelect.value;
  const request = assistTagRequest();
  if ((request.mode === "assist" && !settingName) || state.assistTagBusy
      || (!state.connected && !state.screenshotBase64)) {
    return;
  }
  state.assistTagBusy = true;
  resetAssistTagCapture();
  els.assistTagMakerStatus.textContent = "Capturing...";
  updateControls();
  try {
    const body = state.connected ? {} : { screenshot_base64: state.screenshotBase64 };
    if (request.mode === "assist") {
      body.setting_name = settingName;
      body.threshold = 0.85;
    }
    const payload = await api(`${request.endpoint}/candidates`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (!isCurrentAssistTagRequest(request)) return;
    const image = await loadAssistTagCanvasImage(payload.screenshot_base64 || "");
    if (!isCurrentAssistTagRequest(request)) return;
    state.assistTagCandidates = payload.candidates || [];
    state.assistTagScreenshotBase64 = payload.screenshot_base64 || "";
    state.assistTagImage = image;
    els.assistTagCandidate.replaceChildren(
      ...state.assistTagCandidates.map((candidate, index) => {
        const option = document.createElement("option");
        option.value = String(index);
        option.textContent = request.mode === "command" ? `Card ${candidate.slot}`
          : `Match ${index + 1} | ${(candidate.confidence * 100).toFixed(1)}%`;
        return option;
      }),
    );
    els.assistTagCanvas.width = image.naturalWidth;
    els.assistTagCanvas.height = image.naturalHeight;
    els.assistTagCanvasEmpty.hidden = true;
    drawAssistTagCanvas();
    updateAssistTagCropStatus();
    els.assistTagMakerStatus.textContent = request.mode === "command"
      ? `${state.assistTagCandidates.length} command cards`
      : `${state.assistTagCandidates.length} supports matched`;
  } catch (error) {
    if (!isCurrentAssistTagRequest(request)) return;
    els.assistTagMakerStatus.textContent = error.message || "Capture failed";
    showError(error);
  } finally {
    if (isCurrentAssistTagRequest(request)) {
      state.assistTagBusy = false;
      updateControls();
    }
  }
}

function loadAssistTagCanvasImage(base64Value) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.addEventListener("load", () => {
      resolve(image);
    }, { once: true });
    image.addEventListener("error", () => reject(new Error("Captured screenshot could not be displayed.")), {
      once: true,
    });
    image.src = `data:image/png;base64,${base64Value}`;
  });
}

function selectedAssistTagCandidate() {
  const index = Number.parseInt(els.assistTagCandidate.value, 10);
  return Number.isInteger(index) ? state.assistTagCandidates[index] || null : null;
}

function assistTagCanvasPoint(event) {
  const bounds = els.assistTagCanvas.getBoundingClientRect();
  const x = Math.round((event.clientX - bounds.left) * els.assistTagCanvas.width / bounds.width);
  const y = Math.round((event.clientY - bounds.top) * els.assistTagCanvas.height / bounds.height);
  const candidate = selectedAssistTagCandidate();
  const [left, top, width, height] = state.assistTagMode === "command" && candidate
    ? candidate.bounds : [0, 0, els.assistTagCanvas.width, els.assistTagCanvas.height];
  return [Math.min(Math.max(x, left), left + width), Math.min(Math.max(y, top), top + height)];
}

function beginAssistTagCrop(event) {
  if (!state.assistTagImage || !selectedAssistTagCandidate() || state.assistTagBusy) {
    return;
  }
  event.preventDefault();
  const point = assistTagCanvasPoint(event);
  state.assistTagDragStart = point;
  state.assistTagCropBounds = [point[0], point[1], point[0], point[1]];
  els.assistTagCanvas.setPointerCapture(event.pointerId);
  updateAssistTagCropStatus();
  updateControls();
  drawAssistTagCanvas();
}

function moveAssistTagCrop(event) {
  if (!state.assistTagDragStart) {
    return;
  }
  event.preventDefault();
  const point = assistTagCanvasPoint(event);
  const [startX, startY] = state.assistTagDragStart;
  state.assistTagCropBounds = [
    Math.min(startX, point[0]),
    Math.min(startY, point[1]),
    Math.max(startX, point[0]),
    Math.max(startY, point[1]),
  ];
  updateAssistTagCropStatus();
  drawAssistTagCanvas();
}

function finishAssistTagCrop(event) {
  if (!state.assistTagDragStart) {
    return;
  }
  if (event.type === "pointercancel") {
    state.assistTagCropBounds = null;
  } else {
    moveAssistTagCrop(event);
  }
  state.assistTagDragStart = null;
  if (els.assistTagCanvas.hasPointerCapture(event.pointerId)) {
    els.assistTagCanvas.releasePointerCapture(event.pointerId);
  }
  const crop = state.assistTagCropBounds;
  if (crop && (crop[2] - crop[0] < 4 || crop[3] - crop[1] < 4)) {
    state.assistTagCropBounds = null;
  }
  updateAssistTagCropStatus();
  drawAssistTagCanvas();
  updateControls();
}

function updateAssistTagCropStatus() {
  const crop = state.assistTagCropBounds;
  els.assistTagCropStatus.textContent = crop
    ? `${crop[0]},${crop[1]} -> ${crop[2]},${crop[3]}`
    : "Not selected";
}

function drawAssistTagCanvas() {
  const canvas = els.assistTagCanvas;
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, canvas.width, canvas.height);
  if (!state.assistTagImage) {
    return;
  }
  context.drawImage(state.assistTagImage, 0, 0, canvas.width, canvas.height);
  const selectedIndex = Number.parseInt(els.assistTagCandidate.value, 10);
  state.assistTagCandidates.forEach((candidate, index) => {
    const [x, y, width, height] = candidate.bounds;
    const selected = index === selectedIndex;
    context.lineWidth = selected ? 5 : 3;
    context.strokeStyle = selected ? "#36d399" : "#f6c344";
    context.strokeRect(x, y, width, height);
    context.font = "700 22px sans-serif";
    context.textBaseline = "top";
    const label = String(index + 1);
    const labelWidth = context.measureText(label).width + 14;
    context.fillStyle = selected ? "#147a54" : "#755600";
    context.fillRect(x, Math.max(y - 30, 0), labelWidth, 28);
    context.fillStyle = "#ffffff";
    context.fillText(label, x + 7, Math.max(y - 28, 2));
  });
  const candidate = selectedAssistTagCandidate();
  if (candidate) {
    const [anchorX, anchorY] = candidate.anchor;
    context.strokeStyle = "#36d399";
    context.lineWidth = 3;
    context.beginPath();
    context.moveTo(anchorX - 12, anchorY);
    context.lineTo(anchorX + 12, anchorY);
    context.moveTo(anchorX, anchorY - 12);
    context.lineTo(anchorX, anchorY + 12);
    context.stroke();
  }
  if (state.assistTagCropBounds) {
    const [left, top, right, bottom] = state.assistTagCropBounds;
    context.fillStyle = "rgba(36, 104, 213, 0.18)";
    context.fillRect(left, top, right - left, bottom - top);
    context.strokeStyle = "#5aa7ff";
    context.lineWidth = 4;
    context.strokeRect(left, top, right - left, bottom - top);
  }
}

async function saveAssistTag() {
  const context = assistTagRequest();
  const candidate = selectedAssistTagCandidate();
  const crop = state.assistTagCropBounds;
  const label = els.assistTagLabel.value.trim();
  const threshold = readNumber(els.assistTagThreshold);
  if (!candidate || !crop || !label || state.assistTagBusy) {
    return;
  }
  state.assistTagBusy = true;
  els.assistTagMakerStatus.textContent = "Saving...";
  updateControls();
  const request = {
    screenshot_base64: state.assistTagScreenshotBase64,
    ...(context.mode === "command" ? { slot: candidate.slot } : { anchor: candidate.anchor }),
    bounds: crop,
    label,
    threshold,
    overwrite: false,
  };
  try {
    let tag;
    try {
      tag = await api(context.endpoint, {
        method: "POST",
        body: JSON.stringify(request),
      });
    } catch (error) {
      if (!isCurrentAssistTagRequest(context)) return;
      const conflict = error?.payload?.error?.code === "data_file_conflict";
      if (!conflict || !window.confirm(`Replace the existing ${context.mode} tag?`)) {
        throw error;
      }
      tag = await api(context.endpoint, {
        method: "POST",
        body: JSON.stringify({ ...request, overwrite: true }),
      });
    }
    if (!isCurrentAssistTagRequest(context)) return;
    await Promise.all([loadAssistTags(tag.name), loadTemplates(), loadSettings()]);
    if (!isCurrentAssistTagRequest(context)) return;
    els.assistTagMakerStatus.textContent = `Saved ${assistTagDisplayName(tag.name)}`;
  } catch (error) {
    if (!isCurrentAssistTagRequest(context)) return;
    els.assistTagMakerStatus.textContent = error.message || "Save failed";
    showError(error);
  } finally {
    if (isCurrentAssistTagRequest(context)) {
      state.assistTagBusy = false;
      updateControls();
    }
  }
}

async function importAssistTag() {
  const context = assistTagRequest();
  const file = els.assistTagFile.files[0];
  if (!file || state.assistTagBusy) {
    return;
  }
  state.assistTagBusy = true;
  els.assistTagLibraryStatus.textContent = "Importing...";
  updateControls();
  try {
    const request = {
      name: file.name,
      image_base64: await blobToDataUrl(file),
      overwrite: false,
    };
    if (!isCurrentAssistTagRequest(context)) return;
    let tag;
    try {
      tag = await api(`${context.endpoint}/import`, {
        method: "POST",
        body: JSON.stringify(request),
      });
    } catch (error) {
      if (!isCurrentAssistTagRequest(context)) return;
      const conflict = error?.payload?.error?.code === "data_file_conflict";
      if (!conflict || !window.confirm(`Replace ${file.name}?`)) {
        throw error;
      }
      tag = await api(`${context.endpoint}/import`, {
        method: "POST",
        body: JSON.stringify({ ...request, overwrite: true }),
      });
    }
    if (!isCurrentAssistTagRequest(context)) return;
    els.assistTagFile.value = "";
    await Promise.all([loadAssistTags(tag.name), loadTemplates(), loadSettings()]);
    if (!isCurrentAssistTagRequest(context)) return;
    els.assistTagLibraryStatus.textContent = `Imported ${assistTagDisplayName(tag.name)}`;
  } catch (error) {
    if (!isCurrentAssistTagRequest(context)) return;
    els.assistTagLibraryStatus.textContent = error.message || "Import failed";
    showError(error);
  } finally {
    if (isCurrentAssistTagRequest(context)) {
      state.assistTagBusy = false;
      updateControls();
    }
  }
}

async function toggleAssistTagBinding() {
  const context = assistTagRequest();
  const tag = selectedAssistTag();
  const settingName = els.settingSelect.value;
  if (!tag || !settingName || state.assistTagBusy) {
    return;
  }
  state.assistTagBusy = true;
  updateControls();
  try {
    const detail = await api(`/api/settings/${encodeURIComponent(settingName)}`);
    if (!isCurrentAssistTagRequest(context) || els.settingSelect.value !== settingName) return;
    const config = detail.config;
    const configured = context.mode === "command" ? config.specialKeys : config.assistTags;
    const current = Array.isArray(configured) ? configured : [];
    const bound = current.some((path) => assistTagConfigName(path) === tag.name);
    let message;
    if (context.mode === "command") {
      const result = await api(`/api/settings/${encodeURIComponent(settingName)}/command-tags`, {
        method: "PUT",
        body: JSON.stringify({ tag_name: tag.name, bound: !bound }),
      });
      message = result.command_tag_binding.bound
        ? `Bound to script as ${result.command_tag_binding.code}` : "Unbound from script";
    } else {
      const assistTags = current.filter((path) => assistTagConfigName(path) !== tag.name);
      if (!bound) assistTags.push(tag.template_path);
      config.assistTags = assistTags;
      await api(`/api/settings/${encodeURIComponent(settingName)}`, {
        method: "PUT",
        body: JSON.stringify({ config, overwrite: true }),
      });
      message = bound ? "Unbound from script" : "Bound to script";
    }
    if (!isCurrentAssistTagRequest(context) || els.settingSelect.value !== settingName) return;
    await loadSettings(settingName);
    if (!isCurrentAssistTagRequest(context) || els.settingSelect.value !== settingName) return;
    renderSelectedAssistTag();
    els.assistTagLibraryStatus.textContent = message;
  } catch (error) {
    if (!isCurrentAssistTagRequest(context)) return;
    els.assistTagLibraryStatus.textContent = error.message || "Script update failed";
    showError(error);
  } finally {
    if (isCurrentAssistTagRequest(context)) {
      state.assistTagBusy = false;
      updateControls();
    }
  }
}

async function deleteAssistTag() {
  const context = assistTagRequest();
  const tag = selectedAssistTag();
  if (!tag || state.assistTagBusy || !window.confirm(`Delete ${assistTagDisplayName(tag.name)}?`)) {
    return;
  }
  state.assistTagBusy = true;
  updateControls();
  try {
    await api(`${context.endpoint}/${encodeURIComponent(tag.name)}`, { method: "DELETE" });
    if (!isCurrentAssistTagRequest(context)) return;
    await Promise.all([loadAssistTags(), loadTemplates(), loadSettings()]);
    if (!isCurrentAssistTagRequest(context)) return;
    els.assistTagLibraryStatus.textContent = "Tag deleted";
  } catch (error) {
    if (!isCurrentAssistTagRequest(context)) return;
    els.assistTagLibraryStatus.textContent = error.message || "Delete failed";
    showError(error);
  } finally {
    if (isCurrentAssistTagRequest(context)) {
      state.assistTagBusy = false;
      updateControls();
    }
  }
}

async function openMaterialDrops() {
  try {
    state.materialCatalog = await api("/api/material-drops/catalog");
    populateMaterialFilters();
    els.materialDialog.showModal();
    await queryMaterialDrops();
  } catch (error) {
    showError(error);
  }
}

function populateMaterialFilters() {
  const preferredServer = state.selectedSettingPlan?.server || els.materialServer.value;
  els.materialServer.replaceChildren(
    ...(state.materialCatalog?.servers || []).map((server) => {
      const option = document.createElement("option");
      option.value = server;
      option.textContent = server;
      return option;
    }),
  );
  if ((state.materialCatalog?.servers || []).includes(preferredServer)) {
    els.materialServer.value = preferredServer;
  }
  const preferredQuality = els.materialQuality.value;
  els.materialQuality.replaceChildren(
    ...(state.materialCatalog?.qualities || []).map((quality) => {
      const option = document.createElement("option");
      option.value = quality.name;
      option.textContent = quality.name;
      return option;
    }),
  );
  if ((state.materialCatalog?.qualities || []).some((item) => item.name === preferredQuality)) {
    els.materialQuality.value = preferredQuality;
  }
  updateMaterialNames();
}

function updateMaterialNames() {
  const preferredMaterial = els.materialName.value;
  const quality = (state.materialCatalog?.qualities || []).find(
    (item) => item.name === els.materialQuality.value,
  );
  const materials = quality?.materials || [];
  els.materialName.replaceChildren(
    ...materials.map((material) => {
      const option = document.createElement("option");
      option.value = material;
      option.textContent = material;
      return option;
    }),
  );
  if (materials.includes(preferredMaterial)) {
    els.materialName.value = preferredMaterial;
  }
}

async function queryMaterialDrops(event) {
  event?.preventDefault();
  const server = els.materialServer.value;
  const quality = els.materialQuality.value;
  const material = els.materialName.value;
  if (!server || !quality || !material) {
    return;
  }
  const sequence = ++state.materialQuerySequence;
  els.materialResultStatus.textContent = "Loading...";
  try {
    const parameters = new URLSearchParams({ server, quality, material });
    const result = await api(`/api/material-drops?${parameters}`);
    if (sequence !== state.materialQuerySequence) {
      return;
    }
    renderMaterialDrops(result.stages || []);
    els.materialResultStatus.textContent = `${result.count} stages | sorted by average AP`;
  } catch (error) {
    if (sequence !== state.materialQuerySequence) {
      return;
    }
    els.materialResults.replaceChildren();
    els.materialResultStatus.textContent = "Query failed";
    showError(error);
  }
}

function renderMaterialDrops(stages) {
  if (!stages.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.textContent = "No data";
    row.append(cell);
    els.materialResults.replaceChildren(row);
    return;
  }
  els.materialResults.replaceChildren(
    ...stages.map((stage) => {
      const row = document.createElement("tr");
      row.append(
        materialTableCell(stage.chapter),
        materialTableCell(stage.section),
        materialTableCell(Number(stage.average_ap).toFixed(1)),
        materialTableCell(stage.drop_rate),
      );
      return row;
    }),
  );
}

function materialTableCell(value) {
  const cell = document.createElement("td");
  cell.textContent = String(value ?? "");
  return cell;
}

async function openNotebook() {
  if (state.notebookBusy) {
    return;
  }
  state.notebookBusy = true;
  els.openNotebook.disabled = true;
  try {
    const result = await api("/api/notebook");
    state.notebookSavedContent = result.content || "";
    els.notebookContent.value = state.notebookSavedContent;
    els.notebookStatus.textContent = `Loaded | ${result.bytes || 0} bytes`;
    els.notebookDialog.showModal();
    els.notebookContent.focus();
  } catch (error) {
    showError(error);
  } finally {
    state.notebookBusy = false;
    els.openNotebook.disabled = false;
  }
}

async function saveNotebook(event, closeAfterSave = false) {
  event?.preventDefault();
  if (state.notebookBusy) {
    return false;
  }
  state.notebookBusy = true;
  els.saveNotebook.disabled = true;
  els.notebookStatus.textContent = "Saving...";
  try {
    const result = await api("/api/notebook", {
      method: "PUT",
      body: JSON.stringify({ content: els.notebookContent.value }),
    });
    state.notebookSavedContent = result.content;
    els.notebookStatus.textContent = `Saved | ${result.bytes} bytes`;
    if (closeAfterSave) {
      els.notebookDialog.close();
    }
    return true;
  } catch (error) {
    els.notebookStatus.textContent = "Save failed";
    showError(error);
    return false;
  } finally {
    state.notebookBusy = false;
    els.saveNotebook.disabled = false;
  }
}

async function closeNotebook() {
  if (els.notebookContent.value === state.notebookSavedContent) {
    els.notebookDialog.close();
    return;
  }
  await saveNotebook(undefined, true);
}

async function loadSettings(preferredName = "") {
  try {
    const selectedName = preferredName || els.settingSelect.value;
    const payload = await api("/api/settings");
    state.settings = payload.settings || [];
    els.settingSelect.replaceChildren(
      ...state.settings.map((setting) => {
        const option = document.createElement("option");
        option.value = setting.name;
        option.textContent = setting.name;
        return option;
      }),
    );
    if (state.settings.some((setting) => setting.name === selectedName)) {
      els.settingSelect.value = selectedName;
    }
    await loadSelectedSettingPlan();
    updateControls();
  } catch (error) {
    els.settingValidation.textContent = "Settings unavailable";
    els.settingValidation.classList.add("error");
    showError(error);
  }
}

async function loadSelectedSettingPlan() {
  const name = els.settingSelect.value;
  if (!name) {
    state.selectedSettingPlan = null;
    state.selectedSettingProgram = null;
    renderSettingPlan(null);
    renderBattleProgram(null);
    updateControls();
    return;
  }

  try {
    [state.selectedSettingPlan, state.selectedSettingProgram] = await Promise.all([
      api(`/api/settings/${encodeURIComponent(name)}/plan`),
      api(`/api/settings/${encodeURIComponent(name)}/program`),
    ]);
    renderSettingPlan(state.selectedSettingPlan);
    renderBattleProgram(state.selectedSettingProgram);
  } catch (error) {
    state.selectedSettingPlan = null;
    state.selectedSettingProgram = null;
    renderSettingPlan(null);
    renderBattleProgram(null);
    showError(error);
  }
  updateControls();
}

async function loadStrategies(preferredName = "") {
  try {
    const selectedName = preferredName || els.strategySelect.value;
    const payload = await api("/api/strategies");
    state.strategies = payload.strategies || [];
    els.strategySelect.replaceChildren(
      ...state.strategies.map((strategy) => {
        const option = document.createElement("option");
        option.value = strategy.name;
        option.textContent = strategy.name;
        return option;
      }),
    );
    if (state.strategies.some((strategy) => strategy.name === selectedName)) {
      els.strategySelect.value = selectedName;
    }
    await loadSelectedStrategy();
    renderPresetScriptStrategy();
    updateControls();
  } catch (error) {
    els.strategySummary.textContent = "Strategies unavailable";
    showError(error);
  }
}

async function loadSelectedStrategy() {
  const name = els.strategySelect.value;
  if (!name) {
    state.selectedStrategy = null;
    renderStrategyDetail(null);
    return;
  }

  try {
    state.selectedStrategy = await api(`/api/strategies/${encodeURIComponent(name)}`);
    renderStrategyDetail(state.selectedStrategy);
  } catch (error) {
    state.selectedStrategy = null;
    renderStrategyDetail(null);
    showError(error);
  }
}

async function openPresetEditor(kind, editing) {
  const isSetting = kind === "settings";
  const selectedName = isSetting ? els.settingSelect.value : els.strategySelect.value;
  if (editing && !selectedName) {
    return;
  }
  try {
    let value = isSetting ? { server: "CH", round1_turns: 0 } : [newStrategyEntry("Entry 1")];
    if (editing) {
      const detail = await api(`/api/${kind}/${encodeURIComponent(selectedName)}`);
      value = isSetting ? detail.config : detail.entries;
    }
    state.presetEditor = {
      kind,
      originalName: editing ? selectedName : "",
      strategyIndex: 0,
    };
    els.presetDialogTitle.textContent = `${editing ? "Edit" : "New"} ${isSetting ? "Script" : "Strategy"}`;
    els.presetDialog.showModal();
    els.presetName.value = editing ? selectedName : "";
    els.presetJson.value = JSON.stringify(value, null, 2);
    renderPresetFields();
    setPresetError("");
    els.presetName.focus();
  } catch (error) {
    showError(error);
  }
}

async function handleSettingImport() {
  const file = els.settingFileInput.files[0];
  if (!file) {
    return;
  }
  try {
    const value = JSON.parse(await file.text());
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error("Script JSON must contain an object.");
    }
    const proposedName = file.name.replace(/\.json$/i, "") || "imported-script";
    state.presetEditor = { kind: "settings", originalName: "" };
    els.presetDialogTitle.textContent = "Import Script";
    els.presetName.value = proposedName;
    els.presetJson.value = JSON.stringify(value, null, 2);
    renderPresetFields();
    setPresetError("");
    els.presetDialog.showModal();
    els.presetName.focus();
  } catch (error) {
    showError(error);
  } finally {
    els.settingFileInput.value = "";
  }
}

async function exportSelectedSetting() {
  const name = els.settingSelect.value;
  if (!name) {
    return;
  }
  try {
    const detail = await api(`/api/settings/${encodeURIComponent(name)}`);
    const blob = new Blob([`${JSON.stringify(detail.config, null, 2)}\n`], {
      type: "application/json;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${name}.json`;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    showError(error);
  }
}

function closePresetEditor() {
  els.presetDialog.close();
  state.presetEditor = null;
  updatePresetSaveState();
  setPresetError("");
}

function renderPresetFields() {
  renderPresetSkills();
  renderPresetStrategyRules();
  renderPresetScriptStrategy();
}

function updatePresetSaveState() {
  els.savePreset.disabled = Boolean(state.presetEditor?.saving || state.presetEditor?.strategyApplyBusy);
}

function scriptWaveCounts(config) {
  const rounds = new Map();
  Object.keys(config).forEach((key) => {
    const roundMatch = /^round([0-9]+)_/.exec(key);
    if (!roundMatch) return;
    const round = Number(roundMatch[1]);
    if (!Number.isSafeInteger(round)) throw new Error("Invalid wave number.");
    if (!rounds.has(round)) rounds.set(round, 0);
    const turnMatch = /^round[0-9]+_turn([0-9]+)_(skill|np|strategy|condition|replace)$/.exec(key);
    if (turnMatch) rounds.set(round, Math.max(rounds.get(round), Number(turnMatch[1]) + 1));
  });
  if (rounds.size > 1000) throw new Error("Wave list exceeds 1,000 entries.");
  let total = 0;
  return [...rounds].sort(([left], [right]) => left - right).map(([round, inferred]) => {
    const declared = config[`round${round}_turns`];
    const count = Math.max(inferred, Number.isInteger(declared) ? declared : 0);
    total += count ? count + 1 : 0;
    if (!Number.isSafeInteger(count) || total > 1000) {
      throw new Error("Turn list exceeds 1,000 entries.");
    }
    return { round, count };
  });
}

function scriptStrategyTargets(config) {
  const targets = [];
  scriptWaveCounts(config).forEach(({ round, count }) => {
    if (!count) return;
    for (let turn = 0; turn < count; turn += 1) {
      targets.push({ field: `round${round}_turn${turn}_strategy`, label: `Wave ${round} / Turn ${turn + 1}` });
    }
    targets.push({ field: `round${round}_extraStrategy`, label: `Wave ${round} / Extra turns` });
  });
  return targets;
}

function editableScriptWaves(config) {
  if (!config || typeof config !== "object" || Array.isArray(config)) throw new Error("Invalid script JSON.");
  const canonicalIndex = /^(?:0|[1-9][0-9]*)$/;
  Object.entries(config).forEach(([key, value]) => {
    const match = /^round([^_]*)_(?:turn([^_]*)_)?/.exec(key);
    if (match && (!canonicalIndex.test(match[1]) || !Number.isSafeInteger(Number(match[1]))
        || (match[2] !== undefined && (!canonicalIndex.test(match[2]) || !Number.isSafeInteger(Number(match[2])))))) {
      throw new Error("Wave editing requires canonical round and turn keys.");
    }
    if (/^round[0-9]+_turns$/.test(key) && (!Number.isInteger(value) || value < 0)) {
      throw new Error("Wave turn counts must be non-negative integers.");
    }
  });
  return scriptWaveCounts(config);
}

function renderPresetWaves() {
  const editor = state.presetEditor;
  els.presetWaves.hidden = editor?.kind !== "settings";
  els.presetWaveControls.disabled = true;
  els.presetWaveList.replaceChildren();
  els.presetWaveCount.textContent = "";
  els.presetWaveStatus.hidden = true;
  if (editor?.kind !== "settings") return;
  try {
    const waves = editableScriptWaves(JSON.parse(els.presetJson.value));
    if (!editor.wavesInitialized) {
      els.presetWaves.open = !waves.some((wave) => wave.count);
      editor.wavesInitialized = true;
    }
    els.presetWaveCount.textContent = String(waves.length);
    const lastRound = waves.at(-1)?.round;
    const total = waves.reduce((sum, wave) => sum + (wave.count ? wave.count + 1 : 0), 0);
    els.addScriptWave.disabled = total + 2 > 1000 || waves.length >= 1000
      || !Number.isSafeInteger((lastRound ?? 0) + 1);
    waves.forEach(({ round, count }) => {
      const row = document.createElement("div");
      row.className = "preset-wave-row";
      row.dataset.scriptWave = String(round);
      const name = document.createElement("span");
      name.textContent = `Wave ${round}`;
      const turns = document.createElement("output");
      turns.textContent = `${count} ${count === 1 ? "turn" : "turns"}`;
      row.append(name, turns);
      [
        ["add-turn", `Add turn to wave ${round}`, "plus", total + (count ? 1 : 2) > 1000],
        ["remove-turn", `Remove last turn from wave ${round}`, "minus", !count],
        ["delete-wave", `Delete wave ${round}`, "trash-2", round !== lastRound],
      ].forEach(([action, label, icon, disabled]) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "icon-button";
        button.dataset.waveAction = action;
        button.title = label;
        button.setAttribute("aria-label", label);
        button.disabled = disabled;
        const image = document.createElement("img");
        image.src = `/icons/${icon}.svg`;
        image.alt = "";
        image.width = 16;
        image.height = 16;
        button.append(image);
        row.append(button);
      });
      els.presetWaveList.append(row);
    });
    els.presetWaveControls.disabled = Boolean(editor.saving || editor.strategyApplyBusy);
  } catch (error) {
    els.presetWaveStatus.textContent = error instanceof SyntaxError ? "Invalid script JSON." : error.message;
    els.presetWaveStatus.hidden = false;
  }
}

function changeScriptWaves(action, round) {
  const editor = state.presetEditor;
  if (editor?.kind !== "settings" || editor.saving || editor.strategyApplyBusy || els.presetWaveControls.disabled) return;
  const restoreFocus = els.presetWaveControls.contains(document.activeElement);
  try {
    const config = JSON.parse(els.presetJson.value);
    const waves = editableScriptWaves(config);
    const wave = waves.find((item) => item.round === round);
    if (action === "add-wave") {
      if (els.addScriptWave.disabled) return;
      round = (waves.at(-1)?.round ?? 0) + 1;
      config[`round${round}_turns`] = 1;
      editor.strategyTarget = `round${round}_turn0_strategy`;
    } else if (!wave) {
      return;
    } else if (action === "add-turn") {
      config[`round${round}_turns`] = wave.count + 1;
      editor.strategyTarget = `round${round}_turn${wave.count}_strategy`;
    } else if (action === "remove-turn") {
      if (!wave.count || !window.confirm(`Remove turn ${wave.count} from wave ${round} and all its fields?`)) return;
      const prefix = `round${round}_turn${wave.count - 1}_`;
      Object.keys(config).filter((key) => key.startsWith(prefix)).forEach((key) => { delete config[key]; });
      config[`round${round}_turns`] = wave.count - 1;
    } else if (action === "delete-wave") {
      if (round !== waves.at(-1)?.round || !window.confirm(`Delete wave ${round} and all its fields?`)) return;
      const prefix = `round${round}_`;
      Object.keys(config).filter((key) => key.startsWith(prefix)).forEach((key) => { delete config[key]; });
    } else {
      return;
    }
    editableScriptWaves(config);
    els.presetJson.value = JSON.stringify(config, null, 2);
    renderPresetScriptStrategy();
    if (restoreFocus) {
      const row = els.presetWaveList.querySelector(`[data-script-wave="${round}"]`);
      const preferred = action === "add-wave" ? els.addScriptWave : row?.querySelector(`[data-wave-action="${action}"]`);
      const button = [preferred, row?.querySelector('[data-wave-action="remove-turn"]'),
        row?.querySelector('[data-wave-action="add-turn"]'), els.addScriptWave,
        els.presetWaveList.querySelector("button:not(:disabled)")].find((item) => item && !item.disabled);
      button?.focus({ preventScroll: true });
    }
    setPresetError("");
  } catch (error) {
    setPresetError(error.message);
  }
}

function renderPresetScriptStrategy() {
  presetTeam.render();
  presetAssist.render();
  renderPresetWaves();
  renderPresetRunOptions();
  const editor = state.presetEditor;
  const isSetting = editor?.kind === "settings";
  els.presetScriptStrategy.hidden = !isSetting;
  els.presetScriptStrategy.disabled = true;
  renderPresetTurnNps(null, "");
  updatePresetSaveState();
  if (!isSetting) return;
  let config;
  let targets;
  try {
    config = JSON.parse(els.presetJson.value);
    if (!config || typeof config !== "object" || Array.isArray(config)) throw new Error("Invalid script JSON.");
    targets = scriptStrategyTargets(config);
  } catch (error) {
    els.presetTurnStrategyStatus.textContent = error instanceof SyntaxError ? "Invalid script JSON." : error.message;
    return;
  }
  const target = targets.some((item) => item.field === editor.strategyTarget)
    ? editor.strategyTarget : targets[0]?.field || "";
  editor.strategyTarget = target;
  const source = state.strategies.some((item) => item.name === editor.strategySource)
    ? editor.strategySource : state.strategies[0]?.name || "";
  editor.strategySource = source;
  els.presetStrategyTarget.replaceChildren(...(targets.length ? targets : [{ field: "", label: "No turns configured" }]).map((item) => {
    const option = document.createElement("option");
    option.value = item.field;
    option.textContent = item.label;
    return option;
  }));
  els.presetStrategyTarget.value = target;
  renderPresetTurnNps(config, target);
  els.presetStrategyTarget.disabled = !targets.length;
  els.presetStrategySource.replaceChildren(...(state.strategies.length ? state.strategies : [{ name: "" }]).map((item) => {
    const option = document.createElement("option");
    option.value = item.name;
    option.textContent = item.name || "No presets available";
    return option;
  }));
  els.presetStrategySource.value = source;
  els.presetStrategySource.disabled = !state.strategies.length;
  els.presetScriptStrategy.disabled = Boolean(editor.strategyApplyBusy || editor.saving);
  els.applyTurnStrategy.disabled = !target || !source;
  const strategies = config[target];
  els.clearTurnStrategy.disabled = !target || strategies == null || (Array.isArray(strategies) && !strategies.length);
  els.presetTurnStrategyStatus.textContent = editor.strategyApplyBusy ? "Loading preset..."
    : !target ? "No turn selected"
      : Array.isArray(strategies) && strategies.length ? `${strategies.length} strategies configured`
        : strategies !== undefined && strategies !== null && !Array.isArray(strategies) ? "Invalid strategy value"
          : "No strategy configured";
}

function readScriptStrategyTarget() {
  const config = JSON.parse(els.presetJson.value);
  const field = els.presetStrategyTarget.value;
  if (!config || typeof config !== "object" || Array.isArray(config)
      || !scriptStrategyTargets(config).some((target) => target.field === field)) {
    throw new Error("Select a valid script turn.");
  }
  return { config, field };
}

function renderPresetRunOptions() {
  const editor = state.presetEditor;
  els.presetRunOptions.hidden = editor?.kind !== "settings";
  els.presetRunControls.disabled = editor?.kind !== "settings" || Boolean(editor?.saving || editor?.strategyApplyBusy);
  if (editor?.kind !== "settings") return;
  if (!editor.runOptionsInitialized) {
    els.presetRunOptions.open = false;
    editor.runOptionsInitialized = true;
  }
  try {
    const config = JSON.parse(els.presetJson.value);
    if (!config || typeof config !== "object" || Array.isArray(config)) {
      els.presetRunControls.disabled = true;
      return;
    }
    els.presetRunInputs.forEach((input) => {
      const field = input.dataset.runOption;
      const draft = editor.runOptionDrafts?.[field];
      input.setCustomValidity(draft?.error || "");
      if (input.type === "checkbox") {
        input.checked = Boolean(config[field]);
      } else {
        const value = Object.hasOwn(config, field) ? config[field] : 30;
        // Reassigning value would erase native partial numbers such as "1e".
        if (!draft) input.value = typeof value === "number" ? String(value) : "";
        input.disabled = !config.stuckRestart && !draft;
      }
    });
  } catch {
    // Raw JSON remains authoritative while its syntax is incomplete.
    els.presetRunControls.disabled = true;
  }
}

function updatePresetRunOption(event, draftOnly = false) {
  const editor = state.presetEditor;
  const input = event.currentTarget;
  if (editor?.kind !== "settings" || editor.saving || editor.strategyApplyBusy
      || els.presetRunControls.disabled || input.disabled) return;
  try {
    const config = JSON.parse(els.presetJson.value);
    if (!config || typeof config !== "object" || Array.isArray(config)) return;
    const field = input.dataset.runOption;
    if (input.type === "checkbox") {
      config[field] = input.checked;
    } else {
      const value = input.valueAsNumber;
      if (!Number.isFinite(value) || value < 1 || value > 600) {
        const error = "Check interval must be between 1 and 600 seconds.";
        editor.runOptionDrafts ||= {};
        editor.runOptionDrafts[field] = { error };
        input.setCustomValidity(error);
        return;
      }
      if (editor.runOptionDrafts) delete editor.runOptionDrafts[field];
      input.setCustomValidity("");
      if (draftOnly) return;
      config[field] = value;
    }
    els.presetJson.value = JSON.stringify(config, null, 2);
    renderPresetScriptStrategy();
    setPresetError("");
  } catch (error) {
    setPresetError(error.message);
  }
}

function turnNpField(target) {
  return /^round[0-9]+_turn[0-9]+_strategy$/.test(target) ? target.replace(/_strategy$/, "_np") : "";
}

function readTurnNps(config, field) {
  const nps = Object.hasOwn(config, field) ? config[field] : [];
  if (!Array.isArray(nps) || nps.length > 3 || new Set(nps).size !== nps.length
      || nps.some((value) => !Number.isInteger(value) || value < 1 || value > 3)) {
    throw new Error("Invalid NP sequence.");
  }
  return [...nps];
}

function renderPresetTurnNps(config, target) {
  const field = turnNpField(target);
  els.presetTurnNps.hidden = !field;
  els.presetTurnNpStatus.hidden = true;
  els.presetTurnNpStatus.textContent = "";
  els.clearTurnNps.disabled = true;
  els.presetTurnNpInputs.forEach((input) => { input.disabled = true; });
  if (!field || !config) return;
  const value = config[field];
  els.clearTurnNps.disabled = !Object.hasOwn(config, field) || (Array.isArray(value) && !value.length);
  try {
    const nps = readTurnNps(config, field);
    els.presetTurnNpInputs.forEach((input, index) => {
      input.replaceChildren(...[0, 1, 2, 3].map((servant) => {
        const option = document.createElement("option");
        option.value = String(servant);
        option.textContent = servant ? `NP ${servant}` : "None";
        return option;
      }));
      input.value = String(nps[index] || 0);
      input.disabled = index > nps.length;
    });
  } catch (error) {
    els.presetTurnNpInputs.forEach((input) => { input.value = "0"; });
    els.presetTurnNpStatus.textContent = error.message;
    els.presetTurnNpStatus.hidden = false;
  }
}

function updateTurnNps(event) {
  const editor = state.presetEditor;
  if (editor?.kind !== "settings" || editor.saving || editor.strategyApplyBusy
      || els.presetScriptStrategy.disabled) return;
  try {
    const { config, field: target } = readScriptStrategyTarget();
    const field = turnNpField(target);
    if (!field) return;
    let nps = [];
    if (event) {
      const input = event.currentTarget;
      if (input.disabled) return;
      nps = readTurnNps(config, field);
      const index = Number(input.dataset.turnNpIndex);
      const servant = Number(input.value);
      if (servant === 0) {
        nps.splice(index, 1);
      } else {
        const previousIndex = nps.indexOf(servant);
        if (previousIndex !== -1) nps[previousIndex] = nps[index];
        nps[index] = servant;
        nps = nps.filter((value) => value !== undefined);
      }
    } else if (els.clearTurnNps.disabled || !window.confirm("Clear Noble Phantasms for this turn?")) {
      return;
    }
    config[field] = nps;
    els.presetJson.value = JSON.stringify(config, null, 2);
    renderPresetScriptStrategy();
    setPresetError("");
  } catch (error) {
    setPresetError(error.message);
  }
}

async function applyPresetToTurn() {
  const editor = state.presetEditor;
  if (editor?.kind !== "settings" || editor.saving || editor.strategyApplyBusy || els.applyTurnStrategy.disabled
      || els.presetScriptStrategy.disabled) return;
  try {
    const { config, field } = readScriptStrategyTarget();
    const existing = config[field];
    if (existing != null && (!Array.isArray(existing) || existing.length)
        && !window.confirm("Replace the current turn strategies?")) return;
    const sourceName = els.presetStrategySource.value;
    const sourceJson = els.presetJson.value;
    editor.strategyApplyBusy = true;
    renderPresetScriptStrategy();
    const preset = await api(`/api/strategies/${encodeURIComponent(sourceName)}`);
    if (state.presetEditor !== editor) return;
    if (els.presetJson.value !== sourceJson) throw new Error("Script changed while the preset was loading. Apply it again.");
    if (!preset.validation?.ok || !Array.isArray(preset.entries) || !preset.entries.length) {
      throw new Error("Selected strategy preset is invalid or empty.");
    }
    config[field] = preset.entries.map((entry) => structuredClone(entry.strategy));
    els.presetJson.value = JSON.stringify(config, null, 2);
    setPresetError("");
  } catch (error) {
    if (state.presetEditor === editor) setPresetError(error.message);
  } finally {
    editor.strategyApplyBusy = false;
    if (state.presetEditor === editor) renderPresetScriptStrategy();
    updatePresetSaveState();
  }
}

function clearTurnStrategy() {
  if (state.presetEditor?.kind !== "settings" || state.presetEditor.saving || els.clearTurnStrategy.disabled
      || els.presetScriptStrategy.disabled) return;
  try {
    const { config, field } = readScriptStrategyTarget();
    if (!window.confirm("Clear strategies for this turn?")) return;
    // The empty field preserves turn counts inferred from legacy script keys.
    config[field] = [];
    els.presetJson.value = JSON.stringify(config, null, 2);
    renderPresetScriptStrategy();
    setPresetError("");
  } catch (error) {
    setPresetError(error.message);
  }
}

function newStrategyEntry(tag) {
  const strategy = { breakpoint: [false, false], colorFirst: true };
  ["card1", "card2", "card3"].forEach((card) => {
    strategy[card] = { type: 2, cards: [], criticalStar: 0, more_or_less: true };
  });
  return { tag, strategy };
}

function changePresetStrategyEntries(action) {
  const editor = state.presetEditor;
  if (editor?.kind !== "strategies" || els.presetStrategyRules.disabled) return;
  try {
    const entries = JSON.parse(els.presetJson.value);
    if (!Array.isArray(entries)) return;
    const sources = entries.map((_entry, index) => index);
    const index = editor.strategyIndex || 0;
    let selectedIndex = index;
    if (action === "add") {
      let number = entries.length + 1;
      while (entries.some((entry) => entry?.tag === `Entry ${number}`)) number += 1;
      selectedIndex = entries.length ? index + 1 : 0;
      entries.splice(selectedIndex, 0, newStrategyEntry(`Entry ${number}`));
      sources.splice(selectedIndex, 0, -1);
    } else if (action === "duplicate") {
      const entry = entries[index];
      if (!entry || typeof entry !== "object" || Array.isArray(entry)) return;
      const copy = structuredClone(entry);
      copy.tag = `${typeof entry.tag === "string" && entry.tag ? entry.tag : "Entry"} Copy`;
      selectedIndex = index + 1;
      entries.splice(selectedIndex, 0, copy);
      sources.splice(selectedIndex, 0, index);
    } else if (action === "delete") {
      if (!entries.length || !window.confirm("Delete this strategy entry?")) return;
      entries.splice(index, 1);
      sources.splice(index, 1);
      selectedIndex = Math.min(index, Math.max(0, entries.length - 1));
    } else if (action === "up" || action === "down") {
      selectedIndex = index + (action === "up" ? -1 : 1);
      if (selectedIndex < 0 || selectedIndex >= entries.length) return;
      [entries[index], entries[selectedIndex]] = [entries[selectedIndex], entries[index]];
      [sources[index], sources[selectedIndex]] = [sources[selectedIndex], sources[index]];
    } else {
      return;
    }
    // Carry each entry's rejected edits with it, including copies of draft entries.
    const drafts = {};
    sources.forEach((sourceIndex, newIndex) => {
      if (sourceIndex < 0) return;
      const prefix = `${sourceIndex}.`;
      Object.entries(editor.strategyDrafts || {}).forEach(([key, value]) => {
        if (key.startsWith(prefix)) drafts[`${newIndex}.${key.slice(prefix.length)}`] = { ...value };
      });
    });
    editor.strategyDrafts = drafts;
    editor.strategyIndex = selectedIndex;
    els.presetJson.value = JSON.stringify(entries, null, 2);
    renderPresetStrategyRules();
    setPresetError(Object.values(drafts)[0]?.error || "");
  } catch (error) {
    setPresetError(error.message);
  }
}

function updatePresetStrategyTag() {
  const editor = state.presetEditor;
  if (editor?.kind !== "strategies" || els.presetStrategyTag.disabled || els.presetStrategyRules.disabled) return;
  const key = `${editor.strategyIndex}.tag`;
  const drafts = editor.strategyDrafts ||= {};
  els.presetStrategyTag.setCustomValidity("");
  try {
    const tag = els.presetStrategyTag.value.trim();
    if (!tag) throw new Error("Entry name is required.");
    const entries = JSON.parse(els.presetJson.value);
    entries[editor.strategyIndex].tag = tag;
    delete drafts[key];
    els.presetJson.value = JSON.stringify(entries, null, 2);
    renderPresetStrategyRules();
    setPresetError(Object.values(drafts)[0]?.error || "");
  } catch (error) {
    drafts[key] = { value: els.presetStrategyTag.value, error: error.message };
    els.presetStrategyTag.setCustomValidity(error.message);
    setPresetError(error.message);
  }
}

function renderPresetStrategyRules() {
  const editor = state.presetEditor;
  const isStrategy = editor?.kind === "strategies";
  els.presetStrategyRules.hidden = !isStrategy;
  els.presetStrategyRules.disabled = true;
  if (!isStrategy) {
    return;
  }
  els.presetStrategyEntry.replaceChildren();
  let entries;
  try {
    entries = JSON.parse(els.presetJson.value);
  } catch (_error) {
    return;
  }
  if (!Array.isArray(entries)) return;
  if (!entries.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No strategy entries";
    els.presetStrategyEntry.append(option);
  }
  const selectedIndex = Math.max(0, Math.min(editor.strategyIndex || 0, entries.length - 1));
  editor.strategyIndex = selectedIndex;
  if (entries.length) els.presetStrategyEntry.replaceChildren(...entries.map((entry, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = `${index + 1}. ${typeof entry?.tag === "string" && entry.tag ? entry.tag : "Untitled"}`;
    return option;
  }));
  els.presetStrategyEntry.value = entries.length ? String(selectedIndex) : "";
  els.presetStrategyEntry.disabled = !entries.length;
  els.presetStrategyRules.disabled = false;
  const selectedEntry = entries[selectedIndex];
  const validEntry = selectedEntry && typeof selectedEntry === "object" && !Array.isArray(selectedEntry);
  els.duplicateStrategyEntry.disabled = !validEntry;
  els.deleteStrategyEntry.disabled = !entries.length;
  els.moveStrategyEntryUp.disabled = selectedIndex <= 0;
  els.moveStrategyEntryDown.disabled = selectedIndex >= entries.length - 1;
  const tagDraft = editor.strategyDrafts?.[`${selectedIndex}.tag`];
  els.presetStrategyTag.disabled = !validEntry;
  els.presetStrategyTag.value = tagDraft ? tagDraft.value : typeof selectedEntry?.tag === "string" ? selectedEntry.tag : "";
  els.presetStrategyTag.setCustomValidity(tagDraft?.error || "");
  const strategy = entries[selectedIndex]?.strategy;
  const validStrategy = strategy && typeof strategy === "object" && !Array.isArray(strategy);
  const breakpoints = validStrategy ? strategy.breakpoint : null;
  const validBreakpoints = Array.isArray(breakpoints) && breakpoints.length === 2
    && breakpoints.every((value) => typeof value === "boolean");
  els.presetStrategyBreakpoints.forEach((input, index) => {
    input.disabled = !validBreakpoints;
    input.checked = validBreakpoints && breakpoints[index];
  });
  els.presetStrategyColorFirst.disabled = !validStrategy || (
    strategy.colorFirst !== undefined && typeof strategy.colorFirst !== "boolean"
  );
  els.presetStrategyColorFirst.checked = validStrategy && strategy.colorFirst !== false;
  els.presetStrategyCards.forEach((row) => {
    const spec = validStrategy ? strategy[row.dataset.strategyCard] : null;
    const validSpec = spec && typeof spec === "object" && !Array.isArray(spec);
    row.querySelectorAll("[data-card-field]").forEach((input) => {
      input.setCustomValidity("");
      const field = input.dataset.cardField;
      const draft = editor.strategyDrafts?.[`${selectedIndex}.${row.dataset.strategyCard}.${field}`];
      const value = validSpec ? spec[field] : undefined;
      input.disabled = !validSpec || (!draft && ((field === "cards" && spec.type === 2)
        || (["criticalStar", "more_or_less"].includes(field) && spec.type === 0)));
      if (field === "type") {
        input.value = [0, 1, 2].includes(value) ? String(value) : "";
      } else if (field === "cards") {
        input.value = Array.isArray(value) && value.every((part) => ["string", "number"].includes(typeof part))
          ? value.join(", ") : "";
        input.title = spec?.type === 0 ? "Ordered servant positions: 1, 2, 3" : "Ordered card or tag codes: 1B, S0, 1BS0";
      } else if (field === "more_or_less") {
        input.value = typeof value === "boolean" ? String(value) : "";
      } else {
        input.value = typeof value === "number" && Number.isFinite(value) ? String(value) : "";
      }
      if (draft) {
        input.value = draft.value;
        input.setCustomValidity(draft.error);
      }
    });
  });
}

function updatePresetStrategyCard(event) {
  const input = event.target;
  const field = input.dataset.cardField;
  const row = input.closest("[data-strategy-card]");
  const editor = state.presetEditor;
  if (!field || !row || editor?.kind !== "strategies" || els.presetStrategyRules.disabled || input.disabled) {
    return;
  }
  input.setCustomValidity("");
  // Keep rejected edits separate from the last valid JSON until corrected.
  const draftKey = `${editor.strategyIndex}.${row.dataset.strategyCard}.${field}`;
  const drafts = editor.strategyDrafts ||= {};
  try {
    const entries = JSON.parse(els.presetJson.value);
    const spec = entries[editor.strategyIndex].strategy[row.dataset.strategyCard];
    if (field === "type") {
      const type = Number(input.value);
      if (![0, 1, 2].includes(type)) {
        return;
      }
      spec.type = type;
      if (type === 0 && !validStrategyPreferences(spec.cards, type)) {
        spec.cards = [1];
      } else if (type === 1 && !validStrategyPreferences(spec.cards, type)) {
        spec.cards = ["1B", "2B", "3B", "1A", "2A", "3A", "1Q", "2Q", "3Q"];
      }
    } else if (field === "cards") {
      const tokens = input.value.trim().split(/[\s,]+/).filter(Boolean);
      const preferences = spec.type === 0 ? tokens.map((value) => /^[1-3]$/.test(value) ? Number(value) : value) : tokens;
      if (spec.type !== 2 && !validStrategyPreferences(preferences, spec.type)) {
        throw new Error(spec.type === 0 ? "NP positions must be 1, 2, or 3." : "Card preferences contain an invalid card or tag code.");
      }
      spec.cards = preferences;
    } else if (field === "criticalStar") {
      if (!input.checkValidity() || input.value === "") {
        throw new Error("Critical star threshold must be between 0 and 10.");
      }
      spec.criticalStar = Number(input.value);
    } else if (field === "more_or_less") {
      spec.more_or_less = input.value === "true";
    }
    delete drafts[draftKey];
    els.presetJson.value = JSON.stringify(entries, null, 2);
    renderPresetStrategyRules();
    setPresetError(Object.values(drafts)[0]?.error || "");
  } catch (error) {
    drafts[draftKey] = { value: input.value, error: error.message };
    input.setCustomValidity(error.message);
    setPresetError(error.message);
  }
}

function validStrategyPreferences(preferences, type) {
  return Array.isArray(preferences) && preferences.length > 0 && preferences.every((value) => (
    type === 0 ? Number.isInteger(value) && value >= 1 && value <= 3
      : typeof value === "string" && /^(?:[1-3][ABQ](?:S[0-9]+)?|S[0-9]+)$/.test(value)
  ));
}

function updatePresetStrategyRule(event) {
  const editor = state.presetEditor;
  if (editor?.kind !== "strategies" || els.presetStrategyRules.disabled || event.target.disabled) {
    return;
  }
  try {
    const entries = JSON.parse(els.presetJson.value);
    const strategy = entries[editor.strategyIndex].strategy;
    if (event.target === els.presetStrategyColorFirst) {
      strategy.colorFirst = event.target.checked;
    } else {
      strategy.breakpoint[Number(event.target.dataset.strategyBreakpoint)] = event.target.checked;
    }
    els.presetJson.value = JSON.stringify(entries, null, 2);
    renderPresetStrategyRules();
    setPresetError(Object.values(editor.strategyDrafts || {})[0]?.error || "");
  } catch (error) {
    setPresetError(`Invalid JSON: ${error.message}`);
  }
}

function renderPresetSkills() {
  const isSetting = state.presetEditor?.kind === "settings";
  els.presetAssistSkills.hidden = !isSetting;
  els.presetAssistSkills.disabled = true;
  if (!isSetting) {
    return;
  }
  let config;
  try {
    config = JSON.parse(els.presetJson.value);
    if (!config || typeof config !== "object" || Array.isArray(config)) {
      return;
    }
  } catch (_error) {
    return;
  }
  const levels = Array.isArray(config.skillsLevel) ? config.skillsLevel : [];
  const isCntw = String(config.server).toUpperCase() === "CNTW";
  els.presetAssistSkills.disabled = false;
  els.presetSkillInputs.forEach((input, index) => {
    const level = levels[index] ?? 0;
    const unsupported = isCntw && index >= 6;
    input.value = Number.isInteger(level) && level >= 0 && level <= 10 ? String(level) : "";
    input.max = unsupported ? "0" : "10";
    input.disabled = unsupported && level === 0;
    input.title = unsupported ? "Not available on CNTW" : "Minimum level; 0 means any level";
  });
}

function updatePresetSkills() {
  if (state.presetEditor?.kind !== "settings" || els.presetAssistSkills.disabled) {
    return;
  }
  const levels = els.presetSkillInputs.map((input) => input.valueAsNumber);
  if (els.presetSkillInputs.some((input) => !input.validity.valid)) {
    setPresetError("Skill levels must be integers from 0 to 10 within the server's supported slots.");
    return;
  }
  try {
    const config = JSON.parse(els.presetJson.value);
    config.skillsLevel = levels;
    els.presetJson.value = JSON.stringify(config, null, 2);
    renderPresetSkills();
    setPresetError("");
  } catch (error) {
    setPresetError(`Invalid JSON: ${error.message}`);
  }
}

async function savePreset(event) {
  event.preventDefault();
  const editor = state.presetEditor;
  if (!editor || editor.saving || editor.strategyApplyBusy) {
    return;
  }
  const invalidRunField = editor.kind === "settings" && Object.keys(editor.runOptionDrafts || {})[0];
  if (invalidRunField) {
    els.presetRunOptions.open = true;
    renderPresetRunOptions();
    els.presetRunInputs.find((input) => input.dataset.runOption === invalidRunField)?.reportValidity();
    return;
  }
  const invalidDraft = editor.kind === "strategies" && Object.entries(editor.strategyDrafts || {})[0];
  if (invalidDraft) {
    editor.strategyIndex = Number(invalidDraft[0].split(".")[0]);
    renderPresetStrategyRules();
    setPresetError(invalidDraft[1].error);
    els.presetForm.reportValidity();
    return;
  }
  const name = els.presetName.value.trim();
  if (!name) {
    setPresetError("Name is required.");
    return;
  }
  let value;
  try {
    value = JSON.parse(els.presetJson.value);
  } catch (error) {
    setPresetError(`Invalid JSON: ${error.message}`);
    return;
  }
  const isSetting = editor.kind === "settings";
  const request = isSetting ? { config: value } : { entries: value };
  request.overwrite = Boolean(editor.originalName && editor.originalName === name);
  editor.saving = true;
  renderPresetScriptStrategy();
  try {
    await api(`/api/${editor.kind}/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify(request),
    });
    if (state.presetEditor === editor) closePresetEditor();
    if (isSetting) {
      await loadSettings(name);
    } else {
      await loadStrategies(name);
    }
  } catch (error) {
    if (state.presetEditor === editor) setPresetError(error?.payload?.error?.message || error.message || "Save failed.");
  } finally {
    editor.saving = false;
    if (state.presetEditor === editor) renderPresetScriptStrategy();
    else updatePresetSaveState();
  }
}

async function deletePreset(kind) {
  const isSetting = kind === "settings";
  const name = isSetting ? els.settingSelect.value : els.strategySelect.value;
  if (!name || !window.confirm(`Delete ${name}?`)) {
    return;
  }
  try {
    await api(`/api/${kind}/${encodeURIComponent(name)}`, { method: "DELETE" });
    if (isSetting) {
      await loadSettings();
    } else {
      await loadStrategies();
    }
  } catch (error) {
    showError(error);
  }
}

function setPresetError(message) {
  els.presetError.textContent = message;
  els.presetError.hidden = !message;
}

async function loadDevices(preferredDeviceId = "") {
  try {
    const payload = await api("/api/devices");
    state.devices = payload.devices || [];
    renderDevices(preferredDeviceId);
  } catch (error) {
    showError(error);
  }
}

function renderDevices(preferredDeviceId = "") {
  const backend = els.backendSelect.value;
  const selectedDeviceId = preferredDeviceId || els.deviceList.value;
  const devices = state.devices.filter((device) => !backend || device.backend === backend);
  els.deviceList.replaceChildren(
    ...devices.map((device) => {
      const option = document.createElement("option");
      option.value = device.device_id;
      option.textContent = `${device.name || device.device_id} · ${device.status}`;
      option.disabled = device.status !== "device";
      return option;
    }),
  );
  if (selectedDeviceId) {
    els.deviceList.value = selectedDeviceId;
  }
  updateControls();
}

async function addManualAdbEndpoint() {
  const endpoint = els.manualAdbEndpoint.value.trim();
  if (!endpoint) {
    return;
  }

  try {
    const payload = await api("/api/adb/connect-endpoint", {
      method: "POST",
      body: JSON.stringify({ endpoint }),
    });
    const device = payload.device;
    if (device) {
      selectBackend(device.backend);
      mergeDevice(device);
      renderDevices(device.device_id);
      els.manualAdbEndpoint.value = "";
      await loadDevices(device.device_id);
    }
    await loadEvents();
  } catch (error) {
    showError(error);
  } finally {
    updateControls();
  }
}

async function connect() {
  try {
    const payload = await api("/api/connect", {
      method: "POST",
      body: JSON.stringify({
        backend: els.backendSelect.value,
        device_id: els.deviceList.value,
      }),
    });
    state.connected = payload.connected;
    setConnectionLabel(payload);
    await loadEvents();
  } catch (error) {
    showError(error);
  } finally {
    updateControls();
  }
}

async function disconnect() {
  try {
    const payload = await api("/api/disconnect", { method: "POST" });
    state.connected = payload.connected;
    setConnectionLabel(payload);
    clearScreenshot();
    await loadEvents();
  } catch (error) {
    showError(error);
  } finally {
    updateControls();
  }
}

async function captureScreenshot() {
  try {
    const response = await api("/api/snapshot");
    const blob = await response.blob();
    setScreenshot(await blobToDataUrl(blob));
    await loadEvents();
  } catch (error) {
    showError(error);
  }
}

function setScreenshot(dataUrl) {
  if (state.screenshotUrl) {
    URL.revokeObjectURL(state.screenshotUrl);
  }
  state.screenshotUrl = dataUrl;
  state.screenshotBase64 = dataUrl.split(",", 2)[1] || "";
  state.debugOverlayDataUrl = null;
  state.screenMode = "source";
  state.latestMatch = null;
  els.screenshot.classList.add("visible");
  els.screenEmpty.hidden = true;
  clearMatchOverlay();
  setScreenMode("source");
  updateControls();
}

function clearScreenshot() {
  if (state.screenshotUrl) {
    URL.revokeObjectURL(state.screenshotUrl);
  }
  state.screenshotUrl = null;
  state.screenshotBase64 = "";
  state.debugOverlayDataUrl = null;
  state.screenMode = "source";
  state.screenshotNaturalSize = null;
  state.latestMatch = null;
  els.screenshot.removeAttribute("src");
  els.screenshot.classList.remove("visible", "actual-size");
  els.screenEmpty.hidden = false;
  els.screenMeta.textContent = "No capture";
  els.matchResult.textContent = "No match";
  clearMatchOverlay();
  setScreenMode("source");
  updateControls();
}

async function matchTemplate() {
  try {
    const roi = els.recognitionRoiEnabled.checked
      ? [
        readNumber(els.recognitionRoiX),
        readNumber(els.recognitionRoiY),
        readNumber(els.recognitionRoiWidth),
        readNumber(els.recognitionRoiHeight),
      ]
      : null;
    const payload = await api("/api/match/debug", {
      method: "POST",
      body: JSON.stringify({
        screenshot_base64: state.screenshotBase64,
        template_path: els.templateSelect.value,
        threshold: Number(els.thresholdInput.value),
        roi,
        scales: readScales(),
      }),
    });
    state.latestMatch = payload.result;
    state.debugOverlayDataUrl = `data:image/png;base64,${payload.overlay_base64}`;
    renderMatch(payload.result);
    setScreenMode("debug");
    await loadEvents();
  } catch (error) {
    showError(error);
  }
}

async function sendTap() {
  try {
    await api("/api/tap", {
      method: "POST",
      body: JSON.stringify({
        x: readNumber(els.tapX),
        y: readNumber(els.tapY),
      }),
    });
    await loadEvents();
  } catch (error) {
    showError(error);
  }
}

async function sendSwipe() {
  try {
    await api("/api/swipe", {
      method: "POST",
      body: JSON.stringify({
        x1: readNumber(els.swipeX1),
        y1: readNumber(els.swipeY1),
        x2: readNumber(els.swipeX2),
        y2: readNumber(els.swipeY2),
        duration_ms: readNumber(els.swipeDuration),
      }),
    });
    await loadEvents();
  } catch (error) {
    showError(error);
  }
}

async function startDiagnosticJob() {
  const templatePath = els.templateSelect.value;
  if (!templatePath) {
    return;
  }
  const payload = {
    template_path: templatePath,
    threshold: Number(els.thresholdInput.value),
    timeout_seconds: Number(els.diagnosticTimeout.value),
    tap_on_match: els.diagnosticTap.checked,
  };
  if (els.diagnosticVerifyTemplate.value) {
    payload.verify_template_path = els.diagnosticVerifyTemplate.value;
  }

  await enqueueJob("diagnostic.template-tap", payload);
}

async function startBattleDryRun() {
  const settingName = els.settingSelect.value;
  if (!settingName) {
    return;
  }
  await enqueueJob("battle.dry-run", {
    setting_name: settingName,
    action_delay_seconds: Number(els.battleActionDelay.value),
  });
}

async function startBattlePlan() {
  const settingName = els.settingSelect.value;
  if (!settingName || !state.selectedSettingProgram?.execution?.battle?.ready) {
    return;
  }
  await enqueueJob("battle.execute-plan", {
    setting_name: settingName,
    tap_interval_seconds: Number(els.battleActionDelay.value),
  });
}

async function startFullRun() {
  const settingName = els.settingSelect.value;
  if (!settingName || !state.selectedSettingProgram?.execution?.battle?.ready) {
    return;
  }
  await enqueueJob("battle.run", {
    setting_name: settingName,
    max_runs: readNumber(els.fullRunCount),
    max_restarts: readNumber(els.fullRunRestartLimit),
    entry_mode: els.fullRunEntryMode.value,
    entry: {
      max_map_swipes: readNumber(els.fullRunMapSwipes),
    },
    assist: {
      special_filter: els.fullRunAssistFilter.disabled ? "any" : els.fullRunAssistFilter.value,
    },
    prepare: {
      apple: els.fullRunApple.value,
      team_check_mode: els.fullRunTeamCheck.value,
    },
    battle: {
      tap_interval_seconds: Number(els.battleActionDelay.value),
    },
  });
}

async function restartGame() {
  const settingName = els.settingSelect.value;
  if (!settingName || !state.selectedSettingPlan?.run?.game_crash_restart) {
    return;
  }
  await enqueueJob("battle.restart-game", {
    setting_name: settingName,
  });
}

async function inspectChocolate() {
  const settingName = els.settingSelect.value;
  if (!settingName) {
    return;
  }
  await enqueueJob("event.chocolate.inspect", {
    setting_name: settingName,
  });
}

async function runChocolate() {
  const settingName = els.settingSelect.value;
  if (!settingName) {
    return;
  }
  await enqueueJob("event.chocolate.run", {
    setting_name: settingName,
  });
}

async function inspectDigdig() {
  const settingName = els.settingSelect.value;
  if (!settingName) {
    return;
  }
  await enqueueJob("event.digdig.inspect", {
    setting_name: settingName,
  });
}

async function executeDigdig() {
  const settingName = els.settingSelect.value;
  if (!settingName) {
    return;
  }
  await enqueueJob("event.digdig.execute", {
    setting_name: settingName,
  });
}

function selectedLotteryStars() {
  return [
    [3, els.lotteryStar3],
    [4, els.lotteryStar4],
    [5, els.lotteryStar5],
  ]
    .filter(([, input]) => input.checked)
    .map(([star]) => star);
}

async function inspectLottery() {
  const settingName = els.settingSelect.value;
  if (!settingName) {
    return;
  }
  await enqueueJob("event.lottery.inspect", {
    setting_name: settingName,
  });
}

async function runLottery() {
  const settingName = els.settingSelect.value;
  const stars = selectedLotteryStars();
  if (!settingName || stars.length === 0) {
    return;
  }
  await enqueueJob("event.lottery.run", {
    setting_name: settingName,
    pay_slot: readNumber(els.lotteryPaySlot),
    stars: selectedLotteryStars(),
  });
}

async function inspectExpball() {
  const settingName = els.settingSelect.value;
  if (!settingName) {
    return;
  }
  await enqueueJob("event.expball.inspect", {
    setting_name: settingName,
  });
}

async function navigateExpball() {
  const settingName = els.settingSelect.value;
  if (!settingName) {
    return;
  }
  await enqueueJob("event.expball.navigate", {
    setting_name: settingName,
    destination: els.expballDestination.value,
  });
}

async function inspectExpballGrid() {
  const settingName = els.settingSelect.value;
  if (!settingName) {
    return;
  }
  await enqueueJob("event.expball.inspect-storage-grid", {
    setting_name: settingName,
  });
}

async function runExpballSummon() {
  const settingName = els.settingSelect.value;
  if (!settingName) {
    return;
  }
  await enqueueJob("event.expball.run", {
    setting_name: settingName,
    max_summons: readNumber(els.fpSummonBatches),
  });
}

async function runExpballStorage() {
  const settingName = els.settingSelect.value;
  if (!settingName) {
    return;
  }
  await enqueueJob("event.expball.storage", {
    setting_name: settingName,
  });
}

async function runExpballSell() {
  const settingName = els.settingSelect.value;
  if (!settingName) {
    return;
  }
  await enqueueJob("event.expball.sell", {
    setting_name: settingName,
  });
}

async function enqueueJob(kind, payload) {
  try {
    const response = await api("/api/jobs", {
      method: "POST",
      body: JSON.stringify({ kind, payload }),
    });
    const job = response.job;
    mergeJob(job);
    renderJobHistory(job.job_id);
    await selectJob(job.job_id);
  } catch (error) {
    showError(error);
  } finally {
    updateControls();
  }
}

async function loadJobs(preferredJobId = "") {
  try {
    const payload = await api("/api/jobs?limit=50");
    state.jobs = payload.jobs || [];
    const selectedJobId = preferredJobId || state.activeJob?.job_id || state.jobs[0]?.job_id || "";
    renderJobHistory(selectedJobId);
    if (selectedJobId) {
      await selectJob(selectedJobId);
    } else {
      state.activeJob = null;
      state.jobEvents = [];
      renderJob(null);
      renderJobEvents();
    }
  } catch (error) {
    showError(error);
  }
}

function renderJobHistory(selectedJobId = "") {
  const emptyOption = document.createElement("option");
  emptyOption.value = "";
  emptyOption.textContent = state.jobs.length ? "Select a job" : "No job history";
  els.jobHistory.replaceChildren(
    emptyOption,
    ...state.jobs.map((job) => {
      const option = document.createElement("option");
      option.value = job.job_id;
      option.textContent = `${job.kind} · ${job.status} · ${formatTime(job.created_at)}`;
      return option;
    }),
  );
  els.jobHistory.value = selectedJobId;
}

async function selectJob(jobId) {
  if (!jobId) {
    closeJobEventSource();
    state.activeJob = null;
    state.jobEvents = [];
    renderJob(null);
    renderJobEvents();
    updateControls();
    return;
  }
  const previousJobId = state.activeJob?.job_id;
  try {
    const [jobPayload, eventPayload] = await Promise.all([
      api(`/api/jobs/${encodeURIComponent(jobId)}`),
      api(`/api/jobs/${encodeURIComponent(jobId)}/events?limit=500`),
    ]);
    state.activeJob = jobPayload.job;
    state.jobEvents = eventPayload.events || [];
    mergeJob(state.activeJob);
    renderJobHistory(jobId);
    renderJob(state.activeJob);
    renderJobEvents();
    if (!TERMINAL_JOB_STATES.has(state.activeJob.status)) {
      const lastEventId = state.jobEvents.at(-1)?.event_id || 0;
      if (previousJobId !== jobId || !state.jobEventSource) {
        openJobEventStream(jobId, lastEventId);
      }
    } else {
      closeJobEventSource();
    }
  } catch (error) {
    showError(error);
  } finally {
    updateControls();
  }
}

async function refreshActiveJob(jobId) {
  if (!jobId || state.activeJob?.job_id !== jobId) {
    return;
  }
  try {
    const payload = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    state.activeJob = payload.job;
    mergeJob(state.activeJob);
    renderJobHistory(jobId);
    renderJob(state.activeJob);
    if (TERMINAL_JOB_STATES.has(state.activeJob.status)) {
      closeJobEventSource();
    }
    updateControls();
  } catch (error) {
    closeJobEventSource();
    showError(error);
  }
}

async function controlJob(action) {
  const jobId = state.activeJob?.job_id;
  if (!jobId) {
    return;
  }
  try {
    const payload = await api(`/api/jobs/${encodeURIComponent(jobId)}/${action}`, {
      method: "POST",
    });
    state.activeJob = payload.job;
    mergeJob(state.activeJob);
    renderJobHistory(jobId);
    renderJob(state.activeJob);
    if (!TERMINAL_JOB_STATES.has(state.activeJob.status) && !state.jobEventSource) {
      openJobEventStream(jobId, state.jobEvents.at(-1)?.event_id || 0);
    }
  } catch (error) {
    showError(error);
  } finally {
    updateControls();
  }
}

function openJobEventStream(jobId, afterId) {
  closeJobEventSource();
  const source = new EventSource(
    `/api/jobs/${encodeURIComponent(jobId)}/events/stream?after_id=${encodeURIComponent(afterId)}`,
  );
  state.jobEventSource = source;
  source.addEventListener("job_event", (message) => {
    if (state.activeJob?.job_id !== jobId) {
      return;
    }
    try {
      const event = JSON.parse(message.data);
      if (!state.jobEvents.some((candidate) => candidate.event_id === event.event_id)) {
        state.jobEvents.push(event);
        renderJobEvents();
      }
      refreshActiveJob(jobId);
    } catch {
      closeJobEventSource();
    }
  });
  source.addEventListener("error", () => {
    source.close();
    if (state.jobEventSource === source) {
      state.jobEventSource = null;
    }
    refreshActiveJob(jobId).then(() => {
      if (
        state.activeJob?.job_id === jobId
        && !TERMINAL_JOB_STATES.has(state.activeJob.status)
        && !state.jobEventSource
      ) {
        window.setTimeout(() => {
          if (state.activeJob?.job_id === jobId && !state.jobEventSource) {
            openJobEventStream(jobId, state.jobEvents.at(-1)?.event_id || 0);
          }
        }, 1000);
      }
    });
  });
}

function closeJobEventSource() {
  if (state.jobEventSource) {
    state.jobEventSource.close();
    state.jobEventSource = null;
  }
}

function mergeJob(job) {
  const index = state.jobs.findIndex((candidate) => candidate.job_id === job.job_id);
  if (index === -1) {
    state.jobs.unshift(job);
    return;
  }
  state.jobs[index] = job;
}

function renderJob(job) {
  const status = job?.status || "idle";
  els.jobStatus.textContent = status[0].toUpperCase() + status.slice(1);
  els.jobStatus.className = `job-status ${status}`;
  els.jobKind.textContent = job ? job.kind : "No job selected";
  els.jobStep.textContent = job?.current_step || "Waiting";
  if (typeof job?.progress === "number") {
    els.jobProgress.value = job.progress;
  } else {
    els.jobProgress.removeAttribute("value");
  }
  if (job?.error) {
    els.jobError.hidden = false;
    els.jobError.textContent = `${job.error.type || job.error.code || "Error"}: ${job.error.message || "Job failed"}`;
  } else {
    els.jobError.hidden = true;
    els.jobError.textContent = "";
  }
  renderJobResult(job);
}

function renderJobResult(job) {
  const result = job?.result;
  if (!result) {
    els.jobResult.hidden = true;
    els.jobResult.textContent = "";
    return;
  }
  els.jobResult.hidden = false;
  if (job.kind === "battle.run") {
    const lines = [
      `${result.runs_completed || 0}/${result.max_runs || 0} runs`,
      `${result.drop_count || 0} configured drops`,
    ];
    if (result.cleared_ap) {
      lines.push("AP cleared");
    } else if (result.reason) {
      lines.push(`Stopped: ${String(result.reason).replaceAll("_", " ")}`);
    }
    if (result.restart_count) {
      lines.push(`${result.restart_count} game ${result.restart_count === 1 ? "restart" : "restarts"}`);
    }
    els.jobResult.textContent = lines.join(" · ");
    return;
  }
  if (job.kind === "battle.restart-game") {
    if (result.recovered) {
      const actionCount = result.actions?.length || 0;
      const actionLabel = actionCount === 1 ? "action" : "actions";
      els.jobResult.textContent = [
        `Recovered to ${result.stage || "battle flow"}`,
        `${actionCount} navigation ${actionLabel}`,
      ].join(" · ");
    } else {
      els.jobResult.textContent = `Recovery skipped: ${String(result.reason || "unknown").replaceAll("_", " ")}`;
    }
    return;
  }
  if (job.kind === "event.chocolate.inspect") {
    const details = [
      `Valentine: ${humanizeResultValue(result.state || "unknown")}`,
      humanizeResultValue(result.status || "unknown"),
    ];
    if (result.recommended_action) {
      details.push(`Action: ${humanizeResultValue(result.recommended_action)}`);
    } else if (result.reason) {
      details.push(humanizeResultValue(result.reason));
    }
    els.jobResult.textContent = details.join(" · ");
    return;
  }
  if (job.kind === "event.chocolate.run") {
    const actionCount = result.actions?.length || 0;
    els.jobResult.textContent = [
      result.completed ? "Valentine complete" : "Valentine stopped",
      humanizeResultValue(result.reason || "unknown"),
      `${actionCount} ${actionCount === 1 ? "action" : "actions"}`,
    ].join(" · ");
    return;
  }
  if (job.kind === "event.digdig.inspect") {
    const pieceCount = result.pieces?.length || 0;
    const details = [
      `Dig board: ${humanizeResultValue(result.state || "unknown")}`,
      `${pieceCount} ${pieceCount === 1 ? "piece" : "pieces"}`,
    ];
    if (result.suggested_tool) {
      details.push(`Tool: ${humanizeResultValue(result.suggested_tool)}`);
    }
    els.jobResult.textContent = details.join(" · ");
    return;
  }
  if (job.kind === "event.digdig.execute") {
    const actionCount = result.actions?.length || 0;
    els.jobResult.textContent = [
      result.completed ? "Dig selection executed" : "Dig execution stopped",
      humanizeResultValue(result.reason || "unknown"),
      `${actionCount} ${actionCount === 1 ? "action" : "actions"}`,
    ].join(" · ");
    return;
  }
  if (job.kind === "event.lottery.inspect") {
    const details = [
      `Lottery: ${humanizeResultValue(result.state || "unknown")}`,
      humanizeResultValue(result.status || "unknown"),
    ];
    if (result.recommended_action) {
      details.push(`Action: ${humanizeResultValue(result.recommended_action)}`);
    } else if (result.reason) {
      details.push(humanizeResultValue(result.reason));
    }
    els.jobResult.textContent = details.join(" · ");
    return;
  }
  if (job.kind === "event.lottery.run") {
    els.jobResult.textContent = [
      result.completed ? "Lottery complete" : "Lottery stopped",
      humanizeResultValue(result.reason || "unknown"),
      `${result.giftbox_cycles || 0} gift box cycles`,
      `${result.receive_batches || 0} receive batches`,
    ].join(" · ");
    return;
  }
  if (job.kind === "event.expball.inspect") {
    const details = [
      `EXP ${humanizeResultValue(result.flow || "unknown")}`,
      humanizeResultValue(result.state || "unknown"),
      humanizeResultValue(result.status || "unknown"),
    ];
    if (result.recommended_action) {
      details.push(`Action: ${humanizeResultValue(result.recommended_action)}`);
    } else if (result.reason) {
      details.push(humanizeResultValue(result.reason));
    }
    els.jobResult.textContent = details.join(" · ");
    return;
  }
  if (job.kind === "event.expball.navigate") {
    const actionCount = result.actions?.length || 0;
    els.jobResult.textContent = [
      humanizeResultValue(result.destination || "unknown"),
      result.completed ? "Reached" : "Navigation stopped",
      humanizeResultValue(result.reason || "unknown"),
      `${actionCount} ${actionCount === 1 ? "action" : "actions"}`,
    ].join(" · ");
    return;
  }
  if (job.kind === "event.expball.inspect-storage-grid") {
    const slots = Array.isArray(result.slots) ? result.slots : [];
    const countStar = (star) => slots.filter((slot) => slot.star === star).length;
    els.jobResult.textContent = [
      `${result.recognized_count || 0}/21 EXP cards`,
      `3 star: ${countStar(3)}`,
      `4 star: ${countStar(4)}`,
      `5 star: ${countStar(5)}`,
    ].join(" · ");
    return;
  }
  if (job.kind === "event.expball.run") {
    els.jobResult.textContent = [
      `${result.summons || 0}/${result.max_summons || 0} FP batches`,
      result.completed ? "Completed" : "Stopped",
      humanizeResultValue(result.reason || "unknown"),
    ].join(" · ");
    return;
  }
  if (job.kind === "event.expball.summon") {
    const summonCount = result.summons || 0;
    els.jobResult.textContent = [
      `${summonCount} FP ${summonCount === 1 ? "batch" : "batches"}`,
      result.completed ? "Completed" : "Stopped",
      humanizeResultValue(result.reason || "unknown"),
    ].join(" · ");
    return;
  }
  if (job.kind === "event.expball.storage") {
    const actionCount = result.actions?.length || 0;
    els.jobResult.textContent = [
      result.completed ? "EXP stored" : "EXP storage stopped",
      humanizeResultValue(result.reason || "unknown"),
      `${actionCount} ${actionCount === 1 ? "action" : "actions"}`,
    ].join(" · ");
    return;
  }
  if (job.kind === "event.expball.sell") {
    const actionCount = result.actions?.length || 0;
    els.jobResult.textContent = [
      result.completed ? "EXP selection sold" : "EXP sale stopped",
      humanizeResultValue(result.reason || "unknown"),
      `${actionCount} ${actionCount === 1 ? "action" : "actions"}`,
    ].join(" · ");
    return;
  }
  els.jobResult.textContent = "Completed";
}

function humanizeResultValue(value) {
  return String(value).replaceAll("_", " ");
}

function renderJobEvents() {
  els.jobEventCount.textContent = `${state.jobEvents.length} ${state.jobEvents.length === 1 ? "event" : "events"}`;
  els.jobEvents.replaceChildren(...state.jobEvents.map(renderJobEvent));
  els.jobEvents.scrollTop = els.jobEvents.scrollHeight;
}

function renderJobEvent(event) {
  const row = document.createElement("div");
  row.className = "job-event-row";
  const meta = document.createElement("div");
  meta.className = "job-event-meta";
  meta.textContent = `${formatTime(event.created_at)} · ${event.event_type}`;
  const message = document.createElement("div");
  message.className = event.level === "error" ? "job-event-message error" : "job-event-message";
  message.textContent = event.message;
  row.append(meta, message);
  return row;
}

async function loadEvents() {
  try {
    const payload = await api("/api/events?limit=80");
    const events = payload.events || [];
    els.logCount.textContent = `${events.length} ${events.length === 1 ? "event" : "events"}`;
    els.eventLog.replaceChildren(...events.map(renderEvent));
    els.eventLog.scrollTop = els.eventLog.scrollHeight;
  } catch {
    els.logCount.textContent = "0 events";
  }
}

function renderEvent(event) {
  const row = document.createElement("div");
  row.className = "event-row";
  const time = document.createElement("span");
  time.className = "event-time";
  time.textContent = formatTime(event.timestamp);
  const level = document.createElement("span");
  level.className = `event-level ${event.level || ""}`;
  level.textContent = event.level || "info";
  const message = document.createElement("span");
  message.textContent = `${event.action}: ${event.message}`;
  row.append(time, level, message);
  return row;
}

function renderSettingPlan(plan) {
  els.settingValidation.classList.remove("ok", "error");
  if (!plan) {
    els.settingValidation.textContent = "No setting";
    els.settingPlan.textContent = "No script selected";
    els.battleScriptName.textContent = "No script selected";
    return;
  }

  const errorCount = plan.validation?.errors?.length || 0;
  const warningCount = plan.validation?.warnings?.length || 0;
  const isValid = Boolean(plan.validation?.ok);
  els.settingValidation.textContent = isValid
    ? `Valid · ${plan.summary.round_count} rounds · ${plan.summary.action_count} actions`
    : `${errorCount} errors · ${warningCount} warnings`;
  els.settingValidation.classList.add(isValid ? "ok" : "error");

  const servantText = plan.servants
    .filter((servant) => servant.name)
    .map((servant) => `${servant.slot + 1}:${servant.name}${servant.active ? "*" : ""}`)
    .join(" / ");
  const lines = [
    `${plan.server || "Unknown"} · ${plan.name}`,
    `Servants: ${servantText || "None"}`,
    `Master: ${plan.master.equip ?? "-"} · sex ${plan.master.sex ?? "-"}`,
  ];
  for (const round of plan.rounds) {
    lines.push(`R${round.round}: ${round.turns.length} turns`);
    for (const turn of round.turns) {
      const actions = turn.actions.map(formatPlanAction).join(", ") || "No actions";
      lines.push(`  T${turn.turn}: ${actions}`);
    }
  }
  els.settingPlan.textContent = lines.join("\n");
  els.battleScriptName.textContent = plan.name;
}

function renderBattleProgram(program) {
  els.battleProgramStatus.classList.remove("ok", "warn", "error");
  if (!program) {
    els.battleProgramStatus.textContent = "No program";
    return;
  }
  const summary = program.summary;
  const execution = program.execution?.battle;
  if (execution?.ready) {
    els.battleProgramStatus.textContent = `Ready · ${summary.supported_action_count} actions · ${summary.execution_tap_count} taps`;
    els.battleProgramStatus.classList.add("ok");
    return;
  }
  els.battleProgramStatus.textContent = `${summary.supported_action_count}/${summary.action_count} supported · ${execution?.reason || "Not executable"}`;
  els.battleProgramStatus.classList.add("warn");
}

function renderStrategyDetail(strategy) {
  if (!strategy) {
    els.strategySummary.textContent = "No strategy selected";
    return;
  }
  const status = strategy.validation?.ok ? "Valid" : `${strategy.validation?.errors?.length || 0} errors`;
  const tags = (strategy.entries || []).map((entry) => entry.tag).filter(Boolean);
  els.strategySummary.textContent = [
    `${status} · ${strategy.summary.entry_count} entries`,
    tags.slice(0, 4).join("\n") || strategy.name,
  ].join("\n");
}

function setConnectionLabel(payload) {
  if (payload.connected) {
    els.connectionState.textContent = `${payload.backend} · ${payload.device_id}`;
    els.connectionState.classList.add("connected");
    return;
  }
  els.connectionState.textContent = "Disconnected";
  els.connectionState.classList.remove("connected");
}

function formatPlanAction(action) {
  if (action.type === "replace") {
    return "replace";
  }
  if (action.type === "skill") {
    return `skill ${formatCommand(action.command)}`;
  }
  if (action.type === "np") {
    return `np ${formatCommand(action.servant)}`;
  }
  if (action.type === "strategy") {
    return `strategy ${action.strategies?.length || 0}`;
  }
  return action.type || "action";
}

function formatCommand(value) {
  return Array.isArray(value) ? value.join(":") : String(value);
}

function updateControls() {
  const hasDevice = Boolean(els.deviceList.value);
  const hasScreenshot = Boolean(state.screenshotBase64);
  const hasTemplate = Boolean(els.templateSelect.value);
  const adbCapability = state.backends.find((backend) => backend.name === "adb");
  const canAddAdbEndpoint = Boolean(adbCapability?.available && els.manualAdbEndpoint.value.trim());
  els.addAdbEndpoint.disabled = !canAddAdbEndpoint;
  els.connectDevice.disabled = !hasDevice || state.connected;
  els.disconnectDevice.disabled = !state.connected;
  els.snapshotButton.disabled = !state.connected;
  els.clearScreenshot.disabled = !hasScreenshot;
  els.matchButton.disabled = !hasScreenshot || !hasTemplate;
  els.screenDebugMode.disabled = !state.debugOverlayDataUrl;
  els.tapButton.disabled = !state.connected;
  els.swipeButton.disabled = !state.connected;
  const selectedJobStatus = state.activeJob?.status || "idle";
  const hasRunningJob = state.jobs.some((job) => ACTIVE_JOB_STATES.has(job.status));
  const supportsDigdig = ["CH", "CNTW"].includes(state.selectedSettingPlan?.server);
  const supportsLottery = ["CH", "CNTW", "JP"].includes(state.selectedSettingPlan?.server);
  const supportsExpball = ["CH", "CNTW", "JP"].includes(state.selectedSettingPlan?.server);
  const hasLotteryStars = selectedLotteryStars().length > 0;
  const equipTemplate = selectedEquipTemplate();
  const equipCandidate = selectedEquipCandidate();
  const assistTag = selectedAssistTag();
  const assistTagCandidate = selectedAssistTagCandidate();
  const assistTagThreshold = Number(els.assistTagThreshold.value);
  const validAssistTagThreshold = Number.isFinite(assistTagThreshold)
    && assistTagThreshold > 0
    && assistTagThreshold < 1;
  const hasEquipImage = Boolean(
    els.equipFullImage.files[0]
      || els.equipNonFullImage.files[0]
      || state.equipFullCandidate
      || state.equipNonFullCandidate,
  );
  els.startDiagnostic.disabled = !state.connected || !hasTemplate || hasRunningJob;
  els.startBattleDryRun.disabled = !els.settingSelect.value || hasRunningJob;
  els.startBattlePlan.disabled = !state.connected
    || !state.selectedSettingProgram?.execution?.battle?.ready
    || hasRunningJob;
  els.startFullRun.disabled = !state.connected
    || !state.selectedSettingProgram?.execution?.battle?.ready
    || hasRunningJob;
  els.restartGame.disabled = !state.connected
    || !state.selectedSettingPlan?.run?.game_crash_restart
    || hasRunningJob;
  els.inspectChocolate.disabled = !state.connected
    || !els.settingSelect.value
    || hasRunningJob;
  els.runChocolate.disabled = !state.connected
    || !els.settingSelect.value
    || hasRunningJob;
  els.inspectDigdig.disabled = !state.connected
    || !els.settingSelect.value
    || !supportsDigdig
    || hasRunningJob;
  els.executeDigdig.disabled = !state.connected
    || !els.settingSelect.value
    || !supportsDigdig
    || hasRunningJob;
  els.inspectLottery.disabled = !state.connected
    || !els.settingSelect.value
    || !supportsLottery
    || hasRunningJob;
  els.runLottery.disabled = !state.connected
    || !els.settingSelect.value
    || !supportsLottery
    || !hasLotteryStars
    || hasRunningJob;
  els.lotteryPaySlot.disabled = !supportsLottery || hasRunningJob;
  els.lotteryStar3.disabled = !supportsLottery || hasRunningJob;
  els.lotteryStar4.disabled = !supportsLottery || hasRunningJob;
  els.lotteryStar5.disabled = !supportsLottery || hasRunningJob;
  els.inspectExpball.disabled = !state.connected
    || !els.settingSelect.value
    || !supportsExpball
    || hasRunningJob;
  els.navigateExpball.disabled = !state.connected
    || !els.settingSelect.value
    || !supportsExpball
    || hasRunningJob;
  els.expballDestination.disabled = !supportsExpball || hasRunningJob;
  els.inspectExpballGrid.disabled = !state.connected
    || !els.settingSelect.value
    || !supportsExpball
    || hasRunningJob;
  els.runExpballSummon.disabled = !state.connected
    || !els.settingSelect.value
    || !supportsExpball
    || hasRunningJob;
  els.fpSummonBatches.disabled = !supportsExpball || hasRunningJob;
  els.runExpballStorage.disabled = !state.connected
    || !els.settingSelect.value
    || !supportsExpball
    || hasRunningJob;
  els.runExpballSell.disabled = !state.connected
    || !els.settingSelect.value
    || !supportsExpball
    || hasRunningJob;
  els.fullRunRestartLimit.disabled = !(state.selectedSettingPlan?.run?.game_crash_restart
    || state.selectedSettingPlan?.run?.stuck_restart);
  els.fullRunAssistFilter.disabled = !state.selectedSettingPlan
    || ["不识别", "仅礼装", "冠位助战仅礼装"].includes(state.selectedSettingPlan.assist?.mode);
  els.fullRunMapSwipes.disabled = !["free_quest", "main_story"].includes(
    els.fullRunEntryMode.value,
  );
  els.pauseJob.disabled = selectedJobStatus !== "running";
  els.resumeJob.disabled = selectedJobStatus !== "paused";
  els.cancelJob.disabled = !ACTIVE_JOB_STATES.has(selectedJobStatus)
    || selectedJobStatus === "cancelling";
  els.editSetting.disabled = !els.settingSelect.value;
  els.deleteSetting.disabled = !els.settingSelect.value;
  els.exportSetting.disabled = !els.settingSelect.value;
  els.editStrategy.disabled = !els.strategySelect.value;
  els.deleteStrategy.disabled = !els.strategySelect.value;
  els.equipTemplateName.disabled = state.equipTemplateBusy;
  els.captureEquipCandidates.disabled = state.equipTemplateBusy
    || !els.settingSelect.value
    || (!state.connected && !state.screenshotBase64);
  els.equipCandidateList.disabled = state.equipTemplateBusy || !state.equipCandidates.length;
  els.useEquipFull.disabled = state.equipTemplateBusy || !equipCandidate;
  els.useEquipNonFull.disabled = state.equipTemplateBusy || !equipCandidate;
  els.equipFullImage.disabled = state.equipTemplateBusy;
  els.equipNonFullImage.disabled = state.equipTemplateBusy;
  els.equipTemplateList.disabled = state.equipTemplateBusy || !state.equipTemplates.length;
  els.testEquipTemplate.disabled = state.equipTemplateBusy
    || !equipTemplate
    || (!state.connected && !state.screenshotBase64);
  els.buildEquipTemplate.disabled = state.equipTemplateBusy
    || !els.equipTemplateName.value.trim()
    || !hasEquipImage;
  els.activateEquipTemplate.disabled = state.equipTemplateBusy
    || !equipTemplate
    || equipTemplate.location === "active";
  els.archiveEquipTemplate.disabled = state.equipTemplateBusy
    || !equipTemplate
    || equipTemplate.location === "archive";
  els.captureAssistTagScreen.disabled = state.assistTagBusy
    || (state.assistTagMode === "assist" && !els.settingSelect.value)
    || (!state.connected && !state.screenshotBase64);
  els.assistTagCandidate.disabled = state.assistTagBusy
    || !state.assistTagCandidates.length;
  els.assistTagLabel.disabled = state.assistTagBusy;
  els.assistTagThreshold.disabled = state.assistTagBusy;
  els.saveAssistTag.disabled = state.assistTagBusy
    || Boolean(state.assistTagDragStart)
    || !assistTagCandidate
    || !state.assistTagCropBounds
    || !els.assistTagLabel.value.trim()
    || !validAssistTagThreshold;
  els.assistTagList.disabled = state.assistTagBusy || !state.assistTags.length;
  els.assistTagFile.disabled = state.assistTagBusy;
  els.importAssistTag.disabled = state.assistTagBusy || !els.assistTagFile.files[0];
  els.bindAssistTag.disabled = state.assistTagBusy
    || !assistTag
    || !els.settingSelect.value;
  els.bindAssistTag.textContent = isAssistTagBound(assistTag)
    ? "Unbind from Script"
    : "Bind to Script";
  const binding = (state.selectedSettingPlan?.special_keys || [])
    .find((entry) => entry.template_name === assistTag?.name);
  els.assistTagBindingStatus.hidden = state.assistTagMode !== "command" || !assistTag;
  els.assistTagBindingStatus.textContent = binding ? `Bound as ${binding.code}`
    : els.settingSelect.value ? "Not bound" : "No script selected";
  els.deleteAssistTag.disabled = state.assistTagBusy || !assistTag;
}

function mergeDevice(device) {
  const index = state.devices.findIndex(
    (candidate) => candidate.backend === device.backend && candidate.device_id === device.device_id,
  );
  if (index === -1) {
    state.devices.push(device);
    return;
  }
  state.devices[index] = device;
}

function selectBackend(name) {
  const hasBackend = Array.from(els.backendSelect.options).some((option) => option.value === name);
  if (hasBackend) {
    els.backendSelect.value = name;
  }
}

function onScreenshotLoaded() {
  state.screenshotNaturalSize = {
    width: els.screenshot.naturalWidth,
    height: els.screenshot.naturalHeight,
  };
  els.screenMeta.textContent = `${state.screenshotNaturalSize.width} x ${state.screenshotNaturalSize.height} · ${state.screenMode === "debug" ? "Debug" : "Source"}`;
  if (!els.recognitionRoiEnabled.checked) {
    els.recognitionRoiWidth.value = state.screenshotNaturalSize.width;
    els.recognitionRoiHeight.value = state.screenshotNaturalSize.height;
  }
  if (state.latestMatch) {
    renderMatch(state.latestMatch);
  }
}

function renderMatch(result) {
  els.matchResult.textContent = `${result.matched ? "Matched" : "Below threshold"} · ${result.confidence.toFixed(3)} · ${result.scale.toFixed(2)}x · ${result.center.join(", ")}`;
  if (state.screenMode !== "source") {
    clearMatchOverlay();
    return;
  }
  const screenshotRect = els.screenshot.getBoundingClientRect();
  const stageRect = els.screenStage.getBoundingClientRect();
  const natural = state.screenshotNaturalSize;
  if (!natural || !screenshotRect.width || !screenshotRect.height) {
    clearMatchOverlay();
    return;
  }
  const scaleX = screenshotRect.width / natural.width;
  const scaleY = screenshotRect.height / natural.height;
  els.matchOverlay.hidden = false;
  els.matchOverlay.style.left = `${screenshotRect.left - stageRect.left + result.top_left[0] * scaleX + els.screenStage.scrollLeft}px`;
  els.matchOverlay.style.top = `${screenshotRect.top - stageRect.top + result.top_left[1] * scaleY + els.screenStage.scrollTop}px`;
  els.matchOverlay.style.width = `${result.size[0] * scaleX}px`;
  els.matchOverlay.style.height = `${result.size[1] * scaleY}px`;
}

function clearMatchOverlay() {
  els.matchOverlay.hidden = true;
  els.matchOverlay.removeAttribute("style");
}

function populateTapFromClick(event) {
  if (!state.screenshotNaturalSize || !els.screenshot.classList.contains("visible")) {
    return;
  }
  const rect = els.screenshot.getBoundingClientRect();
  if (
    event.clientX < rect.left ||
    event.clientX > rect.right ||
    event.clientY < rect.top ||
    event.clientY > rect.bottom
  ) {
    return;
  }
  const x = Math.round(((event.clientX - rect.left) / rect.width) * state.screenshotNaturalSize.width);
  const y = Math.round(((event.clientY - rect.top) / rect.height) * state.screenshotNaturalSize.height);
  els.tapX.value = x;
  els.tapY.value = y;
}

function setScreenScale(mode) {
  els.screenshot.classList.toggle("actual-size", mode === "actual");
  if (state.latestMatch) {
    requestAnimationFrame(() => renderMatch(state.latestMatch));
  }
}

function setScreenMode(mode) {
  const nextMode = mode === "debug" && state.debugOverlayDataUrl ? "debug" : "source";
  state.screenMode = nextMode;
  els.screenSourceMode.classList.toggle("active", nextMode === "source");
  els.screenDebugMode.classList.toggle("active", nextMode === "debug");
  els.screenSourceMode.setAttribute("aria-pressed", String(nextMode === "source"));
  els.screenDebugMode.setAttribute("aria-pressed", String(nextMode === "debug"));
  const imageSource = nextMode === "debug" ? state.debugOverlayDataUrl : state.screenshotUrl;
  if (imageSource) {
    els.screenshot.src = imageSource;
  }
  if (nextMode === "source" && state.latestMatch) {
    requestAnimationFrame(() => renderMatch(state.latestMatch));
  } else {
    clearMatchOverlay();
  }
  if (state.screenshotNaturalSize) {
    els.screenMeta.textContent = `${state.screenshotNaturalSize.width} x ${state.screenshotNaturalSize.height} · ${nextMode === "debug" ? "Debug" : "Source"}`;
  }
  updateControls();
}

function showError(error) {
  const message = error?.payload?.error?.message || error.message || "Request failed";
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  document.body.append(toast);
  setTimeout(() => toast.remove(), 4200);
  loadEvents();
}

function readNumber(input) {
  return Number(input.value || 0);
}

function readScales() {
  const values = els.recognitionScales.value
    .split(/[\s,]+/)
    .filter(Boolean)
    .map(Number);
  if (!values.length || values.some((value) => !Number.isFinite(value) || value <= 0)) {
    throw new Error("Scales must be positive numbers separated by commas.");
  }
  return [...new Set(values)];
}

function formatTime(value) {
  if (!value) {
    return "--:--:--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--:--:--";
  }
  return date.toLocaleTimeString([], { hour12: false });
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result || "")));
    reader.addEventListener("error", () => reject(reader.error));
    reader.readAsDataURL(blob);
  });
}

init();
