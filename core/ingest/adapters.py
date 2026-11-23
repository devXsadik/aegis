"""Vendor adapters: AI cameras that already detect faces / plates / vehicles send their own
event JSON; each adapter turns one into NormalizedEvent(s).

Vendor formats differ by firmware. These follow the common shapes of Hikvision ISAPI ANPR /
face-capture events and Dahua TrafficJunction / FaceDetection events; field names that vary are
looked up in several places. Add a vendor by writing one function and listing it in ADAPTERS.
Unknown colours / types map to "other" with the vendor's word kept in attribute_confidences."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from core.ingest.events import EventError, NormalizedEvent

COLOR_MAP = {
    "white": "white", "black": "black", "silver": "silver", "silvery": "silver", "gray": "grey", "grey": "grey",
    "red": "red", "blue": "blue", "green": "green", "yellow": "yellow", "golden": "yellow", "orange": "orange",
    "brown": "brown", "maroon": "maroon", "purple": "other", "pink": "other", "cyan": "blue", "darkgray": "grey",
    "darkgrey": "grey",
}
TYPE_MAP = {
    "car": "car", "sedan": "car", "saloon": "car", "hatchback": "car", "smallcar": "car", "vehicle": "car",
    "suv": "suv", "jeep": "suv", "mpv": "microbus", "van": "microbus", "minibus": "microbus", "microbus": "microbus",
    "pickup": "pickup", "pickuptruck": "pickup", "bus": "bus", "largebus": "bus", "truck": "truck",
    "largetruck": "truck", "lighttruck": "truck", "heavytruck": "truck", "containertruck": "covered_van",
    "coveredvan": "covered_van", "boxtruck": "covered_van", "motorcycle": "motorcycle", "motorbike": "motorcycle",
    "twowheeler": "motorcycle", "tricycle": "cng", "threewheeler": "cng", "autorickshaw": "cng", "cng": "cng",
    "ambulance": "ambulance", "leguna": "leguna", "easybike": "easy_bike", "erickshaw": "easy_bike",
}


def norm_color(v) -> Optional[str]:
    if not v:
        return None
    return COLOR_MAP.get(str(v).lower().replace(" ", "").replace("_", ""), "other")


def norm_type(v) -> Optional[str]:
    if not v:
        return None
    return TYPE_MAP.get(str(v).lower().replace(" ", "").replace("_", "").replace("-", ""), "other")


def _dig(d: dict, *paths, default=None):
    """First non-empty value among dotted paths."""
    for p in paths:
        cur = d
        for part in p.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        if cur not in (None, "", []):
            return cur
    return default


def _conf(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f / 100 if f > 1 else f


# ——— adapters ———

def generic(payload: dict, camera_id: str) -> List[NormalizedEvent]:
    """Our own schema; a single event or {"events": [...]}."""
    items = payload.get("events") if isinstance(payload.get("events"), list) else [payload]
    out = []
    for it in items:
        it = dict(it)
        it.setdefault("camera_id", camera_id)
        if it["camera_id"] != camera_id:
            raise EventError("camera_id in the body does not match the authenticated camera")
        it.setdefault("source", "webhook:generic")
        for k in ("color", "color_secondary"):
            if it.get(k):
                it[k] = norm_color(it[k])
        if it.get("vehicle_type"):
            it["vehicle_type"] = norm_type(it["vehicle_type"])
        out.append(NormalizedEvent.from_dict(it))
    return out


def hikvision(payload: dict, camera_id: str) -> List[NormalizedEvent]:
    kind = str(_dig(payload, "eventType", "EventNotificationAlert.eventType", default="")).lower()
    root = payload.get("EventNotificationAlert", payload)
    ts = _dig(root, "dateTime", "time")
    pic = _dig(root, "picture", "pictureData", "ANPR.pictureData", "faceCapture.faceImage", "targetImage")
    if kind in ("anpr", "vehicledetection", "trafficdetection"):
        anpr = root.get("ANPR", {}) or {}
        veh = root.get("Vehicle", {}) or root.get("vehicleInfo", {}) or {}
        vendor_color = _dig(veh, "vehicleColor", "color") or _dig(anpr, "vehicleColor")
        vendor_type = _dig(veh, "vehicleType") or _dig(anpr, "vehicleType")
        make = _dig(veh, "vehicleLogoRecog", "vehicleBrand")
        model = _dig(veh, "vehicleSubLogoRecog", "vehicleModel")
        conf = {}
        for k, v in (("plate", _dig(anpr, "confidenceLevel")), ("color", _dig(veh, "colorConfidence")),
                     ("type", _dig(veh, "typeConfidence"))):
            c = _conf(v)
            if c is not None:
                conf[k] = c
        return [NormalizedEvent(
            camera_id=camera_id, type="vehicle", timestamp=ts, source="webhook:hikvision",
            plate_text=_dig(anpr, "licensePlate", "plateNumber"), plate_confidence=conf.get("plate"),
            vehicle_type=norm_type(vendor_type), color=norm_color(vendor_color),
            make_model=" ".join(str(x) for x in (make, model) if x) or None, attribute_confidences=conf,
            crop_image=pic, direction=_dig(anpr, "direction"),
            extra={"vendor_color": vendor_color, "vendor_type": vendor_type})]
    if kind in ("facecapture", "facedetection", "facesnap"):
        fc = root.get("faceCapture", root)
        return [NormalizedEvent(camera_id=camera_id, type="face", timestamp=ts, source="webhook:hikvision",
                                crop_image=pic, quality=_conf(_dig(fc, "faceScore", "quality")))]
    raise EventError(f"Unsupported Hikvision event type: {kind or 'missing'}")


def dahua(payload: dict, camera_id: str) -> List[NormalizedEvent]:
    code = str(_dig(payload, "Code", "code", default=""))
    data = payload.get("Data") or payload.get("data") or {}
    ts = _dig(data, "UTC", "utc") or _dig(payload, "UTC")
    box = _dig(data, "Object.BoundingBox", "BoundingBox")
    bbox = None
    if isinstance(box, list) and len(box) == 4:          # Dahua: x1,y1,x2,y2 in a 8192 x 8192 space
        x1, y1, x2, y2 = (float(v) / 8192 for v in box)
        bbox = [x1, y1, max(0.0, x2 - x1), max(0.0, y2 - y1)]
    if code in ("TrafficJunction", "TrafficParking", "TrafficVehicle", "ANPR"):
        car = data.get("TrafficCar", {}) or {}
        obj = data.get("Object", {}) or {}
        vendor_color = car.get("VehicleColor") or obj.get("Color")
        vendor_type = car.get("VehicleType") or obj.get("Category")
        brand = car.get("VehicleSign") or obj.get("Brand")
        conf = {}
        c = _conf(car.get("PlateConfidence") or obj.get("Confidence"))
        if c is not None:
            conf["plate"] = c
        return [NormalizedEvent(
            camera_id=camera_id, type="vehicle", timestamp=ts, source="webhook:dahua", bbox=bbox,
            plate_text=car.get("PlateNumber") or obj.get("Text"), plate_confidence=conf.get("plate"),
            vehicle_type=norm_type(vendor_type), color=norm_color(vendor_color), make_model=brand,
            attribute_confidences=conf, crop_image=_dig(payload, "Image", "image"),
            direction=car.get("Direction"), extra={"vendor_color": vendor_color, "vendor_type": vendor_type})]
    if code in ("FaceDetection", "FaceRecognition"):
        return [NormalizedEvent(camera_id=camera_id, type="face", timestamp=ts, source="webhook:dahua", bbox=bbox,
                                crop_image=_dig(payload, "Image", "image"))]
    raise EventError(f"Unsupported Dahua event code: {code or 'missing'}")


ADAPTERS: Dict[str, Callable[[dict, str], List[NormalizedEvent]]] = {
    "generic": generic, "aegis": generic, "simulator": generic, "hikvision": hikvision, "dahua": dahua,
}


def normalize(vendor: str, payload: dict, camera_id: str) -> List[NormalizedEvent]:
    fn = ADAPTERS.get((vendor or "generic").lower())
    if not fn:
        raise EventError(f"No adapter for vendor '{vendor}'. Known: {', '.join(sorted(ADAPTERS))}")
    if not isinstance(payload, dict):
        raise EventError("Event body must be a JSON object")
    return fn(payload, camera_id)
