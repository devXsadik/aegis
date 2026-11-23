"""Request ids, route metrics, JSON logs and the error-report scrubber."""
import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import observability as o


def _app():
    app = FastAPI()

    @app.get("/items/{item_id}")
    def item(item_id: int):
        logging.getLogger("t").info("got %s", item_id)
        return {"id": item_id}

    app.add_middleware(o.RequestContextMiddleware)
    return app


def test_request_id_and_route_template_metrics():
    o.reset()
    c = TestClient(_app())
    r = c.get("/items/7", headers={"X-Request-ID": "abc123"})
    assert r.headers["x-request-id"] == "abc123"
    assert len(c.get("/items/8").headers["x-request-id"]) == 16
    c.get("/items/notanumber")
    text = "\n".join(o.prometheus_lines())
    assert 'aegis_http_requests_total{method="GET",route="/items/{item_id}",status="2xx"} 2' in text
    assert 'route="/items/{item_id}",status="4xx"} 1' in text
    assert 'aegis_http_request_duration_seconds_count{method="GET",route="/items/{item_id}"} 3' in text
    assert "/items/7" not in text                      # templates only: no ids, plates or names in labels


def test_json_log_line_carries_request_id():
    token = o.request_id.set("rid-1")
    try:
        rec = logging.LogRecord("x", logging.WARNING, __file__, 1, "camera %s down", ("cam1",), None)
        out = json.loads(o.JsonFormatter().format(rec))
    finally:
        o.request_id.reset(token)
    assert out["msg"] == "camera cam1 down" and out["request_id"] == "rid-1" and out["level"] == "WARNING"


def test_scrub_drops_personal_data_and_secrets():
    ev = {"request": {"url": "https://x/api/v1/plates?plate=DHA123", "data": {"name": "someone"},
                      "cookies": {"aegis_session": "s"}, "query_string": "plate=DHA123",
                      "headers": {"Authorization": "Bearer t", "X-Internal-Key": "k", "User-Agent": "ua"}},
          "user": {"username": "op1"},
          "exception": {"values": [{"stacktrace": {"frames": [{"function": "f", "vars": {"face": "..."}}]}}]}}
    out = o.scrub_event(ev)
    assert out["request"] == {"url": "https://x/api/v1/plates", "headers": {"User-Agent": "ua"}}
    assert "user" not in out and "vars" not in out["exception"]["values"][0]["stacktrace"]["frames"][0]
