import cv2

class PoseAnalyzer:
    def __init__(self):
        try:
            import mediapipe as mp
            self.pose = mp.solutions.pose.Pose()
            self.use_mp = True
        except AttributeError:
            print("Warning: mediapipe.solutions not available. PoseAnalyzer disabled.")
            self.pose = None
            self.use_mp = False

    def analyze(self, roi):
        if not self.use_mp or self.pose is None:
            return None
        rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
        result = self.pose.process(rgb)
        return result.pose_landmarks
