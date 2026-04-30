import cv2

class FaceAnalyzer:
    def __init__(self):
        try:
            import mediapipe as mp
            self.mp = mp
            self.mp_face_mesh = mp.solutions.face_mesh
            self.mp_drawing = mp.solutions.drawing_utils
            self.mp_drawing_styles = mp.solutions.drawing_styles
            
            self.face = self.mp_face_mesh.FaceMesh(
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5
            )
            self.use_mp = True
        except AttributeError:
            print("Warning: mediapipe.solutions not available. FaceAnalyzer disabled.")
            self.face = None
            self.use_mp = False

    def analyze(self, roi):
        if not self.use_mp or self.face is None:
            return None
        rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
        result = self.face.process(rgb)
        return result

    def draw_mesh(self, roi, face_landmarks):
        """Draws the face mesh on the given roi."""
        if not self.use_mp or not face_landmarks:
            return roi

        # Drawing specs for a premium sci-fi look (thin white/cyan lines)
        landmark_spec = self.mp_drawing.DrawingSpec(color=(255, 255, 255), thickness=1, circle_radius=1)
        connection_spec = self.mp_drawing.DrawingSpec(color=(200, 200, 200), thickness=1)

        # Draw tessellation
        self.mp_drawing.draw_landmarks(
            image=roi,
            landmark_list=face_landmarks,
            connections=self.mp_face_mesh.FACEMESH_TESSELLATION,
            landmark_drawing_spec=None,
            connection_drawing_spec=connection_spec
        )
        
        # Draw contours (eyes, lips, etc.) with a slightly brighter color
        contour_spec = self.mp_drawing.DrawingSpec(color=(255, 255, 255), thickness=1)
        self.mp_drawing.draw_landmarks(
            image=roi,
            landmark_list=face_landmarks,
            connections=self.mp_face_mesh.FACEMESH_CONTOURS,
            landmark_drawing_spec=None,
            connection_drawing_spec=contour_spec
        )
        return roi
