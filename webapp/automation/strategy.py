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
) -> list[dict[str, Any]]:
    if not strategies:
        raise StrategySelectionError("No command card strategies are configured.")
    errors = []
    for index, strategy in enumerate(strategies, start=1):
        try:
            return _select_strategy(
                strategy,
                recognized_cards,
                preselected_nps or [],
            )
        except StrategySelectionError as exc:
            errors.append(f"strategy {index}: {exc}")
    raise StrategySelectionError("; ".join(errors))


def _select_strategy(
    strategy: dict[str, Any],
    recognized_cards: list[dict[str, Any]],
    preselected_nps: list[int],
) -> list[dict[str, Any]]:
    cards = [card for card in recognized_cards if card.get("code")]
    selected = [
        {"type": "np", "servant": servant}
        for servant in preselected_nps
        if isinstance(servant, int) and not isinstance(servant, bool) and 1 <= servant <= 3
    ]
    selected_nps = {selection["servant"] for selection in selected}
    selected_slots: set[int] = set()
    selected_servants = set(selected_nps)
    color_first = bool(strategy.get("colorFirst", True))

    for card_name in ("card1", "card2", "card3"):
        if len(selected) >= 3:
            break
        spec = strategy.get(card_name)
        if not isinstance(spec, dict):
            raise StrategySelectionError(f"{card_name} is missing.")
        card_type = spec.get("type")
        if card_type == 0:
            servant = _select_np(spec, selected_nps)
            if servant is not None:
                selected.append({"type": "np", "servant": servant})
                selected_nps.add(servant)
                selected_servants.add(servant)
            continue
        if card_type == 1:
            card = _select_preferred_face(
                spec,
                cards,
                selected_slots,
                color_first=color_first,
            )
        elif card_type == 2:
            card = _select_fallback_face(
                spec,
                cards,
                selected_slots,
                selected_servants,
            )
        else:
            raise StrategySelectionError(f"{card_name} has unsupported type {card_type}.")
        if card is None:
            raise StrategySelectionError(f"{card_name} has no matching command card.")
        selected.append(_face_selection(card))
        selected_slots.add(int(card["slot"]))
        selected_servants.add(int(card["servant_position"]))

    while len(selected) < 3:
        card = _select_fallback_face(
            {"criticalStar": 0, "more_or_less": True},
            cards,
            selected_slots,
            selected_servants,
        )
        if card is None:
            break
        selected.append(_face_selection(card))
        selected_slots.add(int(card["slot"]))
        selected_servants.add(int(card["servant_position"]))

    if len(selected) != 3:
        raise StrategySelectionError(
            f"Strategy selected {len(selected)} cards instead of 3."
        )
    return selected


def _select_np(spec: dict[str, Any], selected_nps: set[int]) -> int | None:
    candidates = spec.get("cards")
    if not isinstance(candidates, list):
        raise StrategySelectionError("NP card candidates must be a list.")
    for servant in candidates:
        if isinstance(servant, int) and not isinstance(servant, bool) and 1 <= servant <= 3:
            if servant in selected_nps:
                return None
            return servant
    raise StrategySelectionError("NP strategy has no valid servant position.")


def _select_preferred_face(
    spec: dict[str, Any],
    cards: list[dict[str, Any]],
    selected_slots: set[int],
    *,
    color_first: bool,
) -> dict[str, Any] | None:
    preferences = spec.get("cards")
    if not isinstance(preferences, list):
        raise StrategySelectionError("Face card preferences must be a list.")
    eligible = _eligible_cards(spec, cards, selected_slots)
    ranked = []
    for preference_index, preference in enumerate(preferences):
        for card in eligible:
            special_keys = card.get("special_keys")
            if card.get("code") == preference or (
                isinstance(special_keys, list) and preference in special_keys
            ):
                ranked.append((preference_index, card))
    if not ranked:
        return None
    if color_first:
        return min(ranked, key=lambda item: (item[0], int(item[1]["slot"])))[1]
    reverse_stars = bool(spec.get("more_or_less", True))
    return sorted(
        ranked,
        key=lambda item: (
            -(item[1].get("stars") or 0) if reverse_stars else (item[1].get("stars") or 0),
            item[0],
            int(item[1]["slot"]),
        ),
    )[0][1]


def _select_fallback_face(
    spec: dict[str, Any],
    cards: list[dict[str, Any]],
    selected_slots: set[int],
    selected_servants: set[int],
) -> dict[str, Any] | None:
    eligible = _eligible_cards(spec, cards, selected_slots)
    return min(
        eligible,
        key=lambda card: (
            int(card["servant_position"]) in selected_servants,
            int(card["slot"]),
        ),
        default=None,
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
            if threshold:
                raise StrategySelectionError(
                    "critical star recognition is required by this strategy."
                )
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
