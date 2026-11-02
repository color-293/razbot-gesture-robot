"""개인기 훈련: teach the robot tricks the way you would teach a puppy.

  1. pick a trick in the 훈련 tab -> the robot tries it
  2. if it did well, reward it within a few seconds: 👍 thumbs up to the camera (or the "잘했어!" button)
  3. three rewarded tries -> the trick is learned (memory + EXP); learned tricks can be shown any time
  Lv10 (나만의 개인기): put together your own sequence of moves and train it the same way.
"""
import threading
import time

TRICKS = {  # key -> (emoji, name, robot moves)
    "bow": ("🙇", "꾸벅 인사", ["bow"]),
    "spin": ("🌀", "빙글 돌기", ["spin_dance"]),
    "dance": ("💃", "신나는 춤", ["happy_dance"]),
    "wiggle": ("🐕", "엉덩이 흔들기", ["wiggle"]),
}
CUSTOM = ("🎬", "나만의 개인기")
MOVES = {  # building blocks for 나만의 개인기
    "step_forward": "⬆️ 앞으로",
    "step_back": "⬇️ 뒤로",
    "turn_left": "⬅️ 왼쪽 돌기",
    "turn_right": "➡️ 오른쪽 돌기",
    "wiggle": "〰️ 흔들기",
    "spin_dance": "🌀 빙글",
    "bow": "🙇 꾸벅",
    "beep": "🔔 삐!",
}
MAX_CUSTOM = 6
REPS_TO_LEARN = 3
MAX_TRIES = 8
REWARD_WAIT = 6          # s to wait for a thumbs up after each try
THUMBS_FRAMES = 4        # thumbs-up frames in a row that count as a reward


class Cancelled(Exception):
    pass


class Training:
    def __init__(self, pet, saved=None):
        saved = saved or {}
        self.pet = pet
        self.progress = {k: int(v) for k, v in (saved.get("progress") or {}).items()}
        self.custom = [m for m in (saved.get("custom") or []) if m in MOVES][:MAX_CUSTOM]
        self.active = False
        self.trick = None
        self.phase = "idle"
        self.message = ""
        self._reward = threading.Event()
        self._cancel = threading.Event()
        self._thumbs = 0

    # ---------- tricks ----------
    def info(self, key):
        if key == "custom":
            return CUSTOM[0], CUSTOM[1], self.custom
        return TRICKS[key]

    def exists(self, key):
        return key in TRICKS or (key == "custom" and bool(self.custom))

    def learned(self, key):
        return self.progress.get(key, 0) >= REPS_TO_LEARN

    def set_custom(self, moves):
        moves = [m for m in moves if m in MOVES][:MAX_CUSTOM]
        if not moves:
            return False
        self.custom = moves
        self.progress["custom"] = 0          # a new routine has to be learned again
        self.pet.save()
        return True

    # ---------- input ----------
    def feed(self, label):
        self._thumbs = self._thumbs + 1 if label == "thumbs_up" else 0
        if self.phase == "waiting" and self._thumbs >= THUMBS_FRAMES:
            self._reward.set()

    def reward(self):
        """The web "잘했어!" button."""
        if self.phase == "waiting":
            self._reward.set()
            return True
        return False

    # ---------- control ----------
    def start(self, key):
        pet = self.pet
        if self.active or not self.exists(key):
            return False
        if not pet.growth.has("training") or (key == "custom" and not pet.growth.has("custom_trick")):
            return False
        self.active, self.trick = True, key
        self._cancel.clear()
        threading.Thread(target=self._run, args=(key,), daemon=True).start()
        return True

    def show(self, key):
        """Perform a learned trick once (no training)."""
        if self.active or not self.exists(key) or not self.learned(key) or self.pet.busy():
            return False
        emoji, name, moves = self.info(key)
        threading.Thread(target=self._do, args=(moves, f"{emoji} {name}!"), daemon=True).start()
        self.pet.note(f"{emoji} {name} 보여 줬어요")
        return True

    def cancel(self):
        if self.active:
            self._cancel.set()

    def _wait(self, seconds):
        if self._cancel.wait(seconds) or not self.pet.active():
            raise Cancelled

    def _say(self, phase, message):
        self.phase, self.message = phase, message

    def _do(self, moves, text=None):
        pet = self.pet
        pet.face.show("happy", 1 + 0.8 * len(moves))
        for m in moves:
            if m == "beep":
                pet.beep(0.3)
            else:
                pet.perform(None, 0, None, m)

    def _run(self, key):
        pet = self.pet
        emoji, name, moves = self.info(key)
        try:
            self._say("intro", f"{emoji} {name} 연습하자! 잘하면 👍 엄지 척 해 줘")
            pet.perform("happy", 2, "hello")
            self._wait(1.0)
            tries = 0
            while self.progress.get(key, 0) < REPS_TO_LEARN and tries < MAX_TRIES:
                tries += 1
                done = self.progress.get(key, 0)
                self._say("trying", f"{name} 해 볼게… ({done}/{REPS_TO_LEARN})")
                self._do(moves)
                self._reward.clear()
                self._thumbs = 0
                self._say("waiting", "어땠어? 잘했으면 👍 엄지 척!")
                deadline = time.time() + REWARD_WAIT
                while not self._reward.is_set() and time.time() < deadline:
                    self._wait(0.1)
                if self._reward.is_set():
                    self.progress[key] = done + 1
                    self._say("good", f"헤헤, 칭찬받았다! ({done + 1}/{REPS_TO_LEARN}) 💕")
                    pet.note(f"🎓 {name} 연습 성공 ({done + 1}/{REPS_TO_LEARN})", mood="happy", secs=20, grow="train")
                    pet.perform("love", 2, "love")
                else:
                    self._say("miss", "헷갈려… 다시 해 볼게 🤔")
                    pet.perform("bored", 1.5, "sad")
                self._wait(1.0)
            if self.learned(key):
                self._say("learned", f"🎉 {name} 배웠다! 이제 언제든 보여 줄게")
                pet.note(f"🎓 {emoji} {name}을(를) 배웠어요!", mood="happy", secs=60, grow="trick_learned", cheer_up=True)
                pet.daily.remember("🎓", f"{emoji} {name}을(를) 배웠어요")
                pet.perform("happy", 4, "fanfare", "happy_dance")
            else:
                self._say("tired", "오늘은 여기까지… 다음에 또 연습하자 😮‍💨")
                pet.perform("sleepy", 2, "night")
        except Cancelled:
            self._say("idle", "훈련 그만!")
        finally:
            self.active = False
            if self.phase not in ("learned", "tired"):
                self.phase = "idle"
            pet.activity_over()

    # ---------- persistence / web ----------
    def state(self):
        return {"progress": self.progress, "custom": self.custom}

    def snapshot(self):
        tricks = [{"key": k, "emoji": e, "name": n, "progress": min(self.progress.get(k, 0), REPS_TO_LEARN),
                   "reps": REPS_TO_LEARN, "learned": self.learned(k)} for k, (e, n, _) in TRICKS.items()]
        return {"active": self.active, "trick": self.trick, "phase": self.phase, "message": self.message,
                "tricks": tricks, "moves": MOVES, "max_custom": MAX_CUSTOM,
                "custom": {"moves": self.custom, "progress": min(self.progress.get("custom", 0), REPS_TO_LEARN),
                           "reps": REPS_TO_LEARN, "learned": self.learned("custom")}}
