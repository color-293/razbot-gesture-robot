"""Come when called / follow me: the robot steers toward the hand it sees, like a pet answering its name.

  come   : drive to the hand, stop when it looks big (close), then "sit" (a little bow) -> affection +1
  follow : keep the hand centred and at a fixed distance until a fist is held ("stop") or the hand is lost

The camera rides on the robot, so this is a simple visual-servoing loop:
  hand left/right of centre -> turn, hand small (far) -> forward, hand big (near) -> back.
"""
import threading
import time

TURN_SIGN = 1          # flip to -1 if the robot turns away from the hand (depends on how the camera is mounted)
BASE_SPEED = 55        # forward speed while approaching
TURN_GAIN = 90         # wheel speed difference per unit of horizontal offset
ARRIVE_SIZE = 0.20     # hand size (wrist -> middle knuckle, fraction of the frame height) = close enough
FOLLOW_SIZE = 0.14     # distance kept while following
SIZE_GAIN = 600        # forward speed per unit of size error while following
LOST_AFTER = 1.0       # s without a hand -> stop
STOP_HOLD = 0.6        # s of a fist -> stop following
COME_MAX = 6           # s safety limits
FOLLOW_MAX = 60


class Cancelled(Exception):
    pass


class Follow:
    def __init__(self, pet):
        self.pet = pet
        self.active = False
        self.kind = None
        self.message = ""
        self._hand = None              # (t, x, size, label) of the last frame with a hand
        self._rock_since = None
        self._cancel = threading.Event()

    def feed(self, label, lm, now):
        if lm is None:
            return
        size = ((lm[0].x - lm[9].x) ** 2 + (lm[0].y - lm[9].y) ** 2) ** 0.5
        self._hand = (now, lm[9].x, size, label)
        if label == "rock":
            self._rock_since = self._rock_since or now
        else:
            self._rock_since = None

    def start(self, kind):
        if self.active or kind not in ("come", "follow"):
            return False
        self.active, self.kind = True, kind
        self._hand, self._rock_since = None, None
        self._cancel.clear()
        threading.Thread(target=self._run, args=(kind,), daemon=True).start()
        return True

    def cancel(self):
        if self.active:
            self._cancel.set()

    def _check(self):
        if self._cancel.is_set() or not self.pet.active():
            raise Cancelled

    def _run(self, kind):
        pet = self.pet
        robot = pet.robot
        try:
            if kind == "come":
                self.message = "응! 갈게~ 🐶"
                pet.note("🐶 이리 와")
                pet.perform("happy", 1.5, "hello")
            else:
                self.message = "따라갈게! 👣 (✊ 주먹 쥐면 멈춰요)"
                pet.note("👣 따라와")
                pet.perform("happy", 1.5, "game")
            if not (robot and pet.motion_on()):
                self.message = "가고 싶은데… 로봇 움직이기가 꺼져 있어 🥺"
                pet.perform("bored", 3, "sad")
                return
            self._drive(kind)
        except Cancelled:
            self.message = "그만!"
        finally:
            if robot:
                try:
                    robot.stop()
                except OSError:
                    pass
            self.active = False
            pet.activity_over()

    def _drive(self, kind):
        pet, robot = self.pet, self.pet.robot
        t_end = time.time() + (COME_MAX if kind == "come" else FOLLOW_MAX)
        self._hand = (time.time(), 0.5, 0.0, None)     # grace period before the first frame arrives
        while True:
            self._check()
            now = time.time()
            t, x, size, label = self._hand
            if now - t > LOST_AFTER:
                robot.stop()
                self.message = "어디 갔어? 👀"
                pet.perform("surprised", 2, "call", "look_around")
                return
            if now > t_end:
                robot.stop()
                if kind == "come":
                    self.message = "헥헥… 너무 멀어 😵"
                    pet.perform("bored", 2, "sad")
                else:
                    self.message = "다리 아파~ 이제 쉴래 😮‍💨"
                    pet.perform("sleepy", 2, "night")
                return
            if kind == "come" and size >= ARRIVE_SIZE:
                robot.stop()
                self.message = "왔어! 🐶"
                pet.note("🐶 불러서 달려왔어요", mood="love", secs=30, love=1, cheer_up=True, grow="come")
                pet.perform("love", 3, "love", "sit")
                return
            if kind == "follow" and self._rock_since and now - self._rock_since >= STOP_HOLD:
                robot.stop()
                self.message = "멈출게! 재밌었다 😊"
                pet.note("👣 같이 산책했어요", mood="happy", secs=30, love=1, cheer_up=True, grow="follow")
                pet.perform("happy", 2.5, "happy", "sit")
                return
            # mirrored image: hand right of centre = robot's left -> slow the left wheels to turn left
            turn = TURN_GAIN * (x - 0.5) * TURN_SIGN
            if kind == "come":
                fwd = BASE_SPEED
            else:
                err = FOLLOW_SIZE - size
                fwd = 0 if abs(err) < 0.02 else max(-BASE_SPEED, min(BASE_SPEED, SIZE_GAIN * err))
            try:
                robot.drive(fwd - turn, fwd + turn)
            except OSError:
                pass  # transient I2C error
            time.sleep(0.05)

    def snapshot(self):
        return {"active": self.active, "kind": self.kind, "message": self.message}
