import pytest

from webapp.automation.battle import _matches_hakuno_needs
from webapp.automation import battle


@pytest.mark.parametrize("need", [["S0"], ["1BS0"]])
def test_hakuno_needs_match_a_custom_tag_on_an_available_card(need):
    cards = [{"code": "1B", "special_keys": ["S0"], "available": True}]
    assert _matches_hakuno_needs(cards, [need]) is True


@pytest.mark.parametrize("need", [["1B", "S0"], ["S0", "1BS0"], ["S0", "S1"], ["1B", "1B"]])
def test_one_physical_card_cannot_satisfy_multiple_hakuno_needs_via_aliases(need):
    cards = [{"code": "1B", "special_keys": ["S0", "S1"], "available": True}]
    assert _matches_hakuno_needs(cards, [need]) is False


def test_hakuno_tag_matching_can_choose_another_card_to_complete_the_combination():
    cards = [{"code": "1B", "special_keys": ["S0"], "available": True},
             {"code": "2A", "special_keys": ["S0"], "available": True}]
    assert _matches_hakuno_needs(cards, [["S0", "1B"]]) is True
    assert _matches_hakuno_needs(cards, [["S0", "S0"]]) is True
    assert _matches_hakuno_needs(cards, [["S0", "S0", "S0"]]) is False


def test_combined_hakuno_tag_needs_also_require_the_ordinary_card_code():
    cards = [{"code": "2A", "special_keys": ["S0"], "available": True}]
    assert _matches_hakuno_needs(cards, [["1BS0"]]) is False
    assert _matches_hakuno_needs(cards, [["2AS0"]]) is True


@pytest.mark.parametrize("card", [{"code": "1B", "special_keys": ["S0"], "available": False},
                                 {"code": None, "special_keys": ["S0"], "available": True},
                                 {"code": "2A", "special_keys": ["S1"], "available": True}])
def test_unavailable_unrecognized_and_nonmatching_cards_do_not_satisfy_tag_needs(card):
    assert _matches_hakuno_needs([card], [["S0"], ["1BS0"]]) is False


@pytest.mark.parametrize("tags", [None, "S0", {"S0": True}, []])
def test_malformed_tag_lists_never_expand_into_tag_matches(tags):
    cards = [{"code": "1B", "special_keys": tags}]
    assert _matches_hakuno_needs(cards, [["S0"]]) is False
    assert _matches_hakuno_needs(cards, [["1B"]]) is True


def test_hakuno_tag_needs_keep_unordered_alternatives_and_empty_combination_behavior():
    cards = [{"code": "1B", "special_keys": ["S0"]}, {"code": "2A", "special_keys": []}]
    assert _matches_hakuno_needs(cards, [["3Q"], ["2A", "1BS0"]]) is True
    assert _matches_hakuno_needs(cards, []) is False
    assert _matches_hakuno_needs(cards, [[]]) is True


@pytest.mark.parametrize("needs,expected", [([], False), ([[]], True), ([["S0"]], False)])
def test_empty_hands_keep_existing_need_semantics(needs, expected):
    assert _matches_hakuno_needs([], needs) is expected


def test_five_card_tag_assignment_keeps_the_last_permutation_and_skips_oversized_alternatives():
    cards = [{"code": code, "special_keys": [f"S{index}"]}
             for index, code in enumerate(["1B", "1A", "2Q", "2B", "3A"])]
    need = ["S4", "S3", "S2", "S1", "S0"]
    assert _matches_hakuno_needs(cards, [need + ["S0"], need]) is True
    assert _matches_hakuno_needs(cards, [need + ["S0"]]) is False


def test_oversized_needs_are_rejected_before_generating_assignments(monkeypatch):
    def unexpected_permutations(*_args):
        pytest.fail("Oversized needs must not generate permutations.")

    monkeypatch.setattr(battle, "permutations", unexpected_permutations)
    assert _matches_hakuno_needs([{"code": "1B", "special_keys": ["S0"]}], [["S0"] * 1000]) is False
