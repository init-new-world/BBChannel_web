from importlib.util import find_spec

from fastapi.testclient import TestClient


def create_test_client(app) -> TestClient:
    backend_options = None
    if find_spec("uvloop") is not None:
        import uvloop

        backend_options = {"loop_factory": uvloop.new_event_loop}
    return TestClient(app, backend_options=backend_options)
