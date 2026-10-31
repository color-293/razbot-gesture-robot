"""Goal / home-run scene detection with a local CLIP model (zero-shot)."""
import threading
import time
from collections import deque

import cv2

# scenes we want to celebrate
POSITIVE = [
    "a soccer player celebrating a goal with arms raised",
    "a soccer ball in the back of the goal net",
    "soccer players hugging and celebrating after scoring a goal",
    "a baseball player hitting a home run",
    "a baseball player running the bases after a home run",
    "baseball players celebrating a home run at home plate",
    "a crowd of fans cheering wildly in a stadium",
]
# everything else that is likely on screen
NEGATIVE = [
    "soccer players running on the field during a match",
    "a wide shot of a soccer field from above",
    "a goalkeeper catching the ball",
    "a baseball pitcher throwing a pitch",
    "a batter standing at home plate waiting for a pitch",
    "a wide shot of a baseball field",
    "a close-up of a coach or player standing still",
    "a TV commercial",
    "a news anchor in a studio",
    "a living room",
    "a black screen",
    "a person's hand in front of the camera",
]

MODEL_NAME, PRETRAINED = "ViT-B-32", "openai"


class SceneDetector:
    """Runs CLIP on the latest frame about once per second in a background thread."""

    def __init__(self, on_trigger, threshold=0.6, hits_needed=2, cooldown=20.0, interval=0.8):
        self.on_trigger = on_trigger
        self.threshold = threshold
        self.hits_needed = hits_needed
        self.cooldown = cooldown
        self.interval = interval
        self.enabled = False
        self.ready = False
        self.error = None
        self.score = 0.0
        self.top = None
        self.scores = deque(maxlen=60)        # recent scores for the UI chart
        self.events = deque(maxlen=20)
        self._frame = None
        self._hits = 0
        self._last_trigger = 0.0
        self._lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, frame_bgr):
        self._frame = frame_bgr

    def _load(self):
        import open_clip
        import torch

        torch.set_num_threads(3)  # leave a core for the camera / web server
        model, _, preprocess = open_clip.create_model_and_transforms(MODEL_NAME, pretrained=PRETRAINED)
        model.eval()
        tokenizer = open_clip.get_tokenizer(MODEL_NAME)
        with torch.no_grad():
            text = model.encode_text(tokenizer(POSITIVE + NEGATIVE))
            text /= text.norm(dim=-1, keepdim=True)
        return torch, model, preprocess, text

    def _run(self):
        try:
            torch, model, preprocess, text = self._load()
        except Exception as e:
            self.error = f"CLIP 로드 실패: {e}"
            print(self.error)
            return
        from PIL import Image

        self.ready = True
        n_pos = len(POSITIVE)
        labels = POSITIVE + NEGATIVE
        while True:
            frame = self._frame
            if not self.enabled or frame is None:
                time.sleep(0.2)
                continue
            t0 = time.time()
            img = preprocess(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))).unsqueeze(0)
            with torch.no_grad():
                feat = model.encode_image(img)
                feat /= feat.norm(dim=-1, keepdim=True)
                probs = (100.0 * feat @ text.T).softmax(dim=-1)[0]
            score = float(probs[:n_pos].sum())
            top = labels[int(probs.argmax())]
            self._judge(score, top)
            time.sleep(max(0.0, self.interval - (time.time() - t0)))

    def _judge(self, score, top):
        now = time.time()
        with self._lock:
            self.score, self.top = score, top
            self.scores.append(round(score, 3))
            self._hits = self._hits + 1 if score >= self.threshold else 0
            fire = self._hits >= self.hits_needed and now - self._last_trigger > self.cooldown
            if fire:
                self._hits = 0
                self._last_trigger = now
                self.events.appendleft({"time": time.strftime("%H:%M:%S"), "score": round(score, 2), "scene": top})
        if fire:
            self.on_trigger()

    def snapshot(self):
        with self._lock:
            return {"enabled": self.enabled, "ready": self.ready, "error": self.error,
                    "score": round(self.score, 3), "top": self.top, "threshold": self.threshold,
                    "scores": list(self.scores), "events": list(self.events),
                    "cooldown": max(0.0, self.cooldown - (time.time() - self._last_trigger))}
