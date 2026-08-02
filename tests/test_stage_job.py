from pathlib import Path

import pytest

from webapp.automation.stage import BATTLE_DETECT_STAGE_JOB_KIND, create_stage_handler
from webapp.runtime import JobDatabase, JobManager, JobStatus


class _ScriptData:
    def get_setting_plan(self, _name):
        return {"server": "CH"}


class _Device:
    def snapshot(self):
        return b"screen"


class _Match:
    def __init__(self, matched, confidence=1.0):
        self.matched = matched
        self.confidence = confidence


class _Recognition:
    def __init__(self, matched_name):
        self.matched_name = matched_name

    def match_template(self, _screen, template_path, **_options):
        return _Match(template_path.endswith(f"/{self.matched_name}.png"))


@pytest.mark.parametrize(
    ("template", "stage"),
    [
        ("run_again", "completion"),
        ("friend_apply", "completion"),
        ("friend_apply_1", "completion"),
        ("jblevel10", "completion"),
        ("jbMax", "completion"),
        ("jbup", "completion"),
        ("jbup1", "completion"),
        ("attack", "battle"),
        ("teamDecide", "prepare"),
        ("listupdatebtn", "assist"),
    ],
)
def test_stage_handler_recognizes_current_battle_flow_page(template: str, stage: str):
    handler = create_stage_handler(
        _ScriptData(),
        _Device(),
        _Recognition(template),
    )

    result = handler(None, {"setting_name": "demo"})

    assert result["stage"] == stage
    assert result["matched_template"].endswith(f"/{template}.png")


def test_stage_handler_prefers_stronger_assist_match_over_completion_false_positive():
    class ConflictingRecognition:
        def match_template(self, _screen, template_path, **_options):
            confidence = {
                "battle/CH/battleFinish.png": 0.99,
                "battle/CH/listupdatebtn.png": 0.997,
            }.get(template_path, 0.2)
            return _Match(confidence >= 0.85, confidence)

    handler = create_stage_handler(
        _ScriptData(),
        _Device(),
        ConflictingRecognition(),
    )

    result = handler(None, {"setting_name": "demo"})

    assert result["stage"] == "assist"
    assert result["matched_template"] == "battle/CH/listupdatebtn.png"
    assert result["confidence"] == pytest.approx(0.997)


def test_detect_stage_job_is_device_scoped(tmp_path: Path):
    handler = create_stage_handler(
        _ScriptData(),
        _Device(),
        _Recognition("attack"),
    )
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        manager.register(BATTLE_DETECT_STAGE_JOB_KIND, handler, requires_device=True)
        job = manager.start(
            BATTLE_DETECT_STAGE_JOB_KIND,
            {"setting_name": "demo"},
            device_key="replay:demo",
        )
        result = manager.wait(job.job_id, timeout=2)

    assert result.status == JobStatus.SUCCEEDED
    assert result.result["stage"] == "battle"


@pytest.mark.parametrize("template", ["gotoInterlude", "gotoStage"])
def test_stage_handler_recognizes_post_battle_story_navigation(template: str):
    expected_path = f"battle/Interlude/CH/{template}.png"

    class InterludeRecognition:
        def match_template(self, _screen, template_path, **_options):
            return _Match(template_path == expected_path)

    handler = create_stage_handler(
        _ScriptData(),
        _Device(),
        InterludeRecognition(),
    )

    result = handler(None, {"setting_name": "demo"})

    assert result["stage"] == "completion"
    assert result["matched_template"] == expected_path


def test_stage_handler_recognizes_crawl_tower_auto_formation():
    expected_path = "battle/CrawlTower/CH/zdbc.png"

    class CrawlTowerRecognition:
        def match_template(self, _screen, template_path, **_options):
            return _Match(template_path == expected_path)

    handler = create_stage_handler(
        _ScriptData(),
        _Device(),
        CrawlTowerRecognition(),
    )

    result = handler(None, {"setting_name": "demo"})

    assert result["stage"] == "prepare"
    assert result["matched_template"] == expected_path


def test_stage_handler_recognizes_main_story_next_button():
    expected_path = "battle/MainStory/CH/nextOne.png"
    calls = []

    class MainStoryRecognition:
        def match_template(self, _screen, template_path, **options):
            calls.append((template_path, options))
            return _Match(template_path == expected_path)

    handler = create_stage_handler(
        _ScriptData(),
        _Device(),
        MainStoryRecognition(),
    )

    result = handler(None, {"setting_name": "demo"})

    assert result["stage"] == "completion"
    assert result["matched_template"] == expected_path
    assert dict(calls)[expected_path]["mask_path"] == (
        "battle/MainStory/CH/nextOneMask.png"
    )
