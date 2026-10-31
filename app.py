"""Flask web UI: hand-gesture driving, goal / home-run celebration and companion (emotion) mode."""
import argparse
import threading
import time

import cv2
from flask import Flask, Response, jsonify, render_template_string

from companion import Companion
from control import Controller
from face import Face
from gesture import GestureDetector, draw
from scene import SceneDetector

LABEL_KO = {"rock": "주먹 ✊", "paper": "보 ✋", "scissors": "가위 ✌️", "thumbs_up": "최고 👍",
            "unknown": "알 수 없음", None: "손 없음"}

app = Flask(__name__)
state = {"frame": None, "status": {}, "fps": 0.0, "fingers": None, "mode": "hand"}
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
    s["sound"] = sound["on"]
    s["celebrating"] = celebrating.is_set()
    s["celebrations"] = celebrations["count"]
    s["label_ko"] = LABEL_KO.get(s["status"].get("label"), "?")
    return jsonify(s)


@app.route("/face.png")
def face_png():
    return Response(face.png(), mimetype="image/png", headers={"Cache-Control": "no-store"})


@app.route("/pet/<event>", methods=["POST"])
def pet_event(event):
    return jsonify(ok=pet.trigger(event))


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


@app.route("/")
def index():
    return render_template_string(PAGE)


PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>라즈봇 컨트롤</title>
<style>
 :root{--bg:#f6f7f9;--card:#fff;--fg:#1d2330;--mut:#6b7280;--acc:#2563eb;--fwd:#16a34a;--back:#d97706;--stop:#dc2626;--gold:#eab308}
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
</style></head><body>
<header><h1>🤖 라즈봇</h1>
 <div class="tabs"><button id="m-hand">✋ 손 조종</button><button id="m-watch">⚽ 경기 관람</button><button id="m-pet">🐶 교감</button></div>
 <div class="ctl">
  <label>속도 <input type="range" id="speed" min="30" max="255" step="5"> <span id="spv"></span></label>
  <label><input type="checkbox" id="sound"> 소리</label>
  <label><input type="checkbox" id="motion"> 로봇 움직이기</label></div></header>
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
  <div class="card pet-only"><div class="mut">로봇 얼굴 (OLED)</div>
   <img id="face" class="oled" alt="로봇 얼굴">
   <div style="display:flex;justify-content:space-between;align-items:baseline;margin-top:8px">
    <div class="now" id="mood">-</div><div id="hearts" style="font-size:18px"></div></div>
   <div class="mut" id="aff"></div>
   <div class="behav"><div class="mut">지금 기분에 따른 행동</div><div id="behav" style="font-size:16px;font-weight:600;margin-top:2px"></div>
    <div class="mut" id="lastmove"></div></div>
   <div class="off moff">로봇 움직이기가 꺼져 있어요 (표정·소리만)</div>
   <div class="mut" style="margin:10px 0 6px">기분 바꾸기</div>
   <div class="pbtns" id="mbtns"></div></div>
  <div class="card pet-only"><div class="mut">이렇게 놀아 주세요</div>
   <table class="howto">
    <tr><td>👋 손을 빠르게 좌우로 흔들기</td><td>인사 (아침/낮/밤)</td></tr>
    <tr><td>✋ 손바닥 펴고 가만히</td><td>하이파이브</td></tr>
    <tr><td>🤚 손을 천천히 크게 좌우로</td><td>쓰담쓰담</td></tr>
    <tr><td>👍 엄지 척</td><td>칭찬 → 하트, 애정도↑</td></tr>
    <tr><td>👊 주먹을 휘두르거나 들이밀기</td><td>주춤 뒷걸음질 → 한동안 벌벌, 애정도↓</td></tr>
    <tr><td>🙈 한동안 안 놀아 주기</td><td>심심 → 놀아줘 → 삐짐</td></tr>
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
const MOOD={neutral:'😐 평온',happy:'😊 기쁨',sleepy:'😴 졸림',bored:'🥱 심심',surprised:'😮 놀람',love:'🥰 사랑',shy:'☺️ 부끄럼',sulky:'😤 삐짐',scared:'😨 무서움'};
const PBTN=[['hello','👋 인사'],['high_five','✋ 하이파이브'],['pet','🤚 쓰담쓰담'],['praise','👍 칭찬'],['happy','😊 기쁨'],['shy','☺️ 부끄럼'],
 ['surprised','😮 놀람'],['scared','👊 위협'],['call','🥺 놀아줘'],['sulk','😤 삐짐'],['morning','☀️ 아침'],['night','🌙 잘 자']];
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
  $('fps').textContent=$('fps2').textContent=s.fps+' fps';
  if(mode==='pet'){
   $('mood').textContent=MOOD[P.face]||P.face;
   $('hearts').textContent='❤️'.repeat(Math.min(P.level,5))+'🤍'.repeat(Math.max(0,5-P.level));
   $('aff').textContent='애정도 '+P.affection+'점 · 레벨 '+P.level+(P.sulking?' · 지금 삐져 있어요 (인사·칭찬으로 달래 주세요)':'');
   $('behav').textContent=MOOD[P.mood]+' → '+P.behavior+(P.mood_left>0?' ('+P.mood_left+'초 남음)':'');
   $('lastmove').textContent=P.last_move?'마지막 행동 '+P.last_move.time+' · '+P.last_move.text:'';
   document.querySelectorAll('#mbtns button').forEach(b=>b.classList.toggle('on',b.dataset.m===P.mood));
   $('pev').innerHTML=P.events.map(e=>'<tr><td class="mut">'+e.time+'</td><td>'+e.text+'</td></tr>').join('');
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
