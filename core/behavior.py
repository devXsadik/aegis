import math

LEFT_SHOULDER = 11
LEFT_HIP = 23


def is_lying_down(landmarks):
    ls = landmarks[LEFT_SHOULDER]
    lh = landmarks[LEFT_HIP]
    return abs(ls.y - lh.y) < 0.05


def is_running(track_points, speed_threshold=100):
    if len(track_points) < 2:
        return False

    (t0, x0, y0) = track_points[0]
    (t1, x1, y1) = track_points[-1]

    dt = t1 - t0
    if dt <= 0:
        return False

    dist = math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)
    speed = dist / dt
    return speed > speed_threshold


def is_loitering(track_points, min_time=20, max_move=50):
    if len(track_points) == 0:
        return False

    t0, x0, y0 = track_points[0]
    t1, x1, y1 = track_points[-1]

    if t1 - t0 < min_time:
        return False

    dist = math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)
    return dist < max_move


def is_suspicious_behavior(track_points, pose_landmarks):
    lying = False
    if pose_landmarks is not None:
        landmarks = pose_landmarks.landmark
        lying = is_lying_down(landmarks)

    running = is_running(track_points)
    loiter = is_loitering(track_points)

    suspicious = lying or running or loiter
    reasons = []

    if lying:
        reasons.append("lying_down")
    if running:
        reasons.append("running_fast")
    if loiter:
        reasons.append("loitering")

    return suspicious, reasons
