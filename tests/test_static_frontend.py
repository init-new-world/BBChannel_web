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
    assert 'id="inspect-expball"' in index
    assert 'id="run-expball-summon"' in index
    assert "team_check_mode: els.fullRunTeamCheck.value" in script
    assert "entry_mode: els.fullRunEntryMode.value" in script
    assert '!["free_quest", "main_story"].includes(' in script
    assert "els.fullRunEntryMode.value" in script
    assert "max_map_swipes: readNumber(els.fullRunMapSwipes)" in script
    assert "max_restarts: readNumber(els.fullRunRestartLimit)" in script
    assert "state.selectedSettingPlan?.run?.game_crash_restart" in script
    assert "result.restart_count" in script
    assert 'enqueueJob("battle.restart-game"' in script
    assert 'enqueueJob("event.chocolate.inspect"' in script
    assert 'enqueueJob("event.chocolate.run"' in script
    assert 'enqueueJob("event.digdig.inspect"' in script
    assert 'enqueueJob("event.expball.inspect"' in script
    assert 'enqueueJob("event.expball.summon"' in script
    assert '["CH", "CNTW"].includes(state.selectedSettingPlan?.server)' in script
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
