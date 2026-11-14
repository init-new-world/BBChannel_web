from webapp.services.event_log import EventLog


def test_event_log_returns_newest_events_in_append_order():
    log = EventLog(max_events=5)

    log.info("connect", "connected")
    log.error("snapshot", "failed", {"code": "snapshot_failed"})

    events = log.recent()
    assert [event["action"] for event in events] == ["connect", "snapshot"]
    assert events[0]["level"] == "info"
    assert events[1]["data"] == {"code": "snapshot_failed"}
    assert "timestamp" in events[0]


def test_event_log_trims_oldest_events():
    log = EventLog(max_events=2)

    log.info("one", "1")
    log.info("two", "2")
    log.info("three", "3")

    assert [event["action"] for event in log.recent()] == ["two", "three"]


def test_event_log_copies_event_data():
    log = EventLog(max_events=5)
    payload = {"nested": {"value": 1}}

    log.info("test", "message", payload)
    payload["nested"]["value"] = 2

    assert log.recent()[0]["data"] == {"nested": {"value": 1}}


def test_event_log_notifies_subscribers_until_unsubscribed():
    log = EventLog(max_events=5)
    received: list[dict] = []
    unsubscribe = log.subscribe(lambda event: received.append(event))

    log.info("connect", "connected", {"device_id": "dev1"})
    unsubscribe()
    unsubscribe()
    log.info("disconnect", "disconnected")

    assert len(received) == 1
    assert received[0]["action"] == "connect"
    assert received[0]["data"] == {"device_id": "dev1"}
