from pathlib import Path


STATIC_DIR = Path("webapp/static")


def test_operator_console_static_files_exist():
    assert (STATIC_DIR / "index.html").is_file()
    assert (STATIC_DIR / "styles.css").is_file()
    assert (STATIC_DIR / "app.js").is_file()


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
    assert 'id="full-run-map-swipes"' in index
    assert 'id="full-run-apple"' in index
    assert 'id="full-run-team-check"' in index
    assert 'id="start-full-run"' in index
    assert 'id="restart-game"' in index
    assert 'id="inspect-chocolate"' in index
    assert 'id="run-chocolate"' in index
    assert 'id="inspect-digdig"' in index
    assert 'id="execute-digdig"' in index
    assert 'id="inspect-lottery"' in index
    assert 'id="run-lottery"' in index
    assert 'id="lottery-pay-slot"' in index
    assert 'id="lottery-star-3"' in index
    assert 'id="lottery-star-4"' in index
    assert 'id="lottery-star-5"' in index
    assert 'id="inspect-expball"' in index
    assert 'id="expball-destination"' in index
    assert 'id="navigate-expball"' in index
    assert 'id="run-expball-summon"' in index
    assert 'id="fp-summon-batches"' in index
    assert 'id="expball-overflow-action"' not in index
    assert 'id="run-expball-storage"' in index
    assert 'id="run-expball-sell"' in index
    assert "team_check_mode: els.fullRunTeamCheck.value" in script
    assert "entry_mode: els.fullRunEntryMode.value" in script
    assert '!["free_quest", "main_story"].includes(' in script
    assert "els.fullRunEntryMode.value" in script
    assert "max_map_swipes: readNumber(els.fullRunMapSwipes)" in script
    assert "max_restarts: readNumber(els.fullRunRestartLimit)" in script
    assert "state.selectedSettingPlan?.run?.game_crash_restart" in script
    assert "result.restart_count" in script
    assert 'job.kind === "event.chocolate.inspect"' in script
    assert 'job.kind === "event.chocolate.run"' in script
    assert 'job.kind === "event.digdig.inspect"' in script
    assert 'job.kind === "event.digdig.execute"' in script
    assert 'job.kind === "event.lottery.inspect"' in script
    assert 'job.kind === "event.lottery.run"' in script
    assert 'job.kind === "event.expball.inspect"' in script
    assert 'job.kind === "event.expball.navigate"' in script
    assert 'job.kind === "event.expball.run"' in script
    assert 'job.kind === "event.expball.summon"' in script
    assert 'job.kind === "event.expball.storage"' in script
    assert 'job.kind === "event.expball.sell"' in script
    assert "result.summons || 0" in script
    assert "result.pieces?.length || 0" in script
    assert 'enqueueJob("battle.restart-game"' in script
    assert 'enqueueJob("event.chocolate.inspect"' in script
    assert 'enqueueJob("event.chocolate.run"' in script
    assert 'enqueueJob("event.digdig.inspect"' in script
    assert 'enqueueJob("event.digdig.execute"' in script
    assert 'enqueueJob("event.lottery.inspect"' in script
    assert 'enqueueJob("event.lottery.run"' in script
    assert "pay_slot: readNumber(els.lotteryPaySlot)" in script
    assert "stars: selectedLotteryStars()" in script
    assert 'enqueueJob("event.expball.inspect"' in script
    assert 'enqueueJob("event.expball.navigate"' in script
    assert "destination: els.expballDestination.value" in script
    assert 'enqueueJob("event.expball.run"' in script
    assert "max_summons: readNumber(els.fpSummonBatches)" in script
    assert 'enqueueJob("event.expball.storage"' in script
    assert 'enqueueJob("event.expball.sell"' in script
    assert "overflowCycles" not in script
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
