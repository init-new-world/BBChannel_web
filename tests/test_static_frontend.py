from pathlib import Path


STATIC_DIR = Path("webapp/static")


def test_operator_console_static_files_exist():
    assert (STATIC_DIR / "index.html").is_file()
    assert (STATIC_DIR / "styles.css").is_file()
    assert (STATIC_DIR / "app.js").is_file()
    assert (STATIC_DIR / "preset-team.js").is_file()
    assert (STATIC_DIR / "team-source.js").is_file()
    assert (STATIC_DIR / "preset-assist.js").is_file()
    assert (STATIC_DIR / "assist-source.js").is_file()
    assert (STATIC_DIR / "preset-equips.js").is_file()
    assert (STATIC_DIR / "assist-equips-source.js").is_file()
    assert (STATIC_DIR / "settlement-source.js").is_file()
    assert (STATIC_DIR / "preset-drops.js").is_file()
    assert (STATIC_DIR / "preset-turn-skills.js").is_file()
    assert (STATIC_DIR / "turn-skills-source.js").is_file()
    assert (STATIC_DIR / "special-skills-model.js").is_file()
    assert (STATIC_DIR / "kukulkan-model.js").is_file()
    assert (STATIC_DIR / "third-skill-model.js").is_file()
    assert (STATIC_DIR / "skill-variants-model.js").is_file()
    assert (STATIC_DIR / "hakuno-needs-model.js").is_file()
    assert (STATIC_DIR / "preset-hakuno-needs.js").is_file()
    assert (STATIC_DIR / "turn-nps-source.js").is_file()
    assert (STATIC_DIR / "turn-strategies-source.js").is_file()
    assert (STATIC_DIR / "json-source.js").is_file()
    assert (STATIC_DIR / "vendor" / "jsonc-parser.js").is_file()
    assert (STATIC_DIR / "vendor" / "jsonc-parser.LICENSE.txt").is_file()


def test_operator_console_references_api_controls():
    index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="screenshot"' in index
    assert 'id="device-list"' in index
    assert 'id="manual-adb-endpoint"' in index
    assert 'id="setting-select"' in index
    assert 'id="setting-plan"' in index
    assert 'id="new-setting"' in index
    assert 'id="edit-setting"' in index
    assert 'id="delete-setting"' in index
    assert 'id="refresh-settings" class="ghost-button wide"' in index
    assert 'id="import-setting"' in index
    assert 'id="export-setting"' in index
    assert 'id="setting-file-input"' in index
    assert index.index('id="delete-setting"') < index.index('id="refresh-settings"')
    assert index.index('id="refresh-settings"') < index.index('id="setting-validation"')
    assert 'id="strategy-select"' in index
    assert 'id="new-strategy"' in index
    assert 'id="edit-strategy"' in index
    assert 'id="delete-strategy"' in index
    assert 'id="preset-dialog"' in index
    assert 'id="preset-name"' in index
    assert 'id="preset-json"' in index
    assert 'id="save-preset"' in index
    assert 'id="template-select"' in index
    assert 'id="recognition-scales"' in index
    assert 'id="recognition-roi-enabled"' in index
    assert 'id="recognition-roi-x"' in index
    assert 'id="recognition-roi-y"' in index
    assert 'id="recognition-roi-width"' in index
    assert 'id="recognition-roi-height"' in index
    assert 'id="screen-source-mode"' in index
    assert 'id="screen-debug-mode"' in index
    assert 'id="event-log"' in index
    assert 'id="start-diagnostic"' in index
    assert 'id="battle-script-name"' in index
    assert 'id="battle-action-delay"' in index
    assert 'id="start-battle-dry-run"' in index
    assert 'id="battle-program-status"' in index
    assert 'id="start-battle-plan"' in index
    assert 'id="full-run-count"' in index
    assert 'id="full-run-restart-limit"' in index
    assert 'id="full-run-entry-mode"' in index
    assert '<option value="main_story">Main story</option>' in index
    assert '<option value="interlude">Interlude</option>' in index
    assert 'id="full-run-map-swipes"' in index
    assert 'id="full-run-apple"' in index
    assert 'id="full-run-team-check"' in index
    assert 'id="full-run-crawl-tower"' in index
    assert 'id="full-run-crawl-tower-mode"' in index
    assert 'id="start-full-run"' in index
    assert 'id="restart-game"' in index
    assert 'id="inspect-chocolate"' in index
    assert 'id="capture-chocolate-banner"' in index
    assert 'id="chocolate-female"' in index
    assert 'id="chocolate-male"' in index
    assert 'id="chocolate-batch-10"' in index
    assert 'id="run-chocolate"' in index
    assert 'id="inspect-digdig"' in index
    assert 'id="inspect-digdig-grid"' in index
    assert 'id="digdig-one-key"' in index
    assert 'id="digdig-reset-board"' in index
    assert 'id="digdig-target-pieces"' in index
    assert 'id="digdig-target-extras"' in index
    assert 'id="digdig-max-cycles"' in index
    assert 'id="execute-digdig"' in index
    assert 'id="run-digdig"' in index
    assert 'id="inspect-lottery"' in index
    assert 'id="inspect-lottery-stacks"' in index
    assert 'id="run-lottery"' in index
    assert 'id="lottery-draw-pool"' in index
    assert 'id="lottery-tidy-giftbox"' in index
    assert 'id="lottery-long-touch-draw"' in index
    assert 'id="lottery-pay-slot"' in index
    assert 'id="lottery-onekey-3"' in index
    assert 'id="lottery-onekey-4"' in index
    assert 'id="lottery-onekey-5"' in index
    assert 'id="lottery-star-3"' in index
    assert 'id="lottery-star-4"' in index
    assert 'id="lottery-star-5"' in index
    assert 'id="lottery-keep-3"' in index
    assert 'id="lottery-keep-4"' in index
    assert 'id="lottery-keep-5"' in index
    assert 'id="lottery-first-round-count"' in index
    assert 'id="lottery-overflow-action"' in index
    assert 'id="lottery-overflow-actions"' in index
    assert '<option value="storage_then_sell">Store then sell</option>' in index
    assert 'id="inspect-expball"' in index
    assert 'id="inspect-expball-grid"' in index
    assert 'id="inspect-expball-servant-grid"' in index
    assert 'id="inspect-expball-cc-grid"' in index
    assert 'id="inspect-expball-ce-bomb-grid"' in index
    assert 'id="expball-destination"' in index
    assert 'id="navigate-expball"' in index
    assert 'id="expball-star-3"' in index
    assert 'id="expball-star-4"' in index
    assert 'id="expball-star-5"' in index
    assert 'id="expball-storage-target"' in index
    assert 'id="expball-sell-target"' in index
    assert 'id="expball-overflow-action"' in index
    assert 'id="expball-enhance-target"' in index
    assert 'id="expball-material-select-mode"' in index
    assert 'id="expball-servant-target"' in index
    assert 'id="expball-target-level"' in index
    assert 'id="expball-max-batches"' in index
    assert 'id="expball-auto-limit-break"' in index
    assert 'id="expball-lock-ce-bombs"' in index
    assert 'id="expball-auto-store-ce-bombs"' in index
    assert 'id="expball-eat-3star"' in index
    assert 'id="expball-eat-4star"' in index
    assert 'id="expball-overflow-actions"' in index
    assert 'id="expball-lock-gold-servants"' in index
    assert 'id="expball-lock-inscribed-cc"' in index
    assert 'id="expball-allow-qp-full"' in index
    assert 'id="inspect-expball-servant-target"' in index
    assert 'id="inspect-expball-servant-level"' in index
    assert 'id="run-expball-enhance"' in index
    assert 'id="expball-lock-lily"' in index
    assert 'id="expball-lock-habe"' in index
    assert 'id="expball-lock-hakuno"' in index
    assert 'id="expball-lock-targets"' in index
    assert 'id="expball-lock-enough-stop"' in index
    assert 'id="inspect-expball-summon-locks"' in index
    assert 'id="run-expball-summon"' in index
    assert 'id="fp-summon-batches"' in index
    assert 'id="expball-banner-direction"' in index
    assert 'id="expball-draw-100"' in index
    assert 'id="run-expball-storage"' in index
    assert 'id="run-expball-sell"' in index
    assert 'id="equip-template-name"' in index
    assert 'id="capture-equip-candidates"' in index
    assert 'id="equip-candidate-list"' in index
    assert 'id="equip-candidate-preview"' in index
    assert 'id="use-equip-full"' in index
    assert 'id="use-equip-non-full"' in index
    assert 'id="equip-full-image"' in index
    assert 'id="equip-non-full-image"' in index
    assert 'id="build-equip-template"' in index
    assert 'id="equip-template-list"' in index
    assert 'id="equip-template-preview"' in index
    assert 'id="test-equip-template"' in index
    assert 'id="equip-test-status"' in index
    assert 'id="activate-equip-template"' in index
    assert 'id="archive-equip-template"' in index
    assert 'id="open-assist-tags"' in index
    assert 'id="assist-tag-dialog"' in index
    assert 'id="capture-assist-tag-screen"' in index
    assert 'id="assist-tag-candidate"' in index
    assert 'id="assist-tag-canvas"' in index
    assert 'id="assist-tag-label"' in index
    assert 'id="assist-tag-threshold"' in index
    assert 'id="save-assist-tag"' in index
    assert 'id="assist-tag-list"' in index
    assert 'id="assist-tag-preview"' in index
    assert 'id="assist-tag-file"' in index
    assert 'id="import-assist-tag"' in index
    assert 'id="bind-assist-tag"' in index
    assert 'id="delete-assist-tag"' in index
    assert 'id="open-material-drops"' in index
    assert 'id="material-dialog"' in index
    assert 'id="material-server"' in index
    assert 'id="material-quality"' in index
    assert 'id="material-name"' in index
    assert 'id="material-results"' in index
    assert 'id="open-notebook"' in index
    assert 'id="notebook-dialog"' in index
    assert 'id="notebook-content"' in index
    assert 'id="save-notebook"' in index
    assert "team_check_mode: els.fullRunTeamCheck.value" in script
    assert "crawl_tower: Boolean(els.fullRunCrawlTower?.checked)" in script
    assert "entry_mode: els.fullRunEntryMode.value" in script
    assert '"interlude"' in script
    assert "els.fullRunEntryMode.value" in script
    assert "max_map_swipes: readNumber(els.fullRunMapSwipes)" in script
    assert "max_restarts: readNumber(els.fullRunRestartLimit)" in script
    assert "state.selectedSettingPlan?.run?.game_crash_restart" in script
    assert "result.restart_count" in script
    assert 'job.kind === "event.chocolate.inspect"' in script
    assert 'job.kind === "event.chocolate.capture-banner"' in script
    assert 'job.kind === "event.chocolate.run"' in script
    assert 'job.kind === "event.digdig.inspect"' in script
    assert 'job.kind === "event.digdig.inspect-board-grid"' in script
    assert 'job.kind === "event.digdig.execute"' in script
    assert 'job.kind === "event.digdig.run"' in script
    assert 'job.kind === "event.lottery.inspect"' in script
    assert 'job.kind === "event.lottery.inspect-giftbox-stacks"' in script
    assert 'job.kind === "event.lottery.run"' in script
    assert 'job.kind === "event.expball.inspect"' in script
    assert 'job.kind === "event.expball.inspect-storage-grid"' in script
    assert 'job.kind === "event.expball.inspect-servant-grid"' in script
    assert 'job.kind === "event.expball.inspect-command-code-grid"' in script
    assert 'job.kind === "event.expball.inspect-ce-bomb-grid"' in script
    assert 'job.kind === "event.expball.inspect-servant-target"' in script
    assert 'job.kind === "event.expball.inspect-servant-level"' in script
    assert 'job.kind === "event.expball.inspect-summon-lock-targets"' in script
    assert 'job.kind === "event.expball.enhance"' in script
    assert 'job.kind === "event.expball.navigate"' in script
    assert 'job.kind === "event.expball.run"' in script
    assert 'job.kind === "event.expball.summon"' in script
    assert 'job.kind === "event.expball.storage"' in script
    assert 'job.kind === "event.expball.sell"' in script
    assert "result.summons || 0" in script
    assert "result.pieces?.length || 0" in script
    assert 'enqueueJob("battle.restart-game"' in script
    assert 'enqueueJob("event.chocolate.inspect"' in script
    assert 'enqueueJob("event.chocolate.capture-banner"' in script
    assert 'enqueueJob("event.chocolate.run"' in script
    assert "select_10_batch: Boolean(els.chocolateBatch10?.checked)" in script
    assert 'enqueueJob("event.digdig.inspect"' in script
    assert 'enqueueJob("event.digdig.inspect-board-grid"' in script
    assert 'enqueueJob("event.digdig.execute"' in script
    assert 'enqueueJob("event.digdig.run"' in script
    assert 'enqueueJob("event.lottery.inspect"' in script
    assert 'enqueueJob("event.lottery.inspect-giftbox-stacks"' in script
    assert 'enqueueJob("event.lottery.run"' in script
    assert "draw_pool: drawPool" in script
    assert "tidy_giftbox: tidyGiftbox" in script
    assert "long_touch_draw: Boolean(els.lotteryLongTouchDraw?.checked)" in script
    assert "pay_slot: readNumber(els.lotteryPaySlot)" in script
    assert "...(stars.length ? { stars } : {})" in script
    assert "...(oneKeyStars.length ? { one_key_stars: oneKeyStars } : {})" in script
    assert "first_round_count: Boolean(els.lotteryFirstRoundCount?.checked)" in script
    assert "parseLotteryMaxStackCounts()" in script
    assert "overflow_action: overflowAction" in script
    assert "...(overflowActions.length ? { overflow_actions: overflowActions } : {})" in script
    assert "selectedExpballStars()" in script
    assert 'enqueueJob("event.expball.inspect"' in script
    assert 'enqueueJob("event.expball.inspect-storage-grid"' in script
    assert 'enqueueJob("event.expball.inspect-servant-grid"' in script
    assert 'enqueueJob("event.expball.inspect-command-code-grid"' in script
    assert 'enqueueJob("event.expball.inspect-ce-bomb-grid"' in script
    assert 'enqueueJob("event.expball.inspect-servant-target"' in script
    assert 'enqueueJob("event.expball.inspect-summon-lock-targets"' in script
    assert 'enqueueJob("event.expball.navigate"' in script
    assert "destination: els.expballDestination.value" in script
    assert 'enqueueJob("event.expball.run"' in script
    assert "max_summons: readNumber(els.fpSummonBatches)" in script
    assert 'banner_direction: els.expballBannerDirection?.value || "right"' in script
    assert "draw_100: Boolean(els.expballDraw100?.checked)" in script
    assert "parseDigdigTargets(els.digdigTargetPieces)" in script
    assert "parseDigdigTargets(els.digdigTargetExtras)" in script
    assert 'enqueueJob("event.expball.storage"' in script
    assert 'enqueueJob("event.expball.sell"' in script
    assert "result.overflow_cycles" in script
    assert "result.selected_count" in script
    assert "/api/equip-templates" in script
    assert "/api/material-drops/catalog" in script
    assert "queryMaterialDrops" in script
    assert 'api("/api/notebook")' in script
    assert "saveNotebook" in script
    assert "handleSettingImport" in script
    assert "exportSelectedSetting" in script
    assert "URL.createObjectURL" in script
    assert "full_image_base64" in script
    assert "non_full_image_base64" in script
    assert "loadEquipTemplates" in script
    assert "captureEquipCandidates" in script
    assert "testEquipTemplate" in script
    assert "/test`" in script
    assert "screenshot_base64: state.screenshotBase64 || null" in script
    assert 'data-tag-mode="assist"' in index
    assert 'data-tag-mode="command"' in index
    assert 'endpoint: `/api/${state.assistTagMode}-tags`' in script
    assert 'api(request.endpoint)' in script
    assert 'api(`${request.endpoint}/candidates`' in script
    assert 'api(context.endpoint' in script
    assert '`${context.endpoint}/${encodeURIComponent(tag.name)}`' in script
    assert '/api/settings/${encodeURIComponent(settingName)}/command-tags' in script
    assert 'config.assistTags = assistTags' in script
    assert 'drawAssistTagCanvas' in script
    assert 'pointerdown' in script
    assert '["CH", "CNTW"].includes(state.selectedSettingPlan?.server)' in script
    assert '["CH", "CNTW", "JP"].includes(state.selectedSettingPlan?.server)' in script
    assert "!supportsExpball" in script
    assert 'id="job-status"' in index
    assert 'id="job-progress"' in index
    assert 'id="pause-job"' in index
    assert 'id="resume-job"' in index
    assert 'id="cancel-job"' in index
    assert 'id="job-events"' in index
    assert 'id="job-result"' in index
    assert "/api/capabilities" in script
    assert "/api/adb/connect-endpoint" in script
    assert "/api/settings" in script
    assert 'refreshSettings: document.querySelector("#refresh-settings")' in script
    assert 'els.refreshSettings.addEventListener("click", () => loadSettings())' in script
    assert "/api/strategies" in script
    assert 'method: "PUT"' in script
    assert 'method: "DELETE"' in script
    assert "JSON.parse" in script
    assert "/plan" in script
    assert "/api/snapshot" in script
    assert "/api/match" in script
    assert "/api/match/debug" in script
    assert "overlay_base64" in script
    assert "/api/tap" in script
    assert "/api/swipe" in script
    assert "/api/jobs" in script
    assert "battle.dry-run" in script
    assert "battle.execute-plan" in script
    assert "battle.run" in script
    assert "max_runs" in script
    assert "prepare:" in script
    assert "execution?.battle" in script
    assert "result.cleared_ap" in script
    assert "/program" in script
    assert "/events/stream" in script
    assert "new EventSource" in script
    assert 'id="rotate-screen-left"' in index
    assert 'id="rotate-screen-right"' in index
    assert 'id="rotate-screen-auto"' in index
    assert 'id="click-to-tap"' in index
    assert 'id="auto-refresh-screen"' in index
    assert "/api/screen/rotation" in script
    assert "rotateScreen" in script
    assert "syncAutoRefreshScreen" in script
    assert 'data-run-option="screenRotation"' in index
    assert 'id="audio-alert-enabled"' in index
    assert 'id="test-audio-alert"' in index
    assert 'id="audio-alert-tone"' in index
    assert 'id="choose-audio-alert"' in index
    assert 'id="audio-alert-file"' in index
    assert "playAudioAlert" in script
    assert "trackJobTransitions" in script
    assert "SCREEN_ROTATION_OPTIONS" in script
    assert 'id="add-turn-condition-start"' in index
    assert 'id="add-turn-condition-end"' in index
    assert 'id="preset-turn-conditions"' in index
    assert 'id="add-turn-condition-preset"' in index
    assert 'id="clear-turn-conditions"' in index
    assert "createPresetTurnConditionsEditor" in script
    assert "/api/ws/events" in script
    assert "/api/ws/screen" in script
    assert "new WebSocket" in script
    assert 'id="debug-step-mode"' in index
    assert "debug_step: true" in script
    assert 'id="setting-filter"' in index
    assert 'id="full-run-clear-ap"' in index
    assert 'id="auto-follow-job-screen"' in index
    assert 'id="job-live-summary"' in index
    assert 'id="toggle-log-panel"' in index
    assert 'data-job-tab="battle"' in index
    assert 'data-job-tab="events"' in index
    assert 'data-job-tab="tools"' in index
    assert "apple: els.fullRunApple.value" in script
    assert "CONSOLE_PREFS_STORAGE_KEY" in script
    assert (STATIC_DIR / "preset-wizard.js").is_file()
    assert 'id="new-setting-wizard"' in index
    assert 'id="preset-editor-mode-switch"' in index
    assert 'id="preset-mode-wizard"' in index
    assert 'id="preset-mode-pro"' in index
    assert 'id="preset-wizard-root"' in index
    assert "createPresetWizard" in script

