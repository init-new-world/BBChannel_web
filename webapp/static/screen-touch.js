export const DEFAULT_TOUCH_OPTIONS = Object.freeze({
  dragSlopPx: 10,
  longPressMs: 420,
  longPressIndicatorDelayMs: 150,
  longPressMoveSlopPx: 20,
  moveThrottleMs: 28,
  moveMinDeltaPx: 3,
  tapBounceGuardMs: 45,
  tapBounceRadiusPx: 8,
  swipeMinDurationMs: 140,
  swipeMaxDurationMs: 1200,
  longPressFallbackMinMs: 550,
  longPressFallbackMaxMs: 5000,
});

function hypot(dx, dy) {
  return Math.hypot(dx, dy);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

/**
 * Pure anti-jitter gesture state machine for intuitive real-time touch control:
 * - Quick / hesitant clicks (< longPressMs, displacement < dragSlopPx) -> TAP at press origin
 * - Holding still >= longPressMs -> live TOUCH_DOWN immediately (widened jitter deadzone while holding;
 *   intentional movement >= longPressMoveSlopPx transitions smoothly into live drag-after-hold)
 * - Moving >= dragSlopPx before longPressMs -> cancels long press, sends live TOUCH_DOWN(origin)
 *   + throttled TOUCH_MOVE(current) immediately, and TOUCH_UP on release.
 */
export function createTouchGestureEngine(options = {}) {
  const config = { ...DEFAULT_TOUCH_OPTIONS, ...options };
  const now = options.now || (() => performance.now());
  const setTimer = options.setTimer || ((fn, ms) => window.setTimeout(fn, ms));
  const clearTimer = options.clearTimer || ((id) => window.clearTimeout(id));
  const callbacks = {
    onTap: options.onTap || (() => {}),
    onLiveDown: options.onLiveDown || (() => {}),
    onLiveMove: options.onLiveMove || (() => {}),
    onLiveUp: options.onLiveUp || (() => {}),
    onLiveCancel: options.onLiveCancel || (() => {}),
    onSwipeFallback: options.onSwipeFallback || (() => {}),
    onPickDrag: options.onPickDrag || (() => {}),
    onVisualState: options.onVisualState || (() => {}),
  };

  let liveTouchSupported = options.liveTouchSupported !== false;
  let lastTapAt = -Infinity;
  let lastTapClient = null;

  let active = null;
  let longPressTimer = null;
  let indicatorTimer = null;
  let moveFlushTimer = null;

  function clearTimers() {
    if (longPressTimer !== null) {
      clearTimer(longPressTimer);
      longPressTimer = null;
    }
    if (indicatorTimer !== null) {
      clearTimer(indicatorTimer);
      indicatorTimer = null;
    }
    if (moveFlushTimer !== null) {
      clearTimer(moveFlushTimer);
      moveFlushTimer = null;
    }
  }

  function emitVisual(extra = {}) {
    if (!active) {
      callbacks.onVisualState({ phase: "idle", ...extra });
      return;
    }
    callbacks.onVisualState({
      phase: active.phase,
      controlEnabled: active.controlEnabled,
      startClient: active.startClient,
      currClient: active.currClient,
      startDevice: active.startDevice,
      currDevice: active.currDevice,
      startedAt: active.startedAt,
      longPressStartedAt: active.longPressStartedAt,
      longPressMs: config.longPressMs,
      indicatorDelayMs: config.longPressIndicatorDelayMs,
      chargingVisible: active.chargingVisible,
      ...extra,
    });
  }

  function flushPendingMove() {
    if (moveFlushTimer !== null) {
      clearTimer(moveFlushTimer);
      moveFlushTimer = null;
    }
    if (!active || !active.liveDownSent || !active.pendingMove) {
      return;
    }
    const { device, client } = active.pendingMove;
    active.pendingMove = null;
    if (
      active.lastSentDevice
      && active.lastSentDevice.x === device.x
      && active.lastSentDevice.y === device.y
    ) {
      return;
    }
    active.lastSentAt = now();
    active.lastSentDevice = { ...device };
    active.lastSentClient = { ...client };
    callbacks.onLiveMove({
      x: device.x,
      y: device.y,
      mode: active.phase === "long_pressing" ? "long_press" : "drag",
    });
  }

  function scheduleOrSendLiveMove(client, device) {
    if (!active || !active.liveDownSent) {
      return;
    }
    const lastClient = active.lastSentClient || active.startClient;
    if (hypot(client.x - lastClient.x, client.y - lastClient.y) < config.moveMinDeltaPx) {
      return;
    }
    if (
      active.lastSentDevice
      && active.lastSentDevice.x === device.x
      && active.lastSentDevice.y === device.y
    ) {
      return;
    }
    const elapsedSinceSend = now() - active.lastSentAt;
    if (elapsedSinceSend >= config.moveThrottleMs) {
      active.pendingMove = null;
      if (moveFlushTimer !== null) {
        clearTimer(moveFlushTimer);
        moveFlushTimer = null;
      }
      active.lastSentAt = now();
      active.lastSentDevice = { ...device };
      active.lastSentClient = { ...client };
      callbacks.onLiveMove({
        x: device.x,
        y: device.y,
        mode: active.phase === "long_pressing" ? "long_press" : "drag",
      });
      return;
    }
    active.pendingMove = { client: { ...client }, device: { ...device } };
    if (moveFlushTimer === null) {
      const waitMs = Math.max(1, config.moveThrottleMs - elapsedSinceSend);
      moveFlushTimer = setTimer(() => {
        moveFlushTimer = null;
        flushPendingMove();
      }, waitMs);
    }
  }

  function enterLongPress() {
    longPressTimer = null;
    if (!active || active.phase !== "pending") {
      return;
    }
    active.phase = "long_pressing";
    active.chargingVisible = false;
    active.longPressStartedAt = now();
    active.longPressMoved = false;
    if (active.controlEnabled && liveTouchSupported) {
      active.liveDownSent = true;
      active.lastSentAt = now();
      active.lastSentDevice = { ...active.startDevice };
      active.lastSentClient = { ...active.startClient };
      callbacks.onLiveDown({
        x: active.startDevice.x,
        y: active.startDevice.y,
        mode: "long_press",
      });
    }
    emitVisual();
  }

  function pointerDown({ pointerId, clientX, clientY, deviceX, deviceY, controlEnabled }) {
    const timestamp = now();
    // Anti-bounce: suppress microswitch double-click chatter within tapBounceGuardMs at same point.
    if (
      !active
      && controlEnabled
      && lastTapClient
      && timestamp - lastTapAt < config.tapBounceGuardMs
      && hypot(clientX - lastTapClient.x, clientY - lastTapClient.y) <= config.tapBounceRadiusPx
    ) {
      return false;
    }

    // If a stale gesture somehow lingered, safely cancel it before starting a new one.
    if (active) {
      cancel("replaced");
    }

    active = {
      pointerId,
      phase: "pending",
      controlEnabled: Boolean(controlEnabled),
      startClient: { x: clientX, y: clientY },
      currClient: { x: clientX, y: clientY },
      startDevice: { x: deviceX, y: deviceY },
      currDevice: { x: deviceX, y: deviceY },
      startedAt: timestamp,
      longPressStartedAt: null,
      longPressMoved: false,
      chargingVisible: false,
      liveDownSent: false,
      lastSentAt: 0,
      lastSentDevice: null,
      lastSentClient: null,
      pendingMove: null,
    };

    if (active.controlEnabled) {
      indicatorTimer = setTimer(() => {
        indicatorTimer = null;
        if (active && active.phase === "pending") {
          active.chargingVisible = true;
          emitVisual();
        }
      }, config.longPressIndicatorDelayMs);

      longPressTimer = setTimer(enterLongPress, config.longPressMs);
    }

    emitVisual();
    return true;
  }

  function pointerMove({ pointerId, clientX, clientY, deviceX, deviceY }) {
    if (!active || active.pointerId !== pointerId) {
      return;
    }
    active.currClient = { x: clientX, y: clientY };
    active.currDevice = { x: deviceX, y: deviceY };
    const distFromStart = hypot(clientX - active.startClient.x, clientY - active.startClient.y);

    if (active.phase === "pending") {
      if (distFromStart < config.dragSlopPx) {
        return;
      }
      // Crossed spatial deadzone -> lock DRAGGING and cancel long-press timer!
      if (longPressTimer !== null) {
        clearTimer(longPressTimer);
        longPressTimer = null;
      }
      if (indicatorTimer !== null) {
        clearTimer(indicatorTimer);
        indicatorTimer = null;
      }
      active.phase = "dragging";
      active.chargingVisible = false;

      if (active.controlEnabled && liveTouchSupported) {
        active.liveDownSent = true;
        active.lastSentAt = now();
        active.lastSentDevice = { ...active.startDevice };
        active.lastSentClient = { ...active.startClient };
        callbacks.onLiveDown({
          x: active.startDevice.x,
          y: active.startDevice.y,
          mode: "drag",
        });
        if (
          active.currDevice.x !== active.startDevice.x
          || active.currDevice.y !== active.startDevice.y
        ) {
          active.lastSentAt = now();
          active.lastSentDevice = { ...active.currDevice };
          active.lastSentClient = { ...active.currClient };
          callbacks.onLiveMove({
            x: active.currDevice.x,
            y: active.currDevice.y,
            mode: "drag",
          });
        }
      }
      emitVisual();
      return;
    }

    if (active.phase === "dragging") {
      if (active.controlEnabled && active.liveDownSent) {
        scheduleOrSendLiveMove(active.currClient, active.currDevice);
      }
      emitVisual();
      return;
    }

    if (active.phase === "long_pressing") {
      // Widened anti-jitter deadzone while holding still; deliberate drag >= longPressMoveSlopPx moves live.
      if (!active.longPressMoved && distFromStart >= config.longPressMoveSlopPx) {
        active.longPressMoved = true;
      }
      if (active.longPressMoved && active.controlEnabled && active.liveDownSent) {
        scheduleOrSendLiveMove(active.currClient, active.currDevice);
      }
      emitVisual();
    }
  }

  function pointerUp({ pointerId, clientX, clientY, deviceX, deviceY }) {
    if (!active || active.pointerId !== pointerId) {
      return;
    }
    const gesture = active;
    gesture.currClient = { x: clientX, y: clientY };
    gesture.currDevice = { x: deviceX, y: deviceY };
    const elapsedMs = Math.max(0, Math.round(now() - gesture.startedAt));

    clearTimers();
    active = null;

    if (gesture.phase === "pending") {
      // Clean TAP at the exact pointerdown origin (prevents release jitter!).
      if (gesture.controlEnabled) {
        lastTapAt = now();
        lastTapClient = { ...gesture.startClient };
      }
      callbacks.onTap({
        x: gesture.startDevice.x,
        y: gesture.startDevice.y,
        clientX: gesture.startClient.x,
        clientY: gesture.startClient.y,
        controlEnabled: gesture.controlEnabled,
      });
      callbacks.onVisualState({
        phase: "tap_flash",
        controlEnabled: gesture.controlEnabled,
        startClient: gesture.startClient,
        startDevice: gesture.startDevice,
      });
      return;
    }

    if (gesture.phase === "dragging") {
      const durationMs = clamp(elapsedMs, config.swipeMinDurationMs, config.swipeMaxDurationMs);
      if (!gesture.controlEnabled) {
        callbacks.onPickDrag({
          x1: gesture.startDevice.x,
          y1: gesture.startDevice.y,
          x2: gesture.currDevice.x,
          y2: gesture.currDevice.y,
          durationMs,
        });
      } else if (gesture.liveDownSent) {
        if (
          gesture.lastSentDevice
          && (gesture.lastSentDevice.x !== gesture.currDevice.x
            || gesture.lastSentDevice.y !== gesture.currDevice.y)
        ) {
          callbacks.onLiveMove({
            x: gesture.currDevice.x,
            y: gesture.currDevice.y,
            mode: "drag",
          });
        }
        callbacks.onLiveUp({
          x: gesture.currDevice.x,
          y: gesture.currDevice.y,
          mode: "drag",
          durationMs: elapsedMs,
          start: gesture.startDevice,
          end: gesture.currDevice,
        });
      } else {
        callbacks.onSwipeFallback({
          x1: gesture.startDevice.x,
          y1: gesture.startDevice.y,
          x2: gesture.currDevice.x,
          y2: gesture.currDevice.y,
          durationMs,
          mode: "drag",
        });
      }
      callbacks.onVisualState({ phase: "idle" });
      return;
    }

    if (gesture.phase === "long_pressing") {
      const endPos = gesture.longPressMoved ? gesture.currDevice : gesture.startDevice;
      if (gesture.controlEnabled && gesture.liveDownSent) {
        if (
          gesture.longPressMoved
          && gesture.lastSentDevice
          && (gesture.lastSentDevice.x !== endPos.x || gesture.lastSentDevice.y !== endPos.y)
        ) {
          callbacks.onLiveMove({
            x: endPos.x,
            y: endPos.y,
            mode: "long_press",
          });
        }
        callbacks.onLiveUp({
          x: endPos.x,
          y: endPos.y,
          mode: "long_press",
          durationMs: elapsedMs,
          start: gesture.startDevice,
          end: endPos,
        });
      } else if (gesture.controlEnabled) {
        const holdMs = clamp(elapsedMs, config.longPressFallbackMinMs, config.longPressFallbackMaxMs);
        callbacks.onSwipeFallback({
          x1: gesture.startDevice.x,
          y1: gesture.startDevice.y,
          x2: endPos.x,
          y2: endPos.y,
          durationMs: holdMs,
          mode: "long_press",
        });
      }
      callbacks.onVisualState({ phase: "idle" });
    }
  }

  function cancel(reason = "cancel") {
    if (!active) {
      return;
    }
    const gesture = active;
    clearTimers();
    active = null;
    if (gesture.controlEnabled && gesture.liveDownSent) {
      const pos = gesture.lastSentDevice || gesture.currDevice || gesture.startDevice;
      callbacks.onLiveCancel({
        x: pos.x,
        y: pos.y,
        mode: gesture.phase === "long_pressing" ? "long_press" : "drag",
        reason,
      });
    }
    callbacks.onVisualState({ phase: "idle" });
  }

  function disableLiveTouch() {
    liveTouchSupported = false;
    if (active) {
      active.liveDownSent = false;
    }
  }

  function resetLiveTouchCapability() {
    liveTouchSupported = true;
  }

  function getState() {
    return {
      phase: active ? active.phase : "idle",
      liveTouchSupported,
      liveDownSent: Boolean(active?.liveDownSent),
    };
  }

  return {
    pointerDown,
    pointerMove,
    pointerUp,
    cancel,
    disableLiveTouch,
    resetLiveTouchCapability,
    getState,
  };
}

/**
 * Attaches Pointer Events + GPU-friendly visual gesture overlay onto `#screen-stage`.
 */
export function attachScreenTouchController({
  stage,
  image,
  overlay,
  getNaturalSize,
  isControlEnabled,
  callbacks,
  translate = (text) => text,
  options = {},
}) {
  const t = translate;
  let activePointerId = null;
  let rafId = null;
  let rippleTimer = null;
  let lastVisual = { phase: "idle" };

  function stopRaf() {
    if (rafId !== null) {
      window.cancelAnimationFrame(rafId);
      rafId = null;
    }
  }

  function clientToStage(clientX, clientY) {
    const stageRect = stage.getBoundingClientRect();
    return {
      x: clientX - stageRect.left,
      y: clientY - stageRect.top,
    };
  }

  function syncOverlayViewport() {
    if (!overlay) return { width: 0, height: 0 };
    const width = stage.clientWidth;
    const height = stage.clientHeight;
    overlay.style.left = `${stage.scrollLeft}px`;
    overlay.style.top = `${stage.scrollTop}px`;
    overlay.style.width = `${width}px`;
    overlay.style.height = `${height}px`;
    return { width, height };
  }

  function clampBadgePos(x, y, width, height, yOffset = 26) {
    const padX = Math.min(68, Math.max(24, width * 0.15));
    return {
      x: clamp(x, padX, Math.max(padX, width - padX)),
      y: clamp(y - yOffset, 26, Math.max(26, height - 6)),
    };
  }

  function clientToDevice(clientX, clientY, { clampToBounds = false } = {}) {
    const natural = getNaturalSize();
    if (!natural || !image.classList.contains("visible")) {
      return null;
    }
    const rect = image.getBoundingClientRect();
    if (!rect.width || !rect.height) {
      return null;
    }
    if (!clampToBounds) {
      if (
        clientX < rect.left
        || clientX > rect.right
        || clientY < rect.top
        || clientY > rect.bottom
      ) {
        return null;
      }
    }
    const normX = clamp((clientX - rect.left) / rect.width, 0, 1);
    const normY = clamp((clientY - rect.top) / rect.height, 0, 1);
    return {
      x: clamp(Math.round(normX * natural.width), 0, Math.max(0, natural.width - 1)),
      y: clamp(Math.round(normY * natural.height), 0, Math.max(0, natural.height - 1)),
    };
  }

  function renderOverlay(visual) {
    lastVisual = visual;
    if (!overlay) return;

    if (rippleTimer !== null && visual.phase !== "idle") {
      window.clearTimeout(rippleTimer);
      rippleTimer = null;
    }

    if (visual.phase === "idle") {
      stopRaf();
      overlay.hidden = true;
      overlay.innerHTML = "";
      return;
    }

    if (visual.phase === "tap_flash") {
      stopRaf();
      const { width, height } = syncOverlayViewport();
      const pt = clientToStage(visual.startClient.x, visual.startClient.y);
      const badge = clampBadgePos(pt.x, pt.y, width, height, 24);
      const cls = visual.controlEnabled ? "touch-ripple live" : "touch-ripple pick";
      overlay.hidden = false;
      overlay.innerHTML = `
        <div class="${cls}" style="left:${pt.x}px;top:${pt.y}px"></div>
        <div class="touch-badge" style="left:${badge.x}px;top:${badge.y}px">${visual.startDevice.x}, ${visual.startDevice.y}</div>
      `;
      rippleTimer = window.setTimeout(() => {
        rippleTimer = null;
        if (lastVisual.phase === "tap_flash") {
          overlay.hidden = true;
          overlay.innerHTML = "";
        }
      }, 420);
      return;
    }

    if (visual.phase === "pending") {
      if (!visual.chargingVisible) {
        stopRaf();
        overlay.hidden = true;
        overlay.innerHTML = "";
        return;
      }
      const pt = clientToStage(visual.startClient.x, visual.startClient.y);
      const drawCharge = () => {
        if (lastVisual.phase !== "pending" || !lastVisual.chargingVisible) {
          rafId = null;
          return;
        }
        syncOverlayViewport();
        const elapsed = performance.now() - visual.startedAt;
        const progress = clamp(
          (elapsed - visual.indicatorDelayMs) / Math.max(1, visual.longPressMs - visual.indicatorDelayMs),
          0,
          1,
        );
        const radius = 19;
        const circumference = 2 * Math.PI * radius;
        const offset = circumference * (1 - progress);
        overlay.hidden = false;
        overlay.innerHTML = `
          <svg class="touch-ring-svg" style="left:${pt.x}px;top:${pt.y}px" width="48" height="48" viewBox="0 0 48 48">
            <circle class="touch-ring-track" cx="24" cy="24" r="${radius}" />
            <circle class="touch-ring-progress" cx="24" cy="24" r="${radius}"
              stroke-dasharray="${circumference.toFixed(1)}"
              stroke-dashoffset="${offset.toFixed(1)}" />
          </svg>
        `;
        rafId = window.requestAnimationFrame(drawCharge);
      };
      stopRaf();
      drawCharge();
      return;
    }

    if (visual.phase === "long_pressing") {
      const drawHold = () => {
        if (lastVisual.phase !== "long_pressing") {
          rafId = null;
          return;
        }
        const { width, height } = syncOverlayViewport();
        const p0 = clientToStage(lastVisual.startClient.x, lastVisual.startClient.y);
        const p1 = clientToStage(lastVisual.currClient.x, lastVisual.currClient.y);
        const moved = hypot(p1.x - p0.x, p1.y - p0.y) >= (options.longPressMoveSlopPx || DEFAULT_TOUCH_OPTIONS.longPressMoveSlopPx);
        const holdSec = ((performance.now() - (lastVisual.longPressStartedAt || lastVisual.startedAt)) / 1000).toFixed(1);
        const label = moved
          ? `${t("Hold & drag")} ${holdSec}s`
          : `${t("Holding")} ${holdSec}s`;
        const anchorX = moved ? p1.x : p0.x;
        const anchorY = moved ? p1.y : p0.y;
        const badge = clampBadgePos(anchorX, anchorY, width, height, 30);
        const lineSvg = moved
          ? `<svg class="touch-trail-svg" width="${width}" height="${height}">
              <line class="touch-trail-line hold" x1="${p0.x}" y1="${p0.y}" x2="${p1.x}" y2="${p1.y}" />
              <circle class="touch-trail-start hold" cx="${p0.x}" cy="${p0.y}" r="5" />
            </svg>`
          : "";
        overlay.hidden = false;
        overlay.innerHTML = `
          ${lineSvg}
          <div class="touch-hold-pulse" style="left:${anchorX}px;top:${anchorY}px"></div>
          <div class="touch-badge hold" style="left:${badge.x}px;top:${badge.y}px">${label}</div>
        `;
        rafId = window.requestAnimationFrame(drawHold);
      };
      stopRaf();
      drawHold();
      return;
    }

    if (visual.phase === "dragging") {
      stopRaf();
      const { width, height } = syncOverlayViewport();
      const p0 = clientToStage(visual.startClient.x, visual.startClient.y);
      const p1 = clientToStage(visual.currClient.x, visual.currClient.y);
      const badge = clampBadgePos(p1.x, p1.y, width, height, 26);
      const modeClass = visual.controlEnabled ? "live" : "pick";
      const label = visual.controlEnabled
        ? `${t("Drag")} ${visual.startDevice.x},${visual.startDevice.y} → ${visual.currDevice.x},${visual.currDevice.y}`
        : `${t("Swipe pick")} ${visual.startDevice.x},${visual.startDevice.y} → ${visual.currDevice.x},${visual.currDevice.y}`;
      overlay.hidden = false;
      overlay.innerHTML = `
        <svg class="touch-trail-svg" width="${width}" height="${height}">
          <line class="touch-trail-line ${modeClass}" x1="${p0.x}" y1="${p0.y}" x2="${p1.x}" y2="${p1.y}" />
          <circle class="touch-trail-start ${modeClass}" cx="${p0.x}" cy="${p0.y}" r="5" />
          <circle class="touch-trail-end ${modeClass}" cx="${p1.x}" cy="${p1.y}" r="6" />
        </svg>
        <div class="touch-badge ${modeClass}" style="left:${badge.x}px;top:${badge.y}px">${label}</div>
      `;
    }
  }

  const engine = createTouchGestureEngine({
    ...options,
    ...callbacks,
    onVisualState: renderOverlay,
  });

  function onPointerDown(event) {
    if (!event.isPrimary) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const devicePos = clientToDevice(event.clientX, event.clientY, { clampToBounds: false });
    if (!devicePos) return;

    event.preventDefault();
    const accepted = engine.pointerDown({
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      deviceX: devicePos.x,
      deviceY: devicePos.y,
      controlEnabled: isControlEnabled(),
    });
    if (!accepted) return;

    activePointerId = event.pointerId;
    try {
      stage.setPointerCapture(event.pointerId);
    } catch {
      // Ignore capture errors in synthetic test environments.
    }
  }

  function onPointerMove(event) {
    if (activePointerId === null || event.pointerId !== activePointerId) return;
    const devicePos = clientToDevice(event.clientX, event.clientY, { clampToBounds: true });
    if (!devicePos) return;
    engine.pointerMove({
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      deviceX: devicePos.x,
      deviceY: devicePos.y,
    });
  }

  function finishPointer(event, cancelled = false) {
    if (activePointerId === null || event.pointerId !== activePointerId) return;
    activePointerId = null;
    try {
      if (stage.hasPointerCapture?.(event.pointerId)) {
        stage.releasePointerCapture(event.pointerId);
      }
    } catch {
      // Ignore capture release errors.
    }
    if (cancelled) {
      engine.cancel("pointercancel");
      return;
    }
    const devicePos = clientToDevice(event.clientX, event.clientY, { clampToBounds: true });
    if (!devicePos) {
      engine.cancel("out_of_bounds");
      return;
    }
    engine.pointerUp({
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      deviceX: devicePos.x,
      deviceY: devicePos.y,
    });
  }

  function onPointerUp(event) {
    finishPointer(event, false);
  }

  function onPointerCancel(event) {
    finishPointer(event, true);
  }

  function onDragStart(event) {
    event.preventDefault();
  }

  function onContextMenu(event) {
    if (activePointerId !== null) {
      event.preventDefault();
    }
  }

  function onWindowBlur() {
    if (activePointerId !== null) {
      activePointerId = null;
      engine.cancel("blur");
    }
  }

  function onVisibilityChange() {
    if (document.hidden && activePointerId !== null) {
      activePointerId = null;
      engine.cancel("hidden");
    }
  }

  function onKeyDown(event) {
    if (event.key === "Escape" && activePointerId !== null) {
      activePointerId = null;
      engine.cancel("escape");
    }
  }

  image.setAttribute("draggable", "false");
  stage.addEventListener("pointerdown", onPointerDown);
  stage.addEventListener("pointermove", onPointerMove);
  stage.addEventListener("pointerup", onPointerUp);
  stage.addEventListener("pointercancel", onPointerCancel);
  stage.addEventListener("dragstart", onDragStart);
  stage.addEventListener("contextmenu", onContextMenu);
  window.addEventListener("blur", onWindowBlur);
  document.addEventListener("visibilitychange", onVisibilityChange);
  window.addEventListener("keydown", onKeyDown);

  return {
    cancel(reason = "external") {
      activePointerId = null;
      engine.cancel(reason);
    },
    disableLiveTouch() {
      engine.disableLiveTouch();
    },
    resetLiveTouchCapability() {
      engine.resetLiveTouchCapability();
    },
    getState() {
      return engine.getState();
    },
    destroy() {
      stopRaf();
      stage.removeEventListener("pointerdown", onPointerDown);
      stage.removeEventListener("pointermove", onPointerMove);
      stage.removeEventListener("pointerup", onPointerUp);
      stage.removeEventListener("pointercancel", onPointerCancel);
      stage.removeEventListener("dragstart", onDragStart);
      stage.removeEventListener("contextmenu", onContextMenu);
      window.removeEventListener("blur", onWindowBlur);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      window.removeEventListener("keydown", onKeyDown);
    },
  };
}
