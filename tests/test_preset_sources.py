import json

import pytest

from tests.test_api import _client, _strategy_payload


def _setup(tmp_path):
    client = _client(tmp_path)
    (tmp_path / "data" / "servant_info_CH.json").write_text("{}")
    return client


def _value(kind):
    if kind == "settings":
        return {"server": "CH", "round1_turns": 1, "round1_turn0_skill": [1.0],
                "extension": {"integer": 9007199254740993, "float": 1.0}}
    return [{"tag": "Typed", "strategy": _strategy_payload(),
             "extension": {"integer": 9007199254740993, "float": 1.0}}]


@pytest.mark.parametrize("kind", ["settings", "strategies"])
def test_preset_details_include_the_original_json_source_from_one_document(tmp_path, kind):
    client = _setup(tmp_path)
    directory = tmp_path / "data" / ("settings" if kind == "settings" else "strategy")
    directory.mkdir()
    source = "\n" + json.dumps(_value(kind), indent=3) + "\n"
    (directory / "Typed.json").write_text(source)
    response = client.get(f"/api/{kind}/Typed")
    assert response.status_code == 200
    assert response.json()["source"] == source
    assert json.loads(response.json()["source"]) == _value(kind)
    if kind == "settings":
        program = client.get("/api/settings/Typed/program")
        assert program.status_code == 200
        assert program.json()["summary"]["unsupported_action_count"] == 1


@pytest.mark.parametrize("kind", ["settings", "strategies"])
def test_saving_source_preserves_float_types_and_large_integer_values(tmp_path, kind):
    client = _setup(tmp_path)
    source = json.dumps(_value(kind))
    response = client.put(f"/api/{kind}/Typed", json={"source": source})
    assert response.status_code == 200
    saved = json.loads(response.json()["source"])
    extension = saved["extension"] if kind == "settings" else saved[0]["extension"]
    assert extension["integer"] == 9007199254740993
    assert type(extension["integer"]) is int
    assert type(extension["float"]) is float
    if kind == "settings":
        assert type(saved["round1_turn0_skill"][0]) is float
        program = client.get("/api/settings/Typed/program")
        assert program.json()["summary"]["unsupported_action_count"] == 1
    else:
        assert response.json()["validation"]["ok"] is True
    assert client.get(f"/api/{kind}/Typed").json()["source"] == response.json()["source"]


@pytest.mark.parametrize("kind", ["settings", "strategies"])
def test_source_requests_keep_existing_name_and_overwrite_protection(tmp_path, kind):
    client = _setup(tmp_path)
    source = json.dumps(_value(kind))
    first = client.put(f"/api/{kind}/Typed", json={"source": source})
    assert first.status_code == 200
    assert client.put(f"/api/{kind}/Typed", json={"source": source}).status_code == 409
    second = client.put(f"/api/{kind}/Typed", json={"source": source, "overwrite": True})
    assert second.status_code == 200
    assert first.json()["source"] == second.json()["source"]


@pytest.mark.parametrize("kind", ["settings", "strategies"])
@pytest.mark.parametrize("source", ["{", "null", "true", '"text"', "123", '{"extension":NaN}', '{"extension":Infinity}'])
def test_invalid_json_sources_do_not_create_files(tmp_path, kind, source):
    client = _setup(tmp_path)
    response = client.put(f"/api/{kind}/Invalid", json={"source": source})
    assert response.status_code == 400
    assert client.get(f"/api/{kind}/Invalid").status_code == 404


@pytest.mark.parametrize("kind,source", [("settings", "[]"), ("strategies", "{}")])
def test_source_top_level_type_must_match_the_preset_kind(tmp_path, kind, source):
    client = _setup(tmp_path)
    response = client.put(f"/api/{kind}/Invalid", json={"source": source})
    assert response.status_code == 400


@pytest.mark.parametrize("kind,field", [("settings", "config"), ("strategies", "entries")])
@pytest.mark.parametrize("mode", ["both", "neither", "empty_source", "nonstring_source"])
def test_preset_requests_require_exactly_one_source_or_structured_payload(tmp_path, kind, field, mode):
    client = _setup(tmp_path)
    value = _value(kind)
    request = {"source": json.dumps(value), field: value} if mode == "both" else {}
    if mode == "empty_source":
        request["source"] = ""
    elif mode == "nonstring_source":
        request["source"] = value
    assert client.put(f"/api/{kind}/Invalid", json=request).status_code == 422


@pytest.mark.parametrize("kind,field", [("settings", "config"), ("strategies", "entries")])
def test_structured_preset_requests_remain_compatible(tmp_path, kind, field):
    client = _setup(tmp_path)
    response = client.put(f"/api/{kind}/Typed", json={field: _value(kind)})
    assert response.status_code == 200
    assert response.json()[field] == _value(kind)


@pytest.mark.parametrize("kind", ["settings", "strategies"])
def test_invalid_source_overwrite_leaves_the_existing_file_unchanged(tmp_path, kind):
    client = _setup(tmp_path)
    assert client.put(f"/api/{kind}/Typed", json={"source": json.dumps(_value(kind))}).status_code == 200
    path = tmp_path / "data" / ("settings" if kind == "settings" else "strategy") / "Typed.json"
    before = path.read_bytes()
    assert client.put(f"/api/{kind}/Typed", json={"source": "{", "overwrite": True}).status_code == 400
    assert path.read_bytes() == before


@pytest.mark.parametrize("kind", ["settings", "strategies"])
@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_nonfinite_numbers_in_otherwise_valid_source_are_rejected_before_writing(tmp_path, kind, number):
    client = _setup(tmp_path)
    source = json.dumps(_value(kind)).replace('"float": 1.0', f'"float": {number}')
    response = client.put(f"/api/{kind}/Invalid", json={"source": source})
    assert response.status_code == 400
    assert client.get(f"/api/{kind}/Invalid").status_code == 404
