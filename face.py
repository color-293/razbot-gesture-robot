"""Animated robot face on the 128x32 SSD1306 OLED (I2C 0x3C)."""
import io
import math
import random
import threading
import time

from PIL import Image, ImageDraw

W, H = 128, 32
LX, RX, CY = 40, 88, 16     # eye centers

EXPRESSIONS = ("neutral", "happy", "sleepy", "bored", "surprised", "love", "shy", "sulky", "scared")


def _eye_box(cx, cy, w, h):
    return (cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2)


def _heart(d, cx, cy, s):
    r = s / 4
    d.ellipse((cx - 2 * r, cy - r * 1.6, cx, cy + r * 0.4), fill=255)
    d.ellipse((cx, cy - r * 1.6, cx + 2 * r, cy + r * 0.4), fill=255)
    d.polygon([(cx - 2 * r + 0.5, cy - r * 0.4), (cx + 2 * r - 0.5, cy - r * 0.4), (cx, cy + 2 * r)], fill=255)


def render(expr, t):
    """Draw one frame of an expression at time t (seconds)."""
    img = Image.new("1", (W, H))
    d = ImageDraw.Draw(img)
    blink = (t % 4.0) < 0.15                      # short blink every 4 s
    look = int(6 * math.sin(t * 0.7))             # slow eye wander

    if expr == "neutral":
        h = 3 if blink else 22
        for cx in (LX, RX):
            d.rounded_rectangle(_eye_box(cx + look, CY, 20, h), radius=6 if h > 6 else 1, fill=255)
    elif expr == "happy":
        bounce = int(2 * math.sin(t * 8))
        for cx in (LX, RX):                       # ^ ^ eyes
            d.arc(_eye_box(cx, CY + 9 + bounce, 30, 34), 200, 340, fill=255, width=6)
    elif expr == "sleepy":
        for cx in (LX, RX):
            d.rounded_rectangle(_eye_box(cx, CY + 6, 22, 4), radius=1, fill=255)
        z = (t * 6) % 18                           # drifting z
        d.text((108, 18 - z), "z", fill=255)
        d.text((116, 12 - z / 2), "Z", fill=255)
    elif expr == "bored":
        h = 2 if blink else 10
        for cx in (LX, RX):                       # half-closed lids, looking sideways
            d.rounded_rectangle(_eye_box(cx + 6, CY + 7, 20, h), radius=3, fill=255)
            d.line((cx - 5, CY - 3, cx + 17, CY - 3), fill=255, width=2)
    elif expr == "surprised":
        r = 12 + int(math.sin(t * 10) > 0)
        for cx in (LX, RX):
            d.ellipse(_eye_box(cx, CY, 2 * r, 2 * r), outline=255, width=2)
            d.ellipse(_eye_box(cx, CY, 8, 8), fill=255)
    elif expr == "love":
        s = 20 + 4 * abs(math.sin(t * 4))         # pulsing hearts
        for cx in (LX, RX):
            _heart(d, cx, CY - 2, s)
    elif expr == "shy":
        for cx in (LX, RX):
            d.arc(_eye_box(cx, CY + 4, 20, 20), 200, 340, fill=255, width=4)
            for k in (-6, 0, 6):                  # blush marks
                d.line((cx + k - 2, 30, cx + k + 2, 26), fill=255)
    elif expr == "sulky":
        for cx, side in ((LX, 1), (RX, -1)):      # angry slanted lids
            d.rounded_rectangle(_eye_box(cx, CY + 2, 22, 24), radius=5, fill=255)
            top = CY - 11
            d.polygon([(cx - 12, top), (cx + 12, top), (cx + 12, top + 6 + 6 * side), (cx - 12, top + 6 - 6 * side)], fill=0)
    elif expr == "scared":
        shake = 1 if int(t * 20) % 2 else -1          # trembling
        for cx, side in ((LX, 1), (RX, -1)):         # squeezed > < eyes
            x0, x1 = cx - 9 * side, cx + 9 * side
            d.line((x0 + shake, CY - 9, x1 + shake, CY - 2), fill=255, width=4)
            d.line((x1 + shake, CY - 2, x0 + shake, CY + 5), fill=255, width=4)
        d.ellipse((112, 2 + shake, 120, 14 + shake), fill=255)   # sweat drop
        d.polygon([(113, 6 + shake), (119, 6 + shake), (116, 0 + shake)], fill=255)
    return img


class Face:
    """Background animation loop; falls back to web-only preview when no OLED is attached."""

    def __init__(self, fps=12):
        self.base = "neutral"
        self.expr = "neutral"
        self._until = 0.0
        self._img = render("neutral", 0)
        self._lock = threading.Lock()
        self.device = None
        try:
            from luma.core.interface.serial import i2c
            from luma.oled.device import ssd1306
            self.device = ssd1306(i2c(port=1, address=0x3C), width=W, height=H)
        except Exception as e:
            print("OLED unavailable:", e)
        threading.Thread(target=self._run, args=(1.0 / fps,), daemon=True).start()

    def show(self, expr, hold=3.0):
        """Show an expression for `hold` seconds, then go back to the base mood."""
        with self._lock:
            self.expr = expr
            self._until = time.time() + hold

    def set_base(self, expr):
        with self._lock:
            self.base = expr

    def current(self):
        with self._lock:
            return self.expr if time.time() < self._until else self.base

    def png(self, scale=4):
        img = self._img.resize((W * scale, H * scale), Image.NEAREST).convert("L")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    def _run(self, dt):
        t0 = time.time() + random.random() * 4
        while True:
            img = render(self.current(), time.time() - t0)
            self._img = img
            if self.device:
                try:
                    self.device.display(img)
                except OSError:
                    pass  # transient I2C error; try again next frame
            time.sleep(dt)
