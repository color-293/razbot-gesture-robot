"""Raspbot V2 motor/buzzer control over I2C (expansion board at 0x2B)."""
import random
import time
import smbus

ADDR = 0x2B
REG_MOTOR = 0x01
REG_BUZZER = 0x06

# motor ids: 0=left front, 1=left rear, 2=right front, 3=right rear
LEFT = (0, 1)
RIGHT = (2, 3)


class Robot:
    def __init__(self, bus=1):
        self.bus = smbus.SMBus(bus)

    def _motor(self, mid, speed):
        direction = 0 if speed >= 0 else 1
        self.bus.write_i2c_block_data(ADDR, REG_MOTOR, [mid, direction, min(abs(int(speed)), 255)])

    def drive(self, left, right):
        for m in LEFT:
            self._motor(m, left)
        for m in RIGHT:
            self._motor(m, right)

    def stop(self):
        self.drive(0, 0)

    def buzzer(self, on):
        self.bus.write_byte_data(ADDR, REG_BUZZER, 1 if on else 0)

    # --- composite moves ---
    def forward(self, speed=80, t=0.5):
        self.drive(speed, speed); time.sleep(t); self.stop()

    def backward(self, speed=80, t=0.5):
        self.drive(-speed, -speed); time.sleep(t); self.stop()

    def spin(self, speed=100, t=1.2):
        self.drive(speed, -speed); time.sleep(t); self.stop()

    def wiggle(self, speed=80, times=2):
        for _ in range(times):
            self.drive(speed, -speed); time.sleep(0.2)
            self.drive(-speed, speed); time.sleep(0.2)
        self.stop()

    def beep(self, t=0.15):
        self.buzzer(True); time.sleep(t); self.buzzer(False)

    def pattern(self, beats):
        """Play a buzzer rhythm: beats = [(on_seconds, off_seconds), ...]. The buzzer has a single pitch."""
        for on, off in beats:
            self.buzzer(True); time.sleep(on)
            self.buzzer(False); time.sleep(off)

    # --- body language ---
    def happy_wiggle(self, speed=80):
        self.wiggle(speed=speed, times=3)

    def shy_back(self, speed=50):
        self.backward(speed=speed, t=0.35)

    def sulk_turn(self, speed=90, t=1.0):
        """Turn the back to the user (roughly half a turn; tune t on your floor)."""
        self.drive(speed, -speed); time.sleep(t); self.stop()

    def greet(self, speed=60):
        for _ in range(2):                                 # little bow + sway
            self.drive(speed, speed); time.sleep(0.15)
            self.drive(-speed, -speed); time.sleep(0.15)
        self.wiggle(speed=speed, times=1)

    def high_five(self, speed=90):
        self.drive(speed, speed); time.sleep(0.2)
        self.stop(); time.sleep(0.15)
        self.drive(-speed, -speed); time.sleep(0.2)
        self.stop()

    def nuzzle(self, speed=45):
        for _ in range(2):                                 # slow, gentle rub
            self.drive(speed, -speed); time.sleep(0.3)
            self.drive(-speed, speed); time.sleep(0.3)
        self.stop()

    def ask_to_play(self, speed=70):
        self.forward(speed=speed, t=0.4)
        self.wiggle(speed=speed, times=2)

    def surprised_jump(self, speed=120):
        self.drive(-speed, -speed); time.sleep(0.12); self.stop()

    def flinch(self, speed=130):
        """Startled by a threat: jerk back fast, freeze, then shuffle a little further away."""
        self.drive(-speed, -speed); time.sleep(0.3)
        self.stop(); time.sleep(0.5)
        for _ in range(3):                                 # nervous shiver
            self.drive(40, -40); time.sleep(0.05)
            self.drive(-40, 40); time.sleep(0.05)
        self.stop(); time.sleep(0.3)
        self.drive(-50, -50); time.sleep(0.4)
        self.stop()

    # --- mood idle moves (short, gentle; used repeatedly while a mood lasts) ---
    def tremble(self, speed=45):
        """scared: shiver in place and inch backwards."""
        for _ in range(4):
            self.drive(speed, -speed); time.sleep(0.05)
            self.drive(-speed, speed); time.sleep(0.05)
        self.drive(-40, -40); time.sleep(0.15)
        self.stop()

    def look_around(self, speed=60):
        """neutral: glance left, then right, then back."""
        self.drive(-speed, speed); time.sleep(0.15); self.stop(); time.sleep(0.5)
        self.drive(speed, -speed); time.sleep(0.3); self.stop(); time.sleep(0.5)
        self.drive(-speed, speed); time.sleep(0.15); self.stop()

    def happy_dance(self, speed=85):
        """happy: quick wiggle and a little hop."""
        for _ in range(3):
            self.drive(speed, -speed); time.sleep(0.12)
            self.drive(-speed, speed); time.sleep(0.12)
        self.drive(speed, speed); time.sleep(0.12)
        self.drive(-speed, -speed); time.sleep(0.12)
        self.stop()

    def creep_closer(self, speed=40):
        """love: creep forward a bit and rub."""
        self.drive(speed, speed); time.sleep(0.3); self.stop(); time.sleep(0.2)
        self.drive(speed, -speed); time.sleep(0.25)
        self.drive(-speed, speed); time.sleep(0.25)
        self.stop()

    def shy_fidget(self, speed=45):
        """shy: back off a little and twist."""
        self.drive(-speed, -speed); time.sleep(0.15); self.stop(); time.sleep(0.3)
        self.drive(speed, -speed); time.sleep(0.1)
        self.drive(-speed, speed); time.sleep(0.1)
        self.stop()

    def wander(self, speed=50):
        """bored: turn a random way and roll a short distance."""
        turn = random.uniform(0.2, 0.5) * random.choice((-1, 1))
        self.drive(speed if turn > 0 else -speed, -speed if turn > 0 else speed); time.sleep(abs(turn))
        self.stop(); time.sleep(0.3)
        self.drive(speed, speed); time.sleep(0.4)
        self.stop()

    def doze(self, speed=35):
        """sleepy: slow nod forward and back."""
        self.drive(speed, speed); time.sleep(0.2); self.stop(); time.sleep(0.6)
        self.drive(-speed, -speed); time.sleep(0.2); self.stop()

    def huff(self, speed=100):
        """sulky: snap the head away, then slowly back."""
        self.drive(speed, -speed); time.sleep(0.12); self.stop(); time.sleep(0.8)
        self.drive(-40, 40); time.sleep(0.25); self.stop()

    def celebrate(self, speed=90):
        """Goal / home-run celebration: beeps, a full spin, small back-and-forth and left-right moves."""
        try:
            for _ in range(3):
                self.beep(0.08); time.sleep(0.06)
            self.spin(speed=speed + 20, t=1.4)                 # spin around
            for _ in range(2):                                 # little hops forward / back
                self.drive(speed, speed); time.sleep(0.25)
                self.drive(-speed, -speed); time.sleep(0.25)
            self.stop()
            for _ in range(2):                                 # turn a bit left / right
                self.drive(-speed, speed); time.sleep(0.2)
                self.drive(speed, -speed); time.sleep(0.2)
            self.spin(speed=-(speed + 20), t=1.4)              # spin back the other way
            self.beep(0.4)
        finally:
            self.stop()


if __name__ == "__main__":
    import sys
    r = Robot()
    try:
        for mid in range(4):
            print(f"motor {mid} forward")
            r._motor(mid, 60); time.sleep(0.6); r._motor(mid, 0); time.sleep(0.3)
        if "--moves" in sys.argv:
            print("forward"); r.forward()
            print("backward"); r.backward()
            print("spin"); r.spin()
            print("wiggle"); r.wiggle()
        print("beep"); r.beep()
    finally:
        r.stop()
