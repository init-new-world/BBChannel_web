from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from PIL import Image, UnidentifiedImageError

from webapp.core.errors import AppError, ErrorCode
from webapp.services.battle_servants import (
    CLASS_LIST,
    STATUS_GRID_COLUMNS,
    STATUS_TILE_SIZE,
    FrontlineServantRecognizer,
)
from webapp.services.equip_templates import (
    MAIN_MATCH_BOX,
    TEMPLATE_SIZE,
    EquipTemplateService,
    _validate_name as validate_equip_name,
)
from webapp.services.resources import ResourceService
from webapp.services.script_data import VALID_SERVERS, ScriptDataService


MOONCELL_API_URL = "https://fgo.wiki/api.php"
ATLAS_API_BASE_URL = "https://api.atlasacademy.io"
ALLOWED_UPSTREAM_HOST_SUFFIXES = (
    "fgo.wiki",
    "atlasacademy.io",
)
DEFAULT_USER_AGENT = "BBChannelWebWikiSync/0.1 (+https://github.com/init-new-world/BBChannel_web)"
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
DEFAULT_CE_FOCUS_Y = 220
CE_REFERENCE_WIDTH = 512
CE_CROP_LEFT = 6
CE_CROP_RIGHT = 506
CE_CROP_HEIGHT = 144
SERVANT_FACE_SIZE = (130, 130)
SKILL_ICON_SIZE = (110, 110)
COMMAND_CARD_SIZE = (256, 256)
STATUS_SOURCE_CROP_256 = (95, 30, 155, 96)
LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"

CLASS_NORMALIZATION: dict[str, str] = {
    "saber": "Saber",
    "archer": "Archer",
    "lancer": "Lancer",
    "rider": "Rider",
    "caster": "Caster",
    "assassin": "Assassin",
    "berserker": "Berserker",
    "alterego": "Alterego",
    "alter ego": "Alterego",
    "avenger": "Avenger",
    "foreigner": "Foreigner",
    "mooncancer": "MoonCancer",
    "moon cancer": "MoonCancer",
    "pretender": "Pretender",
    "ruler": "Ruler",
    "shielder": "Shielder",
    "beast": "Beast",
    "unbeast": "Beast",
}

NP_COLOR_MAP: dict[str, str] = {
    "arts": "A",
    "buster": "B",
    "quick": "Q",
    "a": "A",
    "b": "B",
    "q": "Q",
}

HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
SECTION_LST_RE = re.compile(
    r'<section\s+class=["\']?lst["\']?\s+begin=([^\s/>]+)\s*/>(.*?)<section\s+class=["\']?lst["\']?\s+end=\1\s*/>',
    re.DOTALL | re.IGNORECASE,
)
WIKI_LINK_RE = re.compile(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]")
HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


@dataclass(frozen=True)
class ServantIndexEntry:
    collection_no: int
    name_cn: str
    name_jp: str
    name_en: str
    name_link: str
    aliases: tuple[str, ...]
    method: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class CraftEssenceIndexEntry:
    ce_id: int
    name: str
    name_link: str
    aliases: tuple[str, ...]
    des: str
    des_max: str
    ce_type: str
    event: bool


class WikiClient:
    """Polite HTTP client with optional local TTL caching for Mooncell & Atlas Academy."""

    def __init__(
        self,
        *,
        mooncell_api_url: str = MOONCELL_API_URL,
        atlas_api_base_url: str = ATLAS_API_BASE_URL,
        cache_dir: Path | None = None,
        cache_ttl_seconds: float = 1800.0,
        timeout_seconds: float = 15.0,
        user_agent: str = DEFAULT_USER_AGENT,
        http_get: Callable[[str, dict[str, str], float], tuple[int, dict[str, str], bytes]] | None = None,
    ) -> None:
        self.mooncell_api_url = mooncell_api_url
        self.atlas_api_base_url = atlas_api_base_url.rstrip("/")
        self.cache_dir = cache_dir.resolve() if cache_dir is not None else None
        self.cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.user_agent = user_agent
        self._http_get = http_get or _default_http_get

    def mw_api(self, params: dict[str, Any], *, use_cache: bool = True) -> dict[str, Any]:
        merged = {**params, "format": "json"}
        query = urllib.parse.urlencode(sorted((str(k), str(v)) for k, v in merged.items()))
        url = f"{self.mooncell_api_url}?{query}"
        payload = self._fetch_json(url, source="mooncell", use_cache=use_cache)
        if not isinstance(payload, dict):
            raise AppError(
                ErrorCode.WIKI_UPSTREAM_FAILED,
                "Mooncell API returned an unexpected JSON root type.",
                {"url": url},
            )
        if "error" in payload and isinstance(payload["error"], dict):
            raise AppError(
                ErrorCode.WIKI_UPSTREAM_FAILED,
                f"Mooncell API error: {payload['error'].get('info') or payload['error'].get('code')}",
                {"url": url, "upstream_error": payload["error"]},
            )
        return payload

    def mw_page_contents(self, titles: list[str], *, use_cache: bool = True) -> dict[str, str]:
        cleaned = [t.strip() for t in titles if isinstance(t, str) and t.strip()]
        if not cleaned:
            return {}
        contents: dict[str, str] = {}
        for start in range(0, len(cleaned), 20):
            chunk = cleaned[start : start + 20]
            data = self.mw_api(
                {
                    "action": "query",
                    "titles": "|".join(chunk),
                    "prop": "revisions",
                    "rvprop": "content",
                    "rvslots": "main",
                    "redirects": "1",
                },
                use_cache=use_cache,
            )
            query_obj = data.get("query") or {}
            alias_map: dict[str, str] = {}
            for item in query_obj.get("normalized") or []:
                if isinstance(item, dict) and item.get("from") and item.get("to"):
                    alias_map[str(item["from"])] = str(item["to"])
            redirect_map: dict[str, str] = {}
            for item in query_obj.get("redirects") or []:
                if isinstance(item, dict) and item.get("from") and item.get("to"):
                    redirect_map[str(item["from"])] = str(item["to"])
            by_canonical: dict[str, str] = {}
            for page in (query_obj.get("pages") or {}).values():
                if not isinstance(page, dict) or "missing" in page:
                    continue
                title = str(page.get("title") or "")
                revisions = page.get("revisions") or []
                text = ""
                if revisions and isinstance(revisions[0], dict):
                    slots = revisions[0].get("slots")
                    if isinstance(slots, dict) and isinstance(slots.get("main"), dict):
                        text = str(slots["main"].get("*") or slots["main"].get("content") or "")
                    else:
                        text = str(revisions[0].get("*") or "")
                if title:
                    by_canonical[title] = text
                    contents[title] = text
            for requested in chunk:
                target = alias_map.get(requested, requested)
                visited: set[str] = set()
                while target in redirect_map and target not in visited:
                    visited.add(target)
                    target = redirect_map[target]
                if target in by_canonical:
                    contents[requested] = by_canonical[target]
        return contents

    def mw_image_urls(self, filenames: list[str], *, use_cache: bool = True) -> dict[str, str]:
        cleaned: list[str] = []
        for raw in filenames:
            name = str(raw or "").strip()
            if not name:
                continue
            if not name.startswith(("File:", "文件:")):
                name = f"File:{name}"
            if name not in cleaned:
                cleaned.append(name)
        if not cleaned:
            return {}
        resolved: dict[str, str] = {}
        for start in range(0, len(cleaned), 20):
            chunk = cleaned[start : start + 20]
            data = self.mw_api(
                {
                    "action": "query",
                    "titles": "|".join(chunk),
                    "prop": "imageinfo",
                    "iiprop": "url",
                    "redirects": "1",
                },
                use_cache=use_cache,
            )
            query_obj = data.get("query") or {}
            norm_map: dict[str, str] = {}
            for item in query_obj.get("normalized") or []:
                if isinstance(item, dict) and item.get("from") and item.get("to"):
                    norm_map[str(item["from"])] = str(item["to"])
            by_title: dict[str, str] = {}
            for page in (query_obj.get("pages") or {}).values():
                if not isinstance(page, dict):
                    continue
                title = str(page.get("title") or "")
                infos = page.get("imageinfo") or []
                if infos and isinstance(infos[0], dict) and infos[0].get("url"):
                    url = str(infos[0]["url"])
                    by_title[title] = url
                    bare = title.split(":", 1)[-1]
                    resolved[bare] = url
                    resolved[bare.replace(" ", "_")] = url
            for requested in chunk:
                canonical = norm_map.get(requested, requested)
                if canonical in by_title:
                    bare_req = requested.split(":", 1)[-1]
                    resolved[bare_req] = by_title[canonical]
        return resolved

    def atlas_json(self, path: str, *, use_cache: bool = True) -> Any:
        normalized = path if path.startswith("/") else f"/{path}"
        url = f"{self.atlas_api_base_url}{normalized}"
        return self._fetch_json(url, source="atlas", use_cache=use_cache)

    def fetch_bytes(self, url: str, *, use_cache: bool = True) -> bytes:
        cache_file = self._cache_path("bin", url, ".bin")
        if use_cache and cache_file is not None and self._is_cache_fresh(cache_file, ttl=self.cache_ttl_seconds * 24):
            return cache_file.read_bytes()
        status, headers, body = self._request(url)
        content_type = headers.get("content-type", "").lower()
        if status != 200 or "text/html" in content_type or not body:
            raise AppError(
                ErrorCode.WIKI_UPSTREAM_FAILED,
                f"Failed to download upstream media asset (HTTP {status}).",
                {"url": url, "status": status, "content_type": content_type},
            )
        if cache_file is not None:
            _write_bytes_atomic(cache_file, body)
        return body

    def _fetch_json(self, url: str, *, source: str, use_cache: bool) -> Any:
        cache_file = self._cache_path("json", url, ".json")
        if use_cache and cache_file is not None and self._is_cache_fresh(cache_file, ttl=self.cache_ttl_seconds):
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        status, headers, body = self._request(url)
        content_type = headers.get("content-type", "").lower()
        if status != 200 or "text/html" in content_type:
            raise AppError(
                ErrorCode.WIKI_UPSTREAM_FAILED,
                f"Upstream {source} API returned HTTP {status} ({content_type or 'unknown content-type'}).",
                {"url": url, "source": source, "status": status},
            )
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AppError(
                ErrorCode.WIKI_UPSTREAM_FAILED,
                f"Upstream {source} API response was not valid JSON.",
                {"url": url, "source": source},
            ) from exc
        if cache_file is not None:
            _write_bytes_atomic(cache_file, json.dumps(parsed, ensure_ascii=False).encode("utf-8"))
        return parsed

    def _request(self, url: str) -> tuple[int, dict[str, str], bytes]:
        if self._http_get is _default_http_get:
            extra_hosts = {
                (urllib.parse.urlparse(base).hostname or "").lower()
                for base in (self.mooncell_api_url, self.atlas_api_base_url)
                if base
            }
            _validate_upstream_url(url, extra_hosts=extra_hosts)
        else:
            parsed = urllib.parse.urlparse(str(url or "").strip())
            if parsed.scheme.lower() not in {"https", "http"} or not parsed.hostname:
                raise AppError(
                    ErrorCode.DATA_FILE_INVALID,
                    "Upstream URL must use http(s) with a valid hostname.",
                    {"url": url},
                )
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, image/*;q=0.9, */*;q=0.8",
        }
        try:
            status, resp_headers, body = self._http_get(url, headers, self.timeout_seconds)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                ErrorCode.WIKI_UPSTREAM_FAILED,
                f"Upstream request failed: {exc}",
                {"url": url},
            ) from exc
        normalized_headers = {str(k).lower(): str(v) for k, v in resp_headers.items()}
        return int(status), normalized_headers, body

    def _cache_path(self, kind: str, key: str, suffix: str) -> Path | None:
        if self.cache_dir is None or self.cache_ttl_seconds <= 0:
            return None
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.cache_dir / kind / f"{digest}{suffix}"

    @staticmethod
    def _is_cache_fresh(path: Path, *, ttl: float) -> bool:
        try:
            stat = path.stat()
        except OSError:
            return False
        return stat.st_size > 0 and (time.time() - stat.st_mtime) <= ttl


def _validate_upstream_url(url: str, *, extra_hosts: set[str] | None = None) -> str:
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            "Upstream URL must use https with a valid hostname.",
            {"url": url},
        )
    host = parsed.hostname.lower().rstrip(".")
    allowed_exact = {h.lower().rstrip(".") for h in (extra_hosts or set()) if h}
    if host not in allowed_exact and not any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in ALLOWED_UPSTREAM_HOST_SUFFIXES
    ):
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            f"Upstream URL host is not allowed: {host}",
            {"url": url, "host": host},
        )
    return url


class _SafeHttpsRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_upstream_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_http_get(url: str, headers: dict[str, str], timeout: float) -> tuple[int, dict[str, str], bytes]:
    _validate_upstream_url(url)
    request = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(_SafeHttpsRedirectHandler())
    try:
        with opener.open(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            resp_headers = dict(response.headers.items())
            data = response.read(MAX_DOWNLOAD_BYTES + 1)
            if len(data) > MAX_DOWNLOAD_BYTES:
                raise AppError(
                    ErrorCode.DATA_FILE_INVALID,
                    "Downloaded upstream payload exceeds 20 MB limit.",
                    {"url": url},
                )
            return int(status), resp_headers, data
    except urllib.error.HTTPError as exc:
        resp_headers = dict(exc.headers.items()) if exc.headers else {}
        try:
            exc.close()
        except Exception:
            pass
        return int(exc.code), resp_headers, b""


# ---------------------------------------------------------------------------
# Wikitext & Index Parsers
# ---------------------------------------------------------------------------


def parse_servant_index(raw_text: str) -> list[ServantIndexEntry]:
    entries: list[ServantIndexEntry] = []
    for block in _split_kv_blocks(raw_text):
        raw_id = block.get("id", "").strip()
        if not raw_id.isdigit():
            continue
        collection_no = int(raw_id)
        if collection_no <= 0:
            continue
        aliases = tuple(
            item.strip()
            for item in block.get("name_other", "").split("&")
            if item.strip()
        )
        tags = tuple(
            item.strip()
            for item in block.get("tag", "").split("&")
            if item.strip()
        )
        name_cn = block.get("name_cn", "").strip()
        name_jp = block.get("name_jp", "").strip()
        name_link = block.get("name_link", "").strip() or name_cn or name_jp
        entries.append(
            ServantIndexEntry(
                collection_no=collection_no,
                name_cn=name_cn,
                name_jp=name_jp,
                name_en=block.get("name_en", "").strip(),
                name_link=name_link,
                aliases=aliases,
                method=block.get("method", "").strip(),
                tags=tags,
            )
        )
    entries.sort(key=lambda item: item.collection_no)
    return entries


def parse_ce_index(raw_text: str) -> list[CraftEssenceIndexEntry]:
    entries: list[CraftEssenceIndexEntry] = []
    for block in _split_kv_blocks(raw_text):
        raw_id = block.get("id", "").strip()
        if not raw_id.isdigit():
            continue
        ce_id = int(raw_id)
        if ce_id <= 0:
            continue
        name = block.get("name", "").strip()
        name_link = block.get("name_link", "").strip() or name
        aliases = tuple(
            item.strip()
            for item in block.get("name_other", "").split("&")
            if item.strip()
        )
        entries.append(
            CraftEssenceIndexEntry(
                ce_id=ce_id,
                name=name,
                name_link=name_link,
                aliases=aliases,
                des=block.get("des", "").strip(),
                des_max=block.get("des_max", "").strip(),
                ce_type=block.get("type", "").strip(),
                event=block.get("event", "0").strip() == "1",
            )
        )
    entries.sort(key=lambda item: item.ce_id, reverse=True)
    return entries


def parse_gameinfo_sections(raw_text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    for match in SECTION_LST_RE.finditer(raw_text):
        sections[match.group(1).strip()] = match.group(2).strip()
    return sections


def parse_servant_wikitext(
    wikitext: str,
    index_entry: ServantIndexEntry | None = None,
) -> dict[str, Any]:
    cleaned = HTML_COMMENT_RE.sub("", wikitext)
    base_calls = _extract_template_calls(cleaned, "基础数值")
    if not base_calls:
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            "Mooncell servant page does not contain {{基础数值}}.",
            {"name_link": index_entry.name_link if index_entry else None},
        )
    _, base_named = _split_template_params(base_calls[0])
    sn = base_named.get("从者内部id", "").strip()
    if not sn.isdigit():
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            f"Mooncell servant SN is missing or non-numeric: {sn!r}",
            {"name_link": index_entry.name_link if index_entry else None},
        )
    raw_star = base_named.get("稀有度", "").strip()
    star = int(raw_star) if raw_star.isdigit() else 5
    raw_class = base_named.get("职阶", "").strip()
    servant_class = normalize_servant_class(raw_class)
    raw_no = base_named.get("序号", "").strip()
    collection_no = (
        int(raw_no)
        if raw_no.isdigit()
        else (index_entry.collection_no if index_entry is not None else 0)
    )

    np_calls = _extract_template_calls(cleaned, "宝具")
    np_color = "B"
    if np_calls:
        _, np_named = _split_template_params(np_calls[0])
        raw_color = np_named.get("卡色", "").strip().lower()
        np_color = NP_COLOR_MAP.get(raw_color, "B")

    skill_names, skill_types, skill_details, choice_hints = _parse_active_skills(cleaned)

    cn_name = (
        (index_entry.name_cn if index_entry and index_entry.name_cn else "")
        or base_named.get("中文名", "").strip()
    )
    jp_name = (
        (index_entry.name_jp if index_entry and index_entry.name_jp else "")
        or base_named.get("日文名", "").strip()
    )
    name_link = (
        (index_entry.name_link if index_entry and index_entry.name_link else "")
        or cn_name
        or jp_name
    )

    aliases: list[str] = []
    if index_entry is not None:
        aliases.extend(index_entry.aliases)
    for key in ("中文名", "中文名2", "中文战斗名", "日文名"):
        candidate = base_named.get(key, "").strip()
        if candidate and candidate not in aliases:
            aliases.append(candidate)

    return {
        "collection_no": collection_no,
        "sn": sn,
        "star": star,
        "class": servant_class,
        "np_color": np_color,
        "name_cn": cn_name,
        "name_jp": jp_name,
        "name_link": name_link,
        "aliases": aliases,
        "skill_name": skill_names,
        "skill_type": skill_types,
        "skill_details": skill_details,
        "choice_skill_hints": choice_hints,
    }


def parse_ce_wikitext(
    wikitext: str,
    fallback: CraftEssenceIndexEntry | None = None,
) -> dict[str, Any]:
    cleaned = HTML_COMMENT_RE.sub("", wikitext)
    calls = _extract_template_calls(cleaned, "概念礼装")
    named: dict[str, str] = {}
    if calls:
        _, named = _split_template_params(calls[0])
    raw_id = named.get("礼装id", "").strip()
    ce_id = (
        int(raw_id)
        if raw_id.isdigit()
        else (fallback.ce_id if fallback is not None else 0)
    )
    raw_equip_sn = named.get("礼装内部id", "").strip()
    equip_sn = raw_equip_sn if raw_equip_sn.isdigit() else None
    raw_star = named.get("稀有度", "").strip()
    star = int(raw_star) if raw_star.isdigit() else 5
    cn_name = named.get("名称", "").strip() or (fallback.name if fallback else "")
    jp_name = named.get("日文名称", "").strip()
    link_name = named.get("链接名", "").strip() or (fallback.name_link if fallback else cn_name)
    image_name = named.get("图片名", "").strip() or link_name or cn_name or jp_name
    focus_x, focus_y = _parse_focus_coord(named.get("出场角色坐标", ""))
    skill_text = _clean_wiki_text(named.get("持有技能", "")) or (fallback.des_max or fallback.des if fallback else "")
    event_skill = _clean_wiki_text(named.get("活动技能", ""))
    return {
        "ce_id": ce_id,
        "equip_sn": equip_sn,
        "star": star,
        "name": cn_name or jp_name or f"CE_{ce_id}",
        "jp_name": jp_name,
        "link_name": link_name,
        "image_name": image_name,
        "focus_x": focus_x,
        "focus_y": focus_y,
        "skill": skill_text,
        "event_skill": event_skill,
    }


def parse_event_ce_ids(wikitext: str) -> tuple[list[int], list[str]]:
    """Extract referenced CE IDs and delegated parent event titles from a Mooncell event page."""
    cleaned = HTML_COMMENT_RE.sub("", wikitext)
    ce_ids: list[int] = []

    def add_id(raw: str) -> None:
        if raw.isdigit():
            val = int(raw)
            if val > 0 and val not in ce_ids:
                ce_ids.append(val)

    for tpl_name in ("活动加成礼装", "活动礼装"):
        for body in _extract_template_calls(cleaned, tpl_name):
            _, named = _split_template_params(body)
            for key, value in named.items():
                if "序号" in key and "技能" not in key:
                    for token in re.findall(r"\d+", value):
                        add_id(token)

    for token in re.findall(r"(?:File:|文件:|:)?礼装0*(\d{2,6})(?:\.(?:jpg|png))?", cleaned):
        add_id(token)

    related_pages: list[str] = []
    for body in _extract_template_calls(cleaned, "活动信息"):
        _, named = _split_template_params(body)
        for key in ("主关联页", "关联页面"):
            for token in re.split(r"[,;，；\n]+", named.get(key, "")):
                page = token.strip()
                if page and page not in related_pages:
                    related_pages.append(page)
    return ce_ids, related_pages


# ---------------------------------------------------------------------------
# Image Processing & Cropping
# ---------------------------------------------------------------------------


def crop_ce_banner(
    card_bytes: bytes,
    *,
    focus_y: int = DEFAULT_CE_FOCUS_Y,
    y_offset: int = 0,
    art_source: str = "auto",
) -> tuple[bytes, dict[str, Any]]:
    try:
        with Image.open(BytesIO(card_bytes)) as src:
            src.load()
            if src.width <= 0 or src.height <= 0:
                raise ValueError("Empty image")
            rgb = src.convert("RGB")
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            "Upstream craft essence illustration is not a valid image.",
        ) from exc

    source_size = [rgb.width, rgb.height]
    resolved_source = (
        art_source
        if art_source in {"equip_face", "card_art"}
        else ("equip_face" if rgb.width > rgb.height else "card_art")
    )

    if resolved_source == "equip_face":
        target_w, target_h = TEMPLATE_SIZE
        scaled_height = max(target_h, round(rgb.height * target_w / rgb.width))
        resized = rgb.resize((target_w, scaled_height), Image.Resampling.LANCZOS)
        base_top = (scaled_height - target_h) // 2
        max_top = scaled_height - target_h
        top = max(0, min(max_top, base_top + y_offset))
        crop_box = (0, top, target_w, top + target_h)
        cropped = resized.crop(crop_box)
        out = BytesIO()
        cropped.save(out, format="PNG")
        return out.getvalue(), {
            "art_source": "equip_face",
            "source_size": source_size,
            "normalized_size": [target_w, scaled_height],
            "crop_box": list(crop_box),
            "focus_y": round(scaled_height / 2),
            "y_offset": int(y_offset),
            "max_y_offset": max(base_top, max_top - base_top),
            "effective_center_y": round(top + target_h / 2),
            "template_size": list(TEMPLATE_SIZE),
            "main_match_box": list(MAIN_MATCH_BOX),
        }

    if rgb.width != CE_REFERENCE_WIDTH:
        scaled_height = max(CE_CROP_HEIGHT, round(rgb.height * CE_REFERENCE_WIDTH / rgb.width))
        rgb = rgb.resize((CE_REFERENCE_WIDTH, scaled_height), Image.Resampling.LANCZOS)

    if rgb.height < CE_CROP_HEIGHT:
        rgb = rgb.resize((CE_REFERENCE_WIDTH, CE_CROP_HEIGHT), Image.Resampling.LANCZOS)

    desired_top = round(focus_y - CE_CROP_HEIGHT / 2 + y_offset)
    top = max(0, min(rgb.height - CE_CROP_HEIGHT, desired_top))
    bottom = top + CE_CROP_HEIGHT
    crop_box = (CE_CROP_LEFT, top, CE_CROP_RIGHT, bottom)
    cropped = rgb.crop(crop_box).resize(TEMPLATE_SIZE, Image.Resampling.LANCZOS)

    out = BytesIO()
    cropped.save(out, format="PNG")
    return out.getvalue(), {
        "art_source": "card_art",
        "source_size": source_size,
        "normalized_size": [rgb.width, rgb.height],
        "crop_box": list(crop_box),
        "focus_y": int(focus_y),
        "y_offset": int(y_offset),
        "max_y_offset": 200,
        "effective_center_y": round(top + CE_CROP_HEIGHT / 2),
        "template_size": list(TEMPLATE_SIZE),
        "main_match_box": list(MAIN_MATCH_BOX),
    }


def _resize_rgba_png(image_bytes: bytes, size: tuple[int, int]) -> bytes:
    with Image.open(BytesIO(image_bytes)) as src:
        src.load()
        rgba = src.convert("RGBA")
        if rgba.size != size:
            rgba = rgba.resize(size, Image.Resampling.LANCZOS)
        out = BytesIO()
        rgba.save(out, format="PNG")
        return out.getvalue()


def _status_tile_from_256(image_bytes: bytes) -> Image.Image:
    with Image.open(BytesIO(image_bytes)) as src:
        src.load()
        rgba = src.convert("RGBA")
        if rgba.size != (256, 256):
            rgba = rgba.resize((256, 256), Image.Resampling.LANCZOS)
        bg = Image.new("RGB", (256, 256), (0, 0, 0))
        bg.paste(rgba, mask=rgba.split()[3])
        return bg.crop(STATUS_SOURCE_CROP_256).resize(STATUS_TILE_SIZE, Image.Resampling.LANCZOS)


# ---------------------------------------------------------------------------
# WikiSyncService
# ---------------------------------------------------------------------------


class WikiSyncService:
    def __init__(
        self,
        resources: ResourceService,
        equip_templates: EquipTemplateService,
        *,
        script_data: ScriptDataService | None = None,
        battle_servants: FrontlineServantRecognizer | None = None,
        client: WikiClient | None = None,
    ) -> None:
        self._resources = resources
        self._equip_templates = equip_templates
        self._script_data = script_data
        self._battle_servants = battle_servants
        default_cache = resources.data_dir.parent / ".cache" / "wiki_sync"
        self._client = client or WikiClient(cache_dir=default_cache)
        self._lock = RLock()

    # ---- Event & Craft Essence Workflows ----

    def list_events(self, server: str = "CH", *, limit: int = 8) -> dict[str, Any]:
        normalized_server = _normalize_server_code(server)
        is_jp = normalized_server == "JP"
        smw_server = "jp" if is_jp else "cn"
        sort_prop = "EventStartJP" if is_jp else "EventStart"
        ask_query = (
            f"[[分类:有活动信息的页面]][[EventRecentServer::{smw_server}]]"
            f"|?EventNameJP|?EventStart|?EventEnd|?EventStartJP|?EventEndJP|?EventType"
            f"|sort={sort_prop}|order=desc|limit={max(1, min(int(limit), 20))}"
        )
        ask_data = self._client.mw_api({"action": "ask", "query": ask_query})
        raw_results = (ask_data.get("query") or {}).get("results") or {}
        now_ts = int(time.time())

        ce_index = self._load_ce_index()
        ce_by_id = {entry.ce_id: entry for entry in ce_index}
        local_map = self._local_equip_status_map()
        gameinfo = self._load_gameinfo(is_jp=is_jp)
        patch_new_ces = self._patch_new_ces(ce_index, gameinfo, is_jp=is_jp)

        events: list[dict[str, Any]] = []
        if isinstance(raw_results, dict):
            for title, payload in raw_results.items():
                if not isinstance(payload, dict):
                    continue
                printouts = payload.get("printouts") or {}
                start_ts = _extract_smw_timestamp(
                    printouts.get("EventStartJP" if is_jp else "EventStart")
                    or printouts.get("EventStart")
                )
                end_ts = _extract_smw_timestamp(
                    printouts.get("EventEndJP" if is_jp else "EventEnd")
                    or printouts.get("EventEnd")
                )
                event_types = printouts.get("EventType") or []
                event_type = str(event_types[0]) if event_types else "Event"
                active = bool(start_ts and end_ts and start_ts <= now_ts <= end_ts)
                events.append(
                    {
                        "title": str(title),
                        "jp_title": (printouts.get("EventNameJP") or [str(title)])[0],
                        "type": event_type,
                        "start_timestamp": start_ts,
                        "end_timestamp": end_ts,
                        "active": active,
                    }
                )

        events.sort(
            key=lambda item: (
                1 if item["active"] else 0,
                1 if item["type"] == "Event" else 0,
                item["start_timestamp"] or 0,
            ),
            reverse=True,
        )

        # Resolve event CEs for top events in a single batched page fetch
        candidate_titles: list[str] = []
        for ev in events[:6]:
            t = ev["title"]
            candidate_titles.append(t)
            stripped = _strip_rerun_prefix(t)
            if stripped != t:
                candidate_titles.append(stripped)
        pages = self._client.mw_page_contents(candidate_titles)
        follow_up_titles: list[str] = []
        parsed_by_event: dict[str, list[int]] = {}
        for ev in events[:6]:
            t = ev["title"]
            wikitext = pages.get(t) or pages.get(_strip_rerun_prefix(t)) or ""
            ce_ids, related = parse_event_ce_ids(wikitext)
            parsed_by_event[t] = ce_ids
            if not ce_ids:
                for rel in related:
                    if rel not in pages and rel not in follow_up_titles:
                        follow_up_titles.append(rel)
        if follow_up_titles:
            extra_pages = self._client.mw_page_contents(follow_up_titles)
            pages.update(extra_pages)
            for ev in events[:6]:
                t = ev["title"]
                if parsed_by_event.get(t):
                    continue
                wikitext = pages.get(t) or pages.get(_strip_rerun_prefix(t)) or ""
                _, related = parse_event_ce_ids(wikitext)
                for rel in related:
                    rel_ids, _ = parse_event_ce_ids(pages.get(rel, ""))
                    for cid in rel_ids:
                        if cid not in parsed_by_event[t]:
                            parsed_by_event[t].append(cid)

        for ev in events:
            ids = parsed_by_event.get(ev["title"], [])
            # If a brand-new JP main event page hasn't added {{活动加成礼装}} yet, fall back to patch event=1 CEs
            if not ids and is_jp and ev["active"] and ev["type"] == "Event":
                ids = [entry.ce_id for entry in patch_new_ces if entry.event]
            ev["craft_essences"] = [
                self._serialize_ce_index_entry(ce_by_id[cid], local_map)
                for cid in ids
                if cid in ce_by_id
            ]

        return {
            "server": normalized_server,
            "events": events,
            "patch_craft_essences": [
                self._serialize_ce_index_entry(entry, local_map)
                for entry in patch_new_ces
            ],
        }

    def search_craft_essences(
        self,
        *,
        query: str = "",
        server: str = "CH",
        event_title: str | None = None,
        event_only: bool = False,
        limit: int = 30,
    ) -> dict[str, Any]:
        normalized_server = _normalize_server_code(server)
        ce_index = self._load_ce_index()
        ce_by_id = {entry.ce_id: entry for entry in ce_index}
        local_map = self._local_equip_status_map()
        capped_limit = max(1, min(int(limit), 100))

        if event_title and event_title.strip():
            title = event_title.strip()
            pages = self._client.mw_page_contents([title, _strip_rerun_prefix(title)])
            wikitext = pages.get(title) or pages.get(_strip_rerun_prefix(title)) or ""
            ce_ids, related = parse_event_ce_ids(wikitext)
            if not ce_ids and related:
                rel_pages = self._client.mw_page_contents(related)
                for rel in related:
                    rel_ids, _ = parse_event_ce_ids(rel_pages.get(rel, ""))
                    for cid in rel_ids:
                        if cid not in ce_ids:
                            ce_ids.append(cid)
            if not ce_ids and normalized_server == "JP":
                gameinfo = self._load_gameinfo(is_jp=True)
                ce_ids = [
                    entry.ce_id
                    for entry in self._patch_new_ces(ce_index, gameinfo, is_jp=True)
                    if entry.event
                ]
            candidates = [ce_by_id[cid] for cid in ce_ids if cid in ce_by_id]
        else:
            candidates = ce_index

        if event_only:
            candidates = [entry for entry in candidates if entry.event]

        needle = query.strip().casefold()
        if needle:
            exact_id = int(needle.lstrip("#")) if needle.lstrip("#").isdigit() else None
            filtered: list[CraftEssenceIndexEntry] = []
            for entry in candidates:
                if exact_id is not None and entry.ce_id == exact_id:
                    filtered.insert(0, entry)
                    continue
                haystacks = (
                    str(entry.ce_id),
                    entry.name,
                    entry.name_link,
                    *entry.aliases,
                    entry.ce_type,
                    entry.des,
                    entry.des_max,
                )
                if any(needle in text.casefold() for text in haystacks if text):
                    filtered.append(entry)
            candidates = filtered
        elif not event_title:
            gameinfo = self._load_gameinfo(is_jp=(normalized_server == "JP"))
            patch_ces = self._patch_new_ces(ce_index, gameinfo, is_jp=(normalized_server == "JP"))
            if patch_ces:
                seen = {entry.ce_id for entry in patch_ces}
                candidates = [*patch_ces, *(e for e in candidates if e.ce_id not in seen)]

        items = [
            self._serialize_ce_index_entry(entry, local_map)
            for entry in candidates[:capped_limit]
        ]
        return {
            "total": len(candidates),
            "limit": capped_limit,
            "items": items,
        }

    def preview_craft_essence(self, ce_id: int, *, y_offset: int = 0) -> dict[str, Any]:
        detail, card_bytes = self._fetch_ce_detail_and_art(ce_id)
        cropped_png, crop_meta = crop_ce_banner(
            card_bytes,
            focus_y=detail["focus_y"],
            y_offset=y_offset,
            art_source=str(detail.get("art_source") or "auto"),
        )
        recommended_name = sanitize_template_name(detail["name"])
        local_map = self._local_equip_status_map()
        return {
            **detail,
            "recommended_name": recommended_name,
            "local_status": local_map.get(recommended_name),
            "crop": crop_meta,
            "preview_base64": base64.b64encode(cropped_png).decode("ascii"),
        }

    def import_craft_essence(
        self,
        ce_id: int,
        *,
        name: str | None = None,
        y_offset: int = 0,
        activate: bool = True,
        save_drop: bool = False,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            detail, card_bytes = self._fetch_ce_detail_and_art(ce_id)
            target_name = validate_equip_name(
                name.strip() if isinstance(name, str) and name.strip() else sanitize_template_name(detail["name"])
            )
            target_location = "active" if activate else "archive"
            if not overwrite:
                target_dir = (
                    self._resources.assets_dir / "assist" / "assist_equip"
                    if activate
                    else self._resources.assets_dir / "equipmaker" / "assist_equip_store"
                )
                if (target_dir / f"{target_name}.png").exists():
                    raise AppError(
                        ErrorCode.DATA_FILE_CONFLICT,
                        f"Equip template already exists in {target_location}: {target_name}",
                        {"name": target_name, "location": target_location},
                    )
                if save_drop and (self._resources.assets_dir / "drop" / f"{target_name}.png").exists():
                    raise AppError(
                        ErrorCode.DATA_FILE_CONFLICT,
                        f"Drop template already exists: drop/{target_name}.png",
                        {"name": target_name, "path": f"drop/{target_name}.png"},
                    )

            cropped_png, crop_meta = crop_ce_banner(
                card_bytes,
                focus_y=detail["focus_y"],
                y_offset=y_offset,
                art_source=str(detail.get("art_source") or "auto"),
            )
            prepared_drop_png: bytes | None = None
            if save_drop:
                prepared_drop_png = self._prepare_ce_drop_icon_png(detail["ce_id"], card_bytes)

            template_desc = self._equip_templates.build(
                target_name,
                full_image=cropped_png,
                non_full_image=None,
                overwrite=overwrite,
                location=target_location,
            )

            drop_path_rel: str | None = None
            if save_drop and prepared_drop_png is not None:
                drop_dir = self._resources.assets_dir / "drop"
                drop_dir.mkdir(parents=True, exist_ok=True)
                _write_bytes_atomic(drop_dir / f"{target_name}.png", prepared_drop_png)
                drop_path_rel = f"drop/{target_name}.png"

            self._resources.refresh_template_index()
            return {
                "ce_id": detail["ce_id"],
                "ce_name": detail["name"],
                "template": template_desc,
                "crop": crop_meta,
                "drop_template_path": drop_path_rel,
            }

    # ---- Servant Discovery & Sync Workflows ----

    def check_servants(self) -> dict[str, Any]:
        index_entries = self._load_servant_index()
        cn_info = self._load_gameinfo(is_jp=False)
        jp_info = self._load_gameinfo(is_jp=True)
        cn_max_no = _safe_int(cn_info.get("cnsvts"), default=0)
        jp_max_no = _safe_int(jp_info.get("jpsvts"), default=max((e.collection_no for e in index_entries), default=0))

        jp_catalog = self._read_servant_catalog("JP")
        existing_sns = {
            str(info.get("SN")).strip()
            for info in jp_catalog.values()
            if isinstance(info, dict) and info.get("SN") is not None
        }
        existing_names = set(jp_catalog.keys())
        for info in jp_catalog.values():
            if isinstance(info, dict) and isinstance(info.get("other_name"), list):
                existing_names.update(str(a) for a in info["other_name"] if isinstance(a, str))

        # Check recent entries + any entry whose name/link isn't already known locally
        # Skip unobtainable enemy bosses (e.g. method="无法获得").
        obtainable_entries = [
            entry
            for entry in index_entries
            if "无法获得" not in (entry.method or "")
        ]
        suspects = [
            entry
            for entry in obtainable_entries
            if entry.collection_no > max(0, len(existing_sns) - 10)
            or (
                entry.name_link not in existing_names
                and entry.name_cn not in existing_names
                and entry.name_jp not in existing_names
            )
        ]
        pages = self._client.mw_page_contents([e.name_link for e in suspects])
        missing: list[dict[str, Any]] = []
        for entry in suspects:
            wikitext = pages.get(entry.name_link, "")
            if not wikitext:
                continue
            try:
                parsed = parse_servant_wikitext(wikitext, entry)
            except AppError:
                continue
            if parsed["sn"] not in existing_sns:
                missing.append(
                    {
                        "collection_no": entry.collection_no,
                        "sn": parsed["sn"],
                        "name_cn": parsed["name_cn"],
                        "name_jp": parsed["name_jp"],
                        "name_link": entry.name_link,
                        "class": parsed["class"],
                        "star": parsed["star"],
                        "np_color": parsed["np_color"],
                        "in_cn": entry.collection_no <= cn_max_no if cn_max_no else False,
                    }
                )

        return {
            "local_servant_count": len(existing_sns),
            "mooncell_cn_max_no": cn_max_no,
            "mooncell_jp_max_no": jp_max_no,
            "missing_count": len(missing),
            "missing_servants": missing,
        }

    def sync_servants(
        self,
        *,
        ids: list[int] | None = None,
        since_id: int | None = None,
        include_charagraph: bool = False,
        update_existing: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            index_entries = self._load_servant_index()
            by_no = {entry.collection_no: entry for entry in index_entries}
            catalogs = {srv: self._read_servant_catalog(srv) for srv in sorted(VALID_SERVERS)}
            sn_to_canonical: dict[str, str] = {}
            for canonical_key, details in catalogs["JP"].items():
                if isinstance(details, dict) and details.get("SN") is not None:
                    sn_to_canonical[str(details["SN"]).strip()] = canonical_key

            if ids:
                targets = [by_no[cid] for cid in ids if cid in by_no]
            elif since_id is not None:
                targets = [
                    entry
                    for entry in index_entries
                    if entry.collection_no > int(since_id) and "无法获得" not in (entry.method or "")
                ]
            else:
                check_report = self.check_servants()
                missing_nos = {item["collection_no"] for item in check_report["missing_servants"]}
                targets = [entry for entry in index_entries if entry.collection_no in missing_nos]

            if not targets:
                return {"dry_run": dry_run, "synced_count": 0, "servants": [], "warnings": []}

            pages = self._client.mw_page_contents([entry.name_link for entry in targets])
            skill_db = self._read_skill_details()
            servants_skill_map = dict(skill_db.get("servants") or {})

            # Collect all missing skill icon filenames to resolve URLs in one batch
            parsed_targets: list[tuple[ServantIndexEntry, dict[str, Any]]] = []
            needed_skill_icons: list[str] = []
            warnings: list[str] = []

            for entry in targets:
                wikitext = pages.get(entry.name_link, "")
                if not wikitext:
                    warnings.append(f"Skipped #{entry.collection_no} ({entry.name_link}): Mooncell page missing.")
                    continue
                try:
                    parsed = parse_servant_wikitext(wikitext, entry)
                except AppError as exc:
                    warnings.append(f"Skipped #{entry.collection_no} ({entry.name_link}): {exc.message}")
                    continue
                if parsed["sn"] in sn_to_canonical and not update_existing:
                    continue
                parsed_targets.append((entry, parsed))
                for icon_name in parsed["skill_name"]:
                    icon_file = self._resources.assets_dir / "servant_skill" / f"{sanitize_filename_component(icon_name)}.png"
                    icon_filename = f"{icon_name}.png"
                    if not icon_file.is_file() and icon_filename not in needed_skill_icons:
                        needed_skill_icons.append(icon_filename)

            skill_icon_urls = self._client.mw_image_urls(needed_skill_icons) if needed_skill_icons and not dry_run else {}
            status_info = self._read_status_info()
            status_tiles_to_append: dict[str, list[tuple[str, Image.Image]]] = {}
            synced_summaries: list[dict[str, Any]] = []
            working_jp_catalog = dict(catalogs["JP"])

            for entry, parsed in parsed_targets:
                sn = parsed["sn"]
                canonical = sn_to_canonical.get(sn) or _choose_canonical_servant_name(
                    parsed,
                    existing_catalog=working_jp_catalog,
                )
                sn_to_canonical[sn] = canonical

                if parsed["choice_skill_hints"]:
                    warnings.append(
                        f"{canonical} (SN {sn}) has modal/choice skill wording in {parsed['choice_skill_hints']}; "
                        "verify if special skill variant handling is needed."
                    )

                try:
                    atlas_data = None if dry_run else self._fetch_atlas_servant(sn, entry.collection_no)
                except AppError as exc:
                    warnings.append(f"Skipped #{entry.collection_no} ({canonical}): {exc.message}")
                    continue
                face_urls, cmd_urls, status_urls, charagraph_urls = _extract_atlas_asset_urls(atlas_data)

                face_count = max(len(face_urls), 4)
                cmd_count = max(len([k for k in cmd_urls if k.startswith("card_servant_")]), 3)
                graph_count = max(len(charagraph_urls), 4)

                existing_jp_record = catalogs["JP"].get(canonical) if isinstance(catalogs["JP"].get(canonical), dict) else {}
                existing_aliases = [
                    str(a)
                    for a in (existing_jp_record.get("other_name") or [])
                    if isinstance(a, str) and a and a != canonical
                ]
                other_names = [
                    *existing_aliases,
                    *[
                        alias
                        for alias in [parsed["name_cn"], parsed["name_link"], *parsed["aliases"]]
                        if alias and alias != canonical
                    ],
                ]
                dedup_aliases: list[str] = []
                for alias in other_names:
                    if alias not in dedup_aliases:
                        dedup_aliases.append(alias)

                record = {
                    "skill_name": [sanitize_filename_component(s) for s in parsed["skill_name"]],
                    "skill_type": parsed["skill_type"],
                    "star": parsed["star"],
                    "class": parsed["class"],
                    "SN": sn,
                    "command_card_types": len(cmd_urls) or cmd_count,
                    "graph_types": graph_count,
                    "servant_face_types": face_count,
                    "other_name": dedup_aliases,
                    "graph": existing_jp_record.get("graph", 1),
                    "command_card": existing_jp_record.get("command_card", 1),
                    "servant_face": existing_jp_record.get("servant_face", 1),
                    "NPcolor": parsed["np_color"],
                }

                assets_written: dict[str, int] = {
                    "skill_icons": 0,
                    "servant_faces": 0,
                    "command_cards": 0,
                    "status_tiles": 0,
                    "charagraphs": 0,
                }

                if not dry_run:
                    staged_files: list[tuple[Path, bytes]] = []
                    staged_status_tiles: list[tuple[str, Image.Image]] = []
                    try:
                        # 1. Skill icons
                        skill_dir = self._resources.assets_dir / "servant_skill"
                        for raw_icon in parsed["skill_name"]:
                            safe_icon = sanitize_filename_component(raw_icon)
                            icon_path = skill_dir / f"{safe_icon}.png"
                            icon_url = skill_icon_urls.get(f"{raw_icon}.png") or skill_icon_urls.get(f"{raw_icon}.png".replace(" ", "_"))
                            if not icon_path.is_file() and icon_url:
                                raw_bytes = self._client.fetch_bytes(icon_url)
                                staged_files.append((icon_path, _resize_rgba_png(raw_bytes, SKILL_ICON_SIZE)))
                                assets_written["skill_icons"] += 1

                        # 2. Servant faces (130x130)
                        face_dir = self._resources.assets_dir / "servantface"
                        for idx, (_, url) in enumerate(face_urls, start=1):
                            raw_bytes = self._client.fetch_bytes(url)
                            face_path = face_dir / f"{canonical}_{idx}.png"
                            staged_files.append((face_path, _resize_rgba_png(raw_bytes, SERVANT_FACE_SIZE)))
                            assets_written["servant_faces"] += 1

                        # 3. Command cards (256x256 in commands_JP/{SN}/)
                        cmd_dir = (self._resources.assets_dir / "commands_JP" / sn).resolve()
                        for filename, url in cmd_urls.items():
                            safe_cmd_name = f"{sanitize_filename_component(Path(filename).stem)}.png"
                            cmd_path = (cmd_dir / safe_cmd_name).resolve()
                            if not cmd_path.is_relative_to(cmd_dir):
                                continue
                            raw_bytes = self._client.fetch_bytes(url)
                            staged_files.append((cmd_path, _resize_rgba_png(raw_bytes, COMMAND_CARD_SIZE)))
                            assets_written["command_cards"] += 1

                        # 4. Battle frontline status tiles (50x55)
                        servant_class = parsed["class"]
                        existing_class_entries = set(status_info.get(servant_class) or [])
                        for idx, (_, url) in enumerate(status_urls, start=1):
                            entry_name = f"{canonical}_{idx}.png"
                            if entry_name in existing_class_entries:
                                continue
                            raw_bytes = self._client.fetch_bytes(url)
                            tile_img = _status_tile_from_256(raw_bytes)
                            staged_status_tiles.append((entry_name, tile_img))
                            existing_class_entries.add(entry_name)
                            assets_written["status_tiles"] += 1

                        # 5. Optional CharaGraph (512x724)
                        if include_charagraph and charagraph_urls:
                            cg_dir = self._resources.assets_dir / "charagraph"
                            for idx, (_, url) in enumerate(charagraph_urls, start=1):
                                raw_bytes = self._client.fetch_bytes(url)
                                with Image.open(BytesIO(raw_bytes)) as im:
                                    im.load()
                                    out = BytesIO()
                                    im.convert("RGBA").save(out, format="PNG")
                                staged_files.append((cg_dir / f"{sn}_{idx}.png", out.getvalue()))
                                assets_written["charagraphs"] += 1
                    except (AppError, OSError, UnidentifiedImageError) as exc:
                        reason = exc.message if isinstance(exc, AppError) else str(exc)
                        warnings.append(f"Skipped #{entry.collection_no} ({canonical}): asset sync failed ({reason}).")
                        continue

                    for dest_path, payload_bytes in staged_files:
                        _write_bytes_atomic(dest_path, payload_bytes)
                    if staged_status_tiles:
                        status_tiles_to_append.setdefault(parsed["class"], []).extend(staged_status_tiles)

                    for srv in sorted(VALID_SERVERS):
                        srv_existing = catalogs[srv].get(canonical) if isinstance(catalogs[srv].get(canonical), dict) else {}
                        srv_record = dict(record)
                        if srv_existing:
                            srv_aliases = [
                                str(a)
                                for a in (srv_existing.get("other_name") or [])
                                if isinstance(a, str) and a and a != canonical
                            ]
                            merged_aliases = list(dict.fromkeys([*srv_aliases, *record["other_name"]]))
                            srv_record["other_name"] = merged_aliases
                            for pref_key in ("graph", "command_card", "servant_face"):
                                if pref_key in srv_existing:
                                    srv_record[pref_key] = srv_existing[pref_key]
                        catalogs[srv][canonical] = srv_record
                    servants_skill_map[sn] = parsed["skill_details"]

                working_jp_catalog[canonical] = dict(record)

                synced_summaries.append(
                    {
                        "collection_no": entry.collection_no,
                        "canonical_name": canonical,
                        "sn": sn,
                        "class": parsed["class"],
                        "star": parsed["star"],
                        "np_color": parsed["np_color"],
                        "skill_name": record["skill_name"],
                        "skill_type": record["skill_type"],
                        "assets_written": assets_written,
                    }
                )

            if not dry_run and synced_summaries:
                if status_tiles_to_append:
                    self._append_status_tiles(status_info, status_tiles_to_append)
                for srv, catalog in catalogs.items():
                    _write_json_atomic(self._resources.data_dir / f"servant_info_{srv}.json", catalog)
                skill_db["servants"] = servants_skill_map
                _write_json_atomic(self._resources.data_dir / "skill_details.json", skill_db)
                self._resources.refresh_template_index()
                if self._script_data is not None:
                    self._script_data.invalidate_catalog_cache()
                if self._battle_servants is not None:
                    self._battle_servants.invalidate_cache()

            return {
                "dry_run": dry_run,
                "synced_count": len(synced_summaries),
                "servants": synced_summaries,
                "warnings": warnings,
            }

    # ---- Internal Helpers ----

    def _load_servant_index(self) -> list[ServantIndexEntry]:
        pages = self._client.mw_page_contents(["英灵图鉴/数据"])
        return parse_servant_index(pages.get("英灵图鉴/数据", ""))

    def _load_ce_index(self) -> list[CraftEssenceIndexEntry]:
        pages = self._client.mw_page_contents(["礼装图鉴/数据"])
        return parse_ce_index(pages.get("礼装图鉴/数据", ""))

    def _load_gameinfo(self, *, is_jp: bool) -> dict[str, str]:
        title = "Mooncell:Gameinfo/日服/灵基一览" if is_jp else "Mooncell:Gameinfo/国服/灵基一览"
        pages = self._client.mw_page_contents([title])
        return parse_gameinfo_sections(pages.get(title, ""))

    @staticmethod
    def _patch_new_ces(
        ce_index: list[CraftEssenceIndexEntry],
        gameinfo: dict[str, str],
        *,
        is_jp: bool,
    ) -> list[CraftEssenceIndexEntry]:
        prev_key = "jpprevces" if is_jp else "cnprevces"
        curr_key = "jpces" if is_jp else "cnces"
        prev_id = _safe_int(gameinfo.get(prev_key), default=0)
        curr_id = _safe_int(gameinfo.get(curr_key), default=0)
        ahead_ids: set[int] = set()
        if not is_jp:
            curr_ahead = {int(x) for x in re.findall(r"\d+", gameinfo.get("cnaheadces", ""))}
            prev_ahead = {int(x) for x in re.findall(r"\d+", gameinfo.get("cnprevaheadces", ""))}
            ahead_ids = curr_ahead - prev_ahead
        if curr_id > prev_id > 0 or ahead_ids:
            matched = [
                entry
                for entry in ce_index
                if (prev_id < entry.ce_id <= curr_id) or (entry.ce_id in ahead_ids)
            ]
            if matched:
                return matched
        return [entry for entry in ce_index if entry.event][:8]

    def _fetch_ce_detail_and_art(self, ce_id: int) -> tuple[dict[str, Any], bytes]:
        if ce_id <= 0:
            raise AppError(ErrorCode.DATA_FILE_INVALID, "ce_id must be a positive integer.", {"ce_id": ce_id})
        ce_index = self._load_ce_index()
        fallback = next((item for item in ce_index if item.ce_id == ce_id), None)
        lookup_title = fallback.name_link if fallback is not None else f"礼装{ce_id}"
        pages = self._client.mw_page_contents([lookup_title])
        wikitext = pages.get(lookup_title, "")
        if not wikitext and fallback is None:
            raise AppError(
                ErrorCode.DATA_FILE_NOT_FOUND,
                f"Craft essence #{ce_id} was not found on Mooncell Wiki.",
                {"ce_id": ce_id},
            )
        detail = parse_ce_wikitext(wikitext, fallback)

        card_bytes: bytes | None = None
        art_source = "card_art"
        equip_sn = str(detail.get("equip_sn") or "").strip()

        # Prefer FGO's official in-game support banner sprite (EquipFaces, 150x68)
        # from Atlas Academy, which matches real game support rows far more accurately
        # than cropping the full 512x875 card illustration.
        if equip_sn.isdigit():
            direct_equip_face_url = f"https://static.atlasacademy.io/JP/EquipFaces/f_{equip_sn}0.png"
            try:
                card_bytes = self._client.fetch_bytes(direct_equip_face_url)
                art_source = "equip_face"
            except AppError:
                try:
                    atlas_equip = self._client.atlas_json(f"/nice/JP/equip/{equip_sn}?lore=false")
                    ef_map = ((atlas_equip.get("extraAssets") or {}).get("equipFace") or {}).get("equip") or {}
                    ef_url = next((str(v) for v in ef_map.values() if v), None)
                    if ef_url:
                        card_bytes = self._client.fetch_bytes(ef_url)
                        art_source = "equip_face"
                except AppError:
                    card_bytes = None

        image_filename = f"{detail['image_name']}.png"
        if card_bytes is None:
            urls = self._client.mw_image_urls([image_filename])
            url = urls.get(image_filename) or urls.get(image_filename.replace(" ", "_"))
            if url:
                card_bytes = self._client.fetch_bytes(url)
                art_source = "card_art"
            elif equip_sn.isdigit():
                atlas_equip = self._client.atlas_json(f"/nice/JP/equip/{equip_sn}?lore=false")
                cg_map = ((atlas_equip.get("extraAssets") or {}).get("charaGraph") or {}).get("equip") or {}
                atlas_url = next((str(v) for v in cg_map.values() if v), None)
                if atlas_url:
                    card_bytes = self._client.fetch_bytes(atlas_url)
                    art_source = "card_art"

        if card_bytes is None:
            raise AppError(
                ErrorCode.WIKI_UPSTREAM_FAILED,
                f"Could not locate card illustration for CE #{ce_id} ({detail['name']}).",
                {"ce_id": ce_id, "image_name": image_filename},
            )
        detail["art_source"] = art_source
        return detail, card_bytes

    def _prepare_ce_drop_icon_png(
        self,
        ce_id: int,
        fallback_card_bytes: bytes,
    ) -> bytes:
        candidates = [f"礼装{ce_id:03d}.jpg", f"礼装{ce_id}.jpg", f"礼装{ce_id:04d}.jpg"]
        urls = self._client.mw_image_urls(candidates)
        icon_url = next((urls[c] for c in candidates if c in urls), None)
        try:
            if icon_url:
                raw_icon = self._client.fetch_bytes(icon_url)
                with Image.open(BytesIO(raw_icon)) as im:
                    im.load()
                    out = BytesIO()
                    im.convert("RGB").save(out, format="PNG")
                    return out.getvalue()
            with Image.open(BytesIO(fallback_card_bytes)) as im:
                im.load()
                rgb = im.convert("RGB").resize((132, 144), Image.Resampling.LANCZOS)
                out = BytesIO()
                rgb.save(out, format="PNG")
                return out.getvalue()
        except (OSError, UnidentifiedImageError) as exc:
            raise AppError(
                ErrorCode.DATA_FILE_INVALID,
                f"Failed to decode craft essence drop icon for CE #{ce_id}.",
                {"ce_id": ce_id},
            ) from exc

    def _local_equip_status_map(self) -> dict[str, str]:
        status: dict[str, str] = {}
        for item in self._equip_templates.inventory():
            name = str(item.get("name") or "")
            loc = str(item.get("location") or "")
            if not name:
                continue
            if loc == "active" or name not in status:
                status[name] = loc
        return status

    @staticmethod
    def _serialize_ce_index_entry(
        entry: CraftEssenceIndexEntry,
        local_map: dict[str, str],
    ) -> dict[str, Any]:
        rec_name = sanitize_template_name(entry.name)
        return {
            "ce_id": entry.ce_id,
            "name": entry.name,
            "name_link": entry.name_link,
            "recommended_name": rec_name,
            "aliases": list(entry.aliases),
            "type": entry.ce_type,
            "event": entry.event,
            "effect": entry.des_max or entry.des,
            "local_status": local_map.get(rec_name),
        }

    def _fetch_atlas_servant(self, sn: str, collection_no: int) -> dict[str, Any]:
        for identifier in (sn, str(collection_no)):
            if not identifier or identifier == "0":
                continue
            try:
                data = self._client.atlas_json(f"/nice/JP/servant/{identifier}?lore=false")
                if isinstance(data, dict) and data.get("extraAssets"):
                    return data
            except AppError:
                continue
        raise AppError(
            ErrorCode.WIKI_UPSTREAM_FAILED,
            f"Could not fetch Atlas Academy servant assets for SN {sn} (#{collection_no}).",
            {"sn": sn, "collection_no": collection_no},
        )

    def _read_servant_catalog(self, server: str) -> dict[str, Any]:
        path = self._resources.data_dir / f"servant_info_{server}.json"
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_skill_details(self) -> dict[str, Any]:
        path = self._resources.data_dir / "skill_details.json"
        if not path.is_file():
            return {"servants": {}, "masters": {}}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"servants": {}, "masters": {}}

    def _read_status_info(self) -> dict[str, list[str]]:
        path = self._resources.assets_dir / "status" / "status_info.json"
        if not path.is_file():
            return {cls: [] for cls in CLASS_LIST}
        raw = path.read_bytes()
        if raw.startswith(LFS_POINTER_PREFIX):
            self._try_pull_lfs("assets/status/status_info.json")
            raw = path.read_bytes()
        if raw.startswith(LFS_POINTER_PREFIX):
            raise AppError(
                ErrorCode.TEMPLATE_LOAD_FAILED,
                "assets/status/status_info.json is an unpulled Git LFS pointer; run `git lfs pull --include='assets/status/*' first.",
            )
        data = json.loads(raw.decode("utf-8"))
        return {cls: list(data.get(cls) or []) for cls in CLASS_LIST}

    def _append_status_tiles(
        self,
        status_info: dict[str, list[str]],
        pending: dict[str, list[tuple[str, Image.Image]]],
    ) -> None:
        status_dir = self._resources.assets_dir / "status"
        status_dir.mkdir(parents=True, exist_ok=True)
        tile_w, tile_h = STATUS_TILE_SIZE
        sheet_w = STATUS_GRID_COLUMNS * tile_w

        for class_name, items in pending.items():
            if not items:
                continue
            sheet_path = status_dir / f"{class_name}.png"
            entries = list(status_info.get(class_name) or [])
            if sheet_path.is_file():
                raw = sheet_path.read_bytes()
                if raw.startswith(LFS_POINTER_PREFIX):
                    self._try_pull_lfs(f"assets/status/{class_name}.png")
                    raw = sheet_path.read_bytes()
                if raw.startswith(LFS_POINTER_PREFIX):
                    raise AppError(
                        ErrorCode.TEMPLATE_LOAD_FAILED,
                        f"assets/status/{class_name}.png is an unpulled Git LFS pointer; run `git lfs pull --include='assets/status/*' first.",
                        {"class": class_name},
                    )
                with Image.open(BytesIO(raw)) as existing_img:
                    existing_img.load()
                    old_sheet = existing_img.convert("RGB")
            else:
                old_sheet = Image.new("RGB", (sheet_w, tile_h), (0, 0, 0))

            total_count = len(entries) + len(items)
            rows = max(1, math.ceil(total_count / STATUS_GRID_COLUMNS))
            new_sheet = Image.new("RGB", (sheet_w, rows * tile_h), (0, 0, 0))
            new_sheet.paste(old_sheet, (0, 0))

            for entry_name, tile_img in items:
                idx = len(entries)
                row, col = divmod(idx, STATUS_GRID_COLUMNS)
                new_sheet.paste(tile_img, (col * tile_w, row * tile_h))
                entries.append(entry_name)

            out = BytesIO()
            new_sheet.save(out, format="PNG")
            _write_bytes_atomic(sheet_path, out.getvalue())
            status_info[class_name] = entries

        _write_json_atomic(status_dir / "status_info.json", status_info)

    def _try_pull_lfs(self, include_pattern: str) -> None:
        repo_root = self._resources.assets_dir.parent
        if not (repo_root / ".git").exists():
            return
        try:
            subprocess.run(
                ["git", "lfs", "pull", f"--include={include_pattern}"],
                cwd=repo_root,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return


# ---------------------------------------------------------------------------
# Pure Utility Functions
# ---------------------------------------------------------------------------


def normalize_servant_class(raw_class: str) -> str:
    cleaned = raw_class.strip()
    lowered = cleaned.casefold()
    if lowered in CLASS_NORMALIZATION:
        return CLASS_NORMALIZATION[lowered]
    if lowered.startswith("beast"):
        return "Beast"
    for canonical in CLASS_LIST:
        if canonical.casefold() == lowered:
            return canonical
    raise AppError(
        ErrorCode.DATA_FILE_INVALID,
        f"Unsupported servant class from Mooncell: {raw_class!r}",
        {"class": raw_class},
    )


def sanitize_filename_component(value: str) -> str:
    replacements = {
        "/": "／",
        "\\": "＼",
        ":": "：",
        "*": "＊",
        "?": "？",
        '"': "＂",
        "<": "＜",
        ">": "＞",
        "|": "｜",
    }
    out = "".join(replacements.get(ch, ch) for ch in value.strip() if ord(ch) >= 32)
    return out.rstrip(". ") or "unnamed"


def sanitize_template_name(value: str) -> str:
    sanitized = sanitize_filename_component(value)
    return sanitized[:100].rstrip(". ") or "unnamed"


def _normalize_server_code(server: str) -> str:
    normalized = (server or "CH").strip().upper()
    if normalized not in VALID_SERVERS:
        raise AppError(
            ErrorCode.DATA_FILE_INVALID,
            f"Unsupported server: {server}",
            {"server": server, "valid_servers": sorted(VALID_SERVERS)},
        )
    return normalized


def _split_kv_blocks(raw_text: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                blocks.append(current)
                current = {}
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            current[key.strip()] = val.strip()
    if current:
        blocks.append(current)
    return blocks


def _extract_template_calls(text: str, template_name: str) -> list[str]:
    """Extract inner parameter bodies of `{{template_name|...}}` handling nested `{{...}}`."""
    bodies: list[str] = []
    idx = 0
    length = len(text)
    target_len = len(template_name)
    while idx < length:
        start = text.find("{{", idx)
        if start < 0:
            break
        cursor = start + 2
        while cursor < length and text[cursor] in " \t\r\n":
            cursor += 1
        if text.startswith(template_name, cursor):
            after_name = cursor + target_len
            if after_name < length and text[after_name] in " \t\r\n|}":
                depth = 1
                pos = after_name
                while pos < length and depth > 0:
                    if text.startswith("{{", pos):
                        depth += 1
                        pos += 2
                    elif text.startswith("}}", pos):
                        depth -= 1
                        if depth == 0:
                            body = text[after_name:pos]
                            if body.lstrip().startswith("|"):
                                body = body.lstrip()[1:]
                            bodies.append(body)
                            idx = pos + 2
                            break
                        pos += 2
                    else:
                        pos += 1
                else:
                    break
                continue
        idx = start + 2
    return bodies


def _split_template_params(body: str) -> tuple[list[str], dict[str, str]]:
    parts: list[str] = []
    buf: list[str] = []
    brace_depth = 0
    link_depth = 0
    pos = 0
    length = len(body)
    while pos < length:
        if body.startswith("{{", pos):
            brace_depth += 1
            buf.append("{{")
            pos += 2
        elif body.startswith("}}", pos) and brace_depth > 0:
            brace_depth -= 1
            buf.append("}}")
            pos += 2
        elif body.startswith("[[", pos):
            link_depth += 1
            buf.append("[[")
            pos += 2
        elif body.startswith("]]", pos) and link_depth > 0:
            link_depth -= 1
            buf.append("]]")
            pos += 2
        elif body[pos] == "|" and brace_depth == 0 and link_depth == 0:
            parts.append("".join(buf))
            buf = []
            pos += 1
        else:
            buf.append(body[pos])
            pos += 1
    parts.append("".join(buf))

    positional: list[str] = []
    named: dict[str, str] = {}
    for raw_part in parts:
        eq_pos = _top_level_equals(raw_part)
        if eq_pos is not None:
            key = raw_part[:eq_pos].strip()
            val = raw_part[eq_pos + 1 :].strip()
            if key:
                named[key] = val
                continue
        positional.append(raw_part.strip())
    return positional, named


def _top_level_equals(segment: str) -> int | None:
    brace_depth = 0
    link_depth = 0
    pos = 0
    length = len(segment)
    while pos < length:
        if segment.startswith("{{", pos):
            brace_depth += 1
            pos += 2
        elif segment.startswith("}}", pos) and brace_depth > 0:
            brace_depth -= 1
            pos += 2
        elif segment.startswith("[[", pos):
            link_depth += 1
            pos += 2
        elif segment.startswith("]]", pos) and link_depth > 0:
            link_depth -= 1
            pos += 2
        elif segment[pos] == "=" and brace_depth == 0 and link_depth == 0:
            return pos
        else:
            pos += 1
    return None


def _clean_wiki_text(raw: str) -> str:
    if not raw:
        return ""
    text = HTML_COMMENT_RE.sub("", raw)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    # Iteratively expand innermost {{...}} inline templates
    inner_re = re.compile(r"\{\{([^{}]+)\}\}")
    for _ in range(8):
        if "{{" not in text:
            break
        def _replace_inner(match: re.Match[str]) -> str:
            inner = match.group(1)
            parts = [p.strip() for p in inner.split("|")]
            tname = parts[0].casefold()
            pos_args = [p for p in parts[1:] if "=" not in p]
            if tname in {"特攻", "特性"}:
                if len(pos_args) >= 2 and pos_args[1]:
                    return pos_args[1]
                return f"〔{pos_args[0]}〕" if pos_args else ""
            if tname == "ruby":
                return pos_args[0] if pos_args else ""
            if tname in {"ja", "color", "text"}:
                return pos_args[-1] if pos_args else ""
            return pos_args[-1] if pos_args else ""

        updated = inner_re.sub(_replace_inner, text)
        if updated == text:
            break
        text = updated

    text = WIKI_LINK_RE.sub(r"\1", text)
    text = HTML_TAG_RE.sub("", text)
    text = text.replace("'''", "").replace("''", "")
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _parse_active_skills(
    cleaned_wikitext: str,
) -> tuple[list[str], list[int], list[dict[str, str]], list[int]]:
    section_start = cleaned_wikitext.find("===持有技能===")
    section_end = cleaned_wikitext.find("===职阶技能===", section_start if section_start >= 0 else 0)
    section = (
        cleaned_wikitext[section_start : section_end if section_end > section_start else len(cleaned_wikitext)]
        if section_start >= 0
        else cleaned_wikitext
    )

    slot_chunks: list[str] = []
    markers = [m.start() for m in re.finditer(r"'''技能\s*[123１２３]", section)]
    if len(markers) >= 3:
        for i in range(3):
            end = markers[i + 1] if i + 1 < len(markers) else len(section)
            slot_chunks.append(section[markers[i] : end])
    else:
        calls = _extract_template_calls(section, "持有技能")[:3]
        slot_chunks = [f"{{{{持有技能|{c}}}}}" for c in calls]

    skill_icons: list[str] = []
    skill_types: list[int] = []
    skill_details: list[dict[str, str]] = []
    choice_hints: list[int] = []

    for slot_idx, chunk in enumerate(slot_chunks[:3], start=1):
        calls = _extract_template_calls(chunk, "持有技能")
        if not calls:
            skill_icons.append("加攻")
            skill_types.append(0)
            skill_details.append({"name": f"技能{slot_idx}", "detail": ""})
            continue
        positional, _ = _split_template_params(calls[0])
        icon_name = _clean_wiki_text(positional[0]) if len(positional) > 0 else "加攻"
        cn_skill_name = _clean_wiki_text(positional[1]) if len(positional) > 1 else ""
        jp_skill_name = _clean_wiki_text(positional[2]) if len(positional) > 2 else ""
        official_name = cn_skill_name or jp_skill_name or f"技能{slot_idx}"

        effects: list[str] = []
        raw_effects_concat: list[str] = []
        cursor = 4
        while cursor < len(positional):
            raw_eff = positional[cursor]
            eff_clean = _clean_wiki_text(raw_eff).replace("\n", " ")
            vals = positional[cursor + 1 : cursor + 11]
            cursor += 11
            if not eff_clean:
                continue
            raw_effects_concat.append(eff_clean)
            v1 = _clean_wiki_text(vals[0]) if vals else ""
            v10 = _clean_wiki_text(vals[-1]) if len(vals) >= 10 else v1
            scales_with_level = bool(v1 and v1 != "∅" and v1 != v10)
            effects.append(f"{eff_clean}▲" if scales_with_level else eff_clean)

        joined_raw = "＆".join(raw_effects_concat)
        targets_single_ally = any(
            phrase in joined_raw
            for phrase in ("己方单体", "除自身以外的己方单体", "味方単体", "自身を除く味方単体")
        )
        if any(phrase in joined_raw for phrase in ("选择", "選択")):
            choice_hints.append(slot_idx)

        skill_icons.append(icon_name or "加攻")
        skill_types.append(1 if targets_single_ally else 0)
        skill_details.append({"name": official_name, "detail": "＆".join(effects)})

    while len(skill_icons) < 3:
        idx = len(skill_icons) + 1
        skill_icons.append("加攻")
        skill_types.append(0)
        skill_details.append({"name": f"技能{idx}", "detail": ""})

    return skill_icons[:3], skill_types[:3], skill_details[:3], choice_hints


def _parse_focus_coord(raw: str) -> tuple[int, int]:
    if not raw:
        return (256, DEFAULT_CE_FOCUS_Y)
    first_pair = raw.split(";;", 1)[0].strip()
    nums = re.findall(r"-?\d+", first_pair)
    if len(nums) >= 2:
        return (int(nums[0]), int(nums[1]))
    return (256, DEFAULT_CE_FOCUS_Y)


def _extract_smw_timestamp(raw_list: Any) -> int | None:
    if not isinstance(raw_list, list) or not raw_list:
        return None
    first = raw_list[0]
    if isinstance(first, dict) and str(first.get("timestamp", "")).isdigit():
        return int(first["timestamp"])
    if isinstance(first, (int, float)):
        return int(first)
    return None


def _strip_rerun_prefix(title: str) -> str:
    stripped = re.sub(r"^(?:复刻版\s*[:：]\s*|复刻\s*[:：]\s*)", "", title.strip())
    stripped = re.sub(r"\s*轻量版$", "", stripped)
    return stripped.strip() or title


def _safe_int(raw: str | None, *, default: int = 0) -> int:
    if not raw:
        return default
    cleaned = raw.strip()
    return int(cleaned) if cleaned.isdigit() else default


def _choose_canonical_servant_name(
    parsed: dict[str, Any],
    *,
    existing_catalog: dict[str, Any],
) -> str:
    name_cn = parsed["name_cn"]
    name_link = parsed["name_link"]
    name_jp = parsed["name_jp"]
    sn = parsed["sn"]

    if name_cn:
        if name_link.startswith(name_cn) and len(name_link) > len(name_cn):
            candidate = name_link
        else:
            candidate = name_cn
    else:
        candidate = name_link or name_jp or f"Servant_{sn}"

    sanitized = sanitize_filename_component(candidate)
    existing = existing_catalog.get(sanitized)
    if isinstance(existing, dict) and str(existing.get("SN", "")).strip() != sn:
        sanitized = sanitize_filename_component(f"{sanitized}({parsed['class']})")
    return sanitized


def _extract_atlas_asset_urls(
    atlas_data: dict[str, Any] | None,
) -> tuple[list[tuple[str, str]], dict[str, str], list[tuple[str, str]], list[tuple[str, str]]]:
    if not isinstance(atlas_data, dict):
        return [], {}, [], []
    extra = atlas_data.get("extraAssets") or {}

    def ordered_pairs(section_name: str) -> list[tuple[str, str]]:
        section = extra.get(section_name) or {}
        out: list[tuple[str, str]] = []
        for sub_key in ("ascension", "costume"):
            sub = section.get(sub_key) or {}
            if isinstance(sub, dict):
                for k in sorted(sub.keys(), key=lambda x: (len(str(x)), str(x))):
                    url = sub[k]
                    if isinstance(url, str) and url:
                        out.append((str(k), url))
        return out

    faces = ordered_pairs("faces")
    statuses = ordered_pairs("status")
    charagraphs = ordered_pairs("charaGraph")

    commands: dict[str, str] = {}
    cmd_section = extra.get("commands") or {}
    asc_cmds = cmd_section.get("ascension") or {}
    if isinstance(asc_cmds, dict):
        for k in sorted(asc_cmds.keys(), key=lambda x: (len(str(x)), str(x))):
            url = asc_cmds[k]
            if isinstance(url, str) and url:
                safe_k = sanitize_filename_component(str(k))
                commands[f"card_servant_{safe_k}.png"] = url
    costume_cmds = cmd_section.get("costume") or {}
    if isinstance(costume_cmds, dict):
        for k in sorted(costume_cmds.keys(), key=lambda x: (len(str(x)), str(x))):
            url = costume_cmds[k]
            if isinstance(url, str) and url:
                safe_k = sanitize_filename_component(str(k))
                commands[f"{safe_k}.png"] = url

    return faces, commands, statuses, charagraphs


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.stem}-",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _write_json_atomic(path: Path, data: Any) -> None:
    serialized = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    _write_bytes_atomic(path, serialized.encode("utf-8"))
