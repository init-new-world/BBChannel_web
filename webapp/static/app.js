const TERMINAL_JOB_STATES = new Set(["cancelled", "succeeded", "failed"]);
const ACTIVE_JOB_STATES = new Set(["queued", "running", "paused", "cancelling"]);

const state = {
  connected: false,
  backends: [],
  devices: [],
  settings: [],
  strategies: [],
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
  startFullRun: document.querySelector("#start-full-run"),
  restartGame: document.querySelector("#restart-game"),
  inspectChocolate: document.querySelector("#inspect-chocolate"),
  runChocolate: document.querySelector("#run-chocolate"),
  inspectDigdig: document.querySelector("#inspect-digdig"),
  executeDigdig: document.querySelector("#execute-digdig"),
  inspectExpball: document.querySelector("#inspect-expball"),
  fpSummonBatches: document.querySelector("#fp-summon-batches"),
  runExpballSummon: document.querySelector("#run-expball-summon"),
  runExpballStorage: document.querySelector("#run-expball-storage"),
  runExpballSell: document.querySelector("#run-expball-sell"),
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
  els.newStrategy.addEventListener("click", () => openPresetEditor("strategies", false));
  els.editStrategy.addEventListener("click", () => openPresetEditor("strategies", true));
  els.deleteStrategy.addEventListener("click", () => deletePreset("strategies"));
  els.presetForm.addEventListener("submit", savePreset);
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
  els.inspectExpball.addEventListener("click", inspectExpball);
  els.runExpballSummon.addEventListener("click", runExpballSummon);
  els.runExpballStorage.addEventListener("click", runExpballStorage);
  els.runExpballSell.addEventListener("click", runExpballSell);
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
    let value = isSetting ? { server: "CH", round1_turns: 0 } : [];
    if (editing) {
      const detail = await api(`/api/${kind}/${encodeURIComponent(selectedName)}`);
      value = isSetting ? detail.config : detail.entries;
    }
    state.presetEditor = {
      kind,
      originalName: editing ? selectedName : "",
    };
    els.presetDialogTitle.textContent = `${editing ? "Edit" : "New"} ${isSetting ? "Script" : "Strategy"}`;
    els.presetDialog.showModal();
    els.presetName.value = editing ? selectedName : "";
    els.presetJson.value = JSON.stringify(value, null, 2);
    setPresetError("");
    els.presetName.focus();
  } catch (error) {
    showError(error);
  }
}

function closePresetEditor() {
  els.presetDialog.close();
  state.presetEditor = null;
  setPresetError("");
}

async function savePreset(event) {
  event.preventDefault();
  const editor = state.presetEditor;
  if (!editor) {
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
  els.savePreset.disabled = true;
  try {
    await api(`/api/${editor.kind}/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify(request),
    });
    closePresetEditor();
    if (isSetting) {
      await loadSettings(name);
    } else {
      await loadStrategies(name);
    }
  } catch (error) {
    setPresetError(error?.payload?.error?.message || error.message || "Save failed.");
  } finally {
    els.savePreset.disabled = false;
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

async function inspectExpball() {
  const settingName = els.settingSelect.value;
  if (!settingName) {
    return;
  }
  await enqueueJob("event.expball.inspect", {
    setting_name: settingName,
  });
}

async function runExpballSummon() {
  const settingName = els.settingSelect.value;
  if (!settingName) {
    return;
  }
  await enqueueJob("event.expball.summon", {
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
  const supportsExpball = ["CH", "CNTW", "JP"].includes(state.selectedSettingPlan?.server);
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
  els.inspectExpball.disabled = !state.connected
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
  els.fullRunRestartLimit.disabled = !state.selectedSettingPlan?.run?.game_crash_restart;
  els.fullRunMapSwipes.disabled = !["free_quest", "main_story"].includes(
    els.fullRunEntryMode.value,
  );
  els.pauseJob.disabled = selectedJobStatus !== "running";
  els.resumeJob.disabled = selectedJobStatus !== "paused";
  els.cancelJob.disabled = !ACTIVE_JOB_STATES.has(selectedJobStatus)
    || selectedJobStatus === "cancelling";
  els.editSetting.disabled = !els.settingSelect.value;
  els.deleteSetting.disabled = !els.settingSelect.value;
  els.editStrategy.disabled = !els.strategySelect.value;
  els.deleteStrategy.disabled = !els.strategySelect.value;
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
