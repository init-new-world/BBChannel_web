from __future__ import annotations

import base64
import binascii
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictBool, StrictInt, StrictStr, model_validator

from webapp.api import create_job_router
from webapp.automation import (
    compile_battle_program,
    create_assist_handler,
    create_battle_entry_handler,
    create_battle_execute_plan_handler,
    create_completion_handler,
    create_free_quest_entry_handler,
    create_interlude_entry_handler,
    create_main_story_entry_handler,
    create_recovery_handler,
    create_stage_handler,
    register_assist_job,
    register_battle_entry_job,
    register_battle_jobs,
    register_chocolate_capture_banner_job,
    register_chocolate_inspect_job,
    register_chocolate_run_job,
    register_completion_job,
    register_diagnostic_job,
    register_digdig_board_grid_inspect_job,
    register_digdig_execute_job,
    register_digdig_inspect_job,
    register_digdig_run_job,
    register_expball_ce_bomb_grid_inspect_job,
    register_expball_command_code_grid_inspect_job,
    register_expball_enhance_job,
    register_expball_inspect_job,
    register_expball_servant_grid_inspect_job,
    register_expball_servant_level_inspect_job,
    register_expball_servant_target_inspect_job,
    register_expball_storage_grid_inspect_job,
    register_expball_navigate_job,
    register_expball_run_job,
    register_expball_sell_job,
    register_expball_storage_job,
    register_expball_summon_job,
    register_expball_summon_lock_inspect_job,
    register_full_run_job,
    register_free_quest_entry_job,
    register_interlude_entry_job,
    register_main_story_entry_job,
    register_lottery_draw_job,
    register_lottery_giftbox_receive_job,
    register_lottery_giftbox_stacks_inspect_job,
    register_lottery_inspect_job,
    register_lottery_navigate_job,
    register_lottery_run_job,
    register_recovery_job,
    register_stage_job,
)
from webapp.automation.operation_timing import with_script_operation_timing
from webapp.core.errors import AppError, ErrorCode
from webapp.devices.adb import AdbBackend
from webapp.devices.mumu import MumuBackend
from webapp.devices.coordinates import FrameNormalizer
from webapp.devices.replay import ReplayBackend
from webapp.runtime import JobDatabase, JobManager
from webapp.services.cards import CommandCardRecognizer
from webapp.services.chocolate import ChocolateRecognizer
from webapp.services.assist import AssistRecognizer
from webapp.services.assist_tags import AssistTagService
from webapp.services.command_tags import CommandTagService
from webapp.services.devices import DeviceService
from webapp.services.digdig import DigdigRecognizer
from webapp.services.drop_templates import DropTemplateService
from webapp.services.event_log import EventLog
from webapp.services.expball import ExpBallRecognizer
from webapp.services.equip_templates import EquipTemplateService
from webapp.services.master_portraits import MasterPortraitService
from webapp.services.lottery import LotteryRecognizer
from webapp.services.materials import MaterialDropService
from webapp.services.notebook import NotebookService
from webapp.services.np_charge import NpChargeRecognizer
from webapp.services.recognition import RecognitionService
from webapp.services.quest import QuestRecognizer
from webapp.services.resources import ResourceService
from webapp.services.script_data import ScriptDataService
from webapp.services.team import TeamRecognizer


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConnectRequest(BaseModel):
    backend: str
    device_id: str


class ConnectChannelsRequest(BaseModel):
    capture_backend: str
    capture_device_id: str
    control_backend: str
    control_device_id: str


class AdbEndpointRequest(BaseModel):
    endpoint: str = Field(min_length=1)


class TapRequest(BaseModel):
    x: int
    y: int


class SwipeRequest(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    duration_ms: int = Field(default=300, ge=0)


class MatchRequest(BaseModel):
    screenshot_base64: str
    template_path: str
    threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    roi: list[int] | None = Field(default=None, min_length=4, max_length=4)
    scales: list[float] | None = Field(default=None, min_length=1, max_length=20)


class MatchCandidateRequest(BaseModel):
    template_path: str
    threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    roi: list[int] | None = Field(default=None, min_length=4, max_length=4)
    scales: list[float] | None = Field(default=None, min_length=1, max_length=20)


class BatchMatchRequest(BaseModel):
    screenshot_base64: str
    candidates: list[MatchCandidateRequest] = Field(min_length=1, max_length=100)


class SaveSettingRequest(BaseModel):
    config: dict | None = None
    source: StrictStr | None = Field(default=None, min_length=1)
    overwrite: bool = False

    @model_validator(mode="after")
    def require_one_payload(self) -> SaveSettingRequest:
        if (self.config is None) == (self.source is None):
            raise ValueError("Supply exactly one of config or source.")
        return self


class CalculateTurnReplaceRequest(BaseModel):
    config: dict | None = None
    source: StrictStr | None = Field(default=None, min_length=1)
    target_round: StrictInt | None = Field(default=None, ge=1)
    target_turn: StrictInt | None = Field(default=None, ge=0)
    death_slots: list[StrictInt] | dict[str, list[StrictInt]] | None = None
    will_nums: list[StrictInt] | dict[str, StrictInt] | None = None

    @model_validator(mode="after")
    def require_one_payload(self) -> CalculateTurnReplaceRequest:
        if (self.config is None) == (self.source is None):
            raise ValueError("Supply exactly one of config or source.")
        if (self.target_round is None) != (self.target_turn is None):
            raise ValueError("Supply both target_round and target_turn together.")
        return self


class PreviewPreRunReportRequest(BaseModel):
    config: dict | None = None
    source: StrictStr | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def require_one_payload(self) -> PreviewPreRunReportRequest:
        if (self.config is None) == (self.source is None):
            raise ValueError("Supply exactly one of config or source.")
        return self


class ScreenRotationRequest(BaseModel):
    rotation: StrictInt | None = None
    steps: StrictInt | None = None

    @model_validator(mode="after")
    def validate_rotation_choice(self) -> ScreenRotationRequest:
        has_rotation = "rotation" in self.model_fields_set
        has_steps = "steps" in self.model_fields_set and self.steps is not None
        if has_steps and has_rotation:
            raise ValueError("Supply either rotation or steps, not both.")
        if not has_steps and not has_rotation:
            raise ValueError("Supply rotation or steps.")
        if has_rotation and self.rotation is not None and self.rotation not in {0, 90, 180, 270}:
            raise ValueError("rotation must be null, 0, 90, 180, or 270.")
        return self


class SaveStrategyRequest(BaseModel):
    entries: list[dict] | None = None
    source: StrictStr | None = Field(default=None, min_length=1)
    overwrite: bool = False

    @model_validator(mode="after")
    def require_one_payload(self) -> SaveStrategyRequest:
        if (self.entries is None) == (self.source is None):
            raise ValueError("Supply exactly one of entries or source.")
        return self


class BuildEquipTemplateRequest(BaseModel):
    full_image_base64: str | None = None
    non_full_image_base64: str | None = None
    overwrite: bool = False


class MoveEquipTemplateRequest(BaseModel):
    overwrite: bool = False


class CaptureEquipCandidatesRequest(BaseModel):
    setting_name: str = Field(min_length=1)
    screenshot_base64: str | None = None
    threshold: float = Field(default=0.85, ge=0.0, le=1.0)


class TestEquipTemplateRequest(BaseModel):
    location: str = "active"
    screenshot_base64: str | None = None
    threshold: float = Field(default=0.9, ge=0.0, le=1.0)


class SaveNotebookRequest(BaseModel):
    content: str = Field(max_length=1_000_000)


class BuildAssistTagRequest(BaseModel):
    screenshot_base64: str | None = None
    anchor: list[int] = Field(min_length=2, max_length=2)
    bounds: list[int] = Field(min_length=4, max_length=4)
    label: str = Field(min_length=1, max_length=64)
    threshold: float = Field(default=0.8, gt=0.0, lt=1.0)
    overwrite: bool = False


class ImportAssistTagRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    image_base64: str
    overwrite: bool = False


class CaptureCommandTagsRequest(BaseModel):
    screenshot_base64: str | None = None


class BuildCommandTagRequest(CaptureCommandTagsRequest):
    slot: StrictInt = Field(ge=1, le=5)
    bounds: list[StrictInt] = Field(min_length=4, max_length=4)
    label: str = Field(min_length=1, max_length=64)
    threshold: float = Field(default=0.8, gt=0.0, lt=1.0)
    overwrite: bool = False


class BindCommandTagRequest(BaseModel):
    tag_name: str = Field(min_length=1, max_length=255)
    bound: StrictBool


def create_app(
    assets_dir: Path | str | None = None,
    data_dir: Path | str | None = None,
    device_service: DeviceService | None = None,
    event_log: EventLog | None = None,
    job_manager: JobManager | None = None,
    runtime_db_path: Path | str | None = None,
) -> FastAPI:
    event_log = event_log or EventLog()
    resources = ResourceService(
        assets_dir or PROJECT_ROOT / "assets",
        data_dir or PROJECT_ROOT / "data",
    )
    drop_templates = DropTemplateService(resources)
    device_service = device_service or DeviceService(
        [
            MumuBackend(),
            AdbBackend(),
            ReplayBackend(PROJECT_ROOT / "runtime" / "replays"),
        ],
        event_log,
        frame_normalizer=FrameNormalizer(),
    )
    recognition = RecognitionService(resources)
    assist_recognizer = AssistRecognizer(resources, recognition)
    assist_tags = AssistTagService(resources)
    command_tags = CommandTagService(resources)
    card_recognizer = CommandCardRecognizer(resources, recognition)
    np_recognizer = NpChargeRecognizer(recognition)
    team_recognizer = TeamRecognizer(resources, recognition)
    quest_recognizer = QuestRecognizer(recognition)
    chocolate_recognizer = ChocolateRecognizer(resources, recognition)
    digdig_recognizer = DigdigRecognizer(resources, recognition)
    expball_recognizer = ExpBallRecognizer(resources, recognition)
    equip_templates = EquipTemplateService(resources, recognition)
    lottery_recognizer = LotteryRecognizer(resources, recognition)
    material_drops = MaterialDropService(resources.data_dir)
    notebook = NotebookService(resources.data_dir)
    script_data = ScriptDataService(resources.data_dir, resources=resources)
    master_portraits = MasterPortraitService(resources, script_data)
    owns_job_manager = job_manager is None
    if job_manager is None:
        default_db_path = os.environ.get(
            "BBCHANNEL_RUNTIME_DB",
            str(PROJECT_ROOT / "runtime" / "bbchannel.db"),
        )
        job_manager = JobManager(JobDatabase(runtime_db_path or default_db_path))
    register_diagnostic_job(job_manager, device_service, recognition)
    register_chocolate_inspect_job(
        job_manager,
        script_data,
        device_service,
        chocolate_recognizer,
    )
    register_chocolate_capture_banner_job(
        job_manager,
        script_data,
        device_service,
        chocolate_recognizer,
    )
    register_chocolate_run_job(
        job_manager,
        script_data,
        device_service,
        chocolate_recognizer,
    )
    register_digdig_inspect_job(
        job_manager,
        script_data,
        device_service,
        digdig_recognizer,
    )
    register_digdig_board_grid_inspect_job(
        job_manager,
        script_data,
        device_service,
        digdig_recognizer,
    )
    register_digdig_execute_job(
        job_manager,
        script_data,
        device_service,
        digdig_recognizer,
    )
    register_digdig_run_job(
        job_manager,
        script_data,
        device_service,
        digdig_recognizer,
    )
    register_expball_inspect_job(
        job_manager,
        script_data,
        device_service,
        expball_recognizer,
    )
    register_expball_storage_grid_inspect_job(
        job_manager,
        script_data,
        device_service,
        expball_recognizer,
    )
    register_expball_servant_grid_inspect_job(
        job_manager,
        script_data,
        device_service,
        expball_recognizer,
    )
    register_expball_command_code_grid_inspect_job(
        job_manager,
        script_data,
        device_service,
        expball_recognizer,
    )
    register_expball_ce_bomb_grid_inspect_job(
        job_manager,
        script_data,
        device_service,
        expball_recognizer,
    )
    register_expball_servant_level_inspect_job(
        job_manager,
        script_data,
        device_service,
        expball_recognizer,
    )
    register_expball_servant_target_inspect_job(
        job_manager,
        script_data,
        device_service,
        expball_recognizer,
    )
    register_expball_summon_lock_inspect_job(
        job_manager,
        script_data,
        device_service,
        expball_recognizer,
    )
    register_expball_navigate_job(
        job_manager,
        script_data,
        device_service,
        expball_recognizer,
    )
    register_expball_run_job(
        job_manager,
        script_data,
        device_service,
        expball_recognizer,
    )
    register_expball_sell_job(
        job_manager,
        script_data,
        device_service,
        expball_recognizer,
    )
    register_expball_storage_job(
        job_manager,
        script_data,
        device_service,
        expball_recognizer,
    )
    register_expball_summon_job(
        job_manager,
        script_data,
        device_service,
        expball_recognizer,
    )
    register_expball_enhance_job(
        job_manager,
        script_data,
        device_service,
        expball_recognizer,
    )
    register_lottery_inspect_job(
        job_manager,
        script_data,
        device_service,
        lottery_recognizer,
    )
    register_lottery_giftbox_stacks_inspect_job(
        job_manager,
        script_data,
        device_service,
        lottery_recognizer,
    )
    register_lottery_draw_job(
        job_manager,
        script_data,
        device_service,
        lottery_recognizer,
    )
    register_lottery_giftbox_receive_job(
        job_manager,
        script_data,
        device_service,
        lottery_recognizer,
    )
    register_lottery_navigate_job(
        job_manager,
        script_data,
        device_service,
        lottery_recognizer,
    )
    register_lottery_run_job(
        job_manager,
        script_data,
        device_service,
        lottery_recognizer,
        expball_recognizer=expball_recognizer,
    )
    register_assist_job(
        job_manager,
        script_data,
        device_service,
        assist_recognizer,
    )
    register_battle_entry_job(
        job_manager,
        script_data,
        device_service,
        recognition,
        team_recognizer,
    )
    register_completion_job(
        job_manager,
        script_data,
        device_service,
        recognition,
        resources,
    )
    register_battle_jobs(
        job_manager,
        script_data,
        device_service,
        recognition,
        card_recognizer,
        np_recognizer,
    )
    stage_handler = create_stage_handler(
        script_data,
        device_service,
        recognition,
    )
    recovery_handler = create_recovery_handler(
        script_data,
        device_service,
        stage_handler,
        recognition,
    )
    register_stage_job(
        job_manager,
        script_data,
        device_service,
        recognition,
    )
    register_free_quest_entry_job(
        job_manager,
        script_data,
        device_service,
        quest_recognizer,
        stage_handler,
    )
    register_main_story_entry_job(
        job_manager,
        script_data,
        device_service,
        quest_recognizer,
        stage_handler,
    )
    register_interlude_entry_job(
        job_manager,
        script_data,
        device_service,
        quest_recognizer,
        stage_handler,
    )
    register_recovery_job(
        job_manager,
        script_data,
        device_service,
        stage_handler,
        recognition,
    )
    register_full_run_job(
        job_manager,
        script_data,
        create_assist_handler(script_data, device_service, assist_recognizer),
        create_battle_entry_handler(
            script_data,
            device_service,
            recognition,
            team_recognizer,
        ),
        create_battle_execute_plan_handler(
            script_data,
            device_service,
            recognition,
            card_recognizer,
            np_recognizer,
        ),
        create_completion_handler(
            script_data,
            device_service,
            recognition,
            resources,
        ),
        detect_stage=stage_handler,
        recover_game=recovery_handler,
        enter_free_quest=create_free_quest_entry_handler(
            script_data,
            device_service,
            quest_recognizer,
            stage_handler,
        ),
        enter_main_story=create_main_story_entry_handler(
            script_data,
            device_service,
            quest_recognizer,
            stage_handler,
        ),
        enter_interlude=create_interlude_entry_handler(
            script_data,
            device_service,
            quest_recognizer,
            stage_handler,
        ),
        screen_is_stuck=device_service.screen_is_stuck,
        apply_screen_rotation=device_service.set_screen_rotation,
    )

    for kind in job_manager.registered_kinds():
        if job_manager.requires_device(kind) and not kind.startswith("diagnostic."):
            job_manager.wrap_handler(kind, lambda handler: with_script_operation_timing(handler, script_data, device_service))

    def active_device_key() -> str | None:
        return device_service.session_key()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            try:
                if owns_job_manager:
                    job_manager.close()
            finally:
                device_service.close()

    app = FastAPI(title="BBchannel Web PoC", lifespan=lifespan)

    app.state.event_log = event_log
    app.state.resources = resources
    app.state.device_service = device_service
    app.state.recognition = recognition
    app.state.assist_recognizer = assist_recognizer
    app.state.assist_tags = assist_tags
    app.state.command_tags = command_tags
    app.state.card_recognizer = card_recognizer
    app.state.np_recognizer = np_recognizer
    app.state.quest_recognizer = quest_recognizer
    app.state.chocolate_recognizer = chocolate_recognizer
    app.state.digdig_recognizer = digdig_recognizer
    app.state.lottery_recognizer = lottery_recognizer
    app.state.expball_recognizer = expball_recognizer
    app.state.equip_templates = equip_templates
    app.state.material_drops = material_drops
    app.state.notebook = notebook
    app.state.script_data = script_data
    app.state.job_manager = job_manager

    @app.exception_handler(AppError)
    async def app_error_handler(_request, exc: AppError) -> JSONResponse:
        event_log.error("api_error", exc.message, {"code": exc.code.value, **exc.details})
        return JSONResponse(status_code=_status_code_for(exc.code), content=exc.to_response())

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/capabilities")
    def capabilities() -> dict[str, list[dict]]:
        return {"capabilities": [capability.to_dict() for capability in device_service.capabilities()]}

    @app.get("/api/devices")
    def devices() -> dict[str, list[dict]]:
        return {"devices": [device.to_dict() for device in device_service.list_devices()]}

    @app.get("/api/device-diagnostics")
    def device_diagnostics() -> dict[str, list[dict]]:
        return {"diagnostics": device_service.diagnostics()}

    @app.get("/api/state")
    def state() -> dict:
        return device_service.state().to_dict()

    @app.get("/api/screen/geometry")
    def screen_geometry() -> dict:
        return {"geometry": device_service.screen_geometry()}

    @app.get("/api/screen/rotation")
    def screen_rotation() -> dict:
        return device_service.screen_rotation()

    @app.post("/api/screen/rotation")
    def set_screen_rotation(request: ScreenRotationRequest) -> dict:
        if request.steps is not None:
            return device_service.rotate_screen(request.steps)
        return device_service.set_screen_rotation(request.rotation)

    @app.post("/api/connect")
    def connect(request: ConnectRequest) -> dict:
        return device_service.connect(request.backend, request.device_id).to_dict()

    @app.post("/api/connect/channels")
    def connect_channels(request: ConnectChannelsRequest) -> dict:
        return device_service.connect_channels(
            capture_backend=request.capture_backend,
            capture_device_id=request.capture_device_id,
            control_backend=request.control_backend,
            control_device_id=request.control_device_id,
        ).to_dict()

    @app.post("/api/adb/connect-endpoint")
    def connect_adb_endpoint(request: AdbEndpointRequest) -> dict:
        return {"device": device_service.connect_adb_endpoint(request.endpoint).to_dict()}

    @app.post("/api/disconnect")
    def disconnect() -> dict:
        return device_service.disconnect().to_dict()

    @app.get("/api/snapshot")
    def snapshot() -> Response:
        return Response(content=device_service.snapshot(), media_type="image/png")

    @app.post("/api/tap")
    def tap(request: TapRequest) -> dict:
        return device_service.tap(request.x, request.y).to_dict()

    @app.post("/api/swipe")
    def swipe(request: SwipeRequest) -> dict:
        return device_service.swipe(
            request.x1,
            request.y1,
            request.x2,
            request.y2,
            request.duration_ms,
        ).to_dict()

    @app.get("/api/templates")
    def templates() -> dict[str, list[str]]:
        return {"templates": resources.list_templates()}

    @app.get("/api/drop-templates")
    def drop_template_catalog(configured: str | None = None) -> dict[str, object]:
        return drop_templates.catalog(configured)

    @app.get("/api/drop-templates/image")
    def drop_template_image(path: str) -> Response:
        return Response(content=drop_templates.read_image(path), media_type="image/png")

    @app.get("/api/material-drops/catalog")
    def material_drop_catalog() -> dict[str, object]:
        return material_drops.catalog()

    @app.get("/api/material-drops")
    def material_drop_query(server: str, quality: str, material: str) -> dict[str, object]:
        return material_drops.query(server, quality, material)

    @app.get("/api/notebook")
    def read_notebook() -> dict[str, object]:
        return notebook.read()

    @app.put("/api/notebook")
    def save_notebook(request: SaveNotebookRequest) -> dict[str, object]:
        return notebook.save(request.content)

    @app.get("/api/assist-tags")
    def assist_tag_inventory() -> dict[str, list[dict[str, object]]]:
        return {"tags": assist_tags.inventory()}

    @app.post("/api/assist-tags/candidates")
    def capture_assist_tag_candidates(request: CaptureEquipCandidatesRequest) -> dict:
        screenshot = _decode_optional_image(request.screenshot_base64) or device_service.snapshot()
        plan = script_data.get_setting_plan(request.setting_name)
        assist = plan.get("assist") or {}
        capture_assist = {
            "mode": "仅从者",
            "servant_name": assist.get("servant_name"),
            "servant_canonical_name": assist.get("servant_canonical_name"),
            "servant_sn": assist.get("servant_sn"),
        }
        if not capture_assist["servant_canonical_name"]:
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                "The selected script does not have a recognized assist servant.",
                {"setting_name": request.setting_name},
            )
        recognition_result = assist_recognizer.recognize(
            screenshot,
            capture_assist,
            server=str(plan.get("server") or "CH"),
            threshold=request.threshold,
        )
        candidates = [
            {
                "anchor": candidate["anchor"],
                "bounds": candidate["bounds"],
                "confidence": candidate["confidence"],
            }
            for candidate in recognition_result["candidates"]
        ]
        return {
            "servant_name": capture_assist["servant_name"],
            "servant_canonical_name": capture_assist["servant_canonical_name"],
            "candidate_count": len(candidates),
            "candidates": candidates,
            "screenshot_base64": base64.b64encode(screenshot).decode("ascii"),
        }

    @app.post("/api/assist-tags")
    def build_assist_tag(request: BuildAssistTagRequest) -> dict[str, object]:
        screenshot = _decode_optional_image(request.screenshot_base64) or device_service.snapshot()
        return assist_tags.build(
            label=request.label,
            screenshot=screenshot,
            anchor=request.anchor,
            bounds=request.bounds,
            threshold=request.threshold,
            overwrite=request.overwrite,
        )

    @app.post("/api/assist-tags/import")
    def import_assist_tag(request: ImportAssistTagRequest) -> dict[str, object]:
        return assist_tags.import_image(
            request.name,
            _decode_optional_image(request.image_base64) or b"",
            overwrite=request.overwrite,
        )

    @app.get("/api/assist-tags/{name}/image")
    def assist_tag_image(name: str) -> Response:
        return Response(
            content=assist_tags.read_image(name),
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @app.delete("/api/assist-tags/{name}")
    def delete_assist_tag(name: str) -> dict[str, object]:
        with script_data.settings_transaction():
            references = script_data.find_assist_tag_references(name)
            if references:
                raise AppError(
                    ErrorCode.DATA_FILE_CONFLICT,
                    f"Assist tag is still referenced by scripts: {', '.join(references)}",
                    {"name": name, "settings": references},
                )
            return assist_tags.delete(name)

    @app.get("/api/command-tags")
    def command_tag_inventory() -> dict[str, list[dict[str, object]]]:
        return {"tags": command_tags.inventory()}

    @app.post("/api/command-tags/candidates")
    def capture_command_tags(request: CaptureCommandTagsRequest) -> dict[str, object]:
        screenshot = _decode_optional_image(request.screenshot_base64) or device_service.snapshot()
        return command_tags.capture(screenshot)

    @app.post("/api/command-tags")
    def build_command_tag(request: BuildCommandTagRequest) -> dict[str, object]:
        screenshot = _decode_optional_image(request.screenshot_base64) or device_service.snapshot()
        return command_tags.build_card(
            label=request.label, screenshot=screenshot, slot=request.slot,
            bounds=request.bounds, threshold=request.threshold, overwrite=request.overwrite,
        )

    @app.post("/api/command-tags/import")
    def import_command_tag(request: ImportAssistTagRequest) -> dict[str, object]:
        return command_tags.import_image(
            request.name, _decode_optional_image(request.image_base64) or b"",
            overwrite=request.overwrite,
        )

    @app.get("/api/command-tags/{name}/image")
    def command_tag_image(name: str) -> Response:
        return Response(
            content=command_tags.read_image(name), media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @app.delete("/api/command-tags/{name}")
    def delete_command_tag(name: str) -> dict[str, object]:
        with script_data.settings_transaction():
            references = script_data.find_command_tag_references(name)
            if references:
                raise AppError(
                    ErrorCode.DATA_FILE_CONFLICT,
                    f"Command tag is still referenced by scripts: {', '.join(references)}",
                    {"name": name, "settings": references},
                )
            return command_tags.delete(name)

    @app.put("/api/settings/{name}/command-tags")
    def bind_command_tag(name: str, request: BindCommandTagRequest) -> dict[str, object]:
        with script_data.settings_transaction():
            if request.bound:
                command_tags.read_image(request.tag_name)
            return script_data.bind_command_tag(
                name, tag_name=request.tag_name,
                template_path=f"battle/customCommandCard/{request.tag_name}", bound=request.bound,
            )

    @app.get("/api/equip-templates")
    def equip_template_inventory() -> dict[str, list[dict[str, object]]]:
        return {"templates": equip_templates.inventory()}

    @app.get("/api/equip-templates/{name}/image")
    def equip_template_image(name: str, location: str = Query(default="active")) -> Response:
        return Response(
            content=equip_templates.read_image(name, location=location),
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/equip-templates/candidates")
    def capture_equip_template_candidates(request: CaptureEquipCandidatesRequest) -> dict:
        screenshot = _decode_optional_image(request.screenshot_base64) or device_service.snapshot()
        plan = script_data.get_setting_plan(request.setting_name)
        assist = plan.get("assist") or {}
        capture_assist = {
            "mode": "仅从者",
            "servant_name": assist.get("servant_name"),
            "servant_canonical_name": assist.get("servant_canonical_name"),
            "servant_sn": assist.get("servant_sn"),
        }
        if not capture_assist["servant_canonical_name"]:
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                "The selected script does not have a recognized assist servant.",
                {"setting_name": request.setting_name},
            )
        recognition_result = assist_recognizer.recognize(
            screenshot,
            capture_assist,
            server=str(plan.get("server") or "CH"),
            threshold=request.threshold,
        )
        servant_candidates = recognition_result["candidates"]
        candidates = equip_templates.extract_candidates(
            screenshot,
            [candidate["anchor"] for candidate in servant_candidates],
        )
        return {
            "servant_name": capture_assist["servant_name"],
            "servant_canonical_name": capture_assist["servant_canonical_name"],
            "servant_match_count": len(servant_candidates),
            "candidate_count": len(candidates),
            "candidates": candidates,
        }

    @app.post("/api/equip-templates/{name}/test")
    def test_equip_template(name: str, request: TestEquipTemplateRequest) -> dict[str, object]:
        screenshot = _decode_optional_image(request.screenshot_base64) or device_service.snapshot()
        return equip_templates.test_template(
            name,
            location=request.location,
            screenshot=screenshot,
            threshold=request.threshold,
        )

    @app.post("/api/equip-templates/{name}")
    def build_equip_template(name: str, request: BuildEquipTemplateRequest) -> dict[str, object]:
        return equip_templates.build(
            name,
            full_image=_decode_optional_image(request.full_image_base64),
            non_full_image=_decode_optional_image(request.non_full_image_base64),
            overwrite=request.overwrite,
        )

    @app.post("/api/equip-templates/{name}/activate")
    def activate_equip_template(name: str, request: MoveEquipTemplateRequest) -> dict[str, object]:
        return equip_templates.activate(name, overwrite=request.overwrite)

    @app.post("/api/equip-templates/{name}/archive")
    def archive_equip_template(name: str, request: MoveEquipTemplateRequest) -> dict[str, object]:
        return equip_templates.archive(name, overwrite=request.overwrite)

    @app.get("/api/template-index")
    def template_index(
        prefix: str | None = None,
        query: str | None = None,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict:
        return resources.template_index(
            prefix=prefix,
            query=query,
            offset=offset,
            limit=limit,
        )

    @app.post("/api/template-index/refresh")
    def refresh_template_index() -> dict[str, int]:
        return {"total": resources.refresh_template_index()}

    @app.get("/api/template-metadata/{template_path:path}")
    def template_metadata(template_path: str) -> dict:
        return resources.template_metadata(template_path)

    @app.get("/api/settings")
    def settings() -> dict[str, list[dict[str, str]]]:
        return {"settings": script_data.list_settings()}

    @app.post("/api/settings/calculate-turn-replace")
    def calculate_turn_replace(request: CalculateTurnReplaceRequest) -> dict:
        return script_data.calculate_setting_turn_replacements(
            config=request.config,
            source=request.source,
            target_round=request.target_round,
            target_turn=request.target_turn,
            death_slots=request.death_slots,
            will_nums=request.will_nums,
        )

    @app.post("/api/settings/pre-run-report")
    def preview_pre_run_report(request: PreviewPreRunReportRequest) -> dict:
        return script_data.preview_pre_run_report(
            config=request.config,
            source=request.source,
        )

    @app.get("/api/settings/{name}")
    def setting_detail(name: str) -> dict:
        return script_data.get_setting(name)

    @app.get("/api/settings/{name}/pre-run-report")
    def setting_pre_run_report(name: str) -> dict:
        return script_data.get_setting_pre_run_report(name)

    @app.get("/api/settings/{name}/plan")
    def setting_plan(name: str) -> dict:
        return script_data.get_setting_plan(name)

    @app.get("/api/settings/{name}/program")
    def setting_program(name: str) -> dict:
        return compile_battle_program(script_data.get_setting_plan(name))

    @app.put("/api/settings/{name}")
    def save_setting(name: str, request: SaveSettingRequest) -> dict:
        if request.source is not None:
            return script_data.save_setting_source(name, request.source, overwrite=request.overwrite)
        return script_data.save_setting(
            name,
            request.config,
            overwrite=request.overwrite,
        )

    @app.delete("/api/settings/{name}")
    def delete_setting(name: str) -> dict:
        return script_data.delete_setting(name)

    @app.get("/api/strategies")
    def strategies() -> dict[str, list[dict[str, str]]]:
        return {"strategies": script_data.list_strategies()}

    @app.get("/api/strategies/{name}")
    def strategy_detail(name: str) -> dict:
        return script_data.get_strategy(name)

    @app.put("/api/strategies/{name}")
    def save_strategy(name: str, request: SaveStrategyRequest) -> dict:
        if request.source is not None:
            return script_data.save_strategy_source(name, request.source, overwrite=request.overwrite)
        return script_data.save_strategy(
            name,
            request.entries,
            overwrite=request.overwrite,
        )

    @app.delete("/api/strategies/{name}")
    def delete_strategy(name: str) -> dict:
        return script_data.delete_strategy(name)

    @app.get("/api/servants")
    def servants(server: str = "CH") -> dict:
        return script_data.list_servants(server)

    @app.get("/api/masters")
    def masters() -> dict:
        return script_data.list_masters()

    @app.get("/api/masters/image")
    def master_portrait(equip: str, sex: int = Query(default=0, ge=0, le=1)) -> Response:
        return Response(content=master_portraits.read_image(equip, sex), media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/api/match")
    def match_template(request: MatchRequest) -> dict:
        resources.resolve_template(request.template_path)
        return recognition.match_template(
            _decode_base64(request.screenshot_base64),
            request.template_path,
            request.threshold,
            roi=request.roi,
            scales=request.scales,
        ).to_dict()

    @app.post("/api/match/batch")
    def match_templates(request: BatchMatchRequest) -> dict[str, list[dict]]:
        candidates = [candidate.model_dump() for candidate in request.candidates]
        for candidate in candidates:
            resources.resolve_template(str(candidate["template_path"]))
        return {
            "matches": [
                result.to_dict()
                for result in recognition.match_templates(
                    _decode_base64(request.screenshot_base64),
                    candidates,
                )
            ]
        }

    @app.post("/api/match/debug")
    def match_template_debug(request: MatchRequest) -> dict:
        resources.resolve_template(request.template_path)
        result, overlay = recognition.match_template_debug(
            _decode_base64(request.screenshot_base64),
            request.template_path,
            request.threshold,
            roi=request.roi,
            scales=request.scales,
        )
        return {
            "result": result.to_dict(),
            "overlay_base64": base64.b64encode(overlay).decode("ascii"),
        }

    @app.get("/api/events")
    def events(limit: int | None = None) -> dict[str, list[dict]]:
        return {"events": event_log.recent(limit)}

    app.include_router(create_job_router(job_manager, active_device_key))

    static_dir = Path(__file__).with_name("static")
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app


def _decode_base64(value: str) -> bytes:
    if "," in value and value.lstrip().startswith("data:"):
        value = value.split(",", 1)[1]
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AppError(ErrorCode.MATCH_FAILED, "Screenshot payload is not valid base64.") from exc


def _decode_optional_image(value: str | None) -> bytes | None:
    if value is None:
        return None
    if "," in value and value.lstrip().startswith("data:"):
        value = value.split(",", 1)[1]
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            "Equip image payload is not valid base64.",
        ) from exc


def _status_code_for(code: ErrorCode) -> int:
    if code in {ErrorCode.TEMPLATE_NOT_FOUND, ErrorCode.DATA_FILE_NOT_FOUND}:
        return 404
    if code == ErrorCode.DATA_FILE_INVALID:
        return 400
    if code == ErrorCode.DATA_FILE_CONFLICT:
        return 409
    if code == ErrorCode.OPENCV_UNAVAILABLE:
        return 503
    if code in {
        ErrorCode.ADB_TIMEOUT,
        ErrorCode.ADB_COMMAND_FAILED,
        ErrorCode.SNAPSHOT_FAILED,
        ErrorCode.TAP_FAILED,
        ErrorCode.SWIPE_FAILED,
        ErrorCode.MATCH_FAILED,
    }:
        return 500
    return 400
