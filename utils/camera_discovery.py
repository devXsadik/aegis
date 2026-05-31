"""
Camera Discovery Utility
Scan local network for RTSP/HTTP cameras, probe streams, output config entries
"""

import argparse
import cv2
import ipaddress
import json
import socket
import sys
import time
import concurrent.futures
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse


def _tcp_check(host: str, port: int, timeout: float = 2.0) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False
    finally:
        s.close()


def probe_rtsp(uri: str, timeout: float = 5.0) -> Optional[Dict]:
    """Open an RTSP stream with cv2 and return stream info."""
    cap = cv2.VideoCapture(uri)
    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(timeout * 1000))
    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(timeout * 1000))
    start = time.time()
    if not cap.isOpened():
        cap.release()
        return None
    ret, frame = cap.read()
    elapsed_ms = (time.time() - start) * 1000
    info = {
        "connected": ret,
        "connection_time_ms": round(elapsed_ms, 1),
        "uri": uri,
    }
    if ret and frame is not None:
        h, w = frame.shape[:2]
        fps = cap.get(cv2.CAP_PROP_FPS)
        codec = int(cap.get(cv2.CAP_PROP_FOURCC))
        codec_str = "".join(chr((codec >> 8 * i) & 0xFF) for i in range(4)) if codec else "unknown"
        info.update({
            "width": w, "height": h, "fps": round(fps, 1),
            "codec": codec_str.strip(), "connected": True,
        })
    cap.release()
    return info


def probe_mjpeg(uri: str, timeout: float = 5.0) -> Optional[Dict]:
    """Probe an HTTP MJPEG stream."""
    return probe_rtsp(uri, timeout)


def probe_onvif(host: str, port: int = 80, user: str = "", password: str = "") -> Dict:
    """Check ONVIF capabilities (requires onvif-zeep)."""
    result = {"onvif_available": False, "ptz_supported": False, "model": None}
    try:
        from onvif import ONVIFCamera
        cam = ONVIFCamera(host, port, user, password)
        dev_info = cam.devicemgmt.GetDeviceInformation()
        result["onvif_available"] = True
        result["model"] = dev_info.Model
        try:
            cam.ptz.GetServiceCapabilities()
            result["ptz_supported"] = True
        except Exception:
            pass
    except ImportError:
        result["onvif_error"] = "onvif not installed (pip install onvif-zeep)"
    except Exception as e:
        result["onvif_error"] = str(e)
    return result


def scan_subnet(subnet: str = "192.168.1.0/24",
                ports: List[int] = None,
                timeout: float = 2.0,
                max_workers: int = 50) -> List[Dict]:
    """TCP scan subnet for open camera ports, then probe each."""
    if ports is None:
        ports = [554, 80, 8080]
    network = ipaddress.ip_network(subnet, strict=False)
    hosts = [str(ip) for ip in network.hosts()]

    found = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {}
        for host in hosts:
            for port in ports:
                future = executor.submit(_tcp_check, host, port, timeout)
                future_map[future] = (host, port)
        for future in concurrent.futures.as_completed(future_map):
            host, port = future_map[future]
            if future.result():
                uri_candidates = []
                if port == 554:
                    uri_candidates.append(f"rtsp://{host}:554/live")
                    uri_candidates.append(f"rtsp://{host}:554/stream1")
                    uri_candidates.append(f"rtsp://{host}:554/h264")
                elif port in (80, 8080):
                    uri_candidates.append(f"http://{host}:{port}/video")
                    uri_candidates.append(f"http://{host}:{port}/mjpg")
                    uri_candidates.append(f"http://{host}:{port}/cam")
                found.append({"host": host, "port": port, "uris": uri_candidates})
    return found


def discover(subnet: str = "192.168.1.0/24",
             user: str = "",
             password: str = "") -> List[Dict]:
    """Full discovery: scan + probe + optional ONVIF."""
    candidates = scan_subnet(subnet)
    cameras = []
    for c in candidates:
        for uri in c["uris"]:
            info = probe_rtsp(uri) if "rtsp" in uri else probe_mjpeg(uri)
            if info and info.get("connected"):
                cam_info = {
                    "camera_id": f"cam_{c['host'].replace('.', '_')}",
                    "name": f"Camera {c['host']}:{c['port']}",
                    "uri": uri,
                    "location": c["host"],
                    "lat": 0.0,
                    "lng": 0.0,
                    "resolution": f"{info.get('width','?')}x{info.get('height','?')}",
                    "fps": info.get("fps", 0),
                    "connection_time_ms": info.get("connection_time_ms", 0),
                }
                if "rtsp" in uri and user:
                    onvif_info = probe_onvif(c["host"], port=554 if c["port"] == 554 else 80, user=user, password=password)
                    cam_info["ptz_supported"] = onvif_info.get("ptz_supported", False)
                cameras.append(cam_info)
                break
    return cameras


def test_uri(uri: str, timeout: float = 5.0) -> Dict:
    """Test a single camera URI and return info."""
    info = probe_rtsp(uri, timeout=timeout)
    if info is None:
        return {"uri": uri, "connected": False, "error": "Failed to open stream"}
    return info


def main():
    parser = argparse.ArgumentParser(description="Camera Discovery & Testing Tool")
    parser.add_argument("--subnet", type=str, default="",
                        help="Network to scan (e.g. 192.168.1.0/24)")
    parser.add_argument("--test", type=str, default="",
                        help="Test a single RTSP/HTTP URI")
    parser.add_argument("--user", type=str, default="",
                        help="Username for ONVIF auth")
    parser.add_argument("--password", type=str, default="",
                        help="Password for ONVIF auth")
    parser.add_argument("--timeout", type=float, default=3.0,
                        help="Connection timeout per host (seconds)")
    parser.add_argument("--output", type=str, default="",
                        help="Write results to file (JSON)")
    args = parser.parse_args()

    results = {}

    if args.test:
        print(f"Testing: {args.test}")
        info = test_uri(args.test, timeout=args.timeout)
        results["test"] = info
        if info.get("connected"):
            print(f"  Connected: YES")
            print(f"  Resolution: {info.get('width','?')}x{info.get('height','?')}")
            print(f"  FPS: {info.get('fps', '?')}")
            print(f"  Codec: {info.get('codec', '?')}")
            print(f"  Connection time: {info.get('connection_time_ms', '?')}ms")
        else:
            print(f"  Connected: NO")
            print(f"  Error: {info.get('error', 'Connection failed')}")
        return

    if args.subnet:
        print(f"Scanning subnet: {args.subnet} (timeout={args.timeout}s)...")
        cameras = discover(subnet=args.subnet, user=args.user, password=args.password)
        results["cameras"] = cameras
        if cameras:
            print(f"\nFound {len(cameras)} camera(s):")
            print()
            for cam in cameras:
                print(f"  ID:       {cam['camera_id']}")
                print(f"  Name:     {cam['name']}")
                print(f"  URI:      {cam['uri']}")
                print(f"  Res:      {cam['resolution']}")
                print(f"  FPS:      {cam['fps']}")
                print(f"  PTZ:      {cam.get('ptz_supported', False)}")
                print(f"  Config snippet:")
                print(f"    - id: {cam['camera_id']}")
                print(f"      name: \"{cam['name']}\"")
                print(f"      uri: \"{cam['uri']}\"")
                print(f"      location: \"{cam['location']}\"")
                print(f"      lat: {cam['lat']}")
                print(f"      lng: {cam['lng']}")
                print()
        else:
            print("No cameras found in subnet.")
    else:
        parser.print_help()

    if args.output and results:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Results written to {args.output}")


if __name__ == "__main__":
    main()
