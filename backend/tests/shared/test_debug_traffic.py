from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.observability.traffic import clear_traffic_events, get_traffic_events


def _client() -> TestClient:
    app = create_app()
    app.state.debug_traffic_enabled = True
    return TestClient(app)


def test_http_trace_uses_route_template_and_does_not_keep_query_string():
    clear_traffic_events()
    client = _client()

    response = client.get("/api/v1/sessions/live-logs?limit=1&token=do-not-store")

    assert response.status_code == 200
    event = get_traffic_events(10)[0]
    assert event["kind"] == "http"
    assert event["path"] == "/api/v1/sessions/live-logs"
    assert "token" not in str(event)
    assert "do-not-store" not in str(event)


def test_debug_route_map_includes_http_and_websocket_routes():
    response = _client().get("/api/v1/debug/routes")

    assert response.status_code == 200
    routes = response.json()["routes"]
    assert any(route["path"] == "/api/v1/cv/upload" for route in routes)
    assert any(route["path"] == "/ws/interview/{session_id}" and route["methods"] == ["WS"] for route in routes)


def test_websocket_trace_records_directions_but_not_payload_values(generated_model):
    clear_traffic_events()
    client = _client()

    created = client.post("/api/v1/sessions/create", json={
        "student_id": "TRACE_LOCAL", "target_company": "Local", "target_role": "Java Backend Intern",
    })
    assert created.status_code == 200
    with client.websocket_connect(f"/ws/interview/{created.json()['session_id']}") as websocket:
        assert websocket.receive_json()["type"] == "state_sync"
        assert websocket.receive_json()["type"] == "question_text"
        websocket.send_json({
            "type": "communication_features",
            "payload": {"private_text": "must-not-be-stored"},
        })

    events = get_traffic_events(20)
    assert any(
        event.get("direction") == "API → Browser" and event.get("message_type") == "state_sync"
        for event in events
    )
    assert any(
        event.get("direction") == "Browser → API" and event.get("message_type") == "communication_features"
        for event in events
    )
    assert "must-not-be-stored" not in str(events)
