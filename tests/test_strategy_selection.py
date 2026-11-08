from itertools import permutations, product

import pytest

from webapp.automation.strategy import (
    StrategySelectionError,
    select_command_cards,
    select_command_cards_default,
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


@pytest.mark.parametrize("unavailable", [[1], [1, 2], [1, 2, 3]])
def test_strategy_replaces_unavailable_nps_with_remaining_cards(unavailable):
    cards = [_card(1, "1B"), _card(2, "2A"), _card(3, "3Q")]
    strategy = {
        "card1": _spec(0, [1, 2, 3]),
        "card2": _spec(2, []), "card3": _spec(2, []),
    }
    selected = select_command_cards(
        [strategy], cards, preselected_nps=[1], unavailable_nps=unavailable,
    )
    assert len(selected) == 3
    selected_nps = [item["servant"] for item in selected if item["type"] == "np"]
    assert selected_nps == ([next(value for value in (1, 2, 3) if value not in unavailable)]
                            if len(unavailable) < 3 else [])
    assert len({item["slot"] for item in selected if item["type"] == "face"}) == 3 - len(selected_nps)


@pytest.mark.parametrize("unavailable", [[0], [4], [True], ["1"]])
def test_strategy_rejects_invalid_unavailable_np_positions(unavailable):
    strategy = {f"card{i}": _spec(2, []) for i in (1, 2, 3)}
    with pytest.raises(StrategySelectionError, match="Unavailable Noble Phantasm"):
        select_command_cards([strategy], [], unavailable_nps=unavailable)


def test_strategy_and_no_chain_skip_unavailable_face_cards():
    cards = [_card(1, "1B"), _card(2, "2A"), _card(3, "3Q"), _card(4, "1A"), _card(5, "2B")]
    cards[0]["available"] = False
    strategy = {"card1": _spec(0, [1]), "card2": _spec(1, ["1B", "2A"]), "card3": _spec(2, [])}
    selected = select_command_cards([strategy], cards)
    assert [entry["slot"] for entry in selected if entry["type"] == "face"] == [2, 3]
    selected = select_command_cards_without_chain(cards, preselected_np=1)
    assert [entry["slot"] for entry in selected if entry["type"] == "face"] == [2, 3]


def test_strategy_rejects_unavailable_special_key_candidates():
    cards = [_card(1, "1B"), _card(2, "2A"), _card(3, "3Q")]
    cards[0].update({"available": False, "special_keys": ["S0"]})
    strategy = {"card1": _spec(1, ["S0"]), "card2": _spec(2, []), "card3": _spec(2, [])}
    with pytest.raises(StrategySelectionError, match="no matching"):
        select_command_cards([strategy], cards)


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


def test_strategy_backtracks_when_first_preference_is_needed_later():
    cards = [_card(1, "1B"), _card(2, "2A"), _card(3, "3Q")]
    strategy = {"card1": _spec(1, ["1B", "2A"]), "card2": _spec(1, ["1B"]), "card3": _spec(2, [])}
    selected = select_command_cards([strategy], cards)
    assert [card["slot"] for card in selected] == [2, 1, 3]


@pytest.mark.parametrize("breakpoints,expected", [
    ([False, False], [1, 2, 3]), ([True, False], [1, 4, 3]),
    ([False, True], [1, 2, 5]), ([True, True], [1, 4, 3]),
])
def test_strategy_enforces_adjacent_face_card_breakpoints(breakpoints, expected):
    cards = [_card(slot, code) for slot, code in enumerate(("1B", "1A", "1Q", "2A", "2Q"), 1)]
    strategy = {
        "card1": _spec(1, ["1B"]), "card2": _spec(1, ["1A", "2A"]),
        "card3": _spec(1, ["1Q", "2Q"]), "breakpoint": breakpoints,
    }
    assert [card["slot"] for card in select_command_cards([strategy], cards)] == expected


def test_strategy_skips_impossible_breakpoint_strategy():
    cards = [_card(1, "1B"), _card(2, "1A"), _card(3, "1Q")]
    strategy = {f"card{index}": _spec(2, []) for index in range(1, 4)}
    strategy["breakpoint"] = [True, True]
    with pytest.raises(StrategySelectionError, match="no matching"):
        select_command_cards([strategy], cards)
    fallback = {**strategy, "breakpoint": [False, False]}
    assert [card["slot"] for card in select_command_cards([strategy, fallback], cards)] == [1, 2, 3]


def test_strategy_breakpoints_do_not_apply_to_noble_phantasms():
    cards = [_card(1, "1B"), _card(2, "2A"), _card(3, "1Q")]
    strategy = {
        "card1": _spec(0, [1]), "card2": _spec(1, ["1B"]),
        "card3": _spec(1, ["2A"]), "breakpoint": [True, True],
    }
    selected = select_command_cards([strategy], cards, preselected_nps=[1])
    assert selected[0] == {"type": "np", "servant": 1}
    assert [card["slot"] for card in selected[1:]] == [1, 2]


def test_strategy_matches_combined_card_code_and_special_key():
    cards = [_card(1, "1B"), _card(2, "2A"), _card(3, "1B"), _card(4, "3Q")]
    cards[1]["special_keys"] = ["S0"]
    cards[2]["special_keys"] = ["S0"]
    strategy = {"card1": _spec(1, ["1BS0"]), "card2": _spec(2, []), "card3": _spec(2, [])}
    assert select_command_cards([strategy], cards)[0]["slot"] == 3


@pytest.mark.parametrize("breakpoint", [[False, "false"], [True], True])
def test_strategy_rejects_invalid_breakpoints(breakpoint):
    strategy = {f"card{index}": _spec(2, []) for index in range(1, 4)}
    strategy["breakpoint"] = breakpoint
    with pytest.raises(StrategySelectionError, match="breakpoint"):
        select_command_cards([strategy], [_card(1, "1B"), _card(2, "2A"), _card(3, "3Q")])


@pytest.mark.parametrize("preselected", [[1, 1], [1, 2, 3, 1]])
def test_strategy_rejects_duplicate_preselected_nps(preselected):
    strategy = {f"card{index}": _spec(2, []) for index in range(1, 4)}
    with pytest.raises(StrategySelectionError, match="duplicate"):
        select_command_cards([strategy], [_card(1, "1B"), _card(2, "2A"), _card(3, "3Q")], preselected_nps=preselected)


def test_strategy_backtracking_matches_exhaustive_face_card_oracle():
    cards = [_card(slot, code) for slot, code in enumerate(("1B", "1A", "2B", "2A", "3Q"), 1)]
    preferences = [["1B", "2B"], ["1A", "2A"], ["1B"], ["3Q"], [card["code"] for card in cards]]
    for specs in product(preferences, repeat=3):
        for breakpoints in product((False, True), repeat=2):
            valid = [
                candidate for candidate in permutations(cards, 3)
                if all(card["code"] in preference for card, preference in zip(candidate, specs, strict=True))
                and all(
                    not enabled or candidate[index]["servant_position"] != candidate[index + 1]["servant_position"]
                    for index, enabled in enumerate(breakpoints)
                )
            ]
            strategy = {f"card{index}": _spec(1, preference) for index, preference in enumerate(specs, 1)}
            strategy["breakpoint"] = list(breakpoints)
            if not valid:
                with pytest.raises(StrategySelectionError, match="no matching"):
                    select_command_cards([strategy], cards)
                continue
            expected = min(valid, key=lambda candidate: tuple(
                (preference.index(card["code"]), card["slot"])
                for card, preference in zip(candidate, specs, strict=True)
            ))
            assert [card["slot"] for card in select_command_cards([strategy], cards)] == [card["slot"] for card in expected]


def test_strategy_backtracks_past_branch_with_unknown_star_counts():
    cards = [_card(1, "1B", 10), _card(2, "2A", None), _card(3, "3Q", 0)]
    strategy = {
        "card1": _spec(1, ["1B", "2A"]), "card2": _spec(1, ["1B"], stars=5),
        "card3": _spec(1, ["3Q"]),
    }
    assert [card["slot"] for card in select_command_cards([strategy], cards)] == [2, 1, 3]


def test_strategy_known_star_match_is_not_blocked_by_unrelated_unknown_card():
    cards = [_card(1, "1B", 10), _card(2, "2A", None), _card(3, "3Q", 0)]
    strategy = {
        "card1": _spec(1, ["1B"], stars=5), "card2": _spec(1, ["2A"]),
        "card3": _spec(1, ["3Q"]),
    }
    assert [card["slot"] for card in select_command_cards([strategy], cards)] == [1, 2, 3]


def test_strategy_does_not_treat_unknown_stars_as_known_zero_for_maximum_constraint():
    cards = [_card(1, "1B", None), _card(2, "2A", 0), _card(3, "3Q", 1)]
    strategy = {"card1": _spec(1, ["1B", "2A"], stars=0, more=False), "card2": _spec(2, []), "card3": _spec(2, [])}
    assert select_command_cards([strategy], cards)[0]["slot"] == 2


def test_default_card_selection_weights_affinity_brave_chain_buffs_and_np_color():
    # Case 1: Weak affinity and Buster Brave Chain outweigh resist cards.
    cards = [
        {**_card(1, "1Q", 0), "affinity": "resist", "affinity_score": -1},
        {**_card(2, "2B", 8), "affinity": "weak", "affinity_score": 1},
        {**_card(3, "1A", 0), "affinity": "resist", "affinity_score": -1},
        {**_card(4, "2B", 5), "affinity": "weak", "affinity_score": 1},
        {**_card(5, "2B", 10), "affinity": "weak", "affinity_score": 1},
    ]
    selected = select_command_cards_default(cards)
    assert [entry["slot"] for entry in selected] == [4, 2, 5]

    # Case 2: With 1 NP preselected on servant 1 (Buster NP), picking servant 1's two remaining
    # Buster face cards triggers the same-color Buster Brave Chain bonus (1.5 * 3.5 = 5.25).
    np_cards = [
        _card(1, "2A", 0),
        _card(2, "1B", 0),
        _card(3, "3Q", 0),
        _card(4, "1B", 0),
        _card(5, "2Q", 0),
    ]
    selected_with_np = select_command_cards_default(
        np_cards,
        preselected_nps=[1],
        frontline_servants=[
            {"slot": 0, "battle_position": 1, "sn": "101", "np_color": "B"},
            {"slot": 1, "battle_position": 2, "sn": "102", "np_color": "A"},
            {"slot": 2, "battle_position": 3, "sn": "103", "np_color": "Q"},
        ],
        buff_counts={0: 3},
        np_servants={0},
        server="CH",
    )
    assert selected_with_np == [
        {"type": "np", "servant": 1},
        {"type": "face", "slot": 2, "code": "1B", "stars": 0},
        {"type": "face", "slot": 4, "code": "1B", "stars": 0},
    ]

