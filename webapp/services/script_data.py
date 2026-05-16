from __future__ import annotations

import json
import re
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from webapp.core.errors import AppError, ErrorCode


VALID_SERVERS = {"CH", "CNTW", "JP"}
TURN_FIELD_RE = re.compile(r"^round(?P<round>\d+)_turn(?P<turn>\d+)_(skill|np|strategy|condition|replace)$")
SETTING_STRATEGY_FIELD_RE = re.compile(r"^round\d+_(?:turn\d+_strategy|extraStrategy)$")


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
        normalized = name[:-5] if name.lower().endswith(".json") else name
        if not normalized or normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
            raise AppError(
                ErrorCode.DATA_FILE_NOT_FOUND,
                f"{kind.title()} data file not found: {name}",
                {"name": name},
            )

        base = directory.resolve()
        candidate = (base / f"{normalized}.json").resolve()
        if not self._is_inside(candidate, base) or not candidate.is_file():
            raise AppError(
                ErrorCode.DATA_FILE_NOT_FOUND,
                f"{kind.title()} data file not found: {name}",
                {"name": name},
            )
        return candidate

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
