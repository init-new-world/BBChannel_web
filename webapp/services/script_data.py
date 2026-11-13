from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from json import JSONDecodeError
from math import isfinite
from pathlib import Path
from threading import RLock
from typing import Any

from webapp.core.errors import AppError, ErrorCode
from webapp.services.assist_tags import parse_assist_tag_filename
from webapp.services.resources import ResourceService


VALID_SERVERS = {"CH", "CNTW", "JP"}
TURN_FIELD_RE = re.compile(r"^round(?P<round>\d+)_turn(?P<turn>\d+)_(skill|np|strategy|condition|replace)$")
SETTING_STRATEGY_FIELD_RE = re.compile(r"^round\d+_(?:turn\d+_strategy|extraStrategy)$")
SETTING_CONDITION_FIELD_RE = re.compile(r"^round\d+_(?:turn\d+_condition|extraCondition)$")
SETTING_SKILL_FIELD_RE = re.compile(r"^round\d+_(?:turn\d+_skill|extraSkill)$")
SETTING_REPLACE_FIELD_RE = re.compile(r"^round\d+_turn\d+_replace$")
ROUND_NUMBER_RE = re.compile(r"^round(?P<round>\d+)_")
SPECIAL_KEY_NAME_RE = re.compile(
    r"^W(?P<W>-?\d+)H(?P<H>-?\d+)"
    r"DXL(?P<DXL>-?\d+)DXR(?P<DXR>-?\d+)"
    r"DYT(?P<DYT>-?\d+)DYB(?P<DYB>-?\d+)CON(?P<CON>\d+)$"
)


def _uses_special_key(value: Any, code: str) -> bool:
    if isinstance(value, str):
        match = re.fullmatch(r"(?:[1-3][ABQ])?(S[0-9]+)", value)
        return match is not None and match.group(1) == code
    if isinstance(value, list):
        return any(_uses_special_key(entry, code) for entry in value)
    if isinstance(value, dict):
        return any(_uses_special_key(entry, code) for entry in value.values())
    return False


class ScriptDataService:
    def __init__(self, data_dir: Path | str, *, resources: ResourceService | None = None) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.settings_dir = self.data_dir / "settings"
        self.strategy_dir = self.data_dir / "strategy"
        self._resources = resources
        self._lock = RLock()

    @contextmanager
    def settings_transaction(self) -> Iterator[None]:
        """Serialize script edits with changes to their referenced resources."""
        with self._lock:
            yield

    def list_settings(self) -> list[dict[str, str]]:
        return self._list_named_json(self.settings_dir, "settings")

    def get_setting(self, name: str) -> dict[str, Any]:
        path = self._resolve_named_json(self.settings_dir, name, "settings")
        config, source = self._load_json_document(path)
        if not isinstance(config, dict):
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                f"Setting file must contain a JSON object: {path.name}",
                {"path": self._relative_path(path)},
            )

        validation = self._validate_setting(config)
        return {
            "name": path.stem,
            "path": self._relative_path(path),
            "config": config,
            "source": source,
            "summary": self._setting_summary(config),
            "validation": validation,
        }

    def save_setting(
        self,
        name: str,
        config: dict[str, Any],
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            return self._save_setting(name, config, overwrite=overwrite)

    def save_setting_source(self, name: str, source: str, *, overwrite: bool = False) -> dict[str, Any]:
        return self.save_setting(name, self._preset_source_value(source, dict), overwrite=overwrite)

    def _save_setting(
        self, name: str, config: dict[str, Any], *, overwrite: bool,
    ) -> dict[str, Any]:
        if not isinstance(config, dict):
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                "Setting file must contain a JSON object.",
                {"name": name},
            )
        validation = self._validate_setting(config)
        if not validation["ok"]:
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                f"Setting data is invalid: {name}",
                {"name": name, "validation": validation},
            )

        path = self._save_named_json(
            self.settings_dir,
            name,
            "settings",
            config,
            overwrite=overwrite,
        )
        return self.get_setting(path.stem)

    def delete_setting(self, name: str) -> dict[str, Any]:
        with self._lock:
            return self._delete_named_json(self.settings_dir, name, "settings")

    def find_assist_tag_references(self, tag_name: str) -> list[str]:
        return self._find_tag_references(tag_name, "assistTags")

    def find_command_tag_references(self, tag_name: str) -> list[str]:
        return self._find_tag_references(tag_name, "specialKeys")

    def _find_tag_references(self, tag_name: str, field: str) -> list[str]:
        references = []
        for setting in self.list_settings():
            try:
                path = self._resolve_named_json(self.settings_dir, setting["name"], "settings")
                config = self._load_json(path)
            except AppError as exc:
                raise AppError(
                    ErrorCode.DATA_FILE_CONFLICT,
                    f"Cannot verify tag references in unreadable script: {setting['name']}",
                    {"settings": [setting["name"]]},
                ) from exc
            tags = config.get(field) if isinstance(config, dict) else None
            if isinstance(tags, str):
                tags = [tags]
            if field == "specialKeys" and isinstance(tags, list):
                tags = [tag[0] if isinstance(tag, list) and tag else tag for tag in tags]
            if isinstance(tags, list) and any(
                isinstance(tag, str) and tag.strip().replace("\\", "/").rsplit("/", 1)[-1] == tag_name
                for tag in tags
            ):
                references.append(setting["name"])
        return references

    def bind_command_tag(
        self, name: str, *, tag_name: str, template_path: str, bound: bool,
    ) -> dict[str, Any]:
        with self._lock:
            detail = self.get_setting(name)
            config = detail["config"]
            try:
                keys = self._plan_special_keys(config)
            except ValueError as exc:
                raise AppError(ErrorCode.DATA_FILE_INVALID, str(exc)) from exc
            matches = [index for index, key in enumerate(keys) if key["template_name"] == tag_name]
            entries = list(config.get("specialKeys") or [])
            index = matches[0] if matches else len(entries)
            code = f"S{index}"
            if bound and not matches:
                entries.append(template_path)
            elif not bound and matches:
                if len(matches) > 1 or index != len(entries) - 1:
                    raise AppError(
                        ErrorCode.DATA_FILE_CONFLICT,
                        "Only the last command tag can be unbound without renumbering other tags.",
                        {"name": name, "code": code},
                    )
                references = [
                    field for field, value in config.items()
                    if (SETTING_STRATEGY_FIELD_RE.fullmatch(field) or SETTING_SKILL_FIELD_RE.fullmatch(field))
                    and _uses_special_key(value, code)
                ]
                if references:
                    raise AppError(
                        ErrorCode.DATA_FILE_CONFLICT,
                        f"Command tag {code} is still referenced by this script's strategies or skill commands.",
                        {"name": name, "code": code, "fields": references},
                    )
                entries.pop()
            if entries != (config.get("specialKeys") or []):
                config["specialKeys"] = entries
                detail = self.save_setting(name, config, overwrite=True)
            detail["command_tag_binding"] = {"bound": bound, "code": code if bound or matches else None}
            return detail

    def get_setting_plan(self, name: str) -> dict[str, Any]:
        detail = self.get_setting(name)
        config = detail["config"]
        try:
            special_keys = self._plan_special_keys(config)
        except ValueError:
            # Keep invalid scripts inspectable; validation prevents execution.
            special_keys = []
        rounds = self._build_rounds(config)
        action_count = sum(
            len(turn["actions"])
            for round_plan in rounds
            for turn in round_plan["turns"]
        )
        return {
            "name": detail["name"],
            "path": detail["path"],
            "server": config.get("server"),
            "servants": self._plan_servants(config),
            "assist": self._plan_assist(config),
            "pre_run": self.build_pre_run_report(config),
            "screen_rotation": self._plan_screen_rotation(config),
            "run": self._plan_run(config),
            "special_keys": special_keys,
            "master": self._plan_master(config),
            "rounds": rounds,
            "summary": {
                **detail["summary"],
                "round_count": len(rounds),
                "action_count": action_count,
            },
            "validation": detail["validation"],
        }

    def get_setting_pre_run_report(self, name: str) -> dict[str, Any]:
        detail = self.get_setting(name)
        report = self.build_pre_run_report(detail["config"])
        return {
            "name": detail["name"],
            "path": detail["path"],
            **report,
        }

    def preview_pre_run_report(
        self,
        *,
        config: dict[str, Any] | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        if source is not None:
            resolved_config = self._preset_source_value(source, dict)
        elif isinstance(config, dict):
            resolved_config = config
        else:
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                "Setting configuration must be a JSON object.",
            )
        return self.build_pre_run_report(resolved_config)

    def build_pre_run_report(self, config: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(config, dict):
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                "Setting configuration must be a JSON object.",
            )
        raw_server = config.get("server")
        server = (
            raw_server.upper()
            if isinstance(raw_server, str) and raw_server.strip()
            else "CH"
        )
        server_label = {"CH": "简中服", "CNTW": "繁中服", "JP": "日服"}.get(
            server,
            str(raw_server or "CH"),
        )
        raw_assist_idx = config.get("assistIdx")
        assist_idx = (
            raw_assist_idx
            if isinstance(raw_assist_idx, int)
            and not isinstance(raw_assist_idx, bool)
            and 0 <= raw_assist_idx < 6
            else None
        )
        missing_frontline_slots = [
            slot
            for slot in range(3)
            if not (
                isinstance(config.get(f"servant_{slot}_name"), str)
                and bool(config.get(f"servant_{slot}_name"))
            )
        ]
        frontline_ready = len(missing_frontline_slots) == 0
        frontline_warning = (
            "编队前排不足3人，是否仍然开始脚本？"
            if not frontline_ready
            else None
        )
        subtitle_warning_applicable = server in {"CH", "CNTW"}
        subtitle_warning = (
            "简中服及繁中服请务必在游戏设置中关闭战斗语音字幕，否则字幕遮挡会导致无法识别宝具值！"
            if subtitle_warning_applicable
            else None
        )

        raw_mode = config.get("assistMode")
        mode = (
            raw_mode
            if isinstance(raw_mode, str) and raw_mode.strip()
            else "从者礼装"
        )
        configured_servant_name = (
            config.get(f"servant_{assist_idx}_name")
            if assist_idx is not None
            else None
        )
        if not isinstance(configured_servant_name, str) or not configured_servant_name:
            configured_servant_name = None
        catalog_by_name = self._servant_canonical_lookup(config)
        servant_canonical_name = (
            catalog_by_name.get(configured_servant_name, configured_servant_name)
            if configured_servant_name
            else None
        )
        servant_specified = (
            mode not in {"仅礼装", "不识别", "冠位助战仅礼装"}
            and configured_servant_name is not None
        )
        servant_display = (
            configured_servant_name
            if servant_specified and configured_servant_name is not None
            else "未指定"
        )

        if mode in {"仅从者", "不识别"}:
            equip_slots = [[], [], []]
        else:
            raw_equip = config.get("assistEquip")
            if isinstance(raw_equip, dict):
                equip_slots = [
                    self._assist_equip_names(raw_equip.get(slot_key))
                    for slot_key in ("normal", "kizuna", "houshuu")
                ]
            elif isinstance(raw_equip, list):
                if not raw_equip:
                    equip_slots = [[], [], []]
                elif isinstance(raw_equip[0], list) or (
                    len(raw_equip) == 3
                    and any(isinstance(item, list) or item is None for item in raw_equip)
                ):
                    equip_slots = [
                        self._assist_equip_names(
                            raw_equip[idx] if idx < len(raw_equip) else None
                        )
                        for idx in range(3)
                    ]
                else:
                    equip_slots = [self._assist_equip_names(raw_equip), [], []]
            else:
                equip_slots = [[], [], []]
        equip_slots_display = [
            "、".join(slot_names) if slot_names else "未指定"
            for slot_names in equip_slots
        ]
        equip_specified = mode not in {"仅从者", "不识别"} and any(
            slot_names for slot_names in equip_slots
        )

        friend_only = bool(config.get("onlyFriendAssist", 0))
        friend_only_effective = (
            mode not in {"仅礼装", "不识别"} and configured_servant_name is not None
        )
        friend_only_warning = (
            "(从者未指定不生效)" if not friend_only_effective else None
        )

        full_limit_break = bool(config.get("fullEquip", 0))
        full_limit_break_effective = equip_specified
        full_limit_break_warning = (
            "(礼装未指定不生效)" if not full_limit_break_effective else None
        )

        servant_constraints_effective = servant_specified
        servant_constraints_warning = (
            "注意以下设置在从者未指定时不生效"
            if not servant_constraints_effective
            else None
        )

        raw_np_level = config.get("NPlevel")
        np_level = (
            raw_np_level
            if isinstance(raw_np_level, int) and not isinstance(raw_np_level, bool)
            else 1
        )
        raw_servant_level = config.get("servantLevel")
        servant_level = (
            raw_servant_level
            if isinstance(raw_servant_level, int)
            and not isinstance(raw_servant_level, bool)
            else 1
        )
        raw_skills = config.get("skillsLevel")
        default_skills = [10, 10, 10, 0, 0, 0, 0, 0]
        if isinstance(raw_skills, list) and raw_skills:
            padded_skills = (raw_skills + [0] * 8)[:8]
        else:
            padded_skills = default_skills
        skill_levels = padded_skills[:3]
        append_skill_levels = (
            padded_skills[3:6] if server == "CNTW" else padded_skills[3:8]
        )

        matched_names = {
            name
            for name in (configured_servant_name, servant_canonical_name)
            if isinstance(name, str) and name
        }
        check_np_color = servant_specified and bool(
            matched_names & {"托勒密", "妖精骑士兰斯洛特"}
        )
        check_servant_name = servant_specified and (
            "U－奥尔加玛丽" in matched_names
        )
        if check_np_color:
            special_filter_options = ["arts", "buster"]
            default_special_filter = "arts"
        elif check_servant_name:
            special_filter_options = ["u_olga", "olga"]
            default_special_filter = "u_olga"
        else:
            special_filter_options = []
            default_special_filter = "any"

        return {
            "frontline_ready": frontline_ready,
            "missing_frontline_slots": missing_frontline_slots,
            "frontline_warning": frontline_warning,
            "subtitle_warning_applicable": subtitle_warning_applicable,
            "subtitle_warning": subtitle_warning,
            "subtitle_tip_image": (
                "ui/closesub.png" if subtitle_warning_applicable else None
            ),
            "assist_report": {
                "server": server,
                "server_label": server_label,
                "mode": mode,
                "slot": assist_idx,
                "servant_name": configured_servant_name,
                "servant_canonical_name": servant_canonical_name,
                "servant_specified": servant_specified,
                "servant_display": servant_display,
                "equip_slots": equip_slots,
                "equip_slots_display": equip_slots_display,
                "equip_specified": equip_specified,
                "friend_only": friend_only,
                "friend_only_effective": friend_only_effective,
                "friend_only_warning": friend_only_warning,
                "full_limit_break": full_limit_break,
                "full_limit_break_effective": full_limit_break_effective,
                "full_limit_break_warning": full_limit_break_warning,
                "servant_constraints_effective": servant_constraints_effective,
                "servant_constraints_warning": servant_constraints_warning,
                "np_level": np_level,
                "servant_level": servant_level,
                "skill_levels": skill_levels,
                "append_skill_levels": append_skill_levels,
                "check_np_color": check_np_color,
                "check_servant_name": check_servant_name,
                "special_filter_options": special_filter_options,
                "default_special_filter": default_special_filter,
            },
        }

    def list_strategies(self) -> list[dict[str, str]]:
        return self._list_named_json(self.strategy_dir, "strategy")

    def get_strategy(self, name: str) -> dict[str, Any]:
        path = self._resolve_named_json(self.strategy_dir, name, "strategy")
        entries, source = self._load_json_document(path)
        validation = self._validate_strategy_file(entries)
        return {
            "name": path.stem,
            "path": self._relative_path(path),
            "entries": entries if isinstance(entries, list) else [],
            "source": source,
            "summary": {"entry_count": len(entries) if isinstance(entries, list) else 0},
            "validation": validation,
        }

    def save_strategy(
        self,
        name: str,
        entries: list[dict[str, Any]],
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        validation = self._validate_strategy_file(entries)
        if not validation["ok"]:
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                f"Strategy data is invalid: {name}",
                {"name": name, "validation": validation},
            )
        path = self._save_named_json(
            self.strategy_dir,
            name,
            "strategy",
            entries,
            overwrite=overwrite,
        )
        return self.get_strategy(path.stem)

    def delete_strategy(self, name: str) -> dict[str, Any]:
        return self._delete_named_json(self.strategy_dir, name, "strategy")

    def save_strategy_source(self, name: str, source: str, *, overwrite: bool = False) -> dict[str, Any]:
        return self.save_strategy(name, self._preset_source_value(source, list), overwrite=overwrite)

    def calculate_setting_turn_replacements(
        self,
        *,
        config: dict[str, Any] | None = None,
        source: str | None = None,
        target_round: int | None = None,
        target_turn: int | None = None,
        death_slots: list[int] | dict[str, list[int]] | None = None,
        will_nums: list[int] | dict[str, int] | None = None,
    ) -> dict[str, Any]:
        if source is not None:
            resolved_config = self._preset_source_value(source, dict)
        elif isinstance(config, dict):
            resolved_config = config
        else:
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                "Setting configuration must be a JSON object.",
            )
        return self.calculate_turn_replacements(
            resolved_config,
            target_round=target_round,
            target_turn=target_turn,
            death_slots=death_slots,
            will_nums=will_nums,
        )

    def calculate_turn_replacements(
        self,
        config: dict[str, Any],
        *,
        target_round: int | None = None,
        target_turn: int | None = None,
        death_slots: list[int] | dict[str, list[int]] | None = None,
        will_nums: list[int] | dict[str, int] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(config, dict):
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                "Setting configuration must be a JSON object.",
            )
        if (target_round is None) != (target_turn is None):
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                "Both target_round and target_turn must be supplied together.",
            )
        if target_round is not None and (
            isinstance(target_round, bool)
            or not isinstance(target_round, int)
            or target_round < 1
        ):
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                "target_round must be a positive integer.",
            )
        if target_turn is not None and (
            isinstance(target_turn, bool)
            or not isinstance(target_turn, int)
            or target_turn < 0
        ):
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                "target_turn must be a non-negative integer.",
            )

        catalog_by_name = self._servant_canonical_lookup(config)
        raw_assist = config.get("assistIdx")
        assist_idx = (
            raw_assist
            if isinstance(raw_assist, int)
            and not isinstance(raw_assist, bool)
            and 0 <= raw_assist < 6
            else None
        )
        initial_will = self._normalize_will_nums(will_nums)
        party: list[dict[str, Any]] = []
        for slot in range(6):
            raw_name = config.get(f"servant_{slot}_name")
            name = raw_name if isinstance(raw_name, str) and raw_name else None
            canonical_name = catalog_by_name.get(name, name) if name else None
            exists = bool(name) or (slot == assist_idx)
            party.append(
                {
                    "initial_slot": slot,
                    "name": name,
                    "canonical_name": canonical_name,
                    "exists": exists,
                    "will_num": initial_will[slot],
                }
            )

        used_initial_slots: set[int] = {
            slot
            for slot in range(3)
            if party[slot]["exists"] and slot != assist_idx
        }

        turn_pairs: list[tuple[int, int]] = []
        for round_num in self._round_numbers(config):
            count = self._turn_count(config, round_num)
            for turn_num in range(count):
                turn_pairs.append((round_num, turn_num))
        if (
            target_round is not None
            and target_turn is not None
            and (target_round, target_turn) not in turn_pairs
        ):
            turn_pairs.append((target_round, target_turn))
            turn_pairs.sort()

        turn_replacements: dict[str, dict[str, int | None]] = {}
        target_party_after: list[dict[str, Any]] | None = None

        for round_num, turn_num in turn_pairs:
            turn_key = f"round{round_num}_turn{turn_num}"
            replace_key = f"{turn_key}_replace"
            for front_idx in range(3):
                if (
                    party[front_idx]["exists"]
                    and party[front_idx]["initial_slot"] != assist_idx
                ):
                    used_initial_slots.add(party[front_idx]["initial_slot"])

            skills = self._list_value(config.get(f"{turn_key}_skill"))
            nps = self._list_value(config.get(f"{turn_key}_np"))

            in_condition = False
            for skill in skills:
                if not isinstance(skill, list) or not skill:
                    continue
                if skill[0] == "Start":
                    in_condition = True
                    continue
                if skill[0] == "End":
                    in_condition = False
                    continue
                if (
                    not in_condition
                    and len(skill) == 3
                    and skill[0] == 12
                    and isinstance(skill[1], int)
                    and not isinstance(skill[1], bool)
                    and isinstance(skill[2], int)
                    and not isinstance(skill[2], bool)
                    and 1 <= skill[1] <= 6
                    and 1 <= skill[2] <= 6
                    and skill[1] != skill[2]
                ):
                    left_idx = skill[1] - 1
                    right_idx = skill[2] - 1
                    for swapped_idx in (left_idx, right_idx):
                        if (
                            party[swapped_idx]["exists"]
                            and party[swapped_idx]["initial_slot"] != assist_idx
                        ):
                            used_initial_slots.add(party[swapped_idx]["initial_slot"])
                    party[left_idx], party[right_idx] = party[right_idx], party[left_idx]

            is_target = (
                target_round is not None
                and target_turn is not None
                and (round_num, turn_num) == (target_round, target_turn)
            )
            is_before_target = (
                target_round is not None
                and target_turn is not None
                and (round_num, turn_num) < (target_round, target_turn)
            )
            is_after_target = (
                target_round is not None
                and target_turn is not None
                and (round_num, turn_num) > (target_round, target_turn)
            )
            turn_deaths = self._resolve_turn_death_slots(
                death_slots,
                turn_key=turn_key,
                round_num=round_num,
                turn_num=turn_num,
                is_target=is_target,
                has_explicit_target=target_round is not None,
                is_last_turn=(
                    bool(turn_pairs) and (round_num, turn_num) == turn_pairs[-1]
                ),
            )

            existing_replace = config.get(replace_key)
            has_existing_replace = (
                isinstance(existing_replace, dict)
                and bool(existing_replace)
                and not self._validate_turn_replace(existing_replace, replace_key)
            )

            try:
                death_info = self._check_turn_death(
                    party=party,
                    skills=skills,
                    nps=nps,
                    death_slots=turn_deaths,
                )
            except AppError:
                if (is_before_target and has_existing_replace) or is_after_target:
                    death_info = None
                else:
                    raise

            calculated_record = (
                self._deal_with_turn_death(party, *death_info)
                if death_info is not None
                else {}
            )
            effective_record = (
                {
                    str(dest): src
                    for dest, src in existing_replace.items()
                }
                if is_before_target and has_existing_replace
                else calculated_record
            )
            turn_replacements[replace_key] = (
                calculated_record if is_target or target_round is None else effective_record
            )
            party = self._apply_turn_replace_record(party, effective_record)
            for front_idx in range(3):
                if (
                    party[front_idx]["exists"]
                    and party[front_idx]["initial_slot"] != assist_idx
                ):
                    used_initial_slots.add(party[front_idx]["initial_slot"])

            if is_target:
                target_party_after = [dict(slot_state) for slot_state in party]

        target_field = (
            f"round{target_round}_turn{target_turn}_replace"
            if target_round is not None and target_turn is not None
            else None
        )
        final_party = target_party_after if target_party_after is not None else party
        return {
            "target_field": target_field,
            "replacements": (
                turn_replacements.get(target_field, {})
                if target_field is not None
                else turn_replacements
            ),
            "turn_replacements": turn_replacements,
            "used_servants": sorted(used_initial_slots),
            "party_after": [
                {
                    "slot": idx + 1,
                    "initial_slot": (
                        slot_state["initial_slot"] + 1
                        if slot_state["exists"]
                        else None
                    ),
                    "name": slot_state["name"] if slot_state["exists"] else None,
                    "canonical_name": (
                        slot_state["canonical_name"] if slot_state["exists"] else None
                    ),
                    "exists": bool(slot_state["exists"]),
                    "will_num": int(slot_state["will_num"]),
                }
                for idx, slot_state in enumerate(final_party)
            ],
        }

    def list_servants(self, server: str) -> dict[str, Any]:
        server = self._normalize_server(server)
        catalog = self._load_servant_catalog(server)
        servants = [
            self._servant_summary(name, details)
            for name, details in sorted(catalog.items(), key=lambda item: item[0])
            if isinstance(details, dict)
        ]
        return {"server": server, "servants": servants}

    def list_masters(self) -> dict[str, Any]:
        path = self.data_dir / "master_info.json"
        if not path.is_file():
            return {"masters": []}
        catalog = self._load_json(path)
        if not isinstance(catalog, dict):
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                "master_info.json must contain a JSON object.",
                {"path": self._relative_path(path)},
            )
        masters = [
            self._master_summary(name, details)
            for name, details in sorted(catalog.items(), key=lambda item: item[0])
            if isinstance(details, dict)
        ]
        return {"masters": masters}

    def _list_named_json(self, directory: Path, prefix: str) -> list[dict[str, str]]:
        if not directory.exists():
            return []
        return [
            {"name": path.stem, "path": f"{prefix}/{path.name}"}
            for path in sorted(directory.glob("*.json"), key=lambda item: item.stem)
            if path.is_file()
        ]

    def _resolve_named_json(self, directory: Path, name: str, kind: str) -> Path:
        candidate = self._named_json_path(directory, name, kind)
        if not candidate.is_file():
            raise AppError(
                ErrorCode.DATA_FILE_NOT_FOUND,
                f"{kind.title()} data file not found: {name}",
                {"name": name},
            )
        return candidate

    def _named_json_path(self, directory: Path, name: str, kind: str) -> Path:
        normalized = name[:-5] if name.lower().endswith(".json") else name
        if not normalized or normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
            raise AppError(
                ErrorCode.DATA_FILE_NOT_FOUND,
                f"{kind.title()} data file not found: {name}",
                {"name": name},
            )

        base = directory.resolve()
        candidate = (base / f"{normalized}.json").resolve()
        if not self._is_inside(candidate, base):
            raise AppError(
                ErrorCode.DATA_FILE_NOT_FOUND,
                f"{kind.title()} data file not found: {name}",
                {"name": name},
            )
        return candidate

    @staticmethod
    def _write_json_atomic(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{path.stem}-",
                suffix=".tmp",
                dir=path.parent,
                delete=False,
            ) as temporary:
                json.dump(payload, temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _save_named_json(
        self,
        directory: Path,
        name: str,
        kind: str,
        payload: Any,
        *,
        overwrite: bool,
    ) -> Path:
        path = self._named_json_path(directory, name, kind)
        if path.exists() and not overwrite:
            raise AppError(
                ErrorCode.DATA_FILE_CONFLICT,
                f"{kind.title()} data file already exists: {name}",
                {"name": name, "path": self._relative_path(path)},
            )
        self._write_json_atomic(path, payload)
        return path

    def _delete_named_json(self, directory: Path, name: str, kind: str) -> dict[str, Any]:
        path = self._resolve_named_json(directory, name, kind)
        result = {
            "name": path.stem,
            "path": self._relative_path(path),
            "deleted": True,
        }
        path.unlink()
        return result

    def _load_json(self, path: Path) -> Any:
        return self._load_json_document(path)[0]

    def _load_json_document(self, path: Path) -> tuple[Any, str]:
        try:
            source = path.read_text(encoding="utf-8")
            return json.loads(source), source
        except JSONDecodeError as exc:
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                f"Invalid JSON data file: {path.name}",
                {"path": self._relative_path(path), "line": exc.lineno, "column": exc.colno},
            ) from exc

    @staticmethod
    def _preset_source_value(source: str, expected_type: type) -> Any:
        def reject_constant(_token: str) -> None:
            raise ValueError("Non-finite JSON number.")

        def finite_float(token: str) -> float:
            value = float(token)
            if not isfinite(value):
                raise ValueError("Non-finite JSON number.")
            return value

        try:
            value = json.loads(source, parse_constant=reject_constant, parse_float=finite_float)
        except (ValueError, RecursionError) as exc:
            raise AppError(ErrorCode.DATA_FILE_INVALID, "Invalid preset JSON source.") from exc
        if not isinstance(value, expected_type):
            raise AppError(ErrorCode.DATA_FILE_INVALID, "Preset JSON source has the wrong top-level type.")
        return value

    def _validate_setting(self, config: dict[str, Any]) -> dict[str, Any]:
        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        server = config.get("server")
        servant_index: set[str] | None = None

        if not isinstance(server, str) or server.upper() not in VALID_SERVERS:
            errors.append(
                self._issue(
                    "unsupported_server",
                    "server",
                    f"Unsupported server: {server}",
                )
            )
        else:
            server = server.upper()
            try:
                servant_index = self._servant_name_index(server)
            except AppError:
                warnings.append(
                    self._issue(
                        "missing_servant_catalog",
                        "server",
                        f"Servant catalog is missing for server: {server}",
                    )
                )

        for slot in range(6):
            field = f"servant_{slot}_name"
            servant_name = config.get(field)
            if servant_name is None or servant_name == "":
                continue
            if not isinstance(servant_name, str):
                errors.append(self._issue("invalid_servant_name", field, "Servant name must be a string."))
                continue
            if servant_index is not None and servant_name not in servant_index:
                errors.append(self._issue("unknown_servant", field, f"Unknown servant: {servant_name}"))

        for field, value in config.items():
            if SETTING_STRATEGY_FIELD_RE.match(field) and value is not None:
                errors.extend(self._validate_strategy_entries(value, field, tagged=False))
            elif SETTING_CONDITION_FIELD_RE.match(field) and value is not None:
                warnings.extend(self._validate_strategy_entries(value, field, tagged=False))
            elif SETTING_REPLACE_FIELD_RE.match(field) and value is not None:
                errors.extend(self._validate_turn_replace(value, field))

        if config.get("stuckRestart"):
            stuck_interval = config.get("checkStuckInterval", 30)
            if (
                isinstance(stuck_interval, bool)
                or not isinstance(stuck_interval, (int, float))
                or not 1 <= stuck_interval <= 600
            ):
                errors.append(
                    self._issue(
                        "invalid_stuck_interval",
                        "checkStuckInterval",
                        "Stuck watchdog interval must be between 1 and 600 seconds.",
                    )
                )

        if "screenRotation" in config and config["screenRotation"] is not None:
            rotation = config["screenRotation"]
            if (
                isinstance(rotation, bool)
                or not isinstance(rotation, int)
                or rotation not in {0, 90, 180, 270}
            ):
                errors.append(
                    self._issue(
                        "invalid_screen_rotation",
                        "screenRotation",
                        "Screen rotation must be null, 0, 90, 180, or 270.",
                    )
                )

        skill_levels = config.get("skillsLevel")
        if skill_levels is not None and (
            not isinstance(skill_levels, list)
            or len(skill_levels) > 8
            or any(isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= 10
                   for level in skill_levels)
        ):
            errors.append(self._issue(
                "invalid_skill_levels", "skillsLevel",
                "Skill requirements must contain up to eight integer levels between 0 and 10.",
            ))
        elif server == "CNTW" and skill_levels and any(skill_levels[6:]):
            errors.append(self._issue(
                "unsupported_append_skill", "skillsLevel",
                "The CNTW assist layout supports three append skill requirements.",
            ))

        try:
            tags = self._plan_assist_tags(config.get("assistTags"))
        except ValueError as exc:
            errors.append(
                self._issue(
                    "invalid_assist_tags",
                    "assistTags",
                    str(exc),
                )
            )
        else:
            if self._resources is not None:
                for index, tag in enumerate(tags):
                    field = f"assistTags[{index}]"
                    try:
                        image = self._resources.template_metadata(tag["template_path"])
                    except AppError as exc:
                        code = (
                            "missing_assist_tag"
                            if exc.code == ErrorCode.TEMPLATE_NOT_FOUND
                            else "invalid_assist_tag_image"
                        )
                        errors.append(self._issue(code, field, exc.message))
                        continue
                    if (image["width"], image["height"]) != (
                        tag["right"] - tag["left"], tag["bottom"] - tag["top"],
                    ):
                        errors.append(self._issue(
                            "invalid_assist_tag_image", field,
                            f"Assist tag dimensions do not match filename metadata: {tag['template_name']}",
                        ))

        try:
            special_keys = self._plan_special_keys(config)
        except ValueError as exc:
            errors.append(self._issue("invalid_special_keys", "specialKeys", str(exc)))
        else:
            if self._resources is not None:
                for index, key in enumerate(special_keys):
                    field = f"specialKeys[{index}]"
                    try:
                        image = self._resources.template_metadata(key["template_path"])
                    except AppError as exc:
                        code = "missing_special_key" if exc.code == ErrorCode.TEMPLATE_NOT_FOUND else "invalid_special_key_image"
                        errors.append(self._issue(code, field, exc.message))
                        continue
                    if (image["width"], image["height"]) != (
                        key["right"] - key["left"], key["bottom"] - key["top"],
                    ):
                        errors.append(self._issue(
                            "invalid_special_key_image", field,
                            f"Special key dimensions do not match filename metadata: {key['template_name']}",
                        ))

        return {"ok": not errors, "errors": errors, "warnings": warnings}

    def _setting_summary(self, config: dict[str, Any]) -> dict[str, Any]:
        servants = [
            config.get(f"servant_{slot}_name")
            for slot in range(6)
            if config.get(f"servant_{slot}_name") is not None and config.get(f"servant_{slot}_name") != ""
        ]
        turns = {
            (match.group("round"), match.group("turn"))
            for key in config
            if (match := TURN_FIELD_RE.match(key))
        }
        return {
            "server": config.get("server"),
            "servants": servants,
            "turn_count": len(turns),
            "strategy_count": self._setting_strategy_count(config),
        }

    def _setting_strategy_count(self, config: dict[str, Any]) -> int:
        count = 0
        for key, value in config.items():
            if not SETTING_STRATEGY_FIELD_RE.match(key) or value is None:
                continue
            count += len(value) if isinstance(value, list) else 1
        return count

    def _plan_servants(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        catalog_by_name: dict[str, tuple[str, dict[str, Any]]] = {}
        server = config.get("server")
        if isinstance(server, str) and server.upper() in VALID_SERVERS:
            for canonical_name, details in self._load_servant_catalog(server.upper()).items():
                if not isinstance(details, dict):
                    continue
                catalog_by_name[canonical_name] = (canonical_name, details)
                aliases = details.get("other_name")
                if isinstance(aliases, list):
                    for alias in aliases:
                        if isinstance(alias, str):
                            catalog_by_name[alias] = (canonical_name, details)

        def metadata(
            name: Any,
        ) -> tuple[str | None, str | None, str | None, str | None]:
            catalog_entry = catalog_by_name.get(name) if isinstance(name, str) else None
            if catalog_entry is None:
                return None, None, None, None
            canonical_name, details = catalog_entry
            sn = details.get("SN")
            np_color = details.get("NPcolor")
            servant_class = details.get("class")
            return (
                canonical_name,
                servant_class if isinstance(servant_class, str) else None,
                str(sn) if isinstance(sn, (str, int)) else None,
                np_color if isinstance(np_color, str) else None,
            )

        configured_used = config.get("usedServant", [0, 1, 2])
        if not isinstance(configured_used, list):
            configured_used = []
        used_slots = {
            slot
            for slot in configured_used
            if isinstance(slot, int)
            and not isinstance(slot, bool)
            and 0 <= slot < 6
        }
        servants = []
        for slot in range(6):
            name = config.get(f"servant_{slot}_name")
            canonical_name, servant_class, sn, np_color = metadata(name)
            servants.append(
                {
                    "slot": slot,
                    "name": name,
                    "canonical_name": canonical_name,
                    "class": servant_class,
                    "active": slot < 3 and bool(name),
                    "used": slot in used_slots and bool(name),
                    "sn": sn,
                    "np_color": np_color,
                }
            )
        return servants

    def _plan_master(self, config: dict[str, Any]) -> dict[str, Any]:
        equip = config.get("master_equip")
        equip_name = next(
            (
                master["name"]
                for master in self.list_masters()["masters"]
                if str(master.get("sn")) == str(equip)
            ),
            None,
        )
        return {
            "equip": equip,
            "name": equip_name,
            "sex": config.get("master_sex"),
        }

    def _plan_assist(self, config: dict[str, Any]) -> dict[str, Any]:
        slot = config.get("assistIdx")
        servant_name = config.get(f"servant_{slot}_name") if isinstance(slot, int) else None
        canonical_name: str | None = None
        servant_sn: str | None = None
        servant_class: str | None = None

        server = config.get("server")
        if isinstance(server, str) and server.upper() in VALID_SERVERS and isinstance(servant_name, str):
            for name, details in self._load_servant_catalog(server.upper()).items():
                if not isinstance(details, dict):
                    continue
                aliases = details.get("other_name")
                if servant_name != name and not (isinstance(aliases, list) and servant_name in aliases):
                    continue
                canonical_name = name
                sn = details.get("SN")
                servant_sn = str(sn) if isinstance(sn, (str, int)) else None
                class_name = details.get("class")
                servant_class = class_name if isinstance(class_name, str) else None
                break

        raw_assist_equip = config.get("assistEquip")
        equip_names = self._assist_equip_names(raw_assist_equip)
        equip_slots = (
            self._assist_equip_slots(raw_assist_equip)
            if config.get("assistMode") in {"冠位助战", "冠位助战仅礼装"}
            else None
        )
        try:
            tags = self._plan_assist_tags(config.get("assistTags"))
        except ValueError:
            # Validation retains the error and execution rejects this plan.
            tags = []

        skill_levels = config.get("skillsLevel")
        skill_levels = (skill_levels + [0] * 8)[:8] if isinstance(skill_levels, list) else [0] * 8
        assist_plan: dict[str, Any] = {
            "mode": config.get("assistMode"),
            "slot": slot,
            "servant_name": servant_name,
            "servant_canonical_name": canonical_name,
            "servant_sn": servant_sn,
            "servant_class": servant_class,
            "equip_names": equip_names,
            "full_limit_break": bool(config.get("fullEquip")),
            "friend_only": bool(config.get("onlyFriendAssist")),
            "np_level": config.get("NPlevel"),
            "servant_level": config.get("servantLevel", 1),
            "skill_levels": skill_levels[:3],
            "append_skill_levels": skill_levels[3:6] if server == "CNTW" else skill_levels[3:8],
            "scroll_limit": config.get("scrollLimit"),
            "interval_after_swipe": config.get("intervalAFswipeAssist", 0.5),
            "no_grand_refresh": bool(config.get("noGrandRefresh")),
            "bond_equip_type": config.get("jbType", "任意"),
            "all_not_skip": bool(config.get("allNotSkip", 1)),
            "tags": tags,
        }
        if equip_slots is not None:
            assist_plan["equip_slots"] = equip_slots
        return assist_plan

    @classmethod
    def _assist_equip_slots(cls, value: Any) -> dict[str, list[str]]:
        if isinstance(value, dict):
            return {
                slot: cls._assist_equip_names(value.get(slot))
                for slot in ("normal", "kizuna", "houshuu")
            }
        if isinstance(value, list) and (
            len(value) == 3
            or any(isinstance(item, list) or item is None for item in value)
        ):
            return {
                slot: cls._assist_equip_names(
                    value[index] if index < len(value) else None
                )
                for index, slot in enumerate(("normal", "kizuna", "houshuu"))
            }
        return {
            "normal": cls._assist_equip_names(value),
            "kizuna": [],
            "houshuu": [],
        }

    @staticmethod
    def _assist_equip_names(value: Any) -> list[str]:
        names: list[str] = []

        def collect(entry: Any) -> None:
            if isinstance(entry, str):
                if entry and entry not in names:
                    names.append(entry)
                return
            if isinstance(entry, list):
                for item in entry:
                    collect(item)

        collect(value)
        return names

    @staticmethod
    def _plan_assist_tags(value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("assistTags must be a list.")

        tags: list[dict[str, Any]] = []
        for index, raw_path in enumerate(value):
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise ValueError(f"assistTags[{index}] must contain an image path.")
            normalized_path = raw_path.strip().replace("\\", "/")
            template_name = normalized_path.rsplit("/", 1)[-1]
            try:
                metadata = parse_assist_tag_filename(template_name)
            except ValueError as exc:
                raise ValueError(f"assistTags[{index}] {exc}") from exc

            assets_marker = "/assets/"
            if assets_marker in normalized_path:
                template_path = normalized_path.split(assets_marker, 1)[1]
            elif normalized_path.startswith("assets/"):
                template_path = normalized_path[7:]
            elif normalized_path.startswith("assist/"):
                template_path = normalized_path
            else:
                template_path = f"assist/assist_tags/{template_name}"
            tags.append(
                {
                    "template_name": template_name,
                    "template_path": template_path,
                    "threshold": metadata.threshold,
                    "source_width": metadata.source_width,
                    "source_height": metadata.source_height,
                    "left": metadata.left,
                    "right": metadata.right,
                    "top": metadata.top,
                    "bottom": metadata.bottom,
                }
            )
        return tags

    @staticmethod
    def _plan_ignored_friendship(value: Any) -> list[int]:
        if not isinstance(value, (str, list)):
            return []
        positions = []
        for item in value:
            try:
                position = int(item)
            except (TypeError, ValueError, OverflowError):
                continue
            if 1 <= position <= 5:
                positions.append(position)
        return positions

    @staticmethod
    def _plan_screen_rotation(config: dict[str, Any]) -> int | None:
        rotation = config.get("screenRotation")
        if (
            rotation is None
            or isinstance(rotation, bool)
            or not isinstance(rotation, int)
            or rotation not in {0, 90, 180, 270}
        ):
            return None
        return rotation

    @staticmethod
    def _plan_run(config: dict[str, Any]) -> dict[str, Any]:
        return {
            "clear_ap": bool(config.get("clearAP")),
            "allow_other_apple": bool(config.get("allowOtherApple")),
            "first_battle_set": bool(config.get("firstBattleSet")),
            "interval_before_fight": config.get("intervalBF", 0),
            "interval_before_operation": config.get("intervalBF", 0),
            "interval_before_choose_card": config.get("intervalBFchooseCard", 0.5),
            "interval_after_fight": config.get("intervalAF", 0),
            "interval_after_operation": config.get("intervalAF", 0.1),
            "random_time": config.get("randomTime", 0),
            "random_touch": bool(config.get("randomTouch")),
            "no_chain": bool(config.get("noChain")),
            "no_speedup_skill": bool(config.get("noSpeedupSkill")),
            "full_friendship_stop": bool(config.get("fullFriendshipStop")),
            "ignored_friendship_slots": ScriptDataService._plan_ignored_friendship(config.get("ignoreFriendship", "")),
            "drop_stop_num": config.get("dropStopNum", 0),
            "drop_image": config.get("dropImage"),
            "game_crash_restart": bool(config.get("gameCrushRestart")),
            "stuck_restart": bool(config.get("stuckRestart")),
            "check_stuck_interval": config.get("checkStuckInterval", 30),
            "add_friend": bool(config.get("addFriend")),
        }

    @staticmethod
    def _plan_special_keys(config: dict[str, Any]) -> list[dict[str, Any]]:
        raw_entries = config.get("specialKeys", [])
        if raw_entries is None:
            return []
        if not isinstance(raw_entries, list):
            raise ValueError("specialKeys must be a list.")

        result = []
        for index, entry in enumerate(raw_entries):
            raw_path = entry[0] if isinstance(entry, list) and entry else entry
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise ValueError(f"specialKeys[{index}] must contain an image path.")
            normalized_path = raw_path.strip().replace("\\", "/")
            template_name = normalized_path.rsplit("/", 1)[-1]
            stem = template_name.rsplit(".", 1)[0].split("]")[-1]
            match = SPECIAL_KEY_NAME_RE.fullmatch(stem)
            if match is None:
                raise ValueError(f"specialKeys[{index}] has an invalid filename.")
            values = {name: int(value) for name, value in match.groupdict().items() if name != "CON"}
            threshold = float(f"0.{match.group('CON')}")
            if not 0 <= threshold <= 1:
                raise ValueError(f"specialKeys[{index}] has an invalid threshold.")
            if values["W"] <= 0 or values["H"] <= 0 or values["DXL"] >= values["DXR"] or values["DYT"] >= values["DYB"]:
                raise ValueError(f"specialKeys[{index}] has invalid metadata.")
            assets_marker = "/assets/"
            if assets_marker in normalized_path:
                template_path = normalized_path.split(assets_marker, 1)[1]
            elif normalized_path.startswith("assets/"):
                template_path = normalized_path[7:]
            elif normalized_path.startswith(("special_keys/", "battle/customCommandCard/")):
                template_path = normalized_path
            else:
                template_path = f"special_keys/{template_name}"
            result.append(
                {
                    "code": f"S{index}",
                    "template_name": template_name,
                    "template_path": template_path,
                    "threshold": threshold,
                    "source_width": values["W"],
                    "source_height": values["H"],
                    "left": values["DXL"],
                    "right": values["DXR"],
                    "top": values["DYT"],
                    "bottom": values["DYB"],
                }
            )
        return result

    def _build_rounds(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        rounds: list[dict[str, Any]] = []
        for round_number in self._round_numbers(config):
            turns = [
                self._build_turn(config, round_number, turn_number)
                for turn_number in range(self._turn_count(config, round_number))
            ]
            if not turns:
                continue
            rounds.append(
                {
                    "round": round_number,
                    "extra_skill": config.get(f"round{round_number}_extraSkill", []),
                    "extra_strategy": config.get(f"round{round_number}_extraStrategy"),
                    "extra_condition": config.get(f"round{round_number}_extraCondition"),
                    "turns": turns,
                }
            )
        return rounds

    def _round_numbers(self, config: dict[str, Any]) -> list[int]:
        rounds = {
            int(match.group("round"))
            for key in config
            if (match := ROUND_NUMBER_RE.match(key))
        }
        return sorted(rounds)

    def _turn_count(self, config: dict[str, Any], round_number: int) -> int:
        declared = config.get(f"round{round_number}_turns")
        field_turns = [
            int(match.group("turn")) + 1
            for key in config
            if (match := TURN_FIELD_RE.match(key)) and int(match.group("round")) == round_number
        ]
        counts = field_turns
        if isinstance(declared, int):
            counts.append(declared)
        return max(counts, default=0)

    def _build_turn(self, config: dict[str, Any], round_number: int, turn_number: int) -> dict[str, Any]:
        prefix = f"round{round_number}_turn{turn_number}"
        skills = self._list_value(config.get(f"{prefix}_skill"))
        nps = self._list_value(config.get(f"{prefix}_np"))
        strategy = config.get(f"{prefix}_strategy")
        condition = config.get(f"{prefix}_condition")
        replace = config.get(f"{prefix}_replace")
        return {
            "round": round_number,
            "turn": turn_number,
            "skills": skills,
            "nps": nps,
            "strategy": strategy,
            "condition": condition,
            "replace": replace,
            "actions": self._turn_actions(skills, nps, strategy, replace),
        }

    def _turn_actions(
        self,
        skills: list[Any],
        nps: list[Any],
        strategy: Any,
        replace: Any,
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        if isinstance(replace, dict) and replace:
            actions.append({"type": "replace", "replacements": replace})
        actions.extend({"type": "skill", "command": skill} for skill in skills)
        actions.extend({"type": "np", "servant": np} for np in nps)
        if strategy:
            actions.append({"type": "strategy", "strategies": strategy})
        return actions

    @staticmethod
    def _list_value(value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    def _validate_turn_replace(self, value: Any, field: str) -> list[dict[str, str]]:
        if not isinstance(value, dict):
            return [
                self._issue(
                    "invalid_turn_replace",
                    field,
                    "Turn replacement must be a JSON object mapping slots 1 through 6 to source slots 1 through 6 or null.",
                )
            ]
        errors: list[dict[str, str]] = []
        for destination, source in value.items():
            slot_field = f"{field}.{destination}" if isinstance(destination, str) else field
            if not isinstance(destination, str) or destination not in {"1", "2", "3", "4", "5", "6"}:
                errors.append(
                    self._issue(
                        "invalid_turn_replace",
                        slot_field,
                        "Turn replacement destination slots must be strings '1' through '6'.",
                    )
                )
                continue
            if source is not None and (
                isinstance(source, bool) or not isinstance(source, int) or not 1 <= source <= 6
            ):
                errors.append(
                    self._issue(
                        "invalid_turn_replace",
                        slot_field,
                        "Turn replacement source slots must be integers 1 through 6 or null.",
                    )
                )
        return errors

    def _servant_canonical_lookup(self, config: dict[str, Any]) -> dict[str, str]:
        server_raw = config.get("server")
        server = (
            server_raw.upper()
            if isinstance(server_raw, str) and server_raw.upper() in VALID_SERVERS
            else "CH"
        )
        try:
            catalog = self._load_servant_catalog(server)
        except AppError:
            if server != "CH":
                try:
                    catalog = self._load_servant_catalog("CH")
                except AppError:
                    return {}
            else:
                return {}
        lookup: dict[str, str] = {}
        for canonical_name, details in catalog.items():
            lookup[canonical_name] = canonical_name
            if isinstance(details, dict):
                aliases = details.get("other_name")
                if isinstance(aliases, list):
                    for alias in aliases:
                        if isinstance(alias, str) and alias:
                            lookup[alias] = canonical_name
        return lookup

    @staticmethod
    def _normalize_will_nums(
        will_nums: list[int] | dict[str, int] | None,
    ) -> list[int]:
        result = [0] * 6
        if will_nums is None:
            return result
        if isinstance(will_nums, list):
            for idx, val in enumerate(will_nums[:6]):
                if isinstance(val, int) and not isinstance(val, bool) and val >= 0:
                    result[idx] = val
            return result
        if isinstance(will_nums, dict):
            zero_based = "0" in will_nums or 0 in will_nums
            for key, val in will_nums.items():
                if isinstance(val, bool) or not isinstance(val, int) or val < 0:
                    continue
                try:
                    slot = int(key)
                except (TypeError, ValueError):
                    continue
                index = slot if zero_based else slot - 1
                if 0 <= index < 6:
                    result[index] = val
        return result

    @staticmethod
    def _resolve_turn_death_slots(
        death_slots: list[int] | dict[str, list[int]] | None,
        *,
        turn_key: str,
        round_num: int,
        turn_num: int,
        is_target: bool,
        has_explicit_target: bool,
        is_last_turn: bool,
    ) -> set[int]:
        if death_slots is None:
            return set()
        raw_list: Any = None
        if isinstance(death_slots, list):
            if (has_explicit_target and is_target) or (
                not has_explicit_target and is_last_turn
            ):
                raw_list = death_slots
        elif isinstance(death_slots, dict):
            for candidate_key in (
                turn_key,
                f"{turn_key}_replace",
                f"{turn_key}_strategy",
                f"{round_num}:{turn_num}",
            ):
                if candidate_key in death_slots:
                    raw_list = death_slots[candidate_key]
                    break
        if not isinstance(raw_list, list):
            return set()
        return {
            slot
            for slot in raw_list
            if isinstance(slot, int)
            and not isinstance(slot, bool)
            and 1 <= slot <= 3
        }

    @staticmethod
    def _check_turn_death(
        *,
        party: list[dict[str, Any]],
        skills: list[Any],
        nps: list[Any],
        death_slots: set[int],
    ) -> tuple[list[int], list[int], list[int]] | None:
        sacrifice_lst: list[int] = []
        replace_lst: list[int] = []
        resurrection_lst: list[int] = []

        def append_replace() -> None:
            for back in range(3, 6):
                if party[back]["exists"] and (back + 1) not in replace_lst:
                    replace_lst.append(back + 1)
                    break

        for raw_np in nps:
            if (
                isinstance(raw_np, bool)
                or not isinstance(raw_np, int)
                or raw_np not in (1, 2, 3)
            ):
                continue
            if raw_np in sacrifice_lst:
                continue
            np_idx = raw_np - 1
            if not party[np_idx]["exists"]:
                continue
            name = party[np_idx]["canonical_name"]
            if name == "图坦卡蒙":
                for skill in skills[::-1]:
                    if isinstance(skill, list):
                        if (
                            len(skill) == 3
                            and skill[0] == 12
                            and all(
                                isinstance(item, int) and not isinstance(item, bool)
                                for item in skill
                            )
                            and min(skill) == raw_np
                        ):
                            if party[np_idx]["will_num"] > 0:
                                party[np_idx]["will_num"] -= 1
                            else:
                                sacrifice_lst.append(raw_np)
                                append_replace()
                            break
                    elif (
                        isinstance(skill, int)
                        and not isinstance(skill, bool)
                        and abs(skill) == 3 * raw_np
                    ):
                        break
                else:
                    if party[np_idx]["will_num"] > 0:
                        party[np_idx]["will_num"] -= 1
                    else:
                        sacrifice_lst.append(raw_np)
                        append_replace()
            elif name in ("阿拉什", "织田信胜", "静希草十郎"):
                if party[np_idx]["will_num"] > 0:
                    party[np_idx]["will_num"] -= 1
                else:
                    sacrifice_lst.append(raw_np)
                    append_replace()
            elif name == "陈宫":
                for idx in range(3):
                    if (
                        idx + 1 != raw_np
                        and party[idx]["exists"]
                        and (idx + 1) not in sacrifice_lst
                    ):
                        if party[idx]["will_num"] > 0:
                            party[idx]["will_num"] -= 1
                        else:
                            sacrifice_lst.append(idx + 1)
                            append_replace()
                        break
                else:
                    raise AppError(
                        ErrorCode.DATA_FILE_INVALID,
                        "Insufficient frontline sacrifice target for Chen Gong NP.",
                        {"servant": "陈宫", "np_slot": raw_np},
                    )
            elif name == "鹤小姐":
                for idx in range(3):
                    if (
                        idx + 1 != raw_np
                        and party[idx]["exists"]
                        and (idx + 1) not in sacrifice_lst
                    ):
                        sacrifice_lst.append(raw_np)
                        append_replace()
                        resurrection_lst.append(raw_np)
                        break

        black2: list[int] = []
        for idx in range(3):
            if (idx + 1) in sacrifice_lst or not party[idx]["exists"]:
                continue
            name = party[idx]["canonical_name"]
            if name == "克洛伊·冯·爱因兹贝伦(Avenger)":
                need_continue = False
                in_condition = False
                for skill in skills[::-1]:
                    if not isinstance(skill, list) or not skill:
                        continue
                    if (
                        len(skill) == 3
                        and skill[0] == 12
                        and all(
                            isinstance(item, int) and not isinstance(item, bool)
                            for item in skill
                        )
                        and min(skill) == idx + 1
                    ):
                        break
                    if skill[0] == "End":
                        in_condition = True
                        continue
                    if skill[0] == "Start":
                        in_condition = False
                        continue
                    if (
                        isinstance(skill[0], int)
                        and not isinstance(skill[0], bool)
                        and abs(skill[0]) == 3 * idx + 2
                    ):
                        if in_condition:
                            need_continue = True
                            break
                        black2.append(idx)
                        need_continue = True
                        break
                if need_continue:
                    continue
            if party[idx]["will_num"] > 0:
                party[idx]["will_num"] -= 1
                continue
            if name == "哈贝特洛特":
                in_condition = False
                for skill in skills[::-1]:
                    if not isinstance(skill, list) or not skill:
                        continue
                    if (
                        len(skill) == 3
                        and skill[0] == 12
                        and all(
                            isinstance(item, int) and not isinstance(item, bool)
                            for item in skill
                        )
                        and min(skill) == idx + 1
                    ):
                        break
                    if skill[0] == "End":
                        in_condition = True
                        continue
                    if skill[0] == "Start":
                        in_condition = False
                        continue
                    if (
                        isinstance(skill[0], int)
                        and not isinstance(skill[0], bool)
                        and abs(skill[0]) == 3 * (idx + 1)
                    ):
                        if in_condition:
                            break
                        if (
                            len(skill) > 1
                            and isinstance(skill[1], int)
                            and not isinstance(skill[1], bool)
                            and skill[1] == idx + 1
                        ):
                            break
                        sacrifice_lst.append(idx + 1)
                        append_replace()
                        break

        for idx in black2:
            for svt in range(3):
                if (
                    idx != svt
                    and party[svt]["exists"]
                    and (svt + 1) not in sacrifice_lst
                ):
                    sacrifice_lst.append(idx + 1)
                    append_replace()
                    resurrection_lst.append(idx + 1)
                    break

        for idx in range(3):
            if (idx + 1) in sacrifice_lst or not party[idx]["exists"]:
                continue
            if (idx + 1) in death_slots:
                sacrifice_lst.append(idx + 1)
                append_replace()

        if sacrifice_lst:
            return sacrifice_lst, replace_lst, resurrection_lst
        return None

    @staticmethod
    def _deal_with_turn_death(
        party: list[dict[str, Any]],
        sacrifice_lst: list[int],
        replace_lst: list[int],
        resurrection_lst: list[int],
    ) -> dict[str, int | None]:
        permanent_sacrifices = sorted(
            [slot for slot in sacrifice_lst if slot not in resurrection_lst]
        )
        replace_queue = list(replace_lst) + list(resurrection_lst)
        emulator_lst: list[int | None] = [
            idx + 1 if party[idx]["exists"] else None for idx in range(6)
        ]
        emulator_tmp = list(emulator_lst)

        for left in resurrection_lst:
            right = replace_queue.pop(0)
            if left != right:
                emulator_lst[left - 1] = emulator_tmp[right - 1]
                if right > 3:
                    emulator_lst[right - 1] = None

        for left in permanent_sacrifices:
            try:
                right = replace_queue.pop(0)
            except IndexError:
                right = None
            if right is None:
                emulator_lst[left - 1] = None
            else:
                emulator_lst[left - 1] = emulator_tmp[right - 1]
                if right > 3:
                    emulator_lst[right - 1] = None

        for i in range(3, 6):
            if emulator_lst[i] is None:
                for j in range(i + 1, 6):
                    if emulator_lst[j] is not None:
                        emulator_lst[i], emulator_lst[j] = (
                            emulator_lst[j],
                            emulator_lst[i],
                        )
                        break
                else:
                    break

        for resurrection in replace_queue:
            for i in range(3, 6):
                if emulator_lst[i] is None:
                    emulator_lst[i] = resurrection
                    break

        record: dict[str, int | None] = {}
        for i in range(6):
            if emulator_lst[i] == emulator_tmp[i]:
                continue
            if emulator_tmp[i] is not None:
                record[str(emulator_tmp[i])] = emulator_lst[i]
        return record

    @staticmethod
    def _apply_turn_replace_record(
        party: list[dict[str, Any]],
        record: dict[str, int | None],
    ) -> list[dict[str, Any]]:
        if not record:
            return party
        previous = [dict(slot_state) for slot_state in party]
        updated = [dict(slot_state) for slot_state in party]
        for dest_str, src_slot in record.items():
            try:
                dest_idx = int(dest_str) - 1
            except (TypeError, ValueError):
                continue
            if not 0 <= dest_idx < 6:
                continue
            if (
                isinstance(src_slot, int)
                and not isinstance(src_slot, bool)
                and 1 <= src_slot <= 6
            ):
                updated[dest_idx] = dict(previous[src_slot - 1])
            else:
                updated[dest_idx] = {
                    "initial_slot": -1,
                    "name": None,
                    "canonical_name": None,
                    "exists": False,
                    "will_num": 0,
                }
        return updated

    def _validate_strategy_file(self, entries: Any) -> dict[str, Any]:
        errors: list[dict[str, str]] = []
        if not isinstance(entries, list):
            errors.append(self._issue("invalid_strategy_file", "", "Strategy file must contain a JSON list."))
            return {"ok": False, "errors": errors, "warnings": []}
        errors.extend(self._validate_strategy_entries(entries, "", tagged=True))
        return {"ok": not errors, "errors": errors, "warnings": []}

    def _validate_strategy_entries(self, entries: Any, field: str, *, tagged: bool) -> list[dict[str, str]]:
        if not isinstance(entries, list):
            return [self._issue("invalid_strategy_list", field, "Strategy value must be a JSON list.")]

        errors: list[dict[str, str]] = []
        for index, entry in enumerate(entries):
            entry_field = f"{field}[{index}]" if field else f"[{index}]"
            if tagged:
                if not isinstance(entry, dict):
                    errors.append(self._issue("invalid_strategy_entry", entry_field, "Strategy entry must be an object."))
                    continue
                if not isinstance(entry.get("tag"), str) or not entry.get("tag"):
                    errors.append(self._issue("missing_strategy_tag", f"{entry_field}.tag", "Strategy tag is missing."))
                strategy = entry.get("strategy")
                strategy_field = f"{entry_field}.strategy"
            else:
                strategy = entry
                strategy_field = entry_field
            errors.extend(self._validate_strategy_payload(strategy, strategy_field))
        return errors

    def _validate_strategy_payload(self, payload: Any, field: str) -> list[dict[str, str]]:
        if not isinstance(payload, dict):
            return [self._issue("invalid_strategy", field, "Strategy payload must be an object.")]

        errors: list[dict[str, str]] = []
        for card_name in ("card1", "card2", "card3"):
            card_field = f"{field}.{card_name}"
            card = payload.get(card_name)
            if card is None:
                errors.append(self._issue("missing_strategy_card", card_field, f"Strategy {card_name} is missing."))
                continue
            if not isinstance(card, dict):
                errors.append(self._issue("invalid_strategy_card", card_field, f"Strategy {card_name} must be an object."))
                continue
            for required_field in ("type", "cards", "criticalStar", "more_or_less"):
                if required_field not in card:
                    errors.append(
                        self._issue(
                            "missing_strategy_card_field",
                            f"{card_field}.{required_field}",
                            f"Strategy {card_name}.{required_field} is missing.",
                        )
                    )
            if "cards" in card and not isinstance(card["cards"], list):
                errors.append(self._issue("invalid_strategy_cards", f"{card_field}.cards", "Strategy cards must be a list."))
            card_type = card.get("type")
            valid_type = isinstance(card_type, int) and not isinstance(card_type, bool) and card_type in {0, 1, 2}
            if "type" in card and not valid_type:
                errors.append(self._issue(
                    "invalid_strategy_card_type", f"{card_field}.type",
                    "Strategy card type must be 0 (NP), 1 (preferred face card), or 2 (any face card).",
                ))
            preferences = card.get("cards")
            if valid_type and card_type in {0, 1} and isinstance(preferences, list):
                valid_preferences = bool(preferences) and all(
                    (isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 3)
                    if card_type == 0 else (
                        isinstance(value, str) and re.fullmatch(r"(?:[1-3][ABQ](?:S[0-9]+)?|S[0-9]+)", value)
                    )
                    for value in preferences
                )
                if not valid_preferences:
                    errors.append(self._issue(
                        "invalid_strategy_card_preferences", f"{card_field}.cards",
                        "NP preferences must contain positions 1 through 3; face preferences must contain card or tag codes.",
                    ))
            stars = card.get("criticalStar")
            if "criticalStar" in card and (
                isinstance(stars, bool) or not isinstance(stars, (int, float)) or not 0 <= stars <= 10
            ):
                errors.append(self._issue(
                    "invalid_strategy_critical_star", f"{card_field}.criticalStar",
                    "Critical star threshold must be a number between 0 and 10.",
                ))
            if "more_or_less" in card and not isinstance(card["more_or_less"], bool):
                errors.append(self._issue(
                    "invalid_strategy_star_comparison", f"{card_field}.more_or_less",
                    "Critical star comparison must be a boolean.",
                ))

        breakpoint = payload.get("breakpoint")
        if (
            not isinstance(breakpoint, list) or len(breakpoint) != 2
            or any(not isinstance(value, bool) for value in breakpoint)
        ):
            errors.append(self._issue("invalid_strategy_breakpoint", f"{field}.breakpoint", "Strategy breakpoint must contain two boolean values."))
        if "colorFirst" in payload and not isinstance(payload["colorFirst"], bool):
            errors.append(self._issue("invalid_strategy_color_first", f"{field}.colorFirst", "Strategy colorFirst must be a boolean."))
        return errors

    def _normalize_server(self, server: str) -> str:
        normalized = server.upper()
        if normalized not in VALID_SERVERS:
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                f"Unsupported server: {server}",
                {"server": server, "valid_servers": sorted(VALID_SERVERS)},
            )
        return normalized

    def _load_servant_catalog(self, server: str) -> dict[str, Any]:
        path = self.data_dir / f"servant_info_{server}.json"
        if not path.is_file():
            raise AppError(
                ErrorCode.DATA_FILE_NOT_FOUND,
                f"Servant catalog not found for server: {server}",
                {"server": server},
            )
        catalog = self._load_json(path)
        if not isinstance(catalog, dict):
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                f"Servant catalog must contain a JSON object: {path.name}",
                {"path": self._relative_path(path)},
            )
        return catalog

    def _servant_name_index(self, server: str) -> set[str]:
        names: set[str] = set()
        for name, details in self._load_servant_catalog(server).items():
            names.add(name)
            if isinstance(details, dict):
                aliases = details.get("other_name")
                if isinstance(aliases, list):
                    names.update(alias for alias in aliases if isinstance(alias, str))
        return names

    def _servant_summary(self, name: str, details: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": name,
            "class": details.get("class"),
            "sn": details.get("SN"),
            "aliases": details.get("other_name") if isinstance(details.get("other_name"), list) else [],
            "skills": details.get("skill_name") if isinstance(details.get("skill_name"), list) else [],
            "skill_types": details.get("skill_type") if isinstance(details.get("skill_type"), list) else [],
            "np_color": details.get("NPcolor"),
        }

    def _master_summary(self, name: str, details: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": name,
            "sn": details.get("SN"),
            "skills": details.get("skill_name") if isinstance(details.get("skill_name"), list) else [],
            "skill_types": details.get("skill_type") if isinstance(details.get("skill_type"), list) else [],
        }

    def _relative_path(self, path: Path) -> str:
        try:
            return path.relative_to(self.data_dir).as_posix()
        except ValueError:
            return path.as_posix()

    @staticmethod
    def _is_inside(path: Path, directory: Path) -> bool:
        try:
            path.relative_to(directory)
        except ValueError:
            return False
        return True

    @staticmethod
    def _issue(code: str, field: str, message: str) -> dict[str, str]:
        return {"code": code, "field": field, "message": message}
