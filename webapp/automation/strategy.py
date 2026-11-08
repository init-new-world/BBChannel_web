from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import permutations
from typing import Any


COLOR_FACTOR = {"B": 1.5, "A": 1.0, "Q": 0.8}
WEAK_FACTOR = {0: 1.0, 1: 2.0, -1: 0.5}
PLACE_FACTOR: dict[str, tuple[float, float, float]] = {
    "B": (1.5, 1.8, 2.1),
    "A": (1.0, 1.2, 1.4),
    "Q": (0.8, 0.96, 1.12),
    "N": (0.0, 0.0, 0.0),
}
EX_FACTOR = {False: 2.0, True: 3.5}


class StrategySelectionError(ValueError):
    pass


def select_command_cards_default(
    recognized_cards: list[dict[str, Any]],
    *,
    preselected_nps: list[int] | None = None,
    unavailable_nps: list[int] | None = None,
    frontline_servants: Sequence[dict[str, Any] | None] | None = None,
    buff_counts: Mapping[Any, int] | Sequence[int] | None = None,
    np_servants: set[Any] | Sequence[Any] | None = None,
    server: str = "CH",
) -> list[dict[str, Any]]:
    if any(
        isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 3
        for value in unavailable_nps or []
    ):
        raise StrategySelectionError(
            "Unavailable Noble Phantasm positions must be between 1 and 3."
        )
    unavailable = set(unavailable_nps or [])
    selected_np_positions = [
        servant
        for servant in preselected_nps or []
        if isinstance(servant, int) and not isinstance(servant, bool) and 1 <= servant <= 3
    ]
    if len(set(selected_np_positions)) != len(selected_np_positions):
        raise StrategySelectionError(
            "Preselected Noble Phantasms must not contain duplicates."
        )
    selected_np_positions = [
        servant for servant in selected_np_positions if servant not in unavailable
    ][:3]
    selected_np_entries = [
        {"type": "np", "servant": servant} for servant in selected_np_positions
    ]
    needed_face_count = 3 - len(selected_np_entries)
    if needed_face_count <= 0:
        return selected_np_entries

    available_cards = sorted(
        (
            card
            for card in recognized_cards
            if isinstance(card.get("slot"), int)
            and not isinstance(card.get("slot"), bool)
            and card.get("available") is not False
        ),
        key=lambda card: int(card["slot"]),
    )
    if len(available_cards) < needed_face_count:
        raise StrategySelectionError(
            f"Default card selection requires at least {needed_face_count} available face cards."
        )

    frontline_by_position = _index_frontline_servants(frontline_servants)
    normalized_server = server.upper() if isinstance(server, str) else "CH"
    supports_color_chain = normalized_server in {"CH", "CNTW", "JP"}
    np_servant_set = set(np_servants or ())

    np_chain_prefix: list[tuple[int | str, str]] = []
    for np_position in selected_np_positions:
        servant = frontline_by_position.get(np_position)
        np_color = (
            (servant.get("np_color") or servant.get("NPcolor"))
            if isinstance(servant, dict)
            else None
        )
        np_chain_prefix.append(
            (np_position, np_color if np_color in {"B", "A", "Q"} else "N")
        )

    best_score: float | None = None
    best_combination: tuple[dict[str, Any], ...] | None = None
    for candidate_cards in permutations(available_cards, needed_face_count):
        parsed_faces = [_parse_default_face_card(card) for card in candidate_cards]
        chain = [*np_chain_prefix, *[(pos, color) for pos, color, _, _ in parsed_faces]]
        S1, C1 = chain[0]
        S2, C2 = chain[1]
        S3, C3 = chain[2]
        three_color = supports_color_chain and {C1, C2, C3} == {"B", "A", "Q"}
        exstar = (
            2
            if (C1 == "Q" and supports_color_chain) or three_color
            else 0
        )

        face_total = 0.0
        for offset, (servant_pos, color, affinity_score, stars) in enumerate(parsed_faces):
            chain_index = (3 - needed_face_count) + offset
            buff_num = _default_card_buff_num(
                servant_pos,
                candidate_cards[offset],
                frontline_by_position,
                buff_counts,
                np_servant_set,
            )
            card_score = PLACE_FACTOR.get(color, PLACE_FACTOR["N"])[chain_index] * (
                1.0 + 0.5 * buff_num
            )
            if C1 == "B" or three_color:
                card_score += 0.5 if color != "N" else 0.0
            card_score *= WEAK_FACTOR.get(affinity_score, 1.0)
            crit_prob = min(10, stars + exstar) / 10.0
            card_score *= (1.0 - crit_prob) * 1.0 + 2.0 * crit_prob
            face_total += card_score

        score_ex = 0.0
        if needed_face_count in (2, 3) and S1 == S2 == S3 and S1 != "N":
            same_color = C1 == C2 == C3
            lead_bonus = 1.5 if (C1 == "B" or three_color) else 1.0
            score_ex = lead_bonus * EX_FACTOR[same_color]

        total_score = face_total + score_ex
        if best_score is None or total_score > best_score:
            best_score = total_score
            best_combination = candidate_cards

    assert best_combination is not None
    return [
        *selected_np_entries,
        *(_face_selection(card) for card in best_combination),
    ]


def _index_frontline_servants(
    frontline_servants: Sequence[dict[str, Any] | None] | None,
) -> dict[int, dict[str, Any]]:
    by_position: dict[int, dict[str, Any]] = {}
    if not frontline_servants:
        return by_position
    for default_pos, servant in enumerate(frontline_servants[:3], start=1):
        if not isinstance(servant, dict):
            continue
        pos = servant.get("battle_position", default_pos)
        if isinstance(pos, bool) or not isinstance(pos, int) or not 1 <= pos <= 3:
            pos = default_pos
        by_position[pos] = servant
    return by_position


def _parse_default_face_card(
    card: dict[str, Any],
) -> tuple[int | str, str, int, int]:
    servant_pos = card.get("servant_position")
    code = card.get("code")
    if (
        (isinstance(servant_pos, bool) or not isinstance(servant_pos, int) or not 1 <= servant_pos <= 3)
        and isinstance(code, str)
        and len(code) == 2
        and code[0] in {"1", "2", "3"}
    ):
        servant_pos = int(code[0])
    parsed_pos: int | str = (
        servant_pos
        if isinstance(servant_pos, int)
        and not isinstance(servant_pos, bool)
        and 1 <= servant_pos <= 3
        else "N"
    )
    color = card.get("color")
    if color not in {"B", "A", "Q"} and isinstance(code, str) and code[-1:] in {"B", "A", "Q"}:
        color = code[-1]
    parsed_color = color if color in {"B", "A", "Q"} else "N"

    raw_affinity = card.get("affinity_score")
    if (
        isinstance(raw_affinity, int)
        and not isinstance(raw_affinity, bool)
        and raw_affinity in (-1, 0, 1)
    ):
        affinity_score = raw_affinity
    elif card.get("affinity") == "weak":
        affinity_score = 1
    elif card.get("affinity") == "resist":
        affinity_score = -1
    else:
        affinity_score = 0

    raw_stars = card.get("stars")
    stars = (
        int(raw_stars)
        if isinstance(raw_stars, (int, float)) and not isinstance(raw_stars, bool)
        else 0
    )
    return parsed_pos, parsed_color, affinity_score, max(stars, 0)


def _default_card_buff_num(
    servant_pos: int | str,
    card: dict[str, Any],
    frontline_by_position: dict[int, dict[str, Any]],
    buff_counts: Mapping[Any, int] | Sequence[int] | None,
    np_servant_set: set[Any],
) -> int:
    if not isinstance(servant_pos, int) or isinstance(servant_pos, bool):
        return 0
    servant = frontline_by_position.get(servant_pos)
    keys: list[Any] = []
    if isinstance(servant, dict):
        slot = servant.get("slot")
        if isinstance(slot, int) and not isinstance(slot, bool) and slot >= 0:
            keys.append(slot)
        for field in ("sn", "canonical_name", "name"):
            value = servant.get(field)
            if value is not None and value != "":
                keys.append(value)
    card_sn = card.get("servant_sn")
    if card_sn is not None and card_sn != "":
        keys.append(card_sn)
    keys.append(f"pos:{servant_pos}")
    if not isinstance(servant, dict) and buff_counts is not None:
        keys.append(servant_pos - 1)

    buff_value = 0
    if isinstance(buff_counts, Mapping):
        for key in keys:
            candidate = buff_counts.get(key)
            if isinstance(candidate, int) and not isinstance(candidate, bool):
                buff_value = candidate
                break
    elif isinstance(buff_counts, Sequence) and not isinstance(buff_counts, (str, bytes)):
        slot_index = (
            servant.get("slot")
            if isinstance(servant, dict)
            and isinstance(servant.get("slot"), int)
            and not isinstance(servant.get("slot"), bool)
            else servant_pos - 1
        )
        if isinstance(slot_index, int) and 0 <= slot_index < len(buff_counts):
            candidate = buff_counts[slot_index]
            if isinstance(candidate, int) and not isinstance(candidate, bool):
                buff_value = candidate

    is_np_servant = any(key in np_servant_set for key in keys)
    return min(9, max(0, buff_value)) + (2 if is_np_servant else 0)



def select_command_cards_without_chain(
    recognized_cards: list[dict[str, Any]],
    *,
    preselected_np: int,
) -> list[dict[str, Any]]:
    if isinstance(preselected_np, bool) or not isinstance(preselected_np, int):
        raise StrategySelectionError("No-chain selection requires one Noble Phantasm.")
    if not 1 <= preselected_np <= 3:
        raise StrategySelectionError("Noble Phantasm position must be between 1 and 3.")
    cards = sorted(
        (
            card
            for card in recognized_cards
            if isinstance(card.get("slot"), int)
            and isinstance(card.get("servant_position"), int)
            and card.get("color") in {"A", "B", "Q"}
            and isinstance(card.get("code"), str)
            and card.get("available") is not False
        ),
        key=lambda card: int(card["slot"]),
    )
    if len(cards) < 2:
        raise StrategySelectionError("No-chain selection requires at least two face cards.")

    selected_cards = None
    for first_index, first in enumerate(cards):
        for second in cards[first_index + 1 :]:
            if (
                first["servant_position"] != second["servant_position"]
                and first["color"] != second["color"]
            ):
                selected_cards = (first, second)
                break
        if selected_cards is not None:
            break
    if selected_cards is None:
        selected_cards = (cards[0], cards[1])
    return [
        {"type": "np", "servant": preselected_np},
        *(_face_selection(card) for card in selected_cards),
    ]


def select_command_cards(
    strategies: list[dict[str, Any]],
    recognized_cards: list[dict[str, Any]],
    *,
    preselected_nps: list[int] | None = None,
    unavailable_nps: list[int] | None = None,
) -> list[dict[str, Any]]:
    if not strategies:
        raise StrategySelectionError("No command card strategies are configured.")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 3
        for value in unavailable_nps or []
    ):
        raise StrategySelectionError("Unavailable Noble Phantasm positions must be between 1 and 3.")
    unavailable = set(unavailable_nps or [])
    errors = []
    for index, strategy in enumerate(strategies, start=1):
        try:
            return _select_strategy(
                strategy,
                recognized_cards,
                preselected_nps or [],
                unavailable,
            )
        except StrategySelectionError as exc:
            errors.append(f"strategy {index}: {exc}")
    raise StrategySelectionError("; ".join(errors))


def _select_strategy(
    strategy: dict[str, Any],
    recognized_cards: list[dict[str, Any]],
    preselected_nps: list[int],
    unavailable_nps: set[int],
) -> list[dict[str, Any]]:
    cards = [card for card in recognized_cards if card.get("code") and card.get("available") is not False]
    breakpoints = strategy.get("breakpoint", [False, False])
    if (
        not isinstance(breakpoints, list) or len(breakpoints) != 2
        or any(not isinstance(value, bool) for value in breakpoints)
    ):
        raise StrategySelectionError("Strategy breakpoint must contain two boolean values.")
    selected = [
        {"type": "np", "servant": servant}
        for servant in preselected_nps
        if isinstance(servant, int) and not isinstance(servant, bool) and 1 <= servant <= 3
    ]
    selected_nps = {selection["servant"] for selection in selected}
    if len(selected_nps) != len(selected):
        raise StrategySelectionError("Preselected Noble Phantasms must not contain duplicates.")
    selected = [item for item in selected if item["servant"] not in unavailable_nps]
    selected_nps -= unavailable_nps
    color_first = bool(strategy.get("colorFirst", True))

    def choose(
        spec_index: int, chosen: list[dict[str, Any]], slots: set[int],
        nps: set[int], servants: set[int],
    ) -> list[dict[str, Any]] | None:
        if len(chosen) == 3:
            return chosen
        card_name = f"card{spec_index + 1}"
        spec = strategy.get(card_name) if spec_index < 3 else {
            "type": 2, "criticalStar": 0, "more_or_less": True,
        }
        if not isinstance(spec, dict):
            raise StrategySelectionError(f"{card_name} is missing.")
        card_type = spec.get("type")
        if card_type == 0:
            servant = _select_np(spec, nps, unavailable_nps)
            if servant is None:
                return choose(spec_index + 1, chosen, slots, nps, servants)
            return choose(
                spec_index + 1, [*chosen, {"type": "np", "servant": servant}],
                slots, nps | {servant}, servants | {servant},
            )
        if card_type == 1:
            candidates = _preferred_faces(spec, cards, slots, color_first=color_first)
        elif card_type == 2:
            candidates = _fallback_faces(spec, cards, slots, servants)
        else:
            raise StrategySelectionError(f"{card_name} has unsupported type {card_type}.")
        for card in candidates:
            position = int(card["servant_position"])
            if (
                chosen and breakpoints[len(chosen) - 1] and chosen[-1]["type"] == "face"
                and chosen[-1]["code"][0] == str(position)
            ):
                continue
            result = choose(
                spec_index + 1, [*chosen, _face_selection(card)],
                slots | {int(card["slot"])}, nps, servants | {position},
            )
            if result is not None:
                return result
        return None

    result = choose(0, selected, set(), selected_nps, set(selected_nps))
    if result is None:
        message = "Strategy has no matching command card combination."
        constrained_stars = any(
            isinstance(spec, dict) and (spec.get("criticalStar", 0) or not spec.get("more_or_less", True))
            for spec in (strategy.get(name) for name in ("card1", "card2", "card3"))
        )
        if constrained_stars and any(card.get("stars") is None for card in cards):
            message += " Some critical star values are unknown."
        raise StrategySelectionError(message)
    return result


def _select_np(
    spec: dict[str, Any], selected_nps: set[int], unavailable_nps: set[int],
) -> int | None:
    candidates = spec.get("cards")
    if not isinstance(candidates, list):
        raise StrategySelectionError("NP card candidates must be a list.")
    has_valid_candidate = False
    for servant in candidates:
        if isinstance(servant, int) and not isinstance(servant, bool) and 1 <= servant <= 3:
            has_valid_candidate = True
            if servant in unavailable_nps:
                continue
            if servant in selected_nps:
                return None
            return servant
    if has_valid_candidate:
        return None
    raise StrategySelectionError("NP strategy has no valid servant position.")


def matches_card_preference(card: dict[str, Any], preference: str) -> bool:
    special_keys = card.get("special_keys")
    return card.get("code") == preference or (
        isinstance(special_keys, list) and (
            preference in special_keys
            or any(preference == f"{card['code']}{key}" for key in special_keys)
        )
    )


def _preferred_faces(
    spec: dict[str, Any],
    cards: list[dict[str, Any]],
    selected_slots: set[int],
    *,
    color_first: bool,
) -> list[dict[str, Any]]:
    preferences = spec.get("cards")
    if not isinstance(preferences, list):
        raise StrategySelectionError("Face card preferences must be a list.")
    eligible = _eligible_cards(spec, cards, selected_slots)
    ranked = []
    ranked_slots: set[int] = set()
    for preference_index, preference in enumerate(preferences):
        for card in eligible:
            if matches_card_preference(card, preference):
                slot = int(card["slot"])
                if slot not in ranked_slots:
                    ranked.append((preference_index, card))
                    ranked_slots.add(slot)
    if color_first:
        ranked.sort(key=lambda item: (item[0], int(item[1]["slot"])))
        return [card for _preference_index, card in ranked]
    reverse_stars = bool(spec.get("more_or_less", True))
    ranked.sort(
        key=lambda item: (
            -(item[1].get("stars") or 0) if reverse_stars else (item[1].get("stars") or 0),
            item[0],
            int(item[1]["slot"]),
        ),
    )
    return [card for _preference_index, card in ranked]


def _fallback_faces(
    spec: dict[str, Any],
    cards: list[dict[str, Any]],
    selected_slots: set[int],
    selected_servants: set[int],
) -> list[dict[str, Any]]:
    eligible = _eligible_cards(spec, cards, selected_slots)
    return sorted(
        eligible,
        key=lambda card: (
            int(card["servant_position"]) in selected_servants,
            int(card["slot"]),
        ),
    )


def _eligible_cards(
    spec: dict[str, Any],
    cards: list[dict[str, Any]],
    selected_slots: set[int],
) -> list[dict[str, Any]]:
    threshold = spec.get("criticalStar", 0)
    more_or_less = spec.get("more_or_less", True)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise StrategySelectionError("critical star threshold must be numeric.")
    eligible = []
    for card in cards:
        slot = card.get("slot")
        if not isinstance(slot, int) or slot in selected_slots:
            continue
        stars = card.get("stars")
        if stars is None:
            if threshold or not more_or_less:
                continue
            stars = 0
        if not isinstance(stars, (int, float)) or isinstance(stars, bool):
            continue
        if more_or_less and stars < threshold:
            continue
        if not more_or_less and stars > threshold:
            continue
        eligible.append(card)
    return eligible


def _face_selection(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "face",
        "slot": int(card["slot"]),
        "code": str(card["code"]),
        "stars": int(card.get("stars") or 0),
    }
