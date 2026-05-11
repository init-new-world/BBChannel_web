const state = {
  connected: false,
  backends: [],
  devices: [],
  screenshotUrl: null,
  screenshotBase64: "",
  screenshotNaturalSize: null,
  latestMatch: null,
};

const els = {
  backendSelect: document.querySelector("#backend-select"),
  deviceList: document.querySelector("#device-list"),
  refreshDevices: document.querySelector("#refresh-devices"),
  connectDevice: document.querySelector("#connect-device"),
  disconnectDevice: document.querySelector("#disconnect-device"),
  connectionState: document.querySelector("#connection-state"),
  snapshotButton: document.querySelector("#snapshot-button"),
  clearScreenshot: document.querySelector("#clear-screenshot"),
  templateSelect: document.querySelector("#template-select"),
  thresholdInput: document.querySelector("#threshold-input"),
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
  fitScreen: document.querySelector("#fit-screen"),
  actualScreen: document.querySelector("#actual-screen"),
  refreshEvents: document.querySelector("#refresh-events"),
  eventLog: document.querySelector("#event-log"),
  logCount: document.querySelector("#log-count"),
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
    const message = payload?.error?.message || `${response.status} ${response.statusText}`;
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
  await Promise.allSettled([loadCapabilities(), loadDevices(), loadTemplates(), loadEvents()]);
  await loadConnectionState();
  updateControls();
}

function bindEvents() {
  els.backendSelect.addEventListener("change", renderDevices);
  els.refreshDevices.addEventListener("click", loadDevices);
  els.connectDevice.addEventListener("click", connect);
  els.disconnectDevice.addEventListener("click", disconnect);
  els.snapshotButton.addEventListener("click", captureScreenshot);
  els.clearScreenshot.addEventListener("click", clearScreenshot);
  els.matchButton.addEventListener("click", matchTemplate);
  els.tapButton.addEventListener("click", sendTap);
  els.swipeButton.addEventListener("click", sendSwipe);
  els.fitScreen.addEventListener("click", () => setScreenScale("fit"));
  els.actualScreen.addEventListener("click", () => setScreenScale("actual"));
  els.refreshEvents.addEventListener("click", loadEvents);
  els.screenshot.addEventListener("load", onScreenshotLoaded);
  els.screenStage.addEventListener("click", populateTapFromClick);
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

async function loadDevices() {
  try {
    const payload = await api("/api/devices");
    state.devices = payload.devices || [];
    renderDevices();
  } catch (error) {
    showError(error);
  }
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
  } catch (error) {
    showError(error);
  }
}

function renderDevices() {
  const backend = els.backendSelect.value;
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
  updateControls();
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
  state.latestMatch = null;
  els.screenshot.src = dataUrl;
  els.screenshot.classList.add("visible");
  els.screenEmpty.hidden = true;
  clearMatchOverlay();
  updateControls();
}

function clearScreenshot() {
  if (state.screenshotUrl) {
    URL.revokeObjectURL(state.screenshotUrl);
  }
  state.screenshotUrl = null;
  state.screenshotBase64 = "";
  state.screenshotNaturalSize = null;
  state.latestMatch = null;
  els.screenshot.removeAttribute("src");
  els.screenshot.classList.remove("visible", "actual-size");
  els.screenEmpty.hidden = false;
  els.screenMeta.textContent = "No capture";
  els.matchResult.textContent = "No match";
  clearMatchOverlay();
  updateControls();
}

async function matchTemplate() {
  try {
    const payload = await api("/api/match", {
      method: "POST",
      body: JSON.stringify({
        screenshot_base64: state.screenshotBase64,
        template_path: els.templateSelect.value,
        threshold: Number(els.thresholdInput.value),
      }),
    });
    state.latestMatch = payload;
    renderMatch(payload);
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

function setConnectionLabel(payload) {
  if (payload.connected) {
    els.connectionState.textContent = `${payload.backend} · ${payload.device_id}`;
    els.connectionState.classList.add("connected");
    return;
  }
  els.connectionState.textContent = "Disconnected";
  els.connectionState.classList.remove("connected");
}

function updateControls() {
  const hasDevice = Boolean(els.deviceList.value);
  const hasScreenshot = Boolean(state.screenshotBase64);
  const hasTemplate = Boolean(els.templateSelect.value);
  els.connectDevice.disabled = !hasDevice || state.connected;
  els.disconnectDevice.disabled = !state.connected;
  els.snapshotButton.disabled = !state.connected;
  els.clearScreenshot.disabled = !hasScreenshot;
  els.matchButton.disabled = !hasScreenshot || !hasTemplate;
  els.tapButton.disabled = !state.connected;
  els.swipeButton.disabled = !state.connected;
}

function onScreenshotLoaded() {
  state.screenshotNaturalSize = {
    width: els.screenshot.naturalWidth,
    height: els.screenshot.naturalHeight,
  };
  els.screenMeta.textContent = `${state.screenshotNaturalSize.width} x ${state.screenshotNaturalSize.height}`;
  if (state.latestMatch) {
    renderMatch(state.latestMatch);
  }
}

function renderMatch(result) {
  els.matchResult.textContent = `${result.matched ? "Matched" : "Below threshold"} · ${result.confidence.toFixed(3)} · ${result.center.join(", ")}`;
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
