"""Raising-game layer: 호감도(EXP) and levels, growth stages, the 교감 도감 (what each level unlocks) and care needs.

  EXP       every good interaction gives 호감도 experience; levels need a little more each time
  stages    🐣 아기봇 -> 🐥 꼬마봇 -> 🤖 친구봇 -> 🦾 든든봇 -> 👑 단짝봇
  FEATURES  the 교감 도감: every interaction and the level it opens at. companion.py asks has(key) before reacting,
            so a locked gesture really does nothing yet ("아직 몰라요"). unlock_all opens everything for demos.
  needs     ⚡ energy, 🎈 fun, 💗 love (0-100): they drop while the robot is running and are refilled by caring
            for it. The app shows 행복 = (fun + love) / 2 and 에너지. Low needs change the mood.
"""
import time

# event -> (exp, {need: change}); "energy": None means "fully rested"
GAINS = {
    "hello": (2, {"love": 10}),
    "morning": (2, {"love": 10}),
    "night": (1, {}),
    "high_five": (2, {"fun": 5, "love": 5}),
    "pet": (3, {"love": 20}),
    "praise": (3, {"love": 15}),
    "snack": (2, {"love": 10, "fun": 5, "energy": 5}),
    "poke": (0, {"fun": 2, "love": 1}),
    "dizzy": (0, {"fun": -5}),
    "scared": (0, {"love": -10}),
    "nap": (1, {}),
    "wake": (1, {"energy": None}),
    "game": (5, {"fun": 30, "energy": -10}),
    "come": (3, {"love": 10, "energy": -3}),
    "follow": (3, {"fun": 20, "energy": -5}),
    "goal": (3, {"fun": 20}),
    "train": (3, {"fun": 10, "energy": -3}),
    "trick_learned": (10, {"love": 10}),
    "quest": (5, {}),
    "quest_all": (10, {}),
    "test": (10, {}),
}

STAGES = [  # (from level, emoji, name)
    (1, "🐣", "아기봇"),
    (3, "🐥", "꼬마봇"),
    (5, "🤖", "친구봇"),
    (8, "🦾", "든든봇"),
    (10, "👑", "단짝봇"),
]

# 교감 도감: (key, level, emoji, name, kind, how)   kind: 손짓 / 버튼 / 자동 / 훈련 / 모드
FEATURES = [
    ("hello", 1, "👋", "인사", "손짓", "손을 빠르게 좌우로 흔들기"),
    ("pet", 1, "🤚", "쓰담쓰담", "손짓", "손을 천천히 크게 좌우로"),
    ("snack", 1, "🍪", "간식 주기", "버튼", "버튼 · 하루 3번"),
    ("nap", 1, "💤", "재우기 / 깨우기", "버튼", "버튼, 또는 편 손을 천천히 내리기(자장자장)"),
    ("watch", 1, "⚽", "같이 경기 보기", "모드", "골·홈런 장면에 같이 세레머니"),
    ("drive", 1, "🕹️", "손으로 운전", "모드", "✌️ 전진 · ✋ 후진 · ✊ 정지"),
    ("high_five", 2, "✋", "하이파이브", "손짓", "손바닥 펴고 가만히"),
    ("praise", 3, "👍", "칭찬", "손짓", "엄지 척 (훈련 보상)"),
    ("training", 3, "🎓", "개인기 훈련", "훈련", "훈련 탭에서 시작"),
    ("bow", 4, "🙇", "꾸벅 인사", "자동", "인사하면 꾸벅 고개 숙여 답해요"),
    ("game", 5, "✌️", "가위바위보", "버튼", "버튼 또는 가위 1초 → 구호에 맞춰 손 내기"),
    ("call", 6, "🥺", "먼저 놀자고 조르기", "자동", "안 놀아 주면 스스로 다가와요"),
    ("come", 7, "🐶", "이리 와", "버튼", "버튼 또는 손 까딱까딱 → 손 쪽으로 와요"),
    ("follow", 8, "👣", "따라와", "손짓", "검지 1초 → 손을 따라다녀요, 주먹 쥐면 멈춤"),
    ("aegyo", 9, "🥰", "애교 부리기", "자동", "행복하면 가끔 노래·빙글 춤, 돌아오면 반겨요"),
    ("custom_trick", 10, "🎬", "나만의 개인기", "훈련", "동작을 직접 조합해 훈련"),
]
LEVEL_OF = {f[0]: f[1] for f in FEATURES}

NEEDS = ("energy", "fun", "love")
DECAY = {"energy": 90, "fun": 40, "love": 60}   # seconds per point lost while awake
REST_EVERY = 6                                  # seconds per energy point regained while sleeping
LOW = 15                                        # below this a need changes the mood


def exp_for(level):
    """EXP needed to go from `level` to the next one."""
    return 10 + 5 * (level - 1)


class Growth:
    def __init__(self, saved=None):
        saved = saved or {}
        self.exp = int(saved.get("exp", 0))
        self.needs = {n: float(saved.get(n, 80)) for n in NEEDS}
        self.unlock_all = False      # demo mode: everything open (not saved)
        self._t = time.time()
        self.level_ups = []          # levels reached since the last check (the companion celebrates them)

    # ---------- levels ----------
    def level_info(self):
        level, left = 1, self.exp
        while left >= exp_for(level):
            left -= exp_for(level)
            level += 1
        return level, left, exp_for(level)

    @property
    def level(self):
        return self.level_info()[0]

    def stage(self, level=None):
        level = level or self.level
        emoji, name = STAGES[0][1:]
        for start, e, n in STAGES:
            if level >= start:
                emoji, name = e, n
        return emoji, name

    def has(self, key):
        return self.unlock_all or self.level >= LEVEL_OF.get(key, 1)

    def needed(self, key):
        return LEVEL_OF.get(key, 1)

    def opened_at(self, level):
        """Features that open exactly at `level` (for the level-up message)."""
        return [f"{e} {n}" for k, lv, e, n, _, _ in FEATURES if lv == level]

    def gain(self, event):
        """Apply an interaction; returns the EXP gained."""
        exp, changes = GAINS.get(event, (0, {}))
        for need, d in changes.items():
            self.needs[need] = 100.0 if d is None else max(0.0, min(100.0, self.needs[need] + d))
        if exp:
            before = self.level
            self.exp += exp
            self.level_ups += range(before + 1, self.level + 1)
        return exp

    # ---------- needs ----------
    def tick(self, sleeping):
        now = time.time()
        dt, self._t = now - self._t, now
        if dt <= 0 or dt > 60:       # first call, or the clock jumped
            return
        if sleeping:
            self.needs["energy"] = min(100.0, self.needs["energy"] + dt / REST_EVERY)
            return
        for need in NEEDS:
            self.needs[need] = max(0.0, self.needs[need] - dt / DECAY[need])

    def low(self, need):
        return self.needs[need] < LOW

    @property
    def happiness(self):
        return (self.needs["fun"] + self.needs["love"]) / 2

    # ---------- persistence / web ----------
    def state(self):
        return {"exp": self.exp, **{n: round(v, 1) for n, v in self.needs.items()}}

    def snapshot(self):
        level, into, need = self.level_info()
        emoji, name = self.stage(level)
        nxt = next(((s, e, n) for s, e, n in STAGES if s > level), None)
        upcoming = sorted({lv for _, lv, *_ in FEATURES if lv > level})
        return {"level": level, "exp": self.exp, "into": into, "need": need, "stage": name, "stage_emoji": emoji,
                "next_stage": {"level": nxt[0], "emoji": nxt[1], "name": nxt[2]} if nxt else None,
                "needs": {n: round(v) for n, v in self.needs.items()}, "happiness": round(self.happiness),
                "unlock_all": self.unlock_all,
                "next_unlock": {"level": upcoming[0], "items": self.opened_at(upcoming[0])} if upcoming else None,
                "features": [{"key": k, "level": lv, "emoji": e, "name": n, "kind": kind, "how": how,
                              "open": self.has(k)} for k, lv, e, n, kind, how in FEATURES]}
