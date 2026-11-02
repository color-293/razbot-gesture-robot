"""Companion mode: the robot reads hand interactions and answers with face, sound and body language.

Interactions (camera)            Reaction
  wave (fast side-to-side)   ->  hello / good morning / good night
  open palm held still       ->  high five
  slow side-to-side stroke   ->  being petted (love face, gentle nuzzle)
  thumbs up                  ->  praise (heart, shy back-off, affection +)
  fist swung / thrust at it  ->  scared: flinches back, trembles for a while (affection -)
  nobody for a while         ->  bored -> asks to play -> sulks and turns away
  hand after a long absence  ->  surprised, then happy
  scissors held for 1 s      ->  "let's play rock-paper-scissors!" (see game.py)
  coming back after a call   ->  the robot suggests a game by itself
  beckon (open/close hand)   ->  comes to you and "sits" (see follow.py)
  index finger held for 1 s  ->  follows your hand until you hold a fist
  open palm lowered slowly   ->  lullaby: takes a nap, wakes up by itself or when you wave

Raising game: growth.py (호감도 EXP, levels, 교감 도감 - gestures really open by level, needs),
daily.py (days together, streak, snacks, today's quests, memories), training.py (teach tricks with 👍).
"""
import json
import math
import random
import threading
import time
from collections import deque
from pathlib import Path

from follow import Follow
from game import RpsGame
from daily import Daily
from growth import STAGES, Growth
from training import Training

AFFECTION_FILE = Path(__file__).with_name("affection.json")

BORED_AFTER = 45          # s without a hand -> bored face
CALL_EVERY = 90           # s between "play with me" calls
CALLS_BEFORE_SULK = 3
SURPRISE_AFTER = 30       # s of absence before a new hand is a surprise
STABLE_FRAMES = 4
GAME_HOLD = 1.0           # s of scissors held -> invite to rock-paper-scissors
CALL_ANSWERED = 120       # s after a call during which a returning hand starts a game
GAME_REST = 5             # s after a game / walk before held scissors or a finger start another one
FOLLOW_HOLD = 1.0         # s of index finger held -> follow me
NAP_SECONDS = 60          # a nap lasts this long unless you wake it up
MIN_SLEEP = 5             # s before a wave can wake it (so a long good-night wave does not)

# buzzer rhythms (single pitch, so emotions are told apart by rhythm)
SOUNDS = {
    "happy": [(0.06, 0.06), (0.06, 0.06), (0.15, 0)],
    "hello": [(0.1, 0.12), (0.1, 0)],
    "night": [(0.4, 0.2), (0.6, 0)],
    "sad": [(0.7, 0)],
    "surprised": [(0.03, 0.03)] * 6,
    "love": [(0.05, 0.12)] * 3 + [(0.25, 0)],
    "call": [(0.08, 0.08), (0.08, 0.4), (0.08, 0.08), (0.08, 0)],
    "scared": [(0.25, 0.05)] + [(0.02, 0.04)] * 8,
    "game": [(0.05, 0.05)] * 3 + [(0.05, 0.15), (0.2, 0)],
    "lose": [(0.3, 0.1), (0.5, 0)],
    "fanfare": [(0.08, 0.04)] * 3 + [(0.3, 0.1), (0.08, 0.04), (0.5, 0)],
    "song": [(0.15, 0.1), (0.15, 0.1), (0.3, 0.15), (0.1, 0.05), (0.1, 0.05), (0.15, 0.1), (0.4, 0)],
    "yum": [(0.04, 0.08)] * 4 + [(0.2, 0)],
    "poke": [(0.03, 0.05), (0.06, 0)],
}

REACTIONS = {
    # event: (face, hold seconds, sound, body move, affection, korean label)
    "hello": ("happy", 3, "hello", "greet", 1, "안녕! 👋"),
    "morning": ("happy", 4, "hello", "happy_wiggle", 1, "좋은 아침! ☀️"),
    "night": ("sleepy", 6, "night", "greet", 1, "잘 자… 🌙"),
    "high_five": ("happy", 2.5, "happy", "high_five", 1, "하이파이브! ✋"),
    "pet": ("love", 4, "love", "nuzzle", 2, "쓰담쓰담 💕"),
    "praise": ("love", 3, "love", "shy_back", 3, "칭찬 고마워 👍"),
    "surprised": ("surprised", 2, "surprised", "surprised_jump", 0, "깜짝이야! 😮"),
    "call": ("bored", 4, "call", "ask_to_play", 0, "놀아줘~ 🥺"),
    "sulk": ("sulky", 6, "sad", "sulk_turn", 0, "흥! 삐졌어 😤"),
    "happy": ("happy", 3, "happy", "happy_wiggle", 0, "기분 좋아! 😊"),
    "shy": ("shy", 3, "love", "shy_back", 0, "부끄러워 ☺️"),
    "scared": ("scared", 3, "scared", "flinch", -1, "무, 무서워… 😨"),
    "nap": ("sleepy", 5, "night", "lie_down", 0, "자장자장… 낮잠 잘게 😴"),
    "wake": ("happy", 3, "hello", "wake_up", 1, "하암~ 잘 잤다! 🌤️"),
    "welcome": ("love", 3, "love", "greet", 1, "보고 싶었어! 🤗"),
    "level_up": ("levelup", 5, "fanfare", "happy_dance", 0, "🎉 레벨 업!"),
    "snack": ("love", 3, "yum", "happy_wiggle", 1, "냠냠 맛있다! 🍪"),
    # touching the character in the app
    "poke": ("happy", 1.5, "poke", None, 0, "콕! 헤헤, 간지러워 😆"),
    "dizzy": ("surprised", 2.5, "surprised", "wiggle", 0, "너무 많이 눌렀어… 어지러워 😵‍💫"),
}


# how long a reaction keeps colouring the mood afterwards: event -> (mood, seconds)
MOOD_AFTER = {
    "hello": ("happy", 30), "morning": ("happy", 40), "high_five": ("happy", 30), "happy": ("happy", 40),
    "pet": ("love", 40), "praise": ("love", 30), "shy": ("shy", 15), "scared": ("scared", 12),
    "wake": ("happy", 30), "welcome": ("love", 30), "level_up": ("happy", 40), "snack": ("happy", 30), "poke": ("happy", 10),
}

# mood-driven body language while nothing else is happening:
# mood -> (min interval s, max interval s, robot method, description)
IDLE_MOVES = {
    "neutral": (8, 14, "look_around", "두리번두리번 주변 살피기"),
    "happy": (4, 7, "happy_dance", "신나서 들썩들썩 춤추기"),
    "love": (5, 8, "creep_closer", "살금살금 다가가 비비기"),
    "shy": (5, 8, "shy_fidget", "꼼지락꼼지락 몸 비틀기"),
    "bored": (6, 10, "wander", "심심해서 어슬렁어슬렁 돌아다니기"),
    "sleepy": (9, 14, "doze", "꾸벅꾸벅 졸기"),
    "sulky": (6, 9, "huff", "흥! 하고 고개 홱 돌리기"),
    "scared": (3, 5, "tremble", "벌벌 떨며 조금씩 물러나기"),
}


class Companion:
    def __init__(self, robot, face, motion_on, sound_on, active=lambda: True):
        self.robot = robot
        self.face = face
        self.motion_on = motion_on      # callables -> bool
        self.sound_on = sound_on
        self.active = active            # callable -> bool (companion mode selected)
        saved = self._load()
        self.affection = saved.get("affection", 0)
        self.game = RpsGame(self, saved.get("games"))
        self.follow = Follow(self)
        self.growth = Growth(saved.get("growth"))
        self.daily = Daily(saved.get("daily"))
        self.training = Training(self, saved.get("training"))
        self.hint = None                # {"ts", "text"}: a short line for the app's speech bubble ("아직 몰라요")
        self.events = deque(maxlen=20)
        self.mood = "neutral"
        self.mood_log = deque([(time.time(), "neutral")], maxlen=1000)   # (since, mood) for the app's mood timeline
        self._track = deque()           # (t, x, label) of recent hand positions
        self._fist = deque()            # (t, x, y, size, label) over the last 0.6 s, for threats
        self._ys = deque()              # (t, y, label) of recent hand heights, for the lullaby
        self._last_seen = time.time()
        self._streak_label, self._streak = None, 0
        self._busy = threading.Event()
        self._last_event_t = 0.0
        self._last_call = 0.0
        self._game_end_t = 0.0
        self._calls = 0
        self._sulking = False
        self._sleeping = False
        self._sleep_t = 0.0
        self._nap_until = 0.0           # 0 = not a nap (night sleep lasts until you wave)
        self._glow, self._glow_until = "neutral", 0.0
        self._glow_cause = ""           # what caused the current feeling (shown in the app)
        self.mood_reason = "평온한 상태예요"
        self._next_move = time.time() + 3
        self._still_since = 0.0         # when the robot last stopped moving
        self.last_move = None
        self._lock = threading.Lock()
        threading.Thread(target=self._behave, daemon=True).start()

    # ---------- persistence ----------
    def _load(self):
        try:
            data = json.loads(AFFECTION_FILE.read_text())
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save(self):
        try:
            AFFECTION_FILE.write_text(json.dumps({"affection": self.affection, "games": self.game.stats,
                                                  "growth": self.growth.state(), "daily": self.daily.state(),
                                                  "training": self.training.state()}, ensure_ascii=False))
        except OSError:
            pass

    # ---------- per-frame input ----------
    def update(self, label, lm):
        now = time.time()
        if self._playing():
            # during a game / walk, hands are throws or a target, not petting / high fives / threats
            if self.game.active:
                self.game.feed(label, now)
            if self.follow.active:
                self.follow.feed(label, lm, now)
            if self.training.active:
                self.training.feed(label)
            self._forget()
            if label is not None:
                self._last_seen = now
            return
        if label is None:
            self._forget()
            self._streak_label, self._streak = None, 0
            self._idle(now)
            return

        absent = now - self._last_seen
        self._last_seen = now
        if label == self._streak_label:
            self._streak += 1
        else:
            self._streak_label, self._streak = label, 1
        if self._busy.is_set() or now - self._still_since < 0.5:
            # the camera rides on the robot: while it moves, hand motion in the image is not the user's
            self._forget()
            return
        self._track.append((now, lm[0].x, label))
        while self._track and now - self._track[0][0] > 4.0:
            self._track.popleft()
        size = math.hypot(lm[0].x - lm[9].x, lm[0].y - lm[9].y)   # wrist -> middle knuckle
        self._fist.append((now, lm[9].x, lm[9].y, size, label))
        while self._fist and now - self._fist[0][0] > 0.6:
            self._fist.popleft()
        self._ys.append((now, lm[9].y, label))
        while self._ys and now - self._ys[0][0] > 4.0:
            self._ys.popleft()

        if now - self._last_event_t < 1.0:
            return
        if self._sleeping:
            # a sleeping robot only notices a threat (startled awake) or a wave (wakes up)
            if self._is_threat(now):
                self._fist.clear()
                return self.trigger("scared")
            if self._wake_due(now) or (now - self._sleep_t > MIN_SLEEP and self._is_wave(now)):
                self._forget()
                return self.trigger("wake")
            return
        answered_call = self._calls > 0 and now - self._last_call < CALL_ANSWERED
        self._calls = 0
        if self._is_threat(now):
            self._fist.clear()
            return self.trigger("scared")
        if absent > SURPRISE_AFTER and not self._sulking:
            if answered_call and self.growth.has("game"):   # it asked to play and you came back: let's play!
                return self.start_game("왔구나! 가위바위보 하자 🎮 손 보여 줘")
            return self.trigger("welcome" if self.growth.has("aegyo") else "surprised")
        if label == "scissors" and now - self._game_end_t > GAME_REST and self._is_held(now, "scissors", GAME_HOLD):
            self._track.clear()
            return self.start_game()
        if label == "point" and now - self._game_end_t > GAME_REST and self._is_held(now, "point", FOLLOW_HOLD):
            self._forget()
            return self.start_follow("follow")
        if self._is_beckon(now):
            self._forget()
            return self.start_follow("come")
        if self._is_lull(now):
            self._forget()
            return self.trigger("nap")
        if self._is_wave(now):
            hour = time.localtime().tm_hour
            return self.trigger("morning" if 5 <= hour < 11 else "night" if hour >= 21 or hour < 5 else "hello")
        if label == "thumbs_up" and self._streak >= STABLE_FRAMES:
            self._streak = -10**6        # one praise per thumbs-up
            return self.trigger("praise") if self._can("praise") else None
        if self._is_stroke(now):
            return self.trigger("pet")
        if label == "paper" and self._is_still(now, 0.7):
            self._track.clear()
            return self.trigger("high_five") if self._can("high_five") else None
        self._refresh_mood(now)

    # ---------- gesture dynamics ----------
    @staticmethod
    def _reversals(pts, min_swing):
        """Count side-to-side direction changes (each swing >= min_swing); returns (count, swing durations)."""
        count, times = 0, []
        direction = 0
        ext_t, ext_x = pts[0]            # current extreme point
        turn_t = pts[0][0]               # time of the previous turning point
        for t, x in pts[1:]:
            if direction == 0:
                if abs(x - ext_x) >= min_swing:
                    direction = 1 if x > ext_x else -1
                    ext_t, ext_x = t, x
            elif (x - ext_x) * direction > 0:
                ext_t, ext_x = t, x      # keep extending the current swing
            elif abs(x - ext_x) >= min_swing:
                count += 1
                times.append(ext_t - turn_t)
                turn_t = ext_t
                direction = -direction
                ext_t, ext_x = t, x
        return count, times

    def _recent(self, now, window):
        return [(t, x) for t, x, _ in self._track if now - t <= window]

    def _is_wave(self, now):
        xs = self._recent(now, 1.5)
        if len(xs) < 8:
            return False
        count, _ = self._reversals(xs, 0.05)
        return count >= 3

    def _is_stroke(self, now):
        xs = self._recent(now, 4.0)
        if len(xs) < 20:
            return False
        count, times = self._reversals(xs, 0.15)
        return count >= 2 and all(dt >= 0.5 for dt in times)

    def _is_threat(self, now):
        """A fist thrust toward the camera (grows fast) or swung across it (moves fast)."""
        pts = [p for p in self._fist if now - p[0] <= 0.5]
        if len(pts) < 4 or pts[-1][4] != "rock" or sum(p[4] == "rock" for p in pts) < len(pts) / 2:
            return False
        _, x, y, size, _ = pts[-1]
        thrust = size / max(min(p[3] for p in pts), 1e-6) >= 1.45
        swing = max(math.hypot(x - p[1], y - p[2]) for p in pts) >= 0.25
        return thrust or swing

    def _is_held(self, now, label, seconds):
        """The same hand shape for (almost) the whole last `seconds`; returns those points or []."""
        pts = [(t, x, l) for t, x, l in self._track if now - t <= seconds]
        if not pts or now - pts[0][0] < seconds * 0.8 or any(l != label for _, _, l in pts):
            return []
        return pts

    def _is_beckon(self, now):
        """'Come here': the hand opens and closes (paper <-> rock) a few times while staying in place."""
        pts = [(x, l) for t, x, l in self._track if now - t <= 2.0 and l in ("rock", "paper")]
        if len(pts) < 6 or max(x for x, _ in pts) - min(x for x, _ in pts) > 0.12:
            return False
        runs = []                         # [label, frames] runs, ignoring one-frame flickers
        for _, l in pts:
            if runs and runs[-1][0] == l:
                runs[-1][1] += 1
            else:
                runs.append([l, 1])
        labels = [l for l, n in runs if n >= 2]
        changes = sum(a != b for a, b in zip(labels, labels[1:]))
        return changes >= 3

    def _is_lull(self, now):
        """Lullaby: an open palm lowered slowly and steadily (like tucking it in)."""
        pts = [(t, y) for t, y, l in self._ys if now - t <= 2.0 and l == "paper"]
        if len(pts) < 8 or len(pts) < 0.8 * sum(now - t <= 2.0 for t, _, _ in self._ys):
            return False
        top = min(range(len(pts)), key=lambda i: pts[i][1])     # highest point (smallest y)
        seg = pts[top:]
        drop, dur = seg[-1][1] - seg[0][1], seg[-1][0] - seg[0][0]
        if drop < 0.2 or dur < 0.6:
            return False
        if any(b[1] < a[1] - 0.05 for a, b in zip(seg, seg[1:])):   # it went back up: not steady
            return False
        xs = [x for t, x, _ in self._track if t >= seg[0][0]]
        return not xs or max(xs) - min(xs) < 0.15

    def _is_still(self, now, seconds):
        pts = self._is_held(now, "paper", seconds)
        if not pts:
            return False
        xs = [x for _, x, _ in pts]
        ys = [y for t, y, _ in self._ys if now - t <= seconds]   # a palm moving down is a lullaby, not a high five
        return max(xs) - min(xs) < 0.04 and (not ys or max(ys) - min(ys) < 0.04)

    # ---------- mood ----------
    @staticmethod
    def _night():
        hour = time.localtime().tm_hour
        return hour >= 22 or hour < 7

    def _refresh_mood(self, now):
        """Pick the lasting mood: sulky > sleepy > recent feeling > low needs > bored > neutral (and say why)."""
        if self._sulking:
            mood, why = "sulky", "놀아 달라고 했는데 계속 안 놀아 줘서 삐졌어요 (인사·칭찬·쓰담으로 풀려요)"
        elif self._sleeping:
            mood, why = "sleepy", "낮잠 자는 중이에요" if self._nap_until else "밤잠 자는 중이에요"
        elif now < self._glow_until:
            mood, why = self._glow, f"방금 '{self._glow_cause}' 때문이에요" if self._glow_cause else "방금 있었던 일 때문이에요"
        elif self.growth.low("energy"):
            mood, why = "sleepy", "에너지가 다 떨어져서 졸려요 (재워 주세요)"
        elif self.growth.low("fun") or self.growth.low("love"):
            need = "재미" if self.growth.low("fun") else "애정"
            mood, why = "bored", f"{need}이(가) 부족해서 심심해요"
        elif now - self._last_seen > BORED_AFTER:
            if self._night():
                mood, why = "sleepy", "밤이 깊었고 한동안 아무도 없어서 졸려요"
            else:
                mood, why = "bored", f"{int(now - self._last_seen)}초 동안 아무도 안 놀아 줘서 심심해요"
        else:
            mood, why = "neutral", "특별한 일 없이 평온해요"
        self.mood_reason = why
        self._set_mood(mood)

    def _set_mood(self, mood):
        if mood != self.mood:
            self.mood = mood
            self.mood_log.append((time.time(), mood))
            self.face.set_base(mood)
            self._next_move = time.time() + 1.5   # show the new mood's body language soon

    def set_mood(self, mood, seconds=60):
        """Force a mood from the web page (for demos)."""
        if mood not in IDLE_MOVES:
            return False
        self._sulking = mood == "sulky"
        self._sleeping = mood == "sleepy"
        self._glow, self._glow_until = mood, time.time() + seconds
        self._glow_cause = "기분 바꾸기 버튼"
        if mood in ("bored", "neutral"):
            self._glow_until = 0.0
            self._last_seen = time.time() - (BORED_AFTER + 1 if mood == "bored" else 0)
        self._refresh_mood(time.time())
        return True

    # ---------- idle behaviour ----------
    def _wake_due(self, now):
        return self._sleeping and self._nap_until and now > self._nap_until

    def _idle(self, now):
        if self._wake_due(now) and not self._busy.is_set():
            self.trigger("wake")
        self._refresh_mood(now)
        if self._busy.is_set() or self._sulking or self._sleeping:
            return
        gone = now - self._last_seen
        if not self.growth.has("call"):       # before Lv6 it just gets bored, it does not come asking yet
            return
        if gone > BORED_AFTER + 15 and not self._night() and now - self._last_call > CALL_EVERY:
            self._last_call = now
            if self._calls >= CALLS_BEFORE_SULK:
                self._sulking = True
                self._calls = 0
                self.trigger("sulk")
            else:
                self._calls += 1
                self.trigger("call")

    def _behave(self):
        """Background loop: perform the current mood's body language every few seconds."""
        last_save = time.time()
        while True:
            time.sleep(0.3)
            now = time.time()
            if self.active():
                self.growth.tick(self._sleeping)
                if now - last_save > 30:
                    last_save = now
                    self._save()
                if self.growth.level_ups and not self._busy.is_set() and not self._playing():
                    level = self.growth.level_ups.pop(0)
                    opened = self.growth.opened_at(level)
                    learned = f" · {', '.join(opened)} 배웠어요" if opened else ""
                    self.daily.remember("⭐", f"Lv.{level} 달성{learned}")
                    if level in [s[0] for s in STAGES]:
                        emoji, name = self.growth.stage(level)
                        self.daily.remember(emoji, f"{name}(으)로 자랐어요")
                    self.trigger("level_up", text=f"🎉 레벨 업! Lv.{level}{learned}")
                    continue
                self._refresh_mood(now)
            if not (self.robot and self.active() and self.motion_on()) or self._busy.is_set() or self._playing():
                continue
            if now < self._next_move or now - self._last_event_t < 2.0:
                continue
            lo, hi, move, text = IDLE_MOVES.get(self.mood, IDLE_MOVES["neutral"])
            sound = None
            if self.mood == "happy":                  # the more it likes you, the livelier it gets
                hi = max(lo, hi - self.affection // 10)
                if self.growth.has("aegyo") and random.random() < 0.35:
                    move, sound, text = "happy_wiggle", "song", "🎵 노래 부르며 들썩들썩"
                elif self.growth.has("aegyo") and random.random() < 0.3:
                    move, text = "spin_dance", "🌀 신나서 빙글빙글 춤추기"
            self._next_move = now + random.uniform(lo, hi)
            self._busy.set()
            self.last_move = {"time": time.strftime("%H:%M:%S"), "mood": self.mood, "text": text}
            try:
                self._act(sound, move)
            finally:
                self._still_since = time.time()
                self._busy.clear()

    # ---------- reactions ----------
    def trigger(self, event, text=None):
        """Play a reaction (also used by the web test buttons)."""
        if event not in REACTIONS or self._busy.is_set() or self._playing():
            return False
        face, hold, sound, move, love, label = REACTIONS[event]
        text = text or label
        if event == "level_up" and self.growth.has("aegyo"):
            move = "spin_dance"
        if event in ("hello", "morning") and self.growth.has("bow"):
            move = "bow"                     # Lv4: answers a greeting with a little bow
        self._busy.set()
        self._last_event_t = time.time()
        self._sleeping = event in ("night", "nap")
        self._sleep_t = self._last_event_t
        self._nap_until = self._last_event_t + NAP_SECONDS if event == "nap" else 0.0
        if event not in ("call", "sulk", "surprised", "scared", "poke", "dizzy"):
            # a sulking robot stays sulky until it is greeted, praised, petted or high-fived
            self._sulking = False
        if event in MOOD_AFTER:
            mood, secs = MOOD_AFTER[event]
            self._glow, self._glow_until = mood, time.time() + hold + secs
            self._glow_cause = text
        self._refresh_mood(time.time())
        if love:
            self.affection = max(0, self.affection + love)
        self.grow(event)
        with self._lock:
            self.events.appendleft({"time": time.strftime("%H:%M:%S"), "ts": time.time(), "event": event, "text": text})
        self.face.show(face, hold)

        def run():
            try:
                self._act(sound, move)
                time.sleep(0.5)
            finally:
                self._still_since = time.time()
                self._busy.clear()

        threading.Thread(target=run, daemon=True).start()
        return True

    def _act(self, sound=None, move=None):
        """Play a buzzer rhythm and a body move together and wait for both."""
        threads = []
        try:
            if self.robot and sound and self.sound_on():
                threads.append(threading.Thread(target=self.robot.pattern, args=(SOUNDS[sound],)))
            if self.robot and move and self.motion_on():
                threads.append(threading.Thread(target=getattr(self.robot, move)))
            for th in threads:
                th.start()
            for th in threads:
                th.join()
        finally:
            if self.robot:
                try:
                    self.robot.stop()
                    self.robot.buzzer(False)
                except OSError:
                    pass  # transient I2C error

    # ---------- used by games (game.py) ----------
    def perform(self, face=None, hold=2.0, sound=None, move=None):
        """Show a face with sound and body language; blocks until the robot has finished."""
        deadline = time.time() + 3
        while self._busy.is_set() and time.time() < deadline:   # let an idle move finish first
            time.sleep(0.05)
        self._busy.set()
        try:
            if face:
                self.face.show(face, hold)
            self._act(sound, move)
        finally:
            self._still_since = time.time()
            self._busy.clear()

    def beep(self, seconds):
        if self.robot and self.sound_on():
            try:
                self.robot.beep(seconds)
            except OSError:
                pass

    def grow(self, event):
        """Give EXP / refill needs for an interaction (see growth.GAINS), count it for today's quests and the
        streak. Level-ups are celebrated by _behave."""
        exp = self.growth.gain(event)
        if event != "test":
            self.daily.visit()
            self.daily.ensure_quests(self.growth.has)
            for kind, label in self.daily.record(event):
                if kind == "quest":
                    self.growth.gain("quest")
                    self._log("quest", f"📋 할 일 완료: {label} (+5 호감도)")
                else:
                    self.growth.gain("quest_all")
                    self._log("quest", "🏅 오늘의 할 일 모두 완료! (+10 호감도)")
        self._save()
        return exp

    def save(self):
        self._save()

    def busy(self):
        return self._busy.is_set() or self._playing()

    def _log(self, event, text):
        with self._lock:
            self.events.appendleft({"time": time.strftime("%H:%M:%S"), "ts": time.time(), "event": event, "text": text})

    def say(self, text):
        """A short line in the app's speech bubble that is not an event (e.g. why nothing happened)."""
        self.hint = {"ts": time.time(), "text": text}

    def _can(self, key):
        """Is this interaction unlocked yet? If not, look puzzled and say when it will be learned."""
        if self.growth.has(key):
            return True
        text = f"아직 몰라요… Lv.{self.growth.needed(key)}이 되면 배워요 🤔"
        if not self.hint or self.hint["text"] != text or time.time() - self.hint["ts"] > 4:
            self.say(text)
            self.face.show("surprised", 1.2)
        return False

    # ---------- buttons in the app ----------
    def give_snack(self):
        if self._sleeping:
            self.say("쿨쿨… 자는 중이에요 😴")
            return False
        if self.busy():
            self.say("잠깐만요, 지금 바빠요!")
            return False
        if not self.daily.eat_snack():
            self.say("오늘 간식은 다 먹었어요. 내일 또 줘요! 🍪")
            return False
        return self.trigger("snack")

    def touch(self, kind):
        """The character in the app was touched: 'poke' (tap), 'stroke' (rubbed) or 'dizzy' (tapped too often)."""
        if self._sleeping:
            return self.trigger("wake") if kind != "stroke" else False   # stroking a sleeping robot lets it sleep
        if kind == "stroke":
            return self.trigger("pet")
        if kind == "dizzy":
            return self.trigger("dizzy")
        if self._sulking:
            self.say("흥… 콕 찔러도 안 풀려 😤")
            return False
        return self.trigger("poke")

    def toggle_sleep(self):
        if self._sleeping:
            return self.trigger("wake")
        return self.trigger("nap")

    def note(self, text, mood=None, secs=0, love=0, cheer_up=False, grow=None):
        """Log something that happened and let it colour the mood / affection (and growth)."""
        now = time.time()
        if cheer_up:                    # playing together is what a bored or sulky robot wanted
            self._sulking = self._sleeping = False
            self._calls = 0
        if mood:
            self._glow, self._glow_until = mood, now + secs
            self._glow_cause = text
        if love:
            self.affection = max(0, self.affection + love)
        if grow:
            self.grow(grow)
        else:
            self._save()
        with self._lock:
            self.events.appendleft({"time": time.strftime("%H:%M:%S"), "ts": time.time(), "event": "game", "text": text})
        self._refresh_mood(now)

    def _playing(self):
        return self.game.active or self.follow.active or self.training.active

    def _forget(self):
        self._track.clear()
        self._fist.clear()
        self._ys.clear()

    def start_game(self, intro=None):
        """Invite the user to rock-paper-scissors (from a gesture, a returning hand or the web page)."""
        if self._playing() or not self._can("game"):
            return False
        self._last_event_t = time.time()
        return self.game.start(intro)

    def start_follow(self, kind):
        """'come' (come here and sit) or 'follow' (follow my hand); asleep, it does not hear you."""
        if self._playing() or self._sleeping or not self._can(kind):
            return False
        self._last_event_t = time.time()
        return self.follow.start(kind)

    def start_training(self, trick):
        if self._playing() or self._sleeping or not self._can("custom_trick" if trick == "custom" else "training"):
            return False
        self._last_event_t = time.time()
        return self.training.start(trick)

    def activity_over(self):
        now = time.time()
        self._save()
        self._last_event_t = self._last_seen = self._game_end_t = now
        self._next_move = now + 4
        self._forget()
        self._refresh_mood(now)

    def mood_history(self, window=600):
        """Mood segments over the last `window` seconds: [{"mood", "start", "end"}] (seconds before now)."""
        now = time.time()
        log = list(self.mood_log)
        out = []
        for i, (since, mood) in enumerate(log):
            until = log[i + 1][0] if i + 1 < len(log) else now
            if until <= now - window:
                continue
            out.append({"mood": mood, "start": round(now - max(since, now - window), 1), "end": round(now - until, 1)})
        return out

    def snapshot(self):
        with self._lock:
            glow_left = max(0.0, self._glow_until - time.time()) if self.mood == self._glow else 0.0
            return {"affection": self.affection, "level": self.affection // 10, "mood": self.mood,
                    "face": self.face.current(), "events": list(self.events), "busy": self._busy.is_set(),
                    "sulking": self._sulking, "behavior": IDLE_MOVES.get(self.mood, IDLE_MOVES["neutral"])[3],
                    "last_move": self.last_move, "mood_left": round(glow_left), "mood_reason": self.mood_reason,
                    "mood_since": round(time.time() - self.mood_log[-1][0]),
                    "mood_moves": {m: v[3] for m, v in IDLE_MOVES.items()}, "game": self.game.snapshot(),
                    "follow": self.follow.snapshot(), "nap_left": round(max(0.0, self._nap_until - time.time()))
                    if self._sleeping and self._nap_until else 0, "sleeping": self._sleeping,
                    "growth": self.growth.snapshot(), "daily": self._daily_snapshot(),
                    "training": self.training.snapshot(),
                    "hint": self.hint if self.hint and time.time() - self.hint["ts"] < 6 else None}

    def _daily_snapshot(self):
        self.daily.ensure_quests(self.growth.has)
        return self.daily.snapshot()
