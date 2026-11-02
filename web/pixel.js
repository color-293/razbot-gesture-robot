/* Pixel 라즈봇: the robot's OLED face, drawn pixel by pixel on a small canvas (48x32), so the app shows the same
   kind of face the real robot wears - but alive: it blinks, follows your finger / mouse / real hand with its eyes,
   and reacts when touched.

   Pixel.mount(canvas, {face: () => name, gaze: () => ({x, y}) | null})   animate a face
   Pixel.touch(el, {poke, stroke, dizzy})                                  tap / rub / tap-too-often detection
   Pixel.pointerGaze(el)                                                    -> () => gaze toward the pointer (or null)
   faces: neutral happy love shy bored sleepy sulky scared surprised dizzy squeeze levelup
*/
window.Pixel = (function () {
  const W = 48, H = 32, ON = '#7dffcf', PINK = '#ff8fc0', BLUE = '#8fd8ff', GOLD = '#ffd166';

  function P(c, x, y, col) {
    x = Math.round(x); y = Math.round(y);
    if (x < 0 || y < 0 || x >= W || y >= H) return;
    c.fillStyle = col || ON; c.fillRect(x, y, 1, 1);
  }
  function R(c, x, y, w, h, col) { c.fillStyle = col || ON; c.fillRect(Math.round(x), Math.round(y), w, h); }
  function box(c, cx, cy, w, h, col) {             // rounded block eye
    const x = Math.round(cx - w / 2), y = Math.round(cy - h / 2);
    R(c, x, y, w, h, col);
    if (w > 3 && h > 3) [[x, y], [x + w - 1, y], [x, y + h - 1], [x + w - 1, y + h - 1]].forEach(([a, b]) => c.clearRect(a, b, 1, 1));
  }
  function arcUp(c, cx, cy, r, th, col) {          // ∩ : happy eyes
    for (let x = -r; x <= r; x++) { const y = Math.round(Math.sqrt(r * r - x * x)); for (let k = 0; k < th; k++) P(c, cx + x, cy - y + k, col); }
  }
  function smile(c, cx, cy, r, col, flip) {        // ∪ mouth (flip: ∩ frown)
    for (let x = -r; x <= r; x++) { const y = Math.round(Math.sqrt(r * r - x * x) * 0.55); P(c, cx + x, flip ? cy - y : cy + y, col); }
  }
  function ring(c, cx, cy, r, th, col) {
    for (let y = -r - 1; y <= r + 1; y++) for (let x = -r - 1; x <= r + 1; x++) {
      const d = Math.hypot(x, y); if (d <= r + 0.45 && d >= r - th + 0.45) P(c, cx + x, cy + y, col);
    }
  }
  function heart(c, cx, cy, s, col) {
    for (let y = -s; y <= s; y++) for (let x = -s; x <= s; x++) {
      const u = x / s * 1.25, v = -y / s * 1.25 + 0.25;
      if (Math.pow(u * u + v * v - 1, 3) - u * u * v * v * v <= 0) P(c, cx + x, cy + y, col);
    }
  }
  function line(c, x0, y0, x1, y1, col) {
    const n = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0)) || 1;
    for (let i = 0; i <= n; i++) P(c, x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n, col);
  }
  function zee(c, x, y, col) { [[0, 0], [1, 0], [2, 0], [1, 1], [0, 2], [1, 2], [2, 2]].forEach(([a, b]) => P(c, x + a, y + b, col)); }
  function wavy(c, cx, cy) { for (let x = -4; x <= 4; x++) P(c, cx + x, cy + (x & 1 ? 1 : 0)); }
  function sparkle(c, x, y, on, col) { if (!on) return; P(c, x, y, col); P(c, x - 1, y, col); P(c, x + 1, y, col); P(c, x, y - 1, col); P(c, x, y + 1, col); }

  function draw(c, f, s) {
    c.clearRect(0, 0, W, H);
    const t = s.t || 0, gx = Math.max(-1, Math.min(1, s.x || 0)), gy = Math.max(-1, Math.min(1, s.y || 0));
    const ox = Math.round(gx * 4), oy = Math.round(gy * 2);
    const L = 15 + ox, Rx = 33 + ox, Y = 13 + oy, M = 24 + Math.round(gx * 2);
    const blink = (t % 4.3) < 0.13;
    switch (f) {
      case 'happy': case 'levelup': {
        const b = Math.round(Math.sin(t * 7));
        arcUp(c, L, Y + 3 + b, 6, 2); arcUp(c, Rx, Y + 3 + b, 6, 2); smile(c, M, 23, 4);
        if (f === 'levelup') { const k = Math.floor(t * 6); sparkle(c, 5, 6, k % 2, GOLD); sparkle(c, 42, 5, (k + 1) % 2, GOLD); sparkle(c, 44, 24, k % 2, GOLD); sparkle(c, 4, 25, (k + 1) % 2, GOLD); }
        break;
      }
      case 'love': {
        const p = Math.sin(t * 6) > 0 ? 8 : 7;
        heart(c, L, Y, p, PINK); heart(c, Rx, Y, p, PINK); smile(c, M, 25, 3);
        break;
      }
      case 'shy':
        arcUp(c, L, Y + 3, 5, 2); arcUp(c, Rx, Y + 3, 5, 2);
        [L - 4, L - 2, L, Rx, Rx + 2, Rx + 4].forEach(x => { P(c, x, Y + 7, PINK); P(c, x + 1, Y + 8, PINK); });
        R(c, M - 1, 25, 3, 1);
        break;
      case 'bored':
        box(c, L + 2, Y + 3, 9, 4); box(c, Rx + 2, Y + 3, 9, 4); R(c, L - 3, Y - 1, 12, 1); R(c, Rx - 3, Y - 1, 12, 1);
        R(c, M - 2, 25, 5, 1);
        break;
      case 'sleepy': {
        R(c, L - 5, Y + 3, 10, 2); R(c, Rx - 5, Y + 3, 10, 2); ring(c, M, 25, 1, 1);
        const k = (t * 3) % 10; zee(c, 41, 9 - k * 0.6); if (k > 4) zee(c, 44, 6 - (k - 4) * 0.5);
        break;
      }
      case 'sulky':
        [[L, 1], [Rx, -1]].forEach(([x, side]) => {
          box(c, x, Y + 1, 10, 11);
          for (let j = 0; j < 10; j++) { const cut = Math.floor((side > 0 ? j : 9 - j) * 0.6); c.clearRect(Math.round(x - 5) + j, Math.round(Y + 1 - 5.5), 1, cut + 1); }
        });
        smile(c, M, 26, 3, null, true);
        break;
      case 'scared': case 'squeeze': {
        const j = f === 'scared' ? (Math.floor(t * 18) % 2 ? 1 : -1) : 0;
        [0, 1].forEach(d => {
          line(c, L - 4 + j, Y - 5 + d, L + 4 + j, Y + d); line(c, L + 4 + j, Y + d, L - 4 + j, Y + 5 + d);
          line(c, Rx + 4 + j, Y - 5 + d, Rx - 4 + j, Y + d); line(c, Rx - 4 + j, Y + d, Rx + 4 + j, Y + 5 + d);
        });
        if (f === 'scared') { P(c, 41, 3, BLUE); R(c, 40, 4, 3, 2, BLUE); P(c, 41, 6, BLUE); wavy(c, M, 25); }
        else ring(c, M, 25, 2, 1);
        break;
      }
      case 'surprised':
        ring(c, L, Y, 7, 2); ring(c, Rx, Y, 7, 2); R(c, L - 1 + Math.round(gx * 2), Y - 1, 3, 3); R(c, Rx - 1 + Math.round(gx * 2), Y - 1, 3, 3);
        ring(c, M, 27, 2, 1);
        break;
      case 'dizzy': {
        ring(c, L, Y, 7, 1); ring(c, L, Y, 4, 1); P(c, L, Y); ring(c, Rx, Y, 7, 1); ring(c, Rx, Y, 4, 1); P(c, Rx, Y); wavy(c, M, 27);
        const a = t * 5; sparkle(c, 24 + Math.cos(a) * 14, 4 + Math.sin(a) * 2, 1, GOLD);
        break;
      }
      default: {                                   // neutral: block eyes that look around and blink
        const h = blink ? 2 : 13;
        box(c, L, Y, 9, h); box(c, Rx, Y, 9, h); R(c, M - 2, 26, 4, 1);
      }
    }
  }

  function mount(canvas, opts) {
    canvas.width = W; canvas.height = H;
    const c = canvas.getContext('2d'); let last = 0; const t0 = performance.now() - 1000 - Math.random() * 3000;   // never start mid-blink
    function loop(ts) {
      if (ts - last > 66) {                         // ~15 fps: it is a pixel screen after all
        last = ts;
        const g = (opts.gaze && opts.gaze()) || { x: Math.sin(ts / 1700) * 0.5, y: 0 };
        draw(c, opts.face(), { t: (ts - t0) / 1000, x: g.x, y: g.y });
      }
      requestAnimationFrame(loop);
    }
    requestAnimationFrame(loop);
  }

  function pointerGaze(el) {
    let px = null, py = null, at = 0;
    window.addEventListener('pointermove', e => { px = e.clientX; py = e.clientY; at = performance.now(); }, { passive: true });
    return () => {
      if (px === null || performance.now() - at > 2500) return null;
      const r = el.getBoundingClientRect();
      return { x: (px - (r.left + r.width / 2)) / (window.innerWidth / 2), y: (py - (r.top + r.height / 2)) / (window.innerHeight / 2) };
    };
  }

  function touch(el, on) {                          // tap = poke, rub side to side = stroke, 5 taps in 3 s = dizzy
    let down = null, dir = 0, turns = 0, lastX = 0, taps = [];
    el.addEventListener('pointerdown', e => { down = { x: e.clientX, y: e.clientY, t: performance.now() }; dir = 0; turns = 0; lastX = e.clientX; el.setPointerCapture(e.pointerId); });
    el.addEventListener('pointermove', e => {
      if (!down) return;
      const dx = e.clientX - lastX;
      if (Math.abs(dx) > 12) { const d = Math.sign(dx); if (dir && d !== dir) turns++; dir = d; lastX = e.clientX; }
      if (turns >= 3) { turns = -99; on.stroke && on.stroke(); }
    });
    el.addEventListener('pointerup', e => {
      if (!down) return;
      const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y), quick = performance.now() - down.t < 350;
      if (turns >= 0 && moved < 10 && quick) {
        const now = performance.now(); taps = taps.filter(t => now - t < 3000); taps.push(now);
        if (taps.length >= 5) { taps = []; on.dizzy && on.dizzy(); } else on.poke && on.poke();
      }
      down = null;
    });
  }

  return { mount, touch, pointerGaze, W, H };
})();
