import math


SUSPICIOUS_SPEED_THRESHOLD = 150
SUSPICIOUS_LOITER_SECONDS = 15
SUSPICIOUS_ERRATIC_ANGLE = 60


def is_suspicious_behavior(track_history, pose_landmarks=None):
    reasons = []
    if len(track_history) < 5:
        return False, reasons

    recent = track_history[-10:]
    speeds = []
    for i in range(1, len(recent)):
        _, cx1, cy1 = recent[i - 1]
        _, cx2, cy2 = recent[i]
        dt = recent[i][0] - recent[i - 1][0]
        if dt > 0:
            speed = math.hypot(cx2 - cx1, cy2 - cy1) / dt
            speeds.append(speed)

    if speeds and max(speeds) > SUSPICIOUS_SPEED_THRESHOLD:
        reasons.append("rapid_movement")

    duration = recent[-1][0] - recent[0][0]
    if duration > SUSPICIOUS_LOITER_SECONDS:
        reasons.append("loitering")

    if len(track_history) >= 15:
        mid = len(track_history) // 2
        _, fx, fy = track_history[mid]
        _, lx, ly = track_history[-1]
        direction_changes = 0
        for i in range(2, len(track_history)):
            _, px, py = track_history[i - 2]
            _, cx, cy = track_history[i - 1]
            _, nx, ny = track_history[i]
            v1 = (cx - px, cy - py)
            v2 = (nx - cx, ny - cy)
            dot = v1[0] * v2[0] + v1[1] * v2[1]
            mag1 = math.hypot(*v1)
            mag2 = math.hypot(*v2)
            if mag1 > 0 and mag2 > 0:
                angle = math.degrees(math.acos(max(-1, min(1, dot / (mag1 * mag2)))))
                if angle > SUSPICIOUS_ERRATIC_ANGLE:
                    direction_changes += 1
        if direction_changes >= 4:
            reasons.append("erratic_movement")

    return len(reasons) > 0, reasons
