from __future__ import annotations

import base64
import binascii
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from webapp.api import create_job_router
from webapp.automation import (
    compile_battle_program,
    register_battle_jobs,
    register_diagnostic_job,
)
from webapp.core.errors import AppError, ErrorCode
from webapp.devices.adb import AdbBackend
from webapp.devices.mumu import MumuBackend
from webapp.devices.coordinates import FrameNormalizer
from webapp.devices.replay import ReplayBackend
from webapp.runtime import JobDatabase, JobManager
from webapp.services.devices import DeviceService
from webapp.services.event_log import EventLog
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService
from webapp.services.script_data import ScriptDataService


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
    config: dict
    overwrite: bool = False


class SaveStrategyRequest(BaseModel):
    entries: list[dict]
    overwrite: bool = False


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
    script_data = ScriptDataService(resources.data_dir)
    owns_job_manager = job_manager is None
    if job_manager is None:
        default_db_path = os.environ.get(
            "BBCHANNEL_RUNTIME_DB",
            str(PROJECT_ROOT / "runtime" / "bbchannel.db"),
        )
        job_manager = JobManager(JobDatabase(runtime_db_path or default_db_path))
    register_diagnostic_job(job_manager, device_service, recognition)
    register_battle_jobs(job_manager, script_data, device_service, recognition)

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

    @app.get("/api/settings/{name}")
    def setting_detail(name: str) -> dict:
        return script_data.get_setting(name)

    @app.get("/api/settings/{name}/plan")
    def setting_plan(name: str) -> dict:
        return script_data.get_setting_plan(name)

    @app.get("/api/settings/{name}/program")
    def setting_program(name: str) -> dict:
        return compile_battle_program(script_data.get_setting_plan(name))

    @app.put("/api/settings/{name}")
    def save_setting(name: str, request: SaveSettingRequest) -> dict:
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
