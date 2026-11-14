from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from functools import wraps
from io import BytesIO
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageDraw

from webapp.core.models import MatchResult
from webapp.runtime.jobs import JobHandler, JobManager
from webapp.runtime.models import JobStatus

if TYPE_CHECKING:
    from webapp.services.devices import DeviceService
    from webapp.services.recognition import RecognitionService


def _resolve_debug_mode(payload: dict[str, Any]) -> str | None:
    raw = payload.get("debug_step")
    if raw is None:
        env = os.environ.get("BBCHANNEL_DEBUG_STEP", "").strip().lower()
        if env in {"1", "true", "yes", "pause"}:
            return "pause"
        if env == "log":
            return "log"
        return None
    if raw is True or str(raw).strip().lower() in {"1", "true", "pause"}:
        return "pause"
    if str(raw).strip().lower() == "log":
        return "log"
    return None


def _render_annotated_png(
    raw_png: bytes,
    matched: list[MatchResult],
    plan: dict[str, Any],
) -> bytes:
    with Image.open(BytesIO(raw_png)) as img:
        canvas = img.convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    for item in matched[:12]:
        x, y = item.top_left
        w, h = item.size
        draw.rectangle([x, y, x + w, y + h], outline=(46, 204, 113, 255), width=2)
        tag = f"{Path(item.template_path).name} {item.confidence:.2f}"
        ty = max(0, y - 14)
        draw.rectangle([x, ty, x + len(tag) * 6 + 6, ty + 13], fill=(20, 26, 32, 220))
        draw.text((x + 3, ty + 1), tag, fill=(180, 255, 200, 255))

    if plan.get("action") == "tap":
        tx, ty = plan["logical"]
        r = 14
        draw.ellipse([tx - r, ty - r, tx + r, ty + r], outline=(255, 45, 85, 255), width=3)
        draw.ellipse([tx - 3, ty - 3, tx + 3, ty + 3], fill=(255, 45, 85, 255))
        draw.line([tx - 22, ty, tx + 22, ty], fill=(255, 45, 85, 255), width=2)
        draw.line([tx, ty - 22, tx, ty + 22], fill=(255, 45, 85, 255), width=2)
    elif plan.get("action") == "swipe":
        (x1, y1), (x2, y2) = plan["logical"]
        draw.line([x1, y1, x2, y2], fill=(255, 45, 85, 255), width=3)
        draw.ellipse([x1 - 7, y1 - 7, x1 + 7, y1 + 7], fill=(255, 180, 0, 255))
        draw.ellipse([x2 - 11, y2 - 11, x2 + 11, y2 + 11], outline=(255, 45, 85, 255), width=3)

    out = BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def with_debug_step(
    handler: JobHandler,
    job_manager: JobManager,
    devices: DeviceService,
    recognition: RecognitionService | None,
    debug_root: Path,
) -> JobHandler:
    @wraps(handler)
    def wrapped(context, payload):
        mode = _resolve_debug_mode(payload)
        if mode is None or devices.action_hooks_active():
            return handler(context, payload)

        job_dir = debug_root / context.job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        latest_png: bytes | None = None
        frame_matches: list[MatchResult] = []
        step_counter = 0

        def on_snapshot(png_bytes: bytes) -> None:
            nonlocal latest_png
            latest_png = png_bytes
            frame_matches.clear()

        def on_match(result: MatchResult) -> None:
            frame_matches.append(result)

        def before_action(plan: dict[str, Any]) -> None:
            nonlocal step_counter
            step_counter += 1
            png = latest_png
            if png is None:
                try:
                    png = devices.snapshot()
                except Exception:
                    png = None

            matched = [m for m in frame_matches if m.matched]
            near_misses = sorted(
                (m for m in frame_matches if not m.matched),
                key=lambda item: item.confidence,
                reverse=True,
            )[:5]

            raw_path: str | None = None
            annotated_path: str | None = None
            if png is not None:
                raw_file = job_dir / f"step_{step_counter:04d}_raw.png"
                ann_file = job_dir / f"step_{step_counter:04d}_annotated.png"
                raw_file.write_bytes(png)
                ann_file.write_bytes(_render_annotated_png(png, matched, plan))
                raw_path = str(raw_file)
                annotated_path = str(ann_file)

            job_record = job_manager.get(context.job_id)
            recent_events = [
                {"event_type": e.event_type, "message": e.message}
                for e in job_manager.database.list_events(context.job_id, limit=50)[-5:]
                if e.event_type not in {"debug_step", "job_paused", "job_resumed"}
            ]
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "job_id": context.job_id,
                "job_kind": job_record.kind,
                "step_index": step_counter,
                "paused": mode == "pause",
                "current_step": job_record.current_step,
                "recent_events": recent_events,
                "action": plan,
                "recognition": {
                    "matched": [
                        {
                            "template_path": m.template_path,
                            "confidence": round(m.confidence, 4),
                            "threshold": m.threshold,
                            "center": m.center,
                            "top_left": m.top_left,
                            "size": m.size,
                        }
                        for m in matched
                    ],
                    "near_misses": [
                        {
                            "template_path": m.template_path,
                            "confidence": round(m.confidence, 4),
                            "threshold": m.threshold,
                            "center": m.center,
                        }
                        for m in near_misses
                    ],
                },
                "raw_screenshot": raw_path,
                "annotated_screenshot": annotated_path,
            }
            (job_dir / "latest.json").write_text(
                json.dumps(entry, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            with (job_dir / "steps.jsonl").open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(entry, ensure_ascii=False) + "\n")

            verb = "Paused before" if mode == "pause" else "Executing"
            summary = f"{verb} #{step_counter} {plan['action']} {plan['logical']} -> {plan['mapped']}"
            context.emit("debug_step", summary, data=entry)

            if mode == "pause":
                if job_manager.get(context.job_id).status == JobStatus.RUNNING:
                    job_manager.pause(context.job_id)
                context.raise_if_cancelled()

        observe_ctx = (
            recognition.observe_matches(on_match)
            if recognition is not None and hasattr(recognition, "observe_matches")
            else nullcontext()
        )
        with observe_ctx, devices.action_hooks(on_snapshot=on_snapshot, before_action=before_action):
            return handler(context, payload)

    return wrapped
