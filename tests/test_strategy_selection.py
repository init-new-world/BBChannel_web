import pytest

from webapp.automation.strategy import (
    StrategySelectionError,
    select_command_cards,
    select_command_cards_without_chain,
)


def _card(slot: int, code: str, stars: int | None = 0) -> dict:
    return {
        "slot": slot,
        "code": code,
        "servant_position": int(code[0]),
        "color": code[1],
        "stars": stars,
    }


def _spec(card_type: int, cards: list, stars: int = 0, more: bool = True) -> dict:
    return {
        "type": card_type,
        "cards": cards,
        "criticalStar": stars,
        "more_or_less": more,
    }


def test_strategy_selects_np_and_preferred_face_cards_without_duplicates():
    strategy = {
        "card1": _spec(0, [1]),
        "card2": _spec(1, ["1A", "2A"]),
        "card3": _spec(1, ["1B", "2B"]),
        "breakpoint": [False, False],
        "colorFirst": True,
    }
    cards = [
        _card(1, "1B"),
        _card(2, "2A"),
        _card(3, "1A"),
        _card(4, "3Q"),
        _card(5, "2B"),
    ]

    selected = select_command_cards([strategy], cards, preselected_nps=[1])

    assert selected == [
        {"type": "np", "servant": 1},
        {"type": "face", "slot": 3, "code": "1A", "stars": 0},
        {"type": "face", "slot": 1, "code": "1B", "stars": 0},
    ]


def test_strategy_fallback_prefers_different_servants():
    strategy = {
        "card1": _spec(0, [1]),
        "card2": _spec(2, []),
        "card3": _spec(2, []),
        "breakpoint": [False, True],
        "colorFirst": True,
    }
    cards = [
        _card(1, "1B"),
        _card(2, "2A"),
        _card(3, "1Q"),
        _card(4, "3B"),
        _card(5, "2Q"),
    ]

    selected = select_command_cards([strategy], cards)

    assert selected == [
        {"type": "np", "servant": 1},
        {"type": "face", "slot": 2, "code": "2A", "stars": 0},
        {"type": "face", "slot": 4, "code": "3B", "stars": 0},
    ]


def test_no_chain_selection_uses_different_servants_and_colors():
    cards = [
        _card(1, "1B"),
        _card(2, "1A"),
        _card(3, "2B"),
        _card(4, "2A"),
        _card(5, "3B"),
    ]

    selected = select_command_cards_without_chain(cards, preselected_np=1)

    assert selected == [
        {"type": "np", "servant": 1},
        {"type": "face", "slot": 1, "code": "1B", "stars": 0},
        {"type": "face", "slot": 4, "code": "2A", "stars": 0},
    ]


def test_strategy_selects_face_card_by_custom_special_key():
    strategy = {
        "card1": _spec(1, ["S0"]),
        "card2": _spec(2, []),
        "card3": _spec(2, []),
        "breakpoint": [False, False],
        "colorFirst": True,
    }
    cards = [_card(slot, code) for slot, code in enumerate(
        ("1B", "2A", "1Q", "3B", "2Q"),
        start=1,
    )]
    cards[3]["special_keys"] = ["S0"]

    selected = select_command_cards([strategy], cards)

    assert selected[0] == {"type": "face", "slot": 4, "code": "3B", "stars": 0}


def test_strategy_rejects_unknown_star_requirement():
    strategy = {
        "card1": _spec(1, ["1B"], stars=5),
        "card2": _spec(2, []),
        "card3": _spec(2, []),
        "breakpoint": [False, False],
        "colorFirst": False,
    }

    with pytest.raises(StrategySelectionError, match="critical star"):
        select_command_cards([strategy], [_card(1, "1B", None)])
