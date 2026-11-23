"""Officer ETAs: OSRM road times when configured, a labelled straight-line estimate otherwise."""
from backend.services import routing


def test_estimate_without_osrm(monkeypatch):
    monkeypatch.delenv("OSRM_URL", raising=False)
    out = routing.etas((23.78, 90.41), {1: (23.79, 90.41)})       # ~1.1 km north
    assert out[1]["eta_source"] == "estimate"
    assert 250 < out[1]["eta_s"] < 300                            # 1.1 km × 1.4 at 20 km/h ≈ 4.6 min


def test_osrm_table(monkeypatch):
    calls = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": "Ok", "durations": [[420.4], [None]], "distances": [[3100.2], [None]]}

    def get(url, params, timeout):
        calls.update(url=url, params=params)
        return Resp()
    import requests
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setenv("OSRM_URL", "http://osrm:5000/")
    out = routing.etas((23.78, 90.41), {7: (23.79, 90.42), 8: (23.70, 90.30)})
    assert calls["url"] == "http://osrm:5000/table/v1/driving/90.410000,23.780000;90.420000,23.790000;90.300000,23.700000"
    assert calls["params"]["destinations"] == "0" and calls["params"]["sources"] == "1;2"
    assert out[7] == {"eta_s": 420, "route_m": 3100, "eta_source": "road"}
    assert out[8]["eta_source"] == "estimate"                     # no road route found: estimate


def test_osrm_down_falls_back(monkeypatch):
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setenv("OSRM_URL", "http://osrm:5000")
    assert routing.etas((23.78, 90.41), {1: (23.79, 90.41)})[1]["eta_source"] == "estimate"
