"""Daily life with the robot: days together, visit streak, snacks per day, today's quests and memories (추억).

  함께한 지 N일   counted from the first day the robot was run
  🔥 N일 연속     days in a row with at least one interaction
  간식            3 per day
  오늘의 할 일    3 quests picked each day from what is already unlocked; each gives EXP, all three a bonus
  추억            milestones (first meeting, level ups, learned tricks, first win, streaks...) kept forever
"""
import datetime
import random

SNACKS_PER_DAY = 3
QUESTS_PER_DAY = 3

# quest key (= event name counted) -> (feature needed, label, how many)
QUEST_POOL = {
    "hello": ("hello", "👋 인사하기", 1),
    "pet": ("pet", "🤚 쓰다듬어 주기", 2),
    "snack": ("snack", "🍪 간식 주기", 1),
    "nap": ("nap", "😴 낮잠 재우기", 1),
    "high_five": ("high_five", "✋ 하이파이브 하기", 1),
    "praise": ("praise", "👍 칭찬해 주기", 2),
    "train": ("training", "🎓 개인기 훈련 성공 1번", 1),
    "game": ("game", "✌️ 가위바위보 한 판", 1),
    "come": ("come", "🐶 이리 와 부르기", 1),
    "follow": ("follow", "👣 같이 산책하기", 1),
    "goal": ("watch", "⚽ 같이 골 응원하기", 1),
}
ALIASES = {"morning": "hello", "night": "hello"}   # events that count as another quest


def today():
    return datetime.date.today()


class Daily:
    def __init__(self, saved=None):
        saved = saved or {}
        self.first_day = saved.get("first_day") or today().isoformat()
        self.last_day = saved.get("last_day")
        self.streak = int(saved.get("streak", 0))
        self.snacks = saved.get("snacks") or {"date": None, "count": 0}
        self.quests = saved.get("quests") or {"date": None, "items": [], "bonus": False}
        self.memories = saved.get("memories") or []
        self.once = saved.get("once") or []
        if not self.memories:
            self.remember("🌱", "라즈봇을 처음 만난 날")

    # ---------- days ----------
    def days_together(self):
        return (today() - datetime.date.fromisoformat(self.first_day)).days + 1

    def visit(self):
        """Call on every interaction: keeps the streak. Returns a memory text when a streak milestone is hit."""
        t = today().isoformat()
        if self.last_day == t:
            return None
        yesterday = (today() - datetime.timedelta(days=1)).isoformat()
        self.streak = self.streak + 1 if self.last_day == yesterday else 1
        self.last_day = t
        if self.streak in (3, 7, 14, 30, 100):
            self.remember("🔥", f"{self.streak}일 연속으로 같이 놀았어요")
        return t

    # ---------- snacks ----------
    def snacks_left(self):
        if self.snacks["date"] != today().isoformat():
            return SNACKS_PER_DAY
        return max(0, SNACKS_PER_DAY - self.snacks["count"])

    def eat_snack(self):
        t = today().isoformat()
        if self.snacks["date"] != t:
            self.snacks = {"date": t, "count": 0}
        if self.snacks["count"] >= SNACKS_PER_DAY:
            return False
        self.snacks["count"] += 1
        return True

    # ---------- quests ----------
    def ensure_quests(self, has):
        """Pick today's quests (only from unlocked features) if the day changed."""
        t = today().isoformat()
        if self.quests["date"] == t and self.quests["items"]:
            return
        pool = [k for k, (feat, _, _) in QUEST_POOL.items() if has(feat)]
        rng = random.Random(t)                     # same quests all day, even after a restart
        keys = rng.sample(pool, min(QUESTS_PER_DAY, len(pool)))
        self.quests = {"date": t, "bonus": False,
                       "items": [{"key": k, "label": QUEST_POOL[k][1], "goal": QUEST_POOL[k][2], "count": 0}
                                 for k in keys]}

    def record(self, event):
        """Count an event toward today's quests. Returns ("quest", label) / ("all", None) rewards earned."""
        key = ALIASES.get(event, event)
        rewards = []
        for q in self.quests["items"]:
            if q["key"] == key and q["count"] < q["goal"]:
                q["count"] += 1
                if q["count"] == q["goal"]:
                    rewards.append(("quest", q["label"]))
        items = self.quests["items"]
        if items and not self.quests["bonus"] and all(q["count"] >= q["goal"] for q in items):
            self.quests["bonus"] = True
            rewards.append(("all", None))
            self.remember("📋", "오늘의 할 일을 모두 해냈어요")
        return rewards

    # ---------- memories ----------
    def remember_once(self, key, emoji, text):
        """A memory that only happens the first time (first game, first goal ...)."""
        if key in self.once:
            return False
        self.once.append(key)
        self.remember(emoji, text)
        return True

    def remember(self, emoji, text):
        now = datetime.datetime.now()
        self.memories.insert(0, {"date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M"),
                                 "emoji": emoji, "text": text})
        del self.memories[200:]

    # ---------- persistence / web ----------
    def state(self):
        return {"first_day": self.first_day, "last_day": self.last_day, "streak": self.streak,
                "snacks": self.snacks, "quests": self.quests, "memories": self.memories,
                "once": self.once}

    def snapshot(self):
        return {"days": self.days_together(), "streak": self.streak, "snacks_left": self.snacks_left(),
                "snacks_per_day": SNACKS_PER_DAY, "quests": self.quests["items"], "quest_bonus": self.quests["bonus"],
                "memories": self.memories[:40]}
