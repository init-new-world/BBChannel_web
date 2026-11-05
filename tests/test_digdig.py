from webapp.automation.digdig import (
    DIGDIG_BOARD_GRID_INSPECT_JOB_KIND,
    DIGDIG_EXECUTE_JOB_KIND,
    DIGDIG_INSPECT_JOB_KIND,
    DIGDIG_RUN_JOB_KIND,
    create_digdig_board_grid_inspect_handler,
    create_digdig_execute_handler,
    create_digdig_inspect_handler,
    create_digdig_run_handler,
    register_digdig_board_grid_inspect_job,
    register_digdig_execute_job,
    register_digdig_inspect_job,
    register_digdig_run_job,
)
from webapp.core.models import MatchResult, OperationResult
from webapp.runtime import JobDatabase, JobManager
from webapp.services.digdig import DigdigRecognizer


def _match(template_path, matched, confidence):
    return MatchResult(
        template_path=template_path,
        matched=matched,
        confidence=confidence,
        threshold=0.82,
        top_left=[300, 200],
        size=[60, 50],
        center=[330, 225],
        scale=2 / 3,
    )


class _Resources:
    def template_index(self, *, prefix, limit):
        assert prefix == "digdig/CH"
        assert limit == 100
        return {
            "entries": [
                {"path": "digdig/CH/freeDig.png"},
                {"path": "digdig/CH/execute.png"},
                {"path": "digdig/CH/hammer_claw.png"},
                {"path": "digdig/CH/shovel_bone.png"},
                {"path": "digdig/CH/reward.png"},
            ]
        }


def test_digdig_recognizer_reports_board_state_and_visible_piece_tools():
    class Recognition:
        def __init__(self):
            self.candidates = None

        def match_templates(self, _screenshot, candidates):
            self.candidates = candidates
            return [
                _match(candidate["template_path"], True, 0.95 - index * 0.01)
                for index, candidate in enumerate(candidates)
            ]

    recognition = Recognition()
    report = DigdigRecognizer(_Resources(), recognition).recognize(
        b"screen",
        "ch",
    )

    assert [candidate["template_path"] for candidate in recognition.candidates] == [
        "digdig/CH/execute.png",
        "digdig/CH/freeDig.png",
        "digdig/CH/reward.png",
        "digdig/CH/hammer_claw.png",
        "digdig/CH/shovel_bone.png",
    ]
    assert report["server"] == "CH"
    assert report["state"] == "execute"
    assert report["status"] == "actionable"
    assert report["recommended_action"] == "execute_dig"
    assert [(piece["name"], piece["tool"]) for piece in report["pieces"]] == [
        ("hammer_claw", "hammer"),
        ("shovel_bone", "shovel"),
    ]
    assert report["suggested_tool"] == "hammer"


class _ScriptData:
    def get_setting_plan(self, name):
        assert name == "demo"
        return {
            "server": "CH",
            "run": {"random_touch": False, "random_time": 0},
        }


class _Device:
    def __init__(self):
        self.taps = []

    def snapshot(self):
        return b"dig-screen"

    def tap(self, x, y):
        self.taps.append((x, y))
        return OperationResult(ok=True, action="tap", data={"x": x, "y": y})


class _Context:
    def __init__(self):
        self.events = []
        self.sleeps = []

    def checkpoint(self, step, **options):
        self.events.append(("checkpoint", step, options))

    def emit(self, event_type, message, **options):
        self.events.append((event_type, message, options))

    def sleep(self, seconds):
        self.sleeps.append(seconds)


def test_digdig_inspect_handler_reports_current_board():
    class Recognizer:
        def recognize(self, screenshot, server, *, threshold):
            assert screenshot == b"dig-screen"
            assert server == "CH"
            assert threshold == 0.9
            return {
                "server": server,
                "state": "freeDig",
                "status": "observed",
                "recommended_action": None,
                "matches": [],
                "pieces": [],
                "suggested_tool": None,
            }

    context = _Context()
    result = create_digdig_inspect_handler(
        _ScriptData(),
        _Device(),
        Recognizer(),
    )(context, {"setting_name": "demo", "threshold": 0.9})

    assert result["state"] == "freeDig"
    assert [event[0] for event in context.events] == [
        "checkpoint",
        "digdig_state",
        "checkpoint",
    ]


def test_digdig_inspect_job_requires_connected_device(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_digdig_inspect_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )

        assert manager.has_kind(DIGDIG_INSPECT_JOB_KIND)
        assert manager.requires_device(DIGDIG_INSPECT_JOB_KIND) is True


def _report(state, status, *, action=None, center=(760, 590)):
    matches = []
    if state != "unknown":
        matches.append(
            {
                "name": state,
                "status": status,
                "recommended_action": action,
                "center": list(center),
                "size": [120, 60],
            }
        )
    return {
        "server": "CH",
        "state": state,
        "status": status,
        "recommended_action": action,
        "matches": matches,
        "pieces": [],
        "suggested_tool": None,
    }


def test_digdig_execute_taps_selection_and_waits_for_result():
    reports = iter(
        (
            _report("execute", "actionable", action="execute_dig"),
            _report("digResult", "observed"),
        )
    )

    class Recognizer:
        def recognize(self, _screenshot, server, *, threshold):
            assert server == "CH"
            assert threshold == 0.82
            return next(reports)

    device = _Device()
    context = _Context()
    result = create_digdig_execute_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(
        context,
        {
            "setting_name": "demo",
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert result["completed"] is True
    assert result["stopped"] is False
    assert result["reason"] == "dig_result"
    assert result["actions"] == ["execute_dig"]
    assert device.taps == [(760, 590)]
    assert context.events[-1][0:2] == ("checkpoint", "complete")


def test_digdig_execute_refuses_to_tap_without_execute_state():
    class Recognizer:
        def recognize(self, _screenshot, _server, *, threshold):
            assert threshold == 0.82
            return _report("freeDig", "observed")

    device = _Device()
    result = create_digdig_execute_handler(
        _ScriptData(),
        device,
        Recognizer(),
    )(_Context(), {"setting_name": "demo"})

    assert result["completed"] is False
    assert result["reason"] == "no_actionable_selection"
    assert result["actions"] == []
    assert device.taps == []


def test_digdig_execute_job_requires_connected_device(tmp_path):
    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_digdig_execute_job(
            manager,
            _ScriptData(),
            _Device(),
            object(),
        )

        assert manager.has_kind(DIGDIG_EXECUTE_JOB_KIND)
        assert manager.requires_device(DIGDIG_EXECUTE_JOB_KIND) is True


def test_digdig_recognizer_board_grid_maps_cells_pieces_and_intersections():
    class GridResources:
        def template_index(self, *, prefix, limit):
            assert prefix == "digdig/CH"
            assert limit == 100
            return {
                "entries": [
                    {"path": "digdig/CH/shovel.png"},
                    {"path": "digdig/CH/hammer.png"},
                    {"path": "digdig/CH/pickaxe.png"},
                    {"path": "digdig/CH/shovel_bone.png"},
                    {"path": "digdig/CH/hammer_claw.png"},
                    {"path": "digdig/CH/hx0.png"},
                    {"path": "digdig/CH/jlg0.png"},
                ]
            }

    class GridRecognition:
        def __init__(self):
            self.calls = []

        def match_templates(self, _screenshot, candidates):
            self.calls.append(candidates)
            if len(self.calls) == 1:
                results = []
                for idx, candidate in enumerate(candidates):
                    slot = idx // 3
                    path = candidate["template_path"]
                    if slot == 0:
                        matched = False
                        conf = 0.0
                    elif slot == 1 and path.endswith("/shovel.png"):
                        matched = True
                        conf = 0.92
                    else:
                        matched = path.endswith("/hammer.png")
                        conf = 0.88 if matched else 0.0
                    results.append(_match(path, matched, conf))
                return results
            results = []
            for candidate in candidates:
                path = candidate["template_path"]
                roi = candidate["roi"]
                if roi == (705, 250, 87, 87) and path.endswith("/shovel_bone.png"):
                    results.append(_match(path, True, 0.94))
                elif roi == (617, 337, 88, 86) and path.endswith("/hammer_claw.png"):
                    results.append(_match(path, True, 0.91))
                elif roi == (661, 293, 88, 87) and path.endswith("/hx0.png"):
                    results.append(_match(path, True, 0.89))
                else:
                    results.append(_match(path, False, 0.0))
            return results

    recognition = GridRecognition()
    report = DigdigRecognizer(GridResources(), recognition).recognize_board_grid(
        b"screen",
        "ch",
    )

    assert len(recognition.calls) == 2
    assert report["server"] == "CH"
    assert report["rows"] == 4
    assert report["columns"] == 7
    assert report["available_template_count"] == 7
    assert report["recognized_tool_count"] == 27
    assert report["recognized_piece_count"] == 2
    assert report["recognized_intersection_count"] == 1
    assert report["dug_count"] == 1
    assert len(report["slots"]) == 28
    assert len(report["intersections"]) == 18

    slot0 = report["slots"][0]
    assert slot0["dug"] is True
    assert slot0["tool"] is None
    assert slot0["piece"] is None
    assert slot0["piece_id"] is None

    slot1 = report["slots"][1]
    assert slot1["dug"] is False
    assert slot1["tool"] == "shovel"
    assert slot1["piece"] == "shovel_bone"
    assert slot1["piece_id"] == 2

    slot7 = report["slots"][7]
    assert slot7["dug"] is False
    assert slot7["tool"] == "hammer"
    assert slot7["piece"] == "hammer_claw"
    assert slot7["piece_id"] == 10

    inter0 = report["intersections"][0]
    assert inter0["surrounding_slots"] == [0, 1, 7, 8]
    assert inter0["dug_slots"] == [0]
    assert inter0["undug_slots"] == [1, 7, 8]
    assert inter0["phase"] == 0
    assert inter0["probe_slot"] is None
    assert inter0["material"] == "hx"
    assert inter0["material_id"] == 1

    inter1 = report["intersections"][1]
    assert inter1["surrounding_slots"] == [1, 2, 8, 9]
    assert inter1["dug_slots"] == []
    assert inter1["phase"] is None
    assert inter1["probe_slot"] == 9
    assert inter1["material"] is None


def test_digdig_board_grid_inspect_handler_and_registration(tmp_path):
    class Recognizer:
        def recognize_board_grid(self, screenshot, server, *, threshold):
            assert screenshot == b"dig-screen"
            assert server == "CH"
            assert threshold == 0.75
            return {
                "server": server,
                "rows": 4,
                "columns": 7,
                "recognized_tool_count": 20,
                "recognized_piece_count": 12,
                "recognized_intersection_count": 2,
                "dug_count": 8,
                "slots": [],
                "intersections": [],
            }

    context = _Context()
    result = create_digdig_board_grid_inspect_handler(
        _ScriptData(),
        _Device(),
        Recognizer(),
    )(context, {"setting_name": "demo", "threshold": 0.75})

    assert result["setting_name"] == "demo"
    assert result["recognized_tool_count"] == 20
    assert result["dug_count"] == 8
    assert [event[0] for event in context.events] == [
        "checkpoint",
        "digdig_board_grid",
        "checkpoint",
    ]

    with JobManager(JobDatabase(tmp_path / "runtime.db")) as manager:
        register_digdig_board_grid_inspect_job(
            manager,
            _ScriptData(),
            _Device(),
            Recognizer(),
        )
        assert manager.has_kind(DIGDIG_BOARD_GRID_INSPECT_JOB_KIND)
        assert manager.requires_device(DIGDIG_BOARD_GRID_INSPECT_JOB_KIND) is True


def test_digdig_run_handler_supports_one_key_and_filtered_excavation_cycles(tmp_path):
    class OneKeyRecognizer:
        def __init__(self):
            self.states = [
                {
                    "server": "CH",
                    "state": "execute",
                    "status": "actionable",
                    "recommended_action": "execute_dig",
                    "matches": [
                        {
                            "name": "execute",
                            "center": [845, 565],
                            "size": [100, 40],
                        }
                    ],
                },
                {
                    "server": "CH",
                    "state": "digResult",
                    "status": "observed",
                    "recommended_action": None,
                    "matches": [{"name": "digResult"}],
                },
                {
                    "server": "CH",
                    "state": "freeDig",
                    "status": "observed",
                    "recommended_action": None,
                    "matches": [{"name": "freeDig"}],
                },
            ]

        def recognize(self, _screenshot, _server, *, threshold):
            assert threshold == 0.82
            return self.states.pop(0)

    device = _Device()
    context = _Context()
    one_key_result = create_digdig_run_handler(
        _ScriptData(),
        device,
        OneKeyRecognizer(),
    )(
        context,
        {
            "setting_name": "demo",
            "one_key": True,
            "max_cycles": 1,
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert one_key_result["completed"] is True
    assert one_key_result["stopped"] is False
    assert one_key_result["mode"] == "one_key"
    assert one_key_result["reason"] == "max_cycles_reached"
    assert one_key_result["cycles_completed"] == 1
    assert one_key_result["actions"] == ["free_dig", "execute_dig", "go_ahead"]
    assert device.taps == [(1070, 200), (845, 565), (640, 637)]

    class FilterRecognizer:
        def __init__(self):
            def make_slots(dug_set):
                return [
                    {
                        "slot": slot,
                        "dug": slot in dug_set,
                        "piece": (
                            None
                            if slot in dug_set
                            else "shovel_bone" if slot == 1 else "hammer_teeth"
                        ),
                        "piece_id": (
                            None if slot in dug_set else 2 if slot == 1 else 6
                        ),
                    }
                    for slot in range(28)
                ]

            initial_dug = set(range(28)) - {1, 7, 8, 19, 20, 26, 27}
            after_piece_dug = initial_dug | {1}
            after_probe_dug = after_piece_dug | {7, 8, 27}
            self.board_reports = [
                {
                    "server": "CH",
                    "rows": 4,
                    "columns": 7,
                    "slots": make_slots(initial_dug),
                    "intersections": [
                        {
                            "index": idx,
                            "material": "hx" if idx == 0 else None,
                            "material_id": 1 if idx == 0 else None,
                        }
                        for idx in range(18)
                    ],
                },
                {
                    "server": "CH",
                    "rows": 4,
                    "columns": 7,
                    "slots": make_slots(after_piece_dug),
                    "intersections": [
                        {
                            "index": idx,
                            "material": "hx" if idx == 0 else None,
                            "material_id": 1 if idx == 0 else None,
                        }
                        for idx in range(18)
                    ],
                },
                {
                    "server": "CH",
                    "rows": 4,
                    "columns": 7,
                    "slots": make_slots(after_probe_dug),
                    "intersections": [
                        {
                            "index": idx,
                            "material": "jlg" if idx == 17 else None,
                            "material_id": 2 if idx == 17 else None,
                        }
                        for idx in range(18)
                    ],
                },
            ]
            self.state_reports = [
                # Cell 1 triggers first-dig confirmation then digResult -> corner
                {"server": "CH", "state": "needConfirm", "status": "observed", "matches": []},
                {"server": "CH", "state": "checkmark", "status": "observed", "matches": []},
                {"server": "CH", "state": "digResult", "status": "observed", "matches": []},
                {"server": "CH", "state": "corner", "status": "observed", "matches": []},
                # Intersection 0 surrounding undug cell 7
                {"server": "CH", "state": "reward", "status": "observed", "matches": []},
                {"server": "CH", "state": "corner", "status": "observed", "matches": []},
                # Intersection 0 surrounding undug cell 8
                {"server": "CH", "state": "digResult", "status": "observed", "matches": []},
                {"server": "CH", "state": "corner", "status": "observed", "matches": []},
                # Intersection 17 unexposed probe cell 27
                {"server": "CH", "state": "digResult", "status": "observed", "matches": []},
                {"server": "CH", "state": "corner", "status": "observed", "matches": []},
                # Intersection 17 surrounding undug cells 19, 20, 26
                {"server": "CH", "state": "digResult", "status": "observed", "matches": []},
                {"server": "CH", "state": "corner", "status": "observed", "matches": []},
                {"server": "CH", "state": "digResult", "status": "observed", "matches": []},
                {"server": "CH", "state": "corner", "status": "observed", "matches": []},
                {"server": "CH", "state": "digResult", "status": "observed", "matches": []},
                {"server": "CH", "state": "corner", "status": "observed", "matches": []},
                # Reset board confirmation
                {
                    "server": "CH",
                    "state": "execute",
                    "status": "actionable",
                    "matches": [{"name": "execute", "center": [840, 563], "size": [100, 40]}],
                },
            ]

        @staticmethod
        def board_cell_roi(slot: int):
            return DigdigRecognizer.board_cell_roi(slot)

        def recognize_board_grid(self, _screenshot, _server, *, threshold):
            assert threshold == 0.7
            return self.board_reports.pop(0)

        def recognize(self, _screenshot, _server, *, threshold):
            assert threshold == 0.82
            return self.state_reports.pop(0)

    filter_device = _Device()
    filter_context = _Context()
    filter_result = create_digdig_run_handler(
        _ScriptData(),
        filter_device,
        FilterRecognizer(),
    )(
        filter_context,
        {
            "setting_name": "demo",
            "one_key": False,
            "target_pieces": ["bone"],
            "target_extras": ["hx", "jlg"],
            "max_cycles": 1,
            "reset_board": True,
            "action_wait_seconds": 0,
            "poll_interval": 0,
        },
    )

    assert filter_result["completed"] is True
    assert filter_result["stopped"] is False
    assert filter_result["mode"] == "filter"
    assert filter_result["target_piece_ids"] == [2]
    assert filter_result["target_extra_ids"] == [1, 2]
    assert filter_result["dug_cells"] == [1, 7, 8, 27, 19, 20, 26]
    assert filter_result["matched_intersections"] == [0, 17]
    assert filter_result["cycles_completed"] == 1
    assert filter_result["actions"] == [
        "dig_cell_1",
        "checkmark",
        "confirm",
        "go_ahead",
        "dig_cell_7",
        "go_ahead",
        "dig_cell_8",
        "go_ahead",
        "dig_cell_27",
        "go_ahead",
        "dig_cell_19",
        "go_ahead",
        "dig_cell_20",
        "go_ahead",
        "dig_cell_26",
        "go_ahead",
        "reset_board",
        "execute_reset",
    ]

    with JobManager(JobDatabase(tmp_path / "runtime2.db")) as manager:
        register_digdig_run_job(
            manager,
            _ScriptData(),
            _Device(),
            FilterRecognizer(),
        )
        assert manager.has_kind(DIGDIG_RUN_JOB_KIND)
        assert manager.requires_device(DIGDIG_RUN_JOB_KIND) is True
