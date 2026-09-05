from __future__ import annotations

from typing import Any


class StrategySelectionError(ValueError):
    pass


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
            special_keys = card.get("special_keys")
            if card.get("code") == preference or (
                isinstance(special_keys, list) and (
                    preference in special_keys
                    or any(preference == f"{card['code']}{key}" for key in special_keys)
                )
            ):
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
