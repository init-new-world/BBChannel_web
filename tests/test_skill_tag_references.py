import pytest

from tests.test_api import _client, _write_json
from tests.test_command_tags import _import


@pytest.mark.parametrize("field,skill", [("round1_turn0_skill", 1), ("round1_turn2_skill", 4), ("round1_extraSkill", 7)])
@pytest.mark.parametrize("code", ["S0", "1BS0"])
def test_command_tag_unbind_blocks_hakuno_skill_need_references_without_writing_the_script(tmp_path, field, skill, code):
    client = _client(tmp_path)
    tag = _import(client)
    config = {"server": "CH", "specialKeys": [tag["template_path"]],
              field: [["Hakuno", skill, [[code]]]], "metadata": {"keep": 1.0}}
    path = tmp_path / "data/settings/demo.json"
    _write_json(path, config)
    before = path.read_bytes()
    response = client.put("/api/settings/demo/command-tags", json={"tag_name": tag["name"], "bound": False})
    assert response.status_code == 409, response.text
    details = response.json()["error"]["details"]
    assert details["code"] == "S0"
    assert details["fields"] == [field]
    assert path.read_bytes() == before
    assert client.get("/api/settings/demo").json()["config"] == config


@pytest.mark.parametrize("code", ["S01", "1BS00", "prefixS0"])
def test_skill_tag_reference_guard_uses_exact_tag_indices(tmp_path, code):
    client = _client(tmp_path)
    tag = _import(client)
    config = {"server": "CH", "specialKeys": [tag["template_path"]], "round1_turn0_skill": [["Hakuno", 1, [[code]]]]}
    _write_json(tmp_path / "data/settings/demo.json", config)
    response = client.put("/api/settings/demo/command-tags", json={"tag_name": tag["name"], "bound": False})
    assert response.status_code == 200, response.text
    assert response.json()["config"] == {**config, "specialKeys": []}


def test_unrelated_extension_fields_do_not_block_command_tag_unbinding(tmp_path):
    client = _client(tmp_path)
    tag = _import(client)
    config = {"server": "CH", "specialKeys": [tag["template_path"]], "metadata": {"note": "S0"},
              "round1_turn0_skills": [["Hakuno", 1, [["S0"]]]], "round1_turn0_skill": [1]}
    _write_json(tmp_path / "data/settings/demo.json", config)
    response = client.put("/api/settings/demo/command-tags", json={"tag_name": tag["name"], "bound": False})
    assert response.status_code == 200, response.text
    assert response.json()["config"] == {**config, "specialKeys": []}
