"""Flask web server: the raising-game app (web/index.html at /), the old full control page (/dev), the JSON API,
the camera loop and mode switching (companion / hand driving / goal celebration)."""
import argparse
import threading
import time
from pathlib import Path

import cv2
from flask import Flask, Response, jsonify, render_template_string, request, send_from_directory

from companion import Companion
from control import Controller
from face import Face
from gesture import GestureDetector, draw
from scene import SceneDetector

WEB = Path(__file__).with_name("web")
LABEL_KO = {"rock": "주먹 ✊", "paper": "보 ✋", "scissors": "가위 ✌️", "thumbs_up": "최고 👍", "point": "검지 ☝️",
            "unknown": "알 수 없음", None: "손 없음"}

app = Flask(__name__)
state = {"frame": None, "status": {}, "fps": 0.0, "fingers": None, "mode": "pet"}   # companion is the main mode
state_lock = threading.Lock()
ctrl: Controller = None
scene: SceneDetector = None
face: Face = None
pet: Companion = None
robot = None
sound = {"on": True}
celebrating = threading.Event()
celebrations = {"count": 0, "last": 0.0}


def celebrate():
    """Run the celebration once; ignored while one is already running."""
    if celebrating.is_set():
        return
    celebrating.set()
    celebrations["count"] += 1
    celebrations["last"] = time.time()
    face.show("happy", 7)
    pet.note("⚽ 골! 같이 응원했어요 🎉", mood="happy", secs=60, love=1, cheer_up=True, grow="goal")
    pet.daily.remember_once("first_goal", "⚽", "처음으로 같이 골 세레머니를 했어요")

    def run():
        try:
            if robot and ctrl.motion_enabled:
                robot.celebrate()
            else:
                time.sleep(3)  # keep the on-screen banner up when the robot is not moving
        finally:
            celebrating.clear()

    threading.Thread(target=run, daemon=True).start()


def camera_loop(cam_index):
    cap = cv2.VideoCapture(cam_index, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    detector = GestureDetector()
    t_prev = time.time()
    fps = 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            ctrl.update(None)
            time.sleep(0.1)
            continue
        mode = state["mode"]
        if mode in ("hand", "pet"):
            frame = cv2.flip(frame, 1)  # mirror view
            label, fingers, lm = detector.detect(frame)
            if mode == "hand":
                status = ctrl.update(label)
            else:
                pet.update(label, lm)
                status = {"label": label}
                if lm is not None:          # where the hand is, so the app's character can look at it
                    status.update(x=round(lm[9].x, 3), y=round(lm[9].y, 3))
            if lm is not None:
                draw(frame, lm)
        else:
            scene.submit(frame.copy())
            label, fingers, status = None, None, {}
        now = time.time()
        fps = 0.9 * fps + 0.1 * (1.0 / max(now - t_prev, 1e-3))
        t_prev = now
        _, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        with state_lock:
            state.update(frame=jpg.tobytes(), status=status, fps=fps, fingers=fingers)


def mjpeg():
    last = None
    while True:
        with state_lock:
            frame = state["frame"]
        if frame is None or frame is last:
            time.sleep(0.02)
            continue
        last = frame
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"


@app.route("/video")
def video():
    return Response(mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/state")
def get_state():
    with state_lock:
        s = {"status": state["status"], "fps": round(state["fps"], 1), "fingers": state["fingers"],
             "mode": state["mode"]}
    s.update(ctrl.snapshot())
    s["scene"] = scene.snapshot()
    s["pet"] = pet.snapshot()
    s["pet"]["history"] = pet.mood_history(600)
    s["sound"] = sound["on"]
    s["robot"] = robot is not None
    s["celebrating"] = celebrating.is_set()
    s["celebrations"] = celebrations["count"]
    s["label_ko"] = LABEL_KO.get(s["status"].get("label"), "?")
    return jsonify(s)


@app.route("/face.png")
def face_png():
    return Response(face.png(), mimetype="image/png", headers={"Cache-Control": "no-store"})


@app.route("/pet/<event>", methods=["POST"])
def pet_event(event):
    if event in ("come", "follow"):
        return jsonify(ok=pet.start_follow(event))
    if event == "stop_follow":
        pet.follow.cancel()
        return jsonify(ok=True)
    if event == "exp":                       # test button: +10 EXP
        return jsonify(ok=pet.grow("test") > 0)
    if event == "snack":
        return jsonify(ok=pet.give_snack())
    if event == "sleep":                     # 재우기 / 깨우기 toggle
        return jsonify(ok=pet.toggle_sleep())
    if event in ("poke", "stroke", "dizzy"):  # the character in the app was touched
        return jsonify(ok=pet.touch(event))
    return jsonify(ok=pet.trigger(event))


@app.route("/pet/game/<action>", methods=["POST"])
def pet_game(action):
    if action == "start":
        return jsonify(ok=pet.start_game())
    pet.game.cancel()
    return jsonify(ok=True)


@app.route("/train/<action>", methods=["POST"])
@app.route("/train/<action>/<trick>", methods=["POST"])
def train(action, trick=None):
    """개인기 훈련: start / show a trick, reward the current try, stop, or save the custom routine."""
    t = pet.training
    if action == "start":
        return jsonify(ok=pet.start_training(trick))
    if action == "show":
        return jsonify(ok=t.show(trick))
    if action == "reward":
        return jsonify(ok=t.reward())
    if action == "stop":
        t.cancel()
        return jsonify(ok=True)
    if action == "custom" and (pet.growth.has("custom_trick")):
        return jsonify(ok=t.set_custom((request.get_json(silent=True) or {}).get("moves", [])))
    return jsonify(ok=False)


@app.route("/demo/<onoff>", methods=["POST"])
def demo(onoff):
    """시연 모드: open every interaction regardless of level (not saved)."""
    pet.growth.unlock_all = onoff == "on"
    return jsonify(ok=True)


@app.route("/pet/mood/<mood>", methods=["POST"])
def pet_mood(mood):
    return jsonify(ok=pet.set_mood(mood))


@app.route("/sound/<onoff>", methods=["POST"])
def set_sound(onoff):
    sound["on"] = onoff == "on"
    return jsonify(sound=sound["on"])


@app.route("/mode/<mode>", methods=["POST"])
def set_mode(mode):
    if mode in ("hand", "watch", "pet"):
        ctrl.halt()
        if mode != "pet":
            pet.game.cancel()
            pet.follow.cancel()
            pet.training.cancel()
        state["mode"] = mode
        scene.enabled = mode == "watch"
        face.set_base("neutral")
    return jsonify(mode=state["mode"])


@app.route("/motion/<onoff>", methods=["POST"])
def motion(onoff):
    ctrl.set_motion(onoff == "on")
    return jsonify(motion_enabled=ctrl.motion_enabled)


@app.route("/speed/<int:value>", methods=["POST"])
def speed(value):
    ctrl.set_speed(value)
    return jsonify(speed=ctrl.speed)


@app.route("/threshold/<int:pct>", methods=["POST"])
def threshold(pct):
    scene.threshold = max(10, min(pct, 99)) / 100
    return jsonify(threshold=scene.threshold)


@app.route("/celebrate", methods=["POST"])
def celebrate_now():
    celebrate()
    return jsonify(ok=True)


@app.route("/mood")
def get_mood():
    """The robot's mood as JSON (for other apps): current mood, affection, what it is doing, last 10 minutes."""
    m = pet.snapshot()
    m["history"] = pet.mood_history(600)
    m["mode"] = state["mode"]
    m["motion"] = ctrl.motion_enabled
    m["sound"] = sound["on"]
    m["robot"] = robot is not None
    return jsonify(m)


@app.route("/")
def index():
    """Landing page: what 라즈봇 is, its emotions, how to play - with an "앱 열기" button."""
    return Response((WEB / "index.html").read_bytes(), mimetype="text/html")


@app.route("/app")
def app_page():
    """The app (pixel game console style): 홈 · 감정 · 놀기 · 도감 · 추억."""
    return Response((WEB / "app.html").read_bytes(), mimetype="text/html")


@app.route("/pixel.js")
def pixel_js():
    return send_from_directory(WEB, "pixel.js")


@app.route("/dev")
def dev():
    """The previous full control page with every test button (for development)."""
    return render_template_string(PAGE)


PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>라즈봇</title>
<style>
 :root{--bg:#f6f7f9;--card:#fff;--fg:#1d2330;--mut:#6b7280;--acc:#2563eb;--fwd:#16a34a;--back:#d97706;--stop:#dc2626;--gold:#eab308;
  --neutral:#94a3b8;--happy:#eab308;--love:#ec4899;--shy:#fb923c;--bored:#8b5cf6;--sleepy:#6366f1;--sulky:#ef4444;--scared:#0ea5e9;--m:var(--neutral)}
 @media (prefers-color-scheme:dark){:root{--bg:#111318;--card:#1b1f27;--fg:#e8eaf0;--mut:#9aa1ad;--acc:#60a5fa}}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);font-family:system-ui,'Apple SD Gothic Neo','Malgun Gothic',sans-serif}
 header{padding:14px 20px;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
 h1{font-size:20px;margin:0}
 main{display:grid;grid-template-columns:minmax(0,640px) minmax(260px,1fr);gap:16px;padding:0 20px 20px}
 @media (max-width:900px){main{grid-template-columns:1fr;padding:0 16px 16px}}
 .card{background:var(--card);border-radius:12px;padding:14px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
 .vwrap{position:relative}
 #video{width:100%;border-radius:8px;display:block;background:#000;aspect-ratio:4/3}
 #party{position:absolute;inset:0;display:none;align-items:center;justify-content:center;font-size:56px;font-weight:900;color:#fff;
   text-shadow:0 3px 12px rgba(0,0,0,.6);background:rgba(234,179,8,.35);border-radius:8px;animation:pulse .6s infinite alternate}
 @keyframes pulse{from{transform:scale(1)}to{transform:scale(1.04)}}
 .now{font-size:30px;font-weight:700;margin:4px 0}
 .bar{height:8px;background:rgba(127,127,127,.2);border-radius:4px;overflow:hidden;position:relative}
 .bar>div{height:100%;background:var(--acc);width:0;transition:width .15s}
 .bar.big{height:16px}
 .bar .th{position:absolute;top:0;bottom:0;width:2px;background:var(--stop)}
 .fingers{display:flex;gap:6px;margin-top:10px}
 .fingers span{flex:1;text-align:center;padding:4px 0;border-radius:6px;font-size:12px;background:rgba(127,127,127,.15);color:var(--mut)}
 .fingers span.on{background:var(--acc);color:#fff}
 .cmd{font-size:40px;font-weight:800;text-align:center;padding:18px 0;border-radius:10px;color:#fff;background:var(--stop)}
 .cmd.forward{background:var(--fwd)} .cmd.backward{background:var(--back)}
 .legend{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;text-align:center;font-size:14px;margin-top:12px}
 .legend div{padding:8px 0;border-radius:8px;background:rgba(127,127,127,.12)}
 .legend div.on{outline:2px solid var(--acc)}
 table{width:100%;border-collapse:collapse;font-size:14px} td{padding:5px 4px;border-top:1px solid rgba(127,127,127,.2)}
 .mut{color:var(--mut);font-size:13px}
 .ctl{display:flex;align-items:center;gap:16px;flex-wrap:wrap;font-size:14px}
 .ctl label{display:flex;align-items:center;gap:8px;cursor:pointer}
 .side{display:flex;flex-direction:column;gap:16px}
 .off{color:var(--stop);font-size:13px;margin-top:8px;text-align:center}
 .tabs{display:flex;gap:4px;background:rgba(127,127,127,.15);padding:4px;border-radius:10px}
 .tabs button{border:0;background:transparent;color:var(--fg);padding:6px 14px;border-radius:7px;font-size:14px;cursor:pointer}
 .tabs button.on{background:var(--card);box-shadow:0 1px 3px rgba(0,0,0,.15);font-weight:700}
 .btn{border:0;background:var(--gold);color:#1d2330;font-weight:700;padding:10px 14px;border-radius:8px;cursor:pointer;width:100%;font-size:15px}
 svg.spark{width:100%;height:60px;display:block;margin-top:8px}
 .hide{display:none!important}
 .oled{width:100%;max-width:512px;image-rendering:pixelated;background:#000;border-radius:6px;display:block;margin-top:8px;
   filter:sepia(1) saturate(4) hue-rotate(160deg) brightness(1.1)}
 .howto td{font-size:13px} .howto td:last-child{color:var(--mut)}
 .pbtns{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
 .pbtns button{border:0;border-radius:8px;padding:8px 4px;background:rgba(127,127,127,.15);color:var(--fg);cursor:pointer;font-size:13px}
 .pbtns button:hover{background:rgba(127,127,127,.28)}
 .pbtns button.on{outline:2px solid var(--acc)}
 .behav{margin-top:10px;padding:10px;border-radius:8px;background:rgba(127,127,127,.1)}
 .game .vs{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;text-align:center;margin:8px 0}
 .game .hand{font-size:44px;line-height:1.1} .game .who{font-size:12px;color:var(--mut)}
 .game .score{font-size:28px;font-weight:800;padding:0 10px}
 .game .msg{font-size:18px;font-weight:700;text-align:center;min-height:26px;margin:6px 0 10px}
 .game .msg.countdown{font-size:30px;color:var(--acc)}
 .btn.stop{background:rgba(127,127,127,.2);color:var(--fg)}
 .moodbar{margin:0 20px 16px;padding:12px 16px;border-radius:12px;display:flex;align-items:center;gap:14px;flex-wrap:wrap;
   background:color-mix(in srgb,var(--m) 16%,var(--card));box-shadow:0 1px 3px rgba(0,0,0,.08);transition:background .6s}
 @media (max-width:900px){.moodbar{margin:0 16px 16px}}
 .moodbar .me{font-size:44px;line-height:1} .moodbar .mn{font-size:22px;font-weight:800} .moodbar .md{font-size:14px;color:var(--mut)}
 .moodbar .mh{margin-left:auto;text-align:right;font-size:18px} .moodbar .mh div{font-size:12px;color:var(--mut)}
 .chip{font-size:14px;font-weight:700;padding:6px 10px;border-radius:8px;background:var(--card);display:none}
 .chip.on{display:inline-block;animation:pop .35s ease-out}
 @keyframes pop{from{transform:scale(.9);opacity:0}to{transform:scale(1);opacity:1}}
 .need{width:100%;font-size:14px;padding:8px 12px;border-radius:8px;border-left:4px solid var(--m);background:var(--card);display:none}
 .need.on{display:block}
 .qbtns{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
 .qbtns .btn{font-size:16px;padding:14px 6px;background:var(--acc);color:#fff}
 .qbtns .btn:disabled{opacity:.45;cursor:default}
 .tl{display:flex;height:20px;border-radius:6px;overflow:hidden;background:rgba(127,127,127,.15);margin-top:8px}
 .tl div{height:100%;min-width:1px}
 .tlx{display:flex;justify-content:space-between;font-size:11px;color:var(--mut);margin-top:4px}
 .tlg{display:flex;flex-wrap:wrap;gap:4px 12px;margin-top:8px;font-size:13px}
 .tlg i{width:10px;height:10px;border-radius:3px;display:inline-block;margin-right:4px}
 .grow{display:flex;align-items:center;gap:10px;min-width:220px}
 .grow .ge{font-size:34px;line-height:1}
 .grow .gl{font-size:15px;font-weight:800} .grow .gx{font-size:12px;color:var(--mut)}
 .xbar{height:8px;border-radius:4px;background:rgba(127,127,127,.2);overflow:hidden;margin-top:3px;width:150px}
 .xbar>div{height:100%;background:linear-gradient(90deg,#a855f7,#ec4899);width:0;transition:width .4s}
 .needs{display:flex;gap:10px;width:100%}
 .needs>div{flex:1;font-size:12px;color:var(--mut)}
 .needs .nb{height:8px;border-radius:4px;background:rgba(127,127,127,.2);overflow:hidden;margin-top:3px}
 .needs .nb>div{height:100%;width:0;transition:width .4s,background .4s}
 .needs .lowv{color:var(--stop);font-weight:700}
 .lvup{position:fixed;left:50%;top:18px;transform:translateX(-50%);z-index:9;padding:14px 22px;border-radius:14px;font-size:20px;font-weight:900;
   color:#fff;background:linear-gradient(90deg,#a855f7,#ec4899);box-shadow:0 6px 24px rgba(0,0,0,.25);display:none;white-space:nowrap}
 .lvup.on{display:block;animation:pop .4s ease-out}
 .stages{display:flex;justify-content:space-between;margin:10px 0 6px;text-align:center;font-size:12px;color:var(--mut)}
 .stages div{flex:1} .stages b{display:block;font-size:26px;filter:grayscale(1);opacity:.4}
 .stages .got b{filter:none;opacity:1} .stages .cur{color:var(--fg);font-weight:700}
 .unl{list-style:none;padding:0;margin:6px 0 0;font-size:14px} .unl li{padding:5px 0;border-top:1px solid rgba(127,127,127,.2)}
 .unl li.lock{color:var(--mut)}
</style></head><body>
<header><h1>🤖 라즈봇</h1>
 <div class="tabs"><button id="m-pet">🐶 교감·놀이</button><button id="m-hand">✋ 손 조종</button><button id="m-watch">⚽ 경기 관람</button></div>
 <div class="ctl">
  <label>속도 <input type="range" id="speed" min="30" max="255" step="5"> <span id="spv"></span></label>
  <label><input type="checkbox" id="sound"> 소리</label>
  <label><input type="checkbox" id="motion"> 로봇 움직이기</label></div></header>
<div class="moodbar" id="moodbar">
 <div class="me" id="mb-emoji">😐</div>
 <div><div class="mn" id="mb-name">평온</div><div class="md" id="mb-desc">-</div></div>
 <span class="chip" id="mb-just"></span>
 <div class="grow"><div class="ge" id="gr-emoji">🐣</div>
  <div><div class="gl" id="gr-lv">Lv.1 아기봇</div><div class="xbar"><div id="gr-bar"></div></div><div class="gx" id="gr-exp"></div></div></div>
 <div class="mh"><span id="mb-hearts"></span><div id="mb-lv"></div></div>
 <div class="needs"><div>⚡ 에너지 <span id="nd-energy-v"></span><div class="nb"><div id="nd-energy"></div></div></div>
  <div>🎈 재미 <span id="nd-fun-v"></span><div class="nb"><div id="nd-fun"></div></div></div>
  <div>💗 애정 <span id="nd-love-v"></span><div class="nb"><div id="nd-love"></div></div></div></div>
 <div class="need" id="mb-need"></div>
</div>
<div class="lvup" id="lvup"></div>
<main>
 <div class="card"><div class="vwrap"><img id="video" src="/video" alt="카메라"><div id="party">🎉 GOAL! 🎉</div></div>
  <div class="nowatch">
   <div style="display:flex;justify-content:space-between;align-items:baseline">
    <div class="now" id="now">-</div><div class="mut" id="fps"></div></div>
   <div class="bar"><div id="prog"></div></div>
   <div class="fingers" id="fingers"></div>
  </div>
  <div class="watch-only">
   <div style="display:flex;justify-content:space-between;align-items:baseline;margin-top:6px">
    <div class="now" id="sc">-</div><div class="mut" id="fps2"></div></div>
   <div class="bar big"><div id="scbar"></div><span class="th" id="thmark"></span></div>
   <div class="mut" id="top" style="margin-top:6px"></div>
   <svg class="spark" id="spark" viewBox="0 0 60 1" preserveAspectRatio="none"></svg>
  </div>
 </div>
 <div class="side">
  <div class="card hand-only"><div class="mut">현재 명령</div><div class="cmd" id="cmd">정지</div>
   <div class="off moff">로봇 움직이기가 꺼져 있어요 (화면에만 표시)</div>
   <div class="legend"><div id="g-scissors">✌️ 가위<br><b>전진</b></div><div id="g-paper">✋ 보<br><b>후진</b></div><div id="g-rock">✊ 주먹<br><b>정지</b></div></div>
   <div class="mut" style="margin-top:10px">손이 1초 넘게 안 보이면 자동으로 멈춰요.</div></div>
  <div class="card hand-only"><div class="mut">명령 기록</div><table id="hist"></table></div>
  <div class="card watch-only"><div class="mut">경기 관람 모드</div>
   <p style="margin:8px 0;font-size:14px">카메라를 TV/모니터에 비춰 주세요. 골·홈런 장면 점수가 기준선을 2번 연속 넘으면 세레머니!</p>
   <div class="off moff">로봇 움직이기가 꺼져 있어요 (화면에만 표시)</div>
   <label class="ctl" style="margin:10px 0">민감도 기준 <input type="range" id="th" min="30" max="95" step="1"> <span id="thv"></span></label>
   <button class="btn" id="test">🎉 세레머니 테스트</button>
   <div class="mut" id="sstat" style="margin-top:8px"></div></div>
  <div class="card watch-only"><div class="mut">세레머니 기록</div><table id="ev"></table></div>
  <div class="card pet-only"><div class="mut" style="margin-bottom:8px">로봇 부르기</div>
   <div class="qbtns"><button class="btn" id="q-come">🐶 이리 와</button><button class="btn" id="q-follow">👣 따라와</button><button class="btn" id="q-nap">😴 낮잠</button></div>
   <div class="mut" id="q-hint" style="margin-top:8px"></div></div>
  <div class="card pet-only"><div class="mut">로봇 얼굴 (OLED)</div>
   <img id="face" class="oled" alt="로봇 얼굴">
   <div style="display:flex;justify-content:space-between;align-items:baseline;margin-top:8px">
    <div class="now" id="mood">-</div><div id="hearts" style="font-size:18px"></div></div>
   <div class="mut" id="aff"></div>
   <div class="behav"><div class="mut">지금 기분에 따른 행동</div><div id="behav" style="font-size:16px;font-weight:600;margin-top:2px"></div>
    <div class="mut" id="lastmove"></div></div>
   <div class="behav hide" id="walk"><div class="mut">지금 하는 일</div><div id="walkmsg" style="font-size:16px;font-weight:600;margin-top:2px"></div>
    <button class="btn stop" id="walkstop" style="margin-top:8px">⏹ 멈춰!</button></div>
   <div class="off moff">로봇 움직이기가 꺼져 있어요 (표정·소리만)</div>
   <div class="mut" style="margin:10px 0 6px">기분 바꾸기</div>
   <div class="pbtns" id="mbtns"></div></div>
  <div class="card pet-only"><div class="mut" style="display:flex;justify-content:space-between"><span>지난 10분 기분 흐름</span><span>지금 →</span></div>
   <div class="tl" id="tl"></div><div class="tlx"><span>10분 전</span><span>5분 전</span><span>지금</span></div>
   <div class="tlg" id="tlg"></div></div>
  <div class="card pet-only"><div class="mut" style="display:flex;justify-content:space-between"><span>🌱 성장</span><span id="gr-total"></span></div>
   <div class="stages" id="stages"></div>
   <div class="mut" id="gr-next"></div>
   <ul class="unl" id="unl"></ul>
   <div class="mut" style="margin-top:8px">EXP 얻는 법: 인사·하이파이브 +2 · 쓰담·칭찬·이리 와·따라와·골 응원 +3 · 가위바위보 한 판 +5</div></div>
  <div class="card pet-only game"><div class="mut">🎮 같이 놀기 · 가위바위보 (3판 2선승)</div>
   <div class="msg" id="gmsg">✌️ 가위를 1초 들고 있으면 같이 놀아요</div>
   <div class="vs"><div><div class="hand" id="grobot">🤖</div><div class="who">로봇</div></div>
    <div class="score" id="gscore">0 : 0</div>
    <div><div class="hand" id="guser">🙂</div><div class="who">나</div></div></div>
   <button class="btn" id="gstart">🎮 가위바위보 하자!</button>
   <div class="mut" id="gstats" style="margin-top:8px"></div></div>
  <div class="card pet-only"><div class="mut">이렇게 놀아 주세요</div>
   <table class="howto">
    <tr><td>👋 손을 빠르게 좌우로 흔들기</td><td>인사 (아침/낮/밤)</td></tr>
    <tr><td>✋ 손바닥 펴고 가만히</td><td>하이파이브</td></tr>
    <tr><td>🤚 손을 천천히 크게 좌우로</td><td>쓰담쓰담</td></tr>
    <tr><td>👍 엄지 척</td><td>칭찬 → 하트, 애정도↑</td></tr>
    <tr><td>👊 주먹을 휘두르거나 들이밀기</td><td>주춤 뒷걸음질 → 한동안 벌벌, 애정도↓</td></tr>
    <tr><td>🤏 손을 쥐었다 폈다 까딱까딱</td><td>이리 와 → 다가와서 꾸벅 (애정도↑)</td></tr>
    <tr><td>☝️ 검지를 1초 들고 있기</td><td>따라와 → 손을 따라다녀요, ✊ 주먹 쥐면 멈춤</td></tr>
    <tr><td>🖐️ 편 손을 위에서 천천히 내리기</td><td>자장자장 → 1분 낮잠, 👋 흔들면 깨어나요</td></tr>
    <tr><td>✌️ 가위를 1초 들고 있기</td><td>가위바위보 하자! (끝까지 하면 애정도↑)</td></tr>
    <tr><td>🙈 한동안 안 놀아 주기</td><td>심심 → 놀아줘 → 삐짐</td></tr>
    <tr><td>🏃 "놀아줘" 뒤에 돌아오기</td><td>로봇이 먼저 게임하자고 해요</td></tr>
   </table>
   <div class="mut" style="margin:10px 0 6px">반응 테스트</div>
   <div class="pbtns" id="pbtns"></div></div>
  <div class="card pet-only"><div class="mut">교감 기록</div><table id="pev"></table></div>
 </div>
</main>
<script>
const CMD={forward:'⬆ 전진',backward:'⬇ 후진',stop:'■ 정지'};
const WHY={scissors:'가위 ✌️',paper:'보 ✋',rock:'주먹 ✊',no_hand:'손 놓침',mode:'모드 변경'};
const FN=['엄지','검지','중지','약지','소지'];
const $=id=>document.getElementById(id);
const post=u=>fetch(u,{method:'POST'});
$('motion').onchange=e=>post('/motion/'+(e.target.checked?'on':'off'));
$('speed').oninput=e=>{$('spv').textContent=e.target.value;};
$('speed').onchange=e=>post('/speed/'+e.target.value);
$('th').oninput=e=>{$('thv').textContent=e.target.value+'%';};
$('th').onchange=e=>post('/threshold/'+e.target.value);
$('test').onclick=()=>post('/celebrate');
$('m-hand').onclick=()=>post('/mode/hand');
$('m-watch').onclick=()=>post('/mode/watch');
$('m-pet').onclick=()=>post('/mode/pet');
$('sound').onchange=e=>post('/sound/'+(e.target.checked?'on':'off'));
const MOOD={neutral:'😐 평온',happy:'😊 기쁨',sleepy:'😴 졸림',bored:'🥱 심심',surprised:'😮 놀람',love:'🥰 사랑',shy:'☺️ 부끄럼',sulky:'😤 삐짐',scared:'😨 무서움',
 levelup:'🎉 레벨 업!',count1:'🎮 가위…',count2:'🎮 바위…',count3:'🎮 보!',rps_rock:'🎮 바위 ✊',rps_paper:'🎮 보 ✋',rps_scissors:'🎮 가위 ✌️'};
const HAND={rock:'✊',paper:'✋',scissors:'✌️'};
const DESC={neutral:'편안하게 주변을 둘러보고 있어요',happy:'기분이 좋아서 들썩들썩해요',love:'네가 좋아서 가까이 가고 싶어 해요',
 shy:'부끄러워서 꼼지락거려요',bored:'심심해서 어슬렁어슬렁 돌아다녀요',sleepy:'꾸벅꾸벅 졸고 있어요',sulky:'삐져서 고개를 홱 돌려요',
 scared:'무서워서 벌벌 떨고 있어요'};
const NEED={sulky:'😤 삐졌어요. 👋 인사하거나 👍 칭찬해서 달래 주세요',bored:'🥱 심심해해요. 같이 놀아 주세요 (✌️ 가위를 1초 들면 가위바위보)',
 scared:'😨 무서워하고 있어요. 🤚 천천히 쓰다듬어 주세요'};
const mk=m=>DESC[m]?m:'neutral';
let lastJust=null, lastLv=null, lvTimer=null;
const STAGES=[[1,'🐣','아기봇'],[3,'🐥','꼬마봇'],[5,'🤖','친구봇'],[8,'🦾','든든봇'],[10,'👑','단짝봇']];
const LOWNEED={energy:'⚡ 너무 피곤해해요. 🖐️ 자장자장 해서 낮잠 재워 주세요',fun:'🎈 놀고 싶어 해요. ✌️ 가위바위보나 ☝️ 산책 어때요?',
 love:'💗 관심이 필요해요. 🤚 쓰다듬거나 👍 칭찬해 주세요'};
function growth(P){
 const g=P.growth; if(!g) return;
 $('gr-emoji').textContent=g.stage_emoji; $('gr-lv').textContent='Lv.'+g.level+' '+g.stage;
 $('gr-bar').style.width=(g.into/g.need*100)+'%'; $('gr-exp').textContent='다음 레벨까지 '+(g.need-g.into)+' EXP';
 ['energy','fun','love'].forEach(n=>{const v=g.needs[n], c=v<15?'var(--stop)':v<40?'var(--gold)':'var(--fwd)';
  $('nd-'+n).style.width=v+'%'; $('nd-'+n).style.background=c; $('nd-'+n+'-v').textContent=v; $('nd-'+n+'-v').className=v<15?'lowv':'';});
 if(lastLv!==null&&g.level>lastLv){ $('lvup').textContent='🎉 레벨 업! Lv.'+g.level+' '+g.stage_emoji+' '+g.stage;
  $('lvup').classList.remove('on'); void $('lvup').offsetWidth; $('lvup').classList.add('on');
  clearTimeout(lvTimer); lvTimer=setTimeout(()=>$('lvup').classList.remove('on'),5000); }
 lastLv=g.level;
 $('gr-total').textContent='총 '+g.exp+' EXP';
 $('stages').innerHTML=STAGES.map(([lv,e,n],i)=>{const nx=STAGES[i+1], cur=g.level>=lv&&(!nx||g.level<nx[0]);
  return '<div class="'+(g.level>=lv?'got ':'')+(cur?'cur':'')+'"><b>'+e+'</b>'+n+'<br>Lv.'+lv+'</div>';}).join('');
 $('gr-next').textContent=g.next_stage?'Lv.'+g.next_stage.level+'이 되면 '+g.next_stage.emoji+' '+g.next_stage.name+'(으)로 자라요':'다 자랐어요! 최고의 단짝 👑';
 $('unl').innerHTML=g.unlocks.map(u=>'<li class="'+(u.open?'':'lock')+'">'+(u.open?'✅ ':'🔒 Lv.'+u.level+' · ')+u.label+'</li>').join('');
}
$('q-come').onclick=()=>post('/pet/come');
$('q-follow').onclick=()=>post('/pet/follow');
$('q-nap').onclick=()=>post('/pet/nap');
function moodbar(s,P){
 const m=mk(P.mood);
 document.documentElement.style.setProperty('--m','var(--'+m+')');
 const [em,...nm]=MOOD[m].split(' ');
 $('mb-emoji').textContent=em; $('mb-name').textContent='지금 기분: '+nm.join(' ');
 $('mb-desc').textContent=P.sleeping&&P.nap_left>0?'낮잠 자는 중… '+P.nap_left+'초 뒤에 일어나요':DESC[m];
 $('mb-hearts').textContent='❤️'.repeat(Math.min(P.level,5))+'🤍'.repeat(Math.max(0,5-P.level));
 $('mb-lv').textContent='애정도 '+P.affection+'점 · 하트 '+Math.min(P.level,5)+'개';
 const e=P.events[0], fresh=e&&e.ts&&Date.now()/1000-e.ts<8;
 if(!fresh) $('mb-just').classList.remove('on');
 else if(e.ts!==lastJust){ $('mb-just').textContent='방금: '+e.text; $('mb-just').classList.remove('on'); void $('mb-just').offsetWidth; $('mb-just').classList.add('on'); lastJust=e.ts; }
 growth(P);
 const g=P.growth||{needs:{}}, lowN=['energy','fun','love'].find(n=>g.needs[n]<15);
 const need=P.sleeping?'😴 자고 있어요. 👋 손을 흔들면 깨어나요':P.sulking?NEED.sulky:lowN?LOWNEED[lowN]:(NEED[m]||'');
 $('mb-need').textContent=need; $('mb-need').classList.toggle('on',!!need);
 // quick buttons
 const playing=P.game.active||P.follow.active, can=s.motion_enabled&&!P.sleeping&&!playing;
 ['q-come','q-follow'].forEach(id=>$(id).disabled=!can); $('q-nap').disabled=P.sleeping||playing;
 $('q-hint').textContent=!s.motion_enabled?'위의 "로봇 움직이기"를 켜야 와요':P.sleeping?'자는 중이라 못 들어요 😴':
  playing?'지금 다른 걸 하고 있어요':'카메라에 손을 보여 주면 그쪽으로 찾아와요';
 // mood timeline (oldest on the left)
 const W=600, tot={}, H=P.history||[];
 let html=H.length&&H[0].start<W?'<div style="flex:'+(W-H[0].start)+' 0 0"></div>':'';
 html+=H.map(h=>{const d=h.start-h.end, k=mk(h.mood); tot[k]=(tot[k]||0)+d;
  return '<div title="'+MOOD[k]+'" style="flex:'+d+' 0 0;background:var(--'+k+')"></div>';}).join('');
 $('tl').innerHTML=html;
 const sum=Object.values(tot).reduce((a,b)=>a+b,0)||1;
 $('tlg').innerHTML=Object.entries(tot).sort((a,b)=>b[1]-a[1]).map(([k,v])=>
  '<span><i style="background:var(--'+k+')"></i>'+MOOD[k]+' '+Math.round(v/sum*100)+'%</span>').join('');
}
$('gstart').onclick=()=>post('/pet/game/'+($('gstart').dataset.on?'stop':'start'));
const PBTN=[['hello','👋 인사'],['high_five','✋ 하이파이브'],['pet','🤚 쓰담쓰담'],['praise','👍 칭찬'],['happy','😊 기쁨'],['shy','☺️ 부끄럼'],
 ['surprised','😮 놀람'],['scared','👊 위협'],['call','🥺 놀아줘'],['sulk','😤 삐짐'],['morning','☀️ 아침'],['night','🌙 잘 자'],
 ['come','🐶 이리 와'],['follow','👣 따라와'],['nap','😴 낮잠'],['wake','🌤️ 깨우기'],['exp','⭐ EXP +10']];
$('walkstop').onclick=()=>post('/pet/stop_follow');
$('pbtns').innerHTML=PBTN.map(b=>'<button data-e="'+b[0]+'">'+b[1]+'</button>').join('');
$('pbtns').onclick=e=>{const k=e.target.dataset.e; if(k) post('/pet/'+k);};
const MBTN=['neutral','happy','love','shy','bored','sleepy','sulky','scared'];
$('mbtns').innerHTML=MBTN.map(m=>'<button data-m="'+m+'">'+MOOD[m]+'</button>').join('');
$('mbtns').onclick=e=>{const k=e.target.dataset.m; if(k) post('/pet/mood/'+k);};
setInterval(()=>{ if(!$('face').closest('.hide')) $('face').src='/face.png?'+Date.now(); },200);
let synced=false;
async function tick(){
 try{
  const s=await (await fetch('/state')).json(), S=s.scene, P=s.pet, mode=s.mode, watch=mode==='watch';
  ['hand','watch','pet'].forEach(m=>$('m-'+m).className=mode===m?'on':'');
  document.querySelectorAll('.hand-only').forEach(e=>e.classList.toggle('hide',mode!=='hand'));
  document.querySelectorAll('.watch-only').forEach(e=>e.classList.toggle('hide',!watch));
  document.querySelectorAll('.pet-only').forEach(e=>e.classList.toggle('hide',mode!=='pet'));
  document.querySelectorAll('.nowatch').forEach(e=>e.classList.toggle('hide',watch));
  document.querySelectorAll('.moff').forEach(e=>e.style.display=s.motion_enabled?'none':'block');
  if(!synced){$('motion').checked=s.motion_enabled;$('sound').checked=s.sound;$('speed').value=s.speed;$('spv').textContent=s.speed;
   $('th').value=Math.round(S.threshold*100);$('thv').textContent=Math.round(S.threshold*100)+'%';synced=true;}
  $('party').style.display=s.celebrating?'flex':'none';
  moodbar(s,P);
  $('fps').textContent=$('fps2').textContent=s.fps+' fps';
  if(mode==='pet'){
   $('mood').textContent=MOOD[P.face]||P.face;
   $('hearts').textContent='❤️'.repeat(Math.min(P.level,5))+'🤍'.repeat(Math.max(0,5-P.level));
   $('aff').textContent='애정도 '+P.affection+'점 · 하트 '+Math.min(P.level,5)+'개'+(P.sulking?' · 지금 삐져 있어요 (인사·칭찬으로 달래 주세요)':'');
   $('behav').textContent=MOOD[P.mood]+' → '+P.behavior+(P.nap_left>0?' (낮잠 '+P.nap_left+'초 남음)':P.mood_left>0?' ('+P.mood_left+'초 남음)':'');
   $('walk').classList.toggle('hide',!P.follow.active); $('walkmsg').textContent=P.follow.message;
   $('lastmove').textContent=P.last_move?'마지막 행동 '+P.last_move.time+' · '+P.last_move.text:'';
   document.querySelectorAll('#mbtns button').forEach(b=>b.classList.toggle('on',b.dataset.m===P.mood));
   $('pev').innerHTML=P.events.map(e=>'<tr><td class="mut">'+e.time+'</td><td>'+e.text+'</td></tr>').join('');
   const G=P.game, st=G.stats;
   $('gmsg').textContent=G.message||'✌️ 가위를 1초 들고 있으면 같이 놀아요';
   $('gmsg').className='msg'+(G.active&&G.phase==='countdown'?' countdown':'');
   $('gscore').textContent=G.score[0]+' : '+G.score[1];
   $('grobot').textContent=G.active&&G.robot_hand?HAND[G.robot_hand]:'🤖';
   $('guser').textContent=G.active&&G.user_hand?HAND[G.user_hand]:(G.active&&s.status.label in HAND&&G.phase!=='invite'?HAND[s.status.label]:'🙂');
   $('gstart').textContent=G.active?'⏹ 그만하기':'🎮 가위바위보 하자!';
   $('gstart').className='btn'+(G.active?' stop':''); if(G.active) $('gstart').dataset.on=1; else delete $('gstart').dataset.on;
   $('gstats').textContent=st.played?'지금까지 '+st.played+'판 · 로봇 '+st.robot+'승 · 나 '+st.user+'승':'';
  }
  if(!watch){
   $('now').textContent=s.label_ko;
   $('prog').style.width=((s.status.progress||0)*100)+'%';
   $('fingers').innerHTML=FN.map((n,i)=>'<span class="'+(s.fingers&&s.fingers[i]?'on':'')+'">'+n+'</span>').join('');
  }
  if(mode==='hand'){
   $('cmd').textContent=CMD[s.command]; $('cmd').className='cmd '+s.command;
   ['scissors','paper','rock'].forEach(g=>$('g-'+g).className=s.status.label===g?'on':'');
   $('hist').innerHTML=s.history.map(h=>'<tr><td class="mut">'+h.time+'</td><td>'+(WHY[h.reason]||h.reason)+'</td><td>'+CMD[h.command]+'</td></tr>').join('');
  }
  if(watch){
   const pct=Math.round(S.score*100);
   $('sc').textContent=S.ready?'골/홈런 점수 '+pct+'%':(S.error||'AI 모델 불러오는 중…');
   $('scbar').style.width=pct+'%'; $('scbar').style.background=S.score>=S.threshold?'var(--gold)':'var(--acc)';
   $('thmark').style.left=(S.threshold*100)+'%';
   $('top').textContent=S.top?'가장 비슷한 장면: '+S.top:'';
   const pts=S.scores.map((v,i)=>i+','+(1-v).toFixed(3)).join(' ');
   $('spark').innerHTML='<line x1="0" x2="60" y1="'+(1-S.threshold)+'" y2="'+(1-S.threshold)+'" stroke="var(--stop)" stroke-width="0.02"/>'+
     '<polyline fill="none" stroke="var(--acc)" stroke-width="0.04" points="'+pts+'"/>';
   $('sstat').textContent=S.cooldown>0?'다음 세레머니까지 '+S.cooldown.toFixed(0)+'초':'';
   $('ev').innerHTML=S.events.map(e=>'<tr><td class="mut">'+e.time+'</td><td>'+Math.round(e.score*100)+'%</td><td class="mut">'+e.scene+'</td></tr>').join('');
  }
 }catch(e){}
 setTimeout(tick,250);
}
tick();
</script></body></html>"""




if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--no-robot", action="store_true")
    args = ap.parse_args()

    if not args.no_robot:
        try:
            from robot import Robot
            robot = Robot()
            robot.stop()
        except Exception as e:  # keep the web UI usable without the motor board
            print("robot unavailable:", e)
    ctrl = Controller(robot)  # motion starts disabled; enable from the web page
    scene = SceneDetector(on_trigger=celebrate)
    face = Face()
    pet = Companion(robot, face, motion_on=lambda: ctrl.motion_enabled, sound_on=lambda: sound["on"],
                    active=lambda: state["mode"] == "pet")
    threading.Thread(target=camera_loop, args=(args.cam,), daemon=True).start()
    try:
        app.run(host="0.0.0.0", port=args.port, threaded=True)
    finally:
        if robot:
            robot.stop()
