"""Hand gesture detection with MediaPipe Tasks HandLandmarker."""
import math
import time
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode

MODEL = Path(__file__).with_name("hand_landmarker.task")

# landmark indices
WRIST = 0
THUMB_IP, THUMB_TIP = 3, 4
FINGERS = [(5, 6, 8), (9, 10, 12), (13, 14, 16), (17, 18, 20)]  # (mcp, pip, tip): index, middle, ring, pinky
CONNECTIONS = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11),
               (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17)]


def _dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def classify(lm):
    """Return (label, fingers) where fingers = [thumb, index, middle, ring, pinky] booleans."""
    wrist = lm[WRIST]
    palm = _dist(wrist, lm[9]) or 1e-6
    # a finger is extended when its tip is clearly farther from the wrist than its pip joint
    ext = [_dist(wrist, lm[tip]) > _dist(wrist, lm[pip]) * 1.15 for _, pip, tip in FINGERS]
    thumb = _dist(lm[THUMB_TIP], lm[5]) / palm > 0.6 and _dist(lm[THUMB_TIP], lm[17]) > _dist(lm[THUMB_IP], lm[17])
    fingers = [thumb] + ext
    n = sum(ext)

    if n == 0:
        if thumb and lm[THUMB_TIP].y < lm[5].y - 0.3 * palm:
            return "thumbs_up", fingers
        return "rock", fingers
    if ext == [True, True, False, False]:
        return "scissors", fingers
    if ext == [True, False, False, False]:
        return "point", fingers
    if n >= 4:
        return "paper", fingers
    return "unknown", fingers


class GestureDetector:
    def __init__(self):
        opts = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL)),
            running_mode=RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.6,
            min_tracking_confidence=0.5,
        )
        self.landmarker = HandLandmarker.create_from_options(opts)
        self._t0 = time.monotonic()

    def detect(self, frame_bgr):
        """Return (label, fingers, landmarks); label is None when no hand is visible."""
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        ts = int((time.monotonic() - self._t0) * 1000)
        result = self.landmarker.detect_for_video(image, ts)
        if not result.hand_landmarks:
            return None, None, None
        lm = result.hand_landmarks[0]
        label, fingers = classify(lm)
        return label, fingers, lm


def draw(frame, lm, color=(0, 255, 120)):
    h, w = frame.shape[:2]
    pts = [(int(p.x * w), int(p.y * h)) for p in lm]
    for a, b in CONNECTIONS:
        cv2.line(frame, pts[a], pts[b], color, 2)
    for p in pts:
        cv2.circle(frame, p, 4, (255, 255, 255), -1)
