"""Gesture driving: scissors -> forward, paper -> backward, rock -> stop."""
import threading
import time
from collections import deque

COMMANDS = {"scissors": "forward", "paper": "backward", "rock": "stop"}
STABLE_FRAMES = 4      # same gesture this many frames in a row -> accepted
LOST_TIMEOUT = 1.0     # seconds without a hand -> stop for safety


class Controller:
    def __init__(self, robot=None, speed=60):
        self.robot = robot
        self.speed = speed
        self.motion_enabled = False
        self.command = "stop"
        self.history = deque(maxlen=20)
        self._streak_label, self._streak = None, 0
        self._last_seen = time.time()
        self._lock = threading.Lock()

    def update(self, label):
        """Feed one frame's label. Returns a status dict for the UI."""
        now = time.time()
        if label is not None:
            self._last_seen = now
        if label == self._streak_label:
            self._streak += 1
        else:
            self._streak_label, self._streak = label, 1

        if label in COMMANDS and self._streak == STABLE_FRAMES:
            self._set(COMMANDS[label], label)
        elif label is None and self.command != "stop" and now - self._last_seen > LOST_TIMEOUT:
            self._set("stop", "no_hand")
        return {
            "label": label,
            "progress": min(self._streak / STABLE_FRAMES, 1.0) if label in COMMANDS else 0,
        }

    def _set(self, command, reason):
        with self._lock:
            if command == self.command:
                return
            self.command = command
            self.history.appendleft({"time": time.strftime("%H:%M:%S"), "command": command, "reason": reason})
        self._apply()

    def _apply(self):
        if not self.robot:
            return
        if not self.motion_enabled or self.command == "stop":
            self.robot.stop()
        elif self.command == "forward":
            self.robot.drive(self.speed, self.speed)
        elif self.command == "backward":
            self.robot.drive(-self.speed, -self.speed)

    def halt(self, reason="mode"):
        self._streak_label, self._streak = None, 0
        self._set("stop", reason)

    def set_motion(self, enabled):
        self.motion_enabled = enabled and self.robot is not None
        self._apply()

    def set_speed(self, speed):
        self.speed = max(30, min(int(speed), 255))
        self._apply()

    def snapshot(self):
        with self._lock:
            return {"command": self.command, "history": list(self.history), "speed": self.speed,
                    "motion_enabled": self.motion_enabled}
