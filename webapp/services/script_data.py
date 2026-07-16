from __future__ import annotations

import json
import os
import re
import tempfile
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from webapp.core.errors import AppError, ErrorCode


VALID_SERVERS = {"CH", "CNTW", "JP"}
TURN_FIELD_RE = re.compile(r"^round(?P<round>\d+)_turn(?P<turn>\d+)_(skill|np|strategy|condition|replace)$")
SETTING_STRATEGY_FIELD_RE = re.compile(r"^round\d+_(?:turn\d+_strategy|extraStrategy)$")
ROUND_NUMBER_RE = re.compile(r"^round(?P<round>\d+)_")
SPECIAL_KEY_NAME_RE = re.compile(
    r"^W(?P<W>-?\d+)H(?P<H>-?\d+)"
    r"DXL(?P<DXL>-?\d+)DXR(?P<DXR>-?\d+)"
    r"DYT(?P<DYT>-?\d+)DYB(?P<DYB>-?\d+)CON(?P<CON>\d+)$"
)


class ScriptDataService:
    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.settings_dir = self.data_dir / "settings"
        self.strategy_dir = self.data_dir / "strategy"

    def list_settings(self) -> list[dict[str, str]]:
        return self._list_named_json(self.settings_dir, "settings")

    def get_setting(self, name: str) -> dict[str, Any]:
        path = self._resolve_named_json(self.settings_dir, name, "settings")
        config = self._load_json(path)
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
        return self._delete_named_json(self.settings_dir, name, "settings")

    def get_setting_plan(self, name: str) -> dict[str, Any]:
        detail = self.get_setting(name)
        config = detail["config"]
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
            "run": self._plan_run(config),
            "special_keys": self._plan_special_keys(config),
            "master": self._plan_master(config),
            "rounds": rounds,
            "summary": {
                **detail["summary"],
                "round_count": len(rounds),
                "action_count": action_count,
            },
            "validation": detail["validation"],
        }

    def list_strategies(self) -> list[dict[str, str]]:
        return self._list_named_json(self.strategy_dir, "strategy")

    def get_strategy(self, name: str) -> dict[str, Any]:
        path = self._resolve_named_json(self.strategy_dir, name, "strategy")
        entries = self._load_json(path)
        validation = self._validate_strategy_file(entries)
        return {
            "name": path.stem,
            "path": self._relative_path(path),
            "entries": entries if isinstance(entries, list) else [],
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
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except JSONDecodeError as exc:
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                f"Invalid JSON data file: {path.name}",
                {"path": self._relative_path(path), "line": exc.lineno, "column": exc.colno},
            ) from exc

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

        equip_value = config.get("assistEquip")
        if isinstance(equip_value, str):
            equip_names = [equip_value] if equip_value else []
        elif isinstance(equip_value, list):
            equip_names = [name for name in equip_value if isinstance(name, str) and name]
        else:
            equip_names = []

        skill_levels = config.get("skillsLevel")
        return {
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
            "skill_levels": skill_levels[:3] if isinstance(skill_levels, list) else [],
            "scroll_limit": config.get("scrollLimit"),
            "interval_after_swipe": config.get("intervalAFswipeAssist", 0.5),
            "no_grand_refresh": bool(config.get("noGrandRefresh")),
            "bond_equip_type": config.get("jbType", "任意"),
            "all_not_skip": bool(config.get("allNotSkip", 1)),
        }

    @staticmethod
    def _plan_run(config: dict[str, Any]) -> dict[str, Any]:
        return {
            "clear_ap": bool(config.get("clearAP")),
            "allow_other_apple": bool(config.get("allowOtherApple")),
            "first_battle_set": bool(config.get("firstBattleSet")),
            "interval_before_fight": config.get("intervalBF", 0),
            "interval_before_choose_card": config.get("intervalBFchooseCard", 0.5),
            "interval_after_fight": config.get("intervalAF", 0),
            "random_time": config.get("randomTime", 0),
            "random_touch": bool(config.get("randomTouch")),
            "no_chain": bool(config.get("noChain")),
            "no_speedup_skill": bool(config.get("noSpeedupSkill")),
            "full_friendship_stop": bool(config.get("fullFriendshipStop")),
            "drop_stop_num": config.get("dropStopNum", 0),
            "drop_image": config.get("dropImage"),
            "game_crash_restart": bool(config.get("gameCrushRestart")),
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
            values = {name: int(value) for name, value in match.groupdict().items()}
            threshold = float(f"0.{values['CON']}")
            if not 0 <= threshold <= 1:
                raise ValueError(f"specialKeys[{index}] has an invalid threshold.")
            assets_marker = "/assets/"
            if assets_marker in normalized_path:
                template_path = normalized_path.split(assets_marker, 1)[1]
            elif normalized_path.startswith("assets/"):
                template_path = normalized_path[7:]
            elif normalized_path.startswith("special_keys/"):
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
        if replace:
            actions.append({"type": "replace", "replacements": replace})
        actions.extend({"type": "skill", "command": skill} for skill in skills)
        actions.extend({"type": "np", "servant": np} for np in nps)
        if strategy:
            actions.append({"type": "strategy", "strategies": strategy})
        return actions

    @staticmethod
    def _list_value(value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

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

        breakpoint = payload.get("breakpoint")
        if not isinstance(breakpoint, list) or len(breakpoint) != 2:
            errors.append(self._issue("invalid_strategy_breakpoint", f"{field}.breakpoint", "Strategy breakpoint must contain two values."))
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
