import cv2
import mediapipe as mp


class FaceAnalyzer:
    def __init__(self):
        self.face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            min_detection_confidence=0.5,
        )
        self.mp_draw = mp.solutions.drawing_utils
        self.mesh_spec = mp.solutions.face_mesh.FACEMESH_TESSELATION

    def analyze(self, roi):
        if roi.size == 0:
            return None
        rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
        result = self.face_mesh.process(rgb)
        return result

    def draw_mesh(self, roi, landmarks):
        h, w = roi.shape[:2]
        for idx, lm in enumerate(landmarks.landmark):
            x, y = int(lm.x * w), int(lm.y * h)
            cv2.circle(roi, (x, y), 1, (0, 255, 0), -1)
