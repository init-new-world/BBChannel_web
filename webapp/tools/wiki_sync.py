from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from webapp.core.errors import AppError, ErrorCode
from webapp.services.battle_servants import FrontlineServantRecognizer
from webapp.services.equip_templates import EquipTemplateService
from webapp.services.resources import ResourceService
from webapp.services.script_data import ScriptDataService
from webapp.services.wiki_sync import WikiClient, WikiSyncService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m webapp.tools.wiki_sync",
        description="Sync FGO servants and event craft essences from Mooncell Wiki & Atlas Academy.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root containing assets/ and data/ (default: auto-detected).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass local .cache/wiki_sync HTTP cache.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check_p = sub.add_parser("check", help="Inspect missing servants and active CN/JP event craft essences.")
    check_p.add_argument("--server", choices=["CH", "JP", "ALL"], default="ALL")
    check_p.add_argument("--json", action="store_true", dest="as_json")

    svt_p = sub.add_parser("sync-servants", help="Incrementally sync new servants and battle assets.")
    svt_p.add_argument("--id", type=int, nargs="+", dest="ids", help="Specific Mooncell servant collection numbers.")
    svt_p.add_argument("--since-id", type=int, default=None, help="Sync all servants with collection number > SINCE_ID.")
    svt_p.add_argument("--include-charagraph", action="store_true", help="Also download 512x724 charagraph art.")
    svt_p.add_argument("--update-existing", action="store_true", help="Refresh metadata/assets even if SN already exists.")
    svt_p.add_argument("--dry-run", action="store_true", help="Preview servants to sync without writing files.")
    svt_p.add_argument("--json", action="store_true", dest="as_json")

    ce_p = sub.add_parser("sync-event-ces", help="Fetch and crop event craft essences into 237x68 support templates.")
    ce_p.add_argument("--server", choices=["CH", "CNTW", "JP"], default="CH")
    ce_p.add_argument("--event", type=str, default=None, help="Mooncell event page title.")
    ce_p.add_argument("--ce", nargs="+", default=None, help="Specific CE IDs or names/queries to import.")
    ce_p.add_argument("--y-offset", type=int, default=0, help="Vertical offset on 512x875 card art (default: 0).")
    ce_p.add_argument(
        "--activate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Activate imported templates into assets/assist/assist_equip/ (default: --activate).",
    )
    ce_p.add_argument("--save-drop", action="store_true", help="Also save 132x144 drop icon to assets/drop/.")
    ce_p.add_argument("--overwrite", action="store_true", help="Overwrite existing templates with the same name.")
    ce_p.add_argument("--dry-run", action="store_true", help="Preview resolved CEs and crop coordinates without writing.")
    ce_p.add_argument("--json", action="store_true", dest="as_json")

    return parser


def create_service(root: Path, *, no_cache: bool = False) -> WikiSyncService:
    resolved_root = root.resolve()
    resources = ResourceService(resolved_root / "assets", resolved_root / "data")
    equip_templates = EquipTemplateService(resources)
    script_data = ScriptDataService(resolved_root / "data", resources=resources)
    battle_servants = FrontlineServantRecognizer(resources)
    cache_dir = None if no_cache else (resolved_root / ".cache" / "wiki_sync")
    client = WikiClient(cache_dir=cache_dir, cache_ttl_seconds=0.0 if no_cache else 1800.0)
    return WikiSyncService(
        resources,
        equip_templates,
        script_data=script_data,
        battle_servants=battle_servants,
        client=client,
    )


def main(argv: Sequence[str] | None = None, *, service: WikiSyncService | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    svc = service or create_service(args.root, no_cache=args.no_cache)

    try:
        if args.command == "check":
            return _run_check(svc, server=args.server, as_json=args.as_json)
        if args.command == "sync-servants":
            return _run_sync_servants(svc, args)
        if args.command == "sync-event-ces":
            return _run_sync_event_ces(svc, args)
    except AppError as exc:
        print(f"[ERROR] ({exc.code.value}) {exc.message}", file=sys.stderr)
        if exc.details:
            print(json.dumps(exc.details, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    return 0


def _run_check(svc: WikiSyncService, *, server: str, as_json: bool) -> int:
    servant_report = svc.check_servants()
    servers = ["CH", "JP"] if server == "ALL" else [server]
    event_reports = {srv: svc.list_events(srv, limit=5) for srv in servers}
    payload = {
        "servants": servant_report,
        "events": event_reports,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(
        f"=== Servants: local={servant_report['local_servant_count']} | "
        f"Mooncell CN max=#{servant_report['mooncell_cn_max_no']} | "
        f"JP max=#{servant_report['mooncell_jp_max_no']} | "
        f"missing={servant_report['missing_count']} ==="
    )
    for svt in servant_report["missing_servants"]:
        cn_tag = "CN+JP" if svt["in_cn"] else "JP"
        label = svt["name_cn"] or svt["name_jp"]
        print(f"  - #{svt['collection_no']} [{cn_tag}] {label} ({svt['class']} ★{svt['star']}, SN={svt['sn']})")

    for srv, rep in event_reports.items():
        print(f"\n=== {srv} Active / Recent Events ===")
        for ev in rep["events"][:5]:
            state = "ACTIVE" if ev["active"] else "recent"
            ce_count = len(ev["craft_essences"])
            print(f"  [{state}] {ev['title']} ({ev['type']}, CEs={ce_count})")
            for ce in ev["craft_essences"]:
                loc = ce["local_status"] or "missing"
                print(f"      * #{ce['ce_id']} {ce['name']} [{ce['type']}] -> local: {loc}")
        if rep["patch_craft_essences"]:
            print(f"  [{srv} Patch New CEs]: " + ", ".join(
                f"#{ce['ce_id']} {ce['name']} ({ce['local_status'] or 'missing'})"
                for ce in rep["patch_craft_essences"][:8]
            ))
    return 0


def _run_sync_servants(svc: WikiSyncService, args: argparse.Namespace) -> int:
    result = svc.sync_servants(
        ids=args.ids,
        since_id=args.since_id,
        include_charagraph=args.include_charagraph,
        update_existing=args.update_existing,
        dry_run=args.dry_run,
    )
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    mode = "DRY-RUN" if result["dry_run"] else "SYNCED"
    print(f"[{mode}] Servants processed: {result['synced_count']}")
    for item in result["servants"]:
        print(
            f"  - #{item['collection_no']} {item['canonical_name']} "
            f"({item['class']} ★{item['star']}, SN={item['sn']}, NP={item['np_color']}, "
            f"skills={item['skill_name']}, types={item['skill_type']})"
        )
    for warning in result["warnings"]:
        print(f"  [WARN] {warning}")
    return 0


def _run_sync_event_ces(svc: WikiSyncService, args: argparse.Namespace) -> int:
    target_ids: list[int] = []
    if args.ce:
        for token in args.ce:
            cleaned = str(token).strip().lstrip("#")
            if cleaned.isdigit():
                cid = int(cleaned)
                if cid not in target_ids:
                    target_ids.append(cid)
            else:
                matches = svc.search_craft_essences(query=cleaned, server=args.server, limit=5)["items"]
                if not matches:
                    print(f"[WARN] No Mooncell CE matched query: {token!r}", file=sys.stderr)
                    continue
                cid = int(matches[0]["ce_id"])
                if cid not in target_ids:
                    target_ids.append(cid)
    elif args.event:
        found = svc.search_craft_essences(event_title=args.event, server=args.server, limit=30)["items"]
        target_ids = [int(item["ce_id"]) for item in found]
    else:
        ev_report = svc.list_events(args.server, limit=6)
        active_with_ces = next(
            (ev for ev in ev_report["events"] if ev["active"] and ev["craft_essences"]),
            None,
        )
        if active_with_ces is not None:
            target_ids = [int(ce["ce_id"]) for ce in active_with_ces["craft_essences"]]
        else:
            target_ids = [
                int(ce["ce_id"])
                for ce in ev_report["patch_craft_essences"]
                if ce.get("event")
            ] or [int(ce["ce_id"]) for ce in ev_report["patch_craft_essences"][:6]]

    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for cid in target_ids:
        if args.dry_run:
            preview = svc.preview_craft_essence(cid, y_offset=args.y_offset)
            preview_summary = {k: v for k, v in preview.items() if k != "preview_base64"}
            imported.append(preview_summary)
        else:
            try:
                res = svc.import_craft_essence(
                    cid,
                    y_offset=args.y_offset,
                    activate=args.activate,
                    save_drop=args.save_drop,
                    overwrite=args.overwrite,
                )
                imported.append(res)
            except AppError as exc:
                if exc.code == ErrorCode.DATA_FILE_CONFLICT and not args.overwrite:
                    skipped.append({"ce_id": cid, "reason": exc.message})
                    continue
                raise

    payload = {"dry_run": args.dry_run, "count": len(imported), "items": imported, "skipped": skipped}
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    mode = "DRY-RUN" if args.dry_run else "IMPORTED"
    print(f"[{mode}] Craft essences processed: {len(imported)}")
    for item in imported:
        if args.dry_run:
            print(
                f"  - #{item['ce_id']} {item['recommended_name']} "
                f"(focus_y={item['focus_y']}, crop={item['crop']['crop_box']})"
            )
        else:
            tpl = item["template"]
            drop_note = f", drop={item['drop_template_path']}" if item.get("drop_template_path") else ""
            print(f"  - #{item['ce_id']} {tpl['name']} -> {tpl['location']} ({tpl['image_path']}{drop_note})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
