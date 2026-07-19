from __future__ import annotations

from typing import Any

from webapp.core.errors import AppError, ErrorCode
from webapp.runtime import JobManager, RunContext
from webapp.services.devices import DeviceService
from webapp.services.recognition import RecognitionService
from webapp.services.script_data import ScriptDataService


BATTLE_DETECT_STAGE_JOB_KIND = "battle.detect-stage"
CERTAIN_STAGE_CONFIDENCE = 0.99


def create_stage_handler(
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognition: RecognitionService,
):
    def handler(context: RunContext | None, payload: dict[str, Any]) -> dict[str, Any]:
        setting_name = payload.get("setting_name")
        if not isinstance(setting_name, str) or not setting_name.strip():
            raise ValueError("setting_name must be a non-empty string.")
        plan = script_data.get_setting_plan(setting_name.strip())
        server = str(plan["server"]).upper()
        screenshot = device_service.snapshot()
        battle_root = f"battle/{server}"
        stage_templates = (
            (
                "completion",
                tuple(
                    f"{battle_root}/{template_name}.png"
                    for template_name in (
                        "run_again",
                        "next",
                        "relationship_up",
                        "friend_apply",
                        "friend_apply_1",
                        "jblevel10",
                        "jbMax",
                        "jbup",
                        "jbup1",
                        "battleFinish",
                        "battleFinish1",
                        "fight_end",
                    )
                )
                + (
                    f"battle/Interlude/{server}/gotoInterlude.png",
                    f"battle/Interlude/{server}/gotoStage.png",
                    f"battle/MainStory/{server}/nextOne.png",
                ),
            ),
            (
                "battle",
                tuple(
                    f"{battle_root}/{template_name}.png"
                    for template_name in (
                        "attack",
                        "phase_1",
                        "phase_2",
                        "phase_3",
                    )
                ),
            ),
            (
                "prepare",
                tuple(
                    f"{battle_root}/{template_name}.png"
                    for template_name in (
                        "apple_close",
                        "apple_decide",
                        "teamDecide",
                        "start_task",
                        "start_battle",
                    )
                )
                + (f"battle/CrawlTower/{server}/zdbc.png",),
            ),
            (
                "assist",
                tuple(
                    f"{battle_root}/{template_name}.png"
                    for template_name in (
                        "listupdatebtn",
                        "assist_exists",
                        "assist",
                        "assist1",
                    )
                ),
            ),
        )
        best_response: dict[str, Any] | None = None
        best_confidence = float("-inf")
        for stage, template_paths in stage_templates:
            for template_path in template_paths:
                try:
                    mask_path = (
                        f"battle/MainStory/{server}/nextOneMask.png"
                        if template_path
                        == f"battle/MainStory/{server}/nextOne.png"
                        else None
                    )
                    result = recognition.match_template(
                        screenshot,
                        template_path,
                        threshold=0.85,
                        scales=(1.0, 0.75, 2 / 3, 0.5),
                        mask_path=mask_path,
                    )
                except AppError as exc:
                    if exc.code == ErrorCode.TEMPLATE_NOT_FOUND:
                        continue
                    raise
                if not result.matched:
                    continue
                confidence = getattr(result, "confidence", None)
                comparable_confidence = (
                    float(confidence)
                    if isinstance(confidence, (int, float))
                    else 1.0
                )
                if comparable_confidence <= best_confidence:
                    continue
                best_confidence = comparable_confidence
                best_response = {
                    "setting_name": setting_name.strip(),
                    "stage": stage,
                    "matched_template": template_path,
                    "confidence": confidence,
                }
                if comparable_confidence >= CERTAIN_STAGE_CONFIDENCE:
                    break
            if best_confidence >= CERTAIN_STAGE_CONFIDENCE:
                break

        if best_response is not None:
            if context is not None:
                context.emit(
                    "battle_stage",
                    "Current battle flow stage was recognized.",
                    data=best_response,
                )
            return best_response

        response = {
            "setting_name": setting_name.strip(),
            "stage": "unknown",
            "matched_template": None,
            "confidence": None,
        }
        if context is not None:
            context.emit(
                "battle_stage",
                "Current battle flow stage was not recognized.",
                level="warning",
                data=response,
            )
        return response

    return handler


def register_stage_job(
    job_manager: JobManager,
    script_data: ScriptDataService,
    device_service: DeviceService,
    recognition: RecognitionService,
) -> None:
    if job_manager.has_kind(BATTLE_DETECT_STAGE_JOB_KIND):
        return
    job_manager.register(
        BATTLE_DETECT_STAGE_JOB_KIND,
        create_stage_handler(script_data, device_service, recognition),
        requires_device=True,
    )
