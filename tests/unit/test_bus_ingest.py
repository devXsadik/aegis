"""Event bus (in-memory semantics) and vendor adapters → normalized events."""
import pytest

from core.bus import MemoryBus, drain
from core.ingest.adapters import normalize, norm_color, norm_type
from core.ingest.events import EventError, NormalizedEvent, decode_vec, encode_vec


def test_memory_bus_groups_each_see_every_message_once():
    bus = MemoryBus()
    for i in range(5):
        bus.publish("detections", {"n": i})
    a = bus.read("detections", "matcher", "m1", count=3, block_ms=0)
    b = bus.read("detections", "matcher", "m2", count=10, block_ms=0)
    assert [d["n"] for _, d in a] == [0, 1, 2] and [d["n"] for _, d in b] == [3, 4]   # shared in a group
    other = bus.read("detections", "tracker", "t1", count=10, block_ms=0)
    assert len(other) == 5                                                              # every group sees all
    assert bus.pending("detections", "matcher") == 5
    bus.ack("detections", "matcher", *[m for m, _ in a + b])
    assert bus.pending("detections", "matcher") == 0
    assert bus.read("detections", "matcher", "m1", block_ms=0) == []


def test_drain_and_maxlen():
    bus = MemoryBus()
    for i in range(10):
        bus.publish("s", {"n": i}, maxlen=4)
    seen = []
    assert drain(bus, "s", "g", "c", lambda d: seen.append(d["n"])) == 4
    assert seen == [6, 7, 8, 9]


def test_event_validation_and_vectors():
    with pytest.raises(EventError):
        NormalizedEvent(camera_id="", type="face")
    with pytest.raises(EventError):
        NormalizedEvent(camera_id="c", type="cat")
    with pytest.raises(EventError):
        NormalizedEvent(camera_id="c", type="face", bbox=[1, 2])
    ev = NormalizedEvent(camera_id="c", type="vehicle", timestamp=1_700_000_000, attribute_confidences={"color": 87})
    assert ev.timestamp.startswith("2023-11-14") and ev.attribute_confidences["color"] == 1.0
    v = decode_vec(encode_vec([0.5, -1.0, 2.0]))
    assert list(v) == [0.5, -1.0, 2.0]
    round_trip = NormalizedEvent.from_dict({**ev.to_dict(), "custom": 1})
    assert round_trip.extra["custom"] == 1


def test_vendor_maps():
    assert norm_color("Silvery") == "silver" and norm_color("Gray") == "grey" and norm_color("Purple") == "other"
    assert norm_type("SUV") == "suv" and norm_type("MPV") == "microbus" and norm_type("Tricycle") == "cng"


def test_hikvision_anpr():
    evs = normalize("hikvision", {"eventType": "ANPR", "dateTime": "2026-11-23T10:00:00+06:00",
                                  "ANPR": {"licensePlate": "DHAKA METRO GA 12-3456", "confidenceLevel": 91, "direction": "N"},
                                  "Vehicle": {"vehicleColor": "white", "vehicleType": "SUV", "vehicleLogoRecog": "Toyota"}}, "cam1")
    e = evs[0]
    assert (e.type, e.plate_text, e.color, e.vehicle_type, e.make_model) == ("vehicle", "DHAKA METRO GA 12-3456", "white", "suv", "Toyota")
    assert e.plate_confidence == pytest.approx(0.91) and e.timestamp == "2026-11-23T04:00:00" and e.source == "webhook:hikvision"


def test_dahua_traffic_and_face():
    e = normalize("dahua", {"Code": "TrafficJunction", "Data": {"UTC": 1_763_892_000,
        "TrafficCar": {"PlateNumber": "ঢাকা মেট্রো-গ ১২-৩৪৫৬", "VehicleColor": "Black", "VehicleType": "Sedan"},
        "Object": {"BoundingBox": [0, 0, 4096, 4096]}}}, "c2")[0]
    assert e.color == "black" and e.vehicle_type == "car" and e.bbox == [0.0, 0.0, 0.5, 0.5]
    f = normalize("dahua", {"Code": "FaceDetection", "Data": {"UTC": 1_763_892_000}}, "c2")[0]
    assert f.type == "face"
    with pytest.raises(EventError):
        normalize("dahua", {"Code": "VideoMotion"}, "c2")


def test_generic_and_camera_mismatch():
    evs = normalize("generic", {"events": [{"type": "vehicle", "plate_text": "X 12-3456", "color": "Gray"},
                                           {"type": "face"}]}, "c3")
    assert [e.type for e in evs] == ["vehicle", "face"] and evs[0].color == "grey"
    with pytest.raises(EventError):
        normalize("generic", {"camera_id": "other", "type": "face"}, "c3")
    with pytest.raises(EventError):
        normalize("acme", {}, "c3")
