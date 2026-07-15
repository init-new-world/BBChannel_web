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
    assert 'id="job-status"' in index
    assert 'id="job-progress"' in index
    assert 'id="pause-job"' in index
    assert 'id="resume-job"' in index
    assert 'id="cancel-job"' in index
    assert 'id="job-events"' in index
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
    assert "/events/stream" in script
    assert "new EventSource" in script
