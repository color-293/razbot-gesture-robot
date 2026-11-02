"""Rock-paper-scissors inside companion mode: playing together is one more way to bond with the robot.

The game is part of the robot's feelings, not a separate mode:
  - how it reacts to an invitation depends on its mood (sleepy / scared robots say no, a sulky one plays grudgingly)
  - every round gets an emotional reaction (gloating, pouting, surprise)
  - a finished match raises affection and leaves a lasting mood (and cheers up a sulky robot)
  - after it has called "play with me", coming back makes the robot suggest a game by itself

Flow: invite -> wait for a hand -> "가위, 바위, 보!" (beeps + OLED countdown) -> the robot shows its hand on the
OLED and reads yours -> reaction -> ... first to 2 wins.
"""
import random
import threading
import time
from collections import Counter, deque

HANDS = ("rock", "paper", "scissors")
BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}   # key beats value
KO = {"rock": "바위 ✊", "paper": "보 ✋", "scissors": "가위 ✌️"}

WINS_NEEDED = 2          # best of three
MAX_ROUNDS = 7           # draws do not count, but stop eventually
MAX_MISSES = 2           # rounds in a row without a readable hand -> give up
READY_TIMEOUT = 10       # s to wait for a hand after the invitation
THROW_READ = 1.0         # s after "보!" during which the user's hand is read
MATCH_LOVE = 2           # affection for finishing a match together
GOOD_SPORT_AT = 20       # affection from which the robot congratulates instead of pouting


class Cancelled(Exception):
    pass


class RpsGame:
    def __init__(self, pet, stats=None):
        self.pet = pet
        self.active = False
        self.phase = "idle"
        self.message = ""
        self.score = [0, 0]             # robot, user
        self.round = 0
        self.robot_hand = self.user_hand = None
        self.stats = {"played": 0, "robot": 0, "user": 0}
        self.stats.update(stats or {})
        self._labels = deque()          # (t, label) of recent frames
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    # ---------- input from the camera loop ----------
    def feed(self, label, now):
        with self._lock:
            self._labels.append((now, label))
            while self._labels and now - self._labels[0][0] > 3.0:
                self._labels.popleft()

    def _frames(self, since):
        with self._lock:
            return [(t, l) for t, l in self._labels if t >= since]

    # ---------- control ----------
    def start(self, intro=None):
        """Invite the user to a match; the robot may say no depending on its mood. Never blocks."""
        if self.active:
            return False
        self.active = True
        self._cancel.clear()
        with self._lock:
            self._labels.clear()        # only hands seen from now on count
        threading.Thread(target=self._run, args=(intro,), daemon=True).start()
        return True

    def cancel(self):
        if self.active:
            self._cancel.set()

    def _wait(self, seconds):
        if self._cancel.wait(seconds) or not self.pet.active():
            raise Cancelled

    def _say(self, phase, message):
        self.phase, self.message = phase, message

    # ---------- the match ----------
    def _run(self, intro):
        pet = self.pet
        try:
            if not self._accepts(intro):
                return
            self.score, self.round = [0, 0], 0
            self.robot_hand = self.user_hand = None
            if not self._wait_for_hand():
                self._say("over", "안 놀아 주는구나… 🥺")
                pet.perform("bored", 3, "sad")
                return
            misses = 0
            while max(self.score) < WINS_NEEDED and self.round < MAX_ROUNDS:
                self.round += 1
                robot, user = self._play_round()
                if user is None:
                    misses += 1
                    if misses > MAX_MISSES:
                        self._say("over", "손이 안 보여서 못 하겠어… 다음에 하자 🤔")
                        pet.perform("bored", 3, "sad")
                        return
                    self._say("result", "손이 안 보였어! 다시~ 🤔")
                    pet.perform("surprised", 1.5, "surprised")
                    self._wait(1.0)
                    continue
                misses = 0
                self._react(robot, user)
            self._finish()
        except Cancelled:
            self._say("over", "게임 그만!")
        finally:
            self.active = False
            if self.phase != "over":
                self.phase = "idle"
            pet.activity_over()

    def _accepts(self, intro):
        pet = self.pet
        if pet.mood == "sleepy":
            self._say("over", "너무 피곤해… 낮잠 재워 줘 😴" if pet.growth.low("energy") else "졸려… 내일 하자 😴")
            pet.perform("sleepy", 4, "night", "doze")
            return False
        if pet.mood == "scared":
            self._say("over", "무, 무서워서 지금은 못 하겠어… 😨")
            pet.perform("scared", 3, "scared", "tremble")
            return False
        if pet.mood == "sulky":
            self._say("invite", "…흥, 한 판만이야 😤 손 보여 줘")
            pet.perform("sulky", 2.5, "sad", "huff")
        else:
            self._say("invite", intro or "가위바위보 하자! 손 보여 줘 ✋")
            pet.perform("happy", 2.5, "game", "happy_wiggle")
        pet.note("🎮 가위바위보 시작")
        return True

    def _wait_for_hand(self):
        deadline = time.time() + READY_TIMEOUT
        while time.time() < deadline:
            recent = self._frames(time.time() - 0.5)
            if len(recent) >= 4 and all(l is not None for _, l in recent):
                return True
            self._wait(0.1)
        return False

    def _play_round(self):
        pet = self.pet
        self.robot_hand = self.user_hand = None
        for i, word in enumerate(("가위…", "바위…", "보!"), 1):
            self._say("countdown", word)
            pet.face.show(f"count{i}", 1)
            pet.beep(0.08 if i < 3 else 0.25)
            if i < 3:
                self._wait(0.55)
        robot = random.choice(HANDS)
        self.robot_hand = robot
        pet.face.show(f"rps_{robot}", THROW_READ + 1.5)
        self._say("reveal", "나는 " + KO[robot] + "!")
        t0 = time.time()
        self._wait(THROW_READ)
        # read the hand the user ends on (they often pump a fist during the countdown)
        thrown = [l for _, l in self._frames(t0 + 0.15) if l in HANDS][-6:]
        if len(thrown) < 3:
            return robot, None
        user = Counter(thrown).most_common(1)[0][0]
        self.user_hand = user
        return robot, user

    def _react(self, robot, user):
        pet = self.pet
        vs = f"나 {KO[robot]} vs 너 {KO[user]} → "
        if robot == user:
            self._say("result", vs + "비겼다! 한 번 더! 😮")
            pet.perform("surprised", 1.5, "surprised")
            self._wait(0.8)
        elif BEATS[robot] == user:
            self.score[0] += 1
            self._say("result", vs + "내가 이겼다! 😆")
            pet.perform("happy", 2, "happy", "happy_wiggle")
            self._wait(1.2)
        else:
            self.score[1] += 1
            self._say("result", vs + "으앗, 졌다… 😣")
            pet.perform("sulky", 2, "lose", "huff")
            self._wait(1.2)

    def _finish(self):
        pet = self.pet
        pet.daily.remember_once("first_game", "✌️", "처음으로 같이 가위바위보를 했어요")
        was_sulky = pet.mood == "sulky"
        robot_won = self.score[0] > self.score[1]
        self.stats["played"] += 1
        self.stats["robot" if robot_won else "user"] += 1
        result = f"{self.score[0]} : {self.score[1]}"
        if robot_won:
            self._say("over", f"{result} 내가 이겼다~ 또 하자! 🎉")
            pet.note(f"🎮 로봇 승리 ({result})", mood="happy", secs=40, love=MATCH_LOVE, cheer_up=True, grow="game")
            pet.perform("happy", 4, "happy", "happy_dance")
        elif pet.affection >= GOOD_SPORT_AT:
            # a robot that already loves you is a good sport
            self._say("over", f"{result} 축하해! 너 진짜 잘한다 👏")
            pet.note(f"🎮 내가 승리 ({result})", mood="love", secs=30, love=MATCH_LOVE, cheer_up=True, grow="game")
            pet.perform("love", 4, "love", "nuzzle")
        else:
            self._say("over", f"{result} 흥, 다음엔 꼭 이길 거야! 😤")
            pet.perform("sulky", 2.5, "lose", "huff")
            self._wait(0.5)
            self._say("over", f"{result} …그래도 재밌었다! 😊")
            pet.note(f"🎮 내가 승리 ({result})", mood="happy", secs=30, love=MATCH_LOVE, cheer_up=True, grow="game")
            pet.perform("happy", 3, "happy")
        if was_sulky:
            self._wait(0.5)
            self._say("over", "헤헤, 기분 다 풀렸어 😊")
            pet.perform("shy", 3, "love", "shy_fidget")

    def snapshot(self):
        return {"active": self.active, "phase": self.phase, "message": self.message, "score": self.score,
                "round": self.round, "robot_hand": self.robot_hand, "user_hand": self.user_hand,
                "stats": dict(self.stats)}
