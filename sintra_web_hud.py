#!/usr/bin/env python3
"""Web HUD for the live sky-catalog loop.

Same process, same continuous cycle, same terminal lines. The page adds
custody, space-weather, and error stats the terminal table does not chart.
Stdlib only, so the locked-down image does not gain a dependency.
"""

import json
import math
import os
import re
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
HOST = os.environ.get("SINTRA_HUD_HOST", "0.0.0.0")
PORT = int(os.environ.get("SINTRA_HUD_PORT", "8080"))
PNG_NAME = "sintra_live_norad_intercept_hud.png"
WEB_PNG_NAME = "sintra_live_norad_intercept_hud_web.png"
PNG_SIG = b"\x89PNG\r\n\x1a\n"

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SINTRA X HUD</title>
<style>
  :root {
    --bg: #050505;
    --ink: #f4f4f4;
    --dim: #8a8a8a;
    --line: #2a2a2a;
    --red: #ff3b30;
    --ice: #d7e4ff;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; min-height: 100%; background: var(--bg); color: var(--ink); }
  body {
    font-family: "Segoe UI", Helvetica, Arial, sans-serif;
    letter-spacing: 0.04em;
    background-image:
      linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px);
    background-size: 56px 56px;
  }
  header {
    display: flex; align-items: center; gap: 16px;
    padding: 14px 18px; border-bottom: 1px solid var(--line);
    background: rgba(0,0,0,0.8);
  }
  .xmark { width: 28px; height: 28px; position: relative; flex: 0 0 28px; }
  .xmark:before, .xmark:after {
    content: ""; position: absolute; left: 13px; top: 0;
    width: 2px; height: 28px; background: #fff;
  }
  .xmark:before { transform: rotate(42deg); }
  .xmark:after { transform: rotate(-42deg); }
  h1 { margin: 0; font-size: 15px; font-weight: 650; letter-spacing: 0.22em; }
  h1 span { color: var(--dim); font-weight: 450; letter-spacing: 0.16em; }
  .grow { flex: 1; }
  .pill {
    border: 1px solid var(--line); padding: 6px 10px;
    font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase;
  }
  .pill.live { border-color: #fff; }
  .pill.down { border-color: var(--red); color: var(--red); }
  main {
    display: grid;
    grid-template-columns: 280px 1fr 300px;
    grid-template-rows: 220px auto auto auto;
    gap: 10px;
    padding: 10px;
    height: auto;
    min-height: calc(100vh - 57px);
  }
  .card {
    position: relative;
    border: 1px solid var(--line);
    background: rgba(0,0,0,0.78);
    padding: 12px 14px;
    min-height: 0;
    overflow: hidden;
  }
  .card:before, .card:after {
    content: ""; position: absolute; width: 9px; height: 9px; border: 1px solid #fff;
  }
  .card:before { top: -1px; left: -1px; border-right: 0; border-bottom: 0; }
  .card:after { right: -1px; bottom: -1px; border-left: 0; border-top: 0; }
  .k {
    font-size: 10px; letter-spacing: 0.2em; text-transform: uppercase; color: var(--dim);
    margin: 0 0 8px;
  }
  .sky { grid-column: 2; grid-row: 1; padding: 8px; }
  .sky canvas, .spark canvas { width: 100%; height: calc(100% - 22px); display: block; }
  .wx { grid-column: 1; grid-row: 1; }
  .active { grid-column: 3; grid-row: 1; }
  .table { grid-column: 1 / span 2; grid-row: 2; overflow: auto; }
  .stats { grid-column: 3; grid-row: 2; overflow: auto; }
  .shot { grid-column: 1 / -1; grid-row: 3; overflow: visible; }
  .logs { grid-column: 1 / -1; grid-row: 4; min-height: 220px; }
  #stack { display: flex; flex-direction: column; gap: 18px; }
  #stack canvas {
    display: block;
    width: 100%;
    height: auto;
    background: #070a12;
  }
  #shot {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
    pointer-events: none;
  }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #1c1c1c; white-space: nowrap; }
  th { color: var(--dim); font-weight: 500; font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; }
  tr.active-row td { background: #111; }
  .num { font-variant-numeric: tabular-nums; font-family: ui-monospace, Menlo, Consolas, monospace; }
  .wx .row, .active .row, .stats .row {
    display: flex; justify-content: space-between; gap: 12px;
    font-size: 12px; padding: 3px 0; border-bottom: 1px solid #161616;
  }
  .wx .row b, .active .row b, .stats .row b {
    font-weight: 500; font-variant-numeric: tabular-nums;
    font-family: ui-monospace, Menlo, Consolas, monospace;
  }
  .big { font-size: 28px; letter-spacing: 0.08em; margin: 4px 0 8px; }
  .klass { font-size: 11px; letter-spacing: 0.14em; }
  .klass.debris { color: var(--red); }
  .klass.station { color: #fff; }
  .klass.payload { color: var(--ice); }
  pre {
    margin: 0; height: 220px; overflow: auto;
    font: 11px/1.45 ui-monospace, Menlo, Consolas, monospace;
    color: #cfcfcf; white-space: pre-wrap; word-break: break-word;
  }
  .empty { color: var(--dim); font-size: 12px; }
  @media (max-width: 1100px) {
    main { grid-template-columns: 1fr; grid-template-rows: auto; height: auto; }
    .sky, .wx, .active, .table, .stats, .logs, .shot { grid-column: 1; grid-row: auto; min-height: 180px; }
    .shot, .logs { min-height: 0; }
  }
</style>
</head>
<body>
<header>
  <div class="xmark" aria-hidden="true"></div>
  <h1>SINTRA <span>X HUD</span></h1>
  <div class="grow"></div>
  <div class="pill" id="cycle">CYCLE —</div>
  <div class="pill" id="phase">BOOT</div>
  <div class="pill" id="feed">FEED</div>
  <div class="pill" id="clock">—</div>
</header>
<main>
  <section class="card wx">
    <p class="k">Space weather</p>
    <div id="wx"><p class="empty">Waiting for the cycle.</p></div>
  </section>
  <section class="card sky">
    <p class="k">X reticle · sub-satellite</p>
    <canvas id="sky" width="900" height="240"></canvas>
  </section>
  <section class="card active">
    <p class="k">Active track</p>
    <div id="active"><p class="empty">No object in the sweep yet.</p></div>
    <canvas id="spark" width="280" height="72"></canvas>
  </section>
  <section class="card table">
    <p class="k">Catalog · same sweep as the terminal</p>
    <div id="table"></div>
  </section>
  <section class="card stats">
    <p class="k">Dashboard</p>
    <div id="stats"></div>
  </section>
  <section class="card shot">
    <p class="k">Terminal snapshot</p>
    <div id="stack"></div>
    <img id="shot" alt="Latest terminal HUD PNG" width="1200" height="720">
    <p class="empty" id="shot-wait">PNG appears after the first cycle saves.</p>
  </section>
  <section class="card logs">
    <p class="k">Terminal log</p>
    <pre id="logs"></pre>
  </section>
</main>
<script>
const $ = (id) => document.getElementById(id);
function n(v, d) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  return Number(v).toFixed(d);
}
function klassOf(name) {
  const c = String(name || "").toUpperCase();
  if (c.includes("DEBRIS")) return "debris";
  if (c.includes("STATION")) return "station";
  return "payload";
}
function row(label, value) {
  const d = document.createElement("div");
  d.className = "row";
  const s = document.createElement("span");
  s.textContent = label;
  const b = document.createElement("b");
  b.textContent = value;
  d.append(s, b);
  return d;
}
function mean(rows, key) {
  if (!rows.length) return null;
  return rows.reduce((a, r) => a + Number(r[key] || 0), 0) / rows.length;
}
function render(s) {
  const w = s.weather || {};
  const cat = s.catalog || [];
  const sum = s.summary || [];
  const act = s.active;
  $("cycle").textContent = "CYCLE " + String(s.cycle || 0).padStart(2, "0");
  $("phase").textContent = (s.phase || "boot").replaceAll("-", " ");
  $("clock").textContent = s.server_time || "—";
  const feed = $("feed");
  const live = !!(w.live);
  feed.textContent = w.status ? (live ? "LIVE" : "FALLBACK") : "FEED";
  feed.className = "pill " + (w.status ? (live ? "live" : "down") : "");

  const wx = $("wx");
  wx.replaceChildren();
  if (!w.status) wx.append(Object.assign(document.createElement("p"), {className:"empty", textContent:"Waiting for NOAA."}));
  else {
    ["Bx nT", n(w.bx, 2), "By nT", n(w.by, 2), "Bz nT", n(w.bz, 2), "|B| nT", n(w.bt, 2),
     "Wind km/s", n(w.speed, 1), "Density", n(w.density, 1), "Temp K", n(w.temperature, 0),
     "Omega rad/s", n(w.omega_i, 1), "Anisotropy", n(w.anisotropy, 2) + "x",
     "Bz sense", w.bz < 0 ? "SOUTHWARD" : "NORTHWARD",
     "Epoch", w.timestamp_utc || "—", "Hash", w.hash || "—"].forEach((_, i, arr) => {
      if (i % 2) return;
      wx.append(row(arr[i], arr[i + 1]));
    });
  }

  const active = $("active");
  active.replaceChildren();
  if (!act) active.append(Object.assign(document.createElement("p"), {className:"empty", textContent:"No object in the sweep yet."}));
  else {
    const title = document.createElement("div");
    title.className = "big";
    title.textContent = act.norad_id;
    const name = document.createElement("div");
    name.className = "klass " + klassOf(act.klass);
    name.textContent = act.name + " · " + (act.klass || "TRACK");
    active.append(title, name);
    [
      ["Frame", act.frame + " / " + act.frames],
      ["SINTRA km", n(act.e_sin, 3)],
      ["IMM km", n(act.e_imm, 1)],
      ["PF km", n(act.e_pf, 1)],
      ["V track", n(act.v_track, 1)],
      ["V true", n(act.v_true, 1)],
      ["sigma km", n(act.sigma_km, 2)],
      ["truth km", n(act.sigma_true_km, 2)],
      ["lambda", n(act.lambda, 3)],
      ["Mass idx", n(act.mass, 1)]
    ].forEach(([a, b]) => active.append(row(a, b)));
  }
  drawSpark(act);

  const done = {};
  sum.forEach((r) => { done[r.norad_id] = r; });
  const table = document.createElement("table");
  const head = document.createElement("tr");
  ["NORAD", "Object", "Alt", "Class", "SINTRA", "IMM", "PF", "sigma", "Mass"].forEach((h) => {
    const th = document.createElement("th");
    th.textContent = h;
    head.append(th);
  });
  table.append(head);
  cat.forEach((t) => {
    const fin = done[t.norad_id];
    const tr = document.createElement("tr");
    if (act && act.norad_id === t.norad_id) tr.className = "active-row";
    const cells = [
      t.norad_id,
      t.name,
      n(t.altitude_km, 1),
      fin ? fin.klass : (act && act.norad_id === t.norad_id ? act.klass : "PENDING"),
      fin ? n(fin.rmse_sin, 3) : (act && act.norad_id === t.norad_id ? n(act.e_sin, 3) : "—"),
      fin ? n(fin.rmse_imm, 1) : (act && act.norad_id === t.norad_id ? n(act.e_imm, 1) : "—"),
      fin ? n(fin.rmse_pf, 1) : (act && act.norad_id === t.norad_id ? n(act.e_pf, 1) : "—"),
      fin ? n(fin.blind_sigma_km, 2) : n(t.true_sigma_km, 2),
      fin ? n(fin.mass, 1) : "—"
    ];
    cells.forEach((c, i) => {
      const td = document.createElement("td");
      td.textContent = c;
      if (i !== 1 && i !== 3) td.className = "num";
      if (i === 3) td.className = "klass " + klassOf(c);
      tr.append(td);
    });
    table.append(tr);
  });
  $("table").replaceChildren(cat.length ? table : Object.assign(document.createElement("p"), {className:"empty", textContent:"Catalog not in yet."}));

  const sin = mean(sum, "rmse_sin");
  const imm = mean(sum, "rmse_imm");
  const pf = mean(sum, "rmse_pf");
  const alts = cat.map((t) => Number(t.altitude_km)).filter((v) => !Number.isNaN(v));
  const mix = {station: 0, payload: 0, debris: 0};
  sum.forEach((r) => { mix[klassOf(r.klass)] += 1; });
  const stats = $("stats");
  stats.replaceChildren();
  [
    ["Custody", sum.length + " / " + (cat.length || 7)],
    ["Frames", String(s.frames || 0)],
    ["Mean SINTRA km", n(sin, 3)],
    ["Mean IMM km", n(imm, 1)],
    ["Mean PF km", n(pf, 1)],
    ["IMM / SINTRA", sin ? n(imm / Math.max(sin, 1e-9), 1) + "x" : "—"],
    ["Stations", String(mix.station)],
    ["Payloads", String(mix.payload)],
    ["Debris", String(mix.debris)],
    ["Alt span km", alts.length ? n(Math.min(...alts), 0) + " – " + n(Math.max(...alts), 0) : "—"],
    ["Background", (s.background && s.background.name) || "—"],
    ["Bg hash", (s.background && s.background.hash) || "—"],
    ["PNG", s.png || "—"]
  ].forEach(([a, b]) => stats.append(row(a, b)));

  const pre = $("logs");
  const stick = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 48;
  pre.textContent = (s.logs || []).map((l) => l.t + "  " + l.line).join("\\n");
  if (stick) pre.scrollTop = pre.scrollHeight;

  const shot = $("shot");
  const version = s.png_version || (s.png ? "ready" : "");
  if (s.png && version && shot.dataset.v !== version) {
    shot.dataset.v = version;
    shot.src = "/hud.png?v=" + encodeURIComponent(version);
    $("shot-wait").hidden = true;
  }
  drawSky(cat, act);
}
function paintStack(img) {
  const stack = $("stack");
  const nw = img.naturalWidth;
  const nh = img.naturalHeight;
  if (!nw || !nh) return;
  const panels = [
    ["1. Live intercept", 0, 0, 0.544, 0.52],
    ["3. Track error", 0.544, 0, 0.456, 0.52],
    ["2. Kernel gate", 0, 0.52, 0.544, 0.48],
    ["4. Mass fingerprint", 0.544, 0.52, 0.456, 0.48]
  ];
  stack.replaceChildren();
  panels.forEach((p) => {
    const label = document.createElement("p");
    label.className = "k";
    label.textContent = p[0];
    const canvas = document.createElement("canvas");
    const sx = Math.round(p[1] * nw);
    const sy = Math.round(p[2] * nh);
    const sw = Math.max(1, Math.round(p[3] * nw));
    const sh = Math.max(1, Math.round(p[4] * nh));
    canvas.width = sw;
    canvas.height = sh;
    canvas.getContext("2d").drawImage(img, sx, sy, sw, sh, 0, 0, sw, sh);
    stack.append(label, canvas);
  });
}
function drawSky(cat, act) {
  const c = $("sky");
  const dpr = window.devicePixelRatio || 1;
  const w = c.clientWidth || 640;
  const h = c.clientHeight || 200;
  c.width = Math.floor(w * dpr);
  c.height = Math.floor(h * dpr);
  const g = c.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  g.strokeStyle = "#2a2a2a";
  g.lineWidth = 1;
  for (let lon = -180; lon <= 180; lon += 30) {
    const x = ((lon + 180) / 360) * w;
    g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke();
  }
  for (let lat = -60; lat <= 60; lat += 30) {
    const y = ((90 - lat) / 180) * h;
    g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke();
  }
  const xy = (lon, lat) => [((Number(lon) + 180) / 360) * w, ((90 - Number(lat)) / 180) * h];
  cat.forEach((t) => {
    const [x, y] = xy(t.lon, t.lat);
    const on = act && act.norad_id === t.norad_id;
    g.strokeStyle = on ? "#fff" : "#8a8a8a";
    g.lineWidth = on ? 1.6 : 1;
    const arm = on ? 16 : 5;
    g.beginPath();
    g.moveTo(x - arm, y - arm); g.lineTo(x + arm, y + arm);
    g.moveTo(x + arm, y - arm); g.lineTo(x - arm, y + arm);
    g.stroke();
    if (on) {
      g.beginPath(); g.arc(x, y, 22, 0, Math.PI * 2); g.stroke();
      g.font = "11px sans-serif";
      g.fillStyle = "#fff";
      g.fillText(String(t.norad_id), x + 26, y - 6);
    }
  });
}
function drawSpark(act) {
  const c = $("spark");
  const dpr = window.devicePixelRatio || 1;
  const w = c.clientWidth || 260;
  const h = 72;
  c.width = Math.floor(w * dpr);
  c.height = Math.floor(h * dpr);
  const g = c.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  if (!act || !(act.spark_sin || []).length) return;
  const series = [
    [act.spark_imm || [], "#ff3b30"],
    [act.spark_pf || [], "#8a8a8a"],
    [act.spark_sin || [], "#fff"]
  ];
  const yOf = (v) => {
    const c = Math.log10(Math.max(Number(v), 0.01));
    const lo = -2, hi = 3.6;
    return h - 4 - ((c - lo) / (hi - lo)) * (h - 8);
  };
  series.forEach(([pts, color]) => {
    if (!pts.length) return;
    g.beginPath();
    g.strokeStyle = color;
    g.lineWidth = color === "#fff" ? 1.8 : 1;
    pts.forEach((v, i) => {
      const x = (i / Math.max(pts.length - 1, 1)) * (w - 4) + 2;
      const y = yOf(v);
      if (i === 0) g.moveTo(x, y); else g.lineTo(x, y);
    });
    g.stroke();
  });
}
const shotEl = $("shot");
shotEl.addEventListener("load", () => {
  if (!shotEl.getAttribute("src")) return;
  paintStack(shotEl);
  $("shot-wait").hidden = true;
});
shotEl.addEventListener("error", () => {
  const wait = $("shot-wait");
  wait.hidden = false;
  wait.textContent = "Snapshot failed to load.";
});
async function tick() {
  try {
    const res = await fetch("/api/state", {cache: "no-store"});
    render(await res.json());
  } catch (err) {
    $("phase").textContent = "LINK DOWN";
  }
}
tick();
setInterval(tick, 700);
</script>
</body>
</html>
"""


class _State:
    def __init__(self):
        self.lock = threading.Lock()
        self.logs = []
        self.buf = ""
        self.data = {
            "cycle": 0,
            "phase": "booting",
            "updated": None,
            "weather": None,
            "background": None,
            "catalog": [],
            "active": None,
            "summary": [],
            "png": None,
            "png_version": None,
            "frames": 0,
        }


STATE = _State()
_started = False
_start_lock = threading.Lock()


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _touch():
    STATE.data["updated"] = _now()


def append_log_chunk(text):
    clean = ANSI.sub("", text).replace("\r", "")
    with STATE.lock:
        STATE.buf += clean
        while "\n" in STATE.buf:
            line, STATE.buf = STATE.buf.split("\n", 1)
            if not line.strip():
                continue
            STATE.logs.append(
                {"t": datetime.now(timezone.utc).strftime("%H:%M:%S"), "line": line}
            )
            if len(STATE.logs) > 400:
                del STATE.logs[: len(STATE.logs) - 400]


class _Tee:
    def __init__(self, stream):
        self.stream = stream

    def write(self, data):
        self.stream.write(data)
        try:
            append_log_chunk(data)
        except Exception:
            pass
        return len(data) if isinstance(data, str) else 0

    def flush(self):
        self.stream.flush()

    def isatty(self):
        return getattr(self.stream, "isatty", lambda: False)()

    def fileno(self):
        return self.stream.fileno()


def _output_dir():
    return os.environ.get("SINTRA_OUTPUT", os.getcwd())


def _png_path():
    return os.path.join(_output_dir(), PNG_NAME)


def _complete_png(raw):
    return (
        isinstance(raw, (bytes, bytearray))
        and len(raw) > 24
        and raw.startswith(PNG_SIG)
        and raw[-8:-4] == b"IEND"
    )


_png_lock = threading.Lock()
_png_published = {"path": None, "version": None, "bytes": None}


def _best_png_path():
    """Prefer the full snapshot so stacked panels stay sharp."""
    directory = _output_dir()
    full = os.path.join(directory, PNG_NAME)
    web = os.path.join(directory, WEB_PNG_NAME)
    if os.path.isfile(full):
        return full
    if os.path.isfile(web):
        return web
    return None


def refresh_png():
    """Publish the newest complete snapshot.

    A cycle used to clear this and set it again only for the few milliseconds
    between save and the next loop, so the page poll never requested the file.
    A save still in progress is ignored and the last good image stays up.
    """
    path = _best_png_path()
    if not path:
        return
    try:
        st = os.stat(path)
    except OSError:
        return
    if st.st_size < 32:
        return
    version = f"{st.st_mtime_ns}-{st.st_size}"
    with _png_lock:
        if _png_published["version"] == version and _png_published["bytes"]:
            cached = True
        else:
            cached = False
    if not cached:
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
        except OSError:
            return
        if not _complete_png(raw):
            return
        with _png_lock:
            _png_published["path"] = path
            _png_published["version"] = version
            _png_published["bytes"] = bytes(raw)
    with STATE.lock:
        STATE.data["png"] = os.path.basename(path)
        STATE.data["png_version"] = version


def _ensure_web_preview():
    """Write a web-sized copy so the web view does not have to decode a 4650px PNG.

    Runs on the caller thread. The HTTP thread only reads the finished file.
    """
    directory = _output_dir()
    full = os.path.join(directory, PNG_NAME)
    web = os.path.join(directory, WEB_PNG_NAME)
    try:
        full_m = os.stat(full).st_mtime_ns
    except OSError:
        return
    try:
        if os.stat(web).st_mtime_ns >= full_m and os.path.getsize(web) > 32:
            return
    except OSError:
        pass
    tmp = web + ".part"
    try:
        import matplotlib.image as mpimg

        image = mpimg.imread(full)
        step = max(1, int(math.ceil(max(image.shape[0], image.shape[1]) / 1400)))
        small = image[::step, ::step]
        # format is explicit: a .part suffix is not a PNG extension.
        mpimg.imsave(tmp, small, format="png")
        os.replace(tmp, web)
        try:
            os.chmod(web, 0o644)
        except OSError:
            pass
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def _send(self, code, body, content_type, cache=False):
        payload = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        if cache:
            self.send_header("Cache-Control", "private, max-age=86400")
        else:
            self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        try:
            self.wfile.flush()
        except OSError:
            pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(200, PAGE, "text/html; charset=utf-8")
            return
        if path == "/api/health":
            self._send(200, b'{"ok":true}', "application/json")
            return
        if path == "/api/state":
            refresh_png()
            with STATE.lock:
                payload = dict(STATE.data)
                payload["logs"] = list(STATE.logs[-250:])
                payload["server_time"] = _now()
            self._send(200, json.dumps(payload), "application/json")
            return
        if path == "/hud.png":
            refresh_png()
            with _png_lock:
                body = _png_published["bytes"]
            if body:
                self._send(200, body, "image/png", cache=True)
                return
            self._send(404, b"png not ready", "text/plain; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")


def start():
    """Bind the HUD. Safe to call more than once. Never raises into the loop."""
    global _started
    if os.environ.get("SINTRA_HUD", "1") == "0":
        return
    with _start_lock:
        if _started:
            return
        if not isinstance(sys.stdout, _Tee):
            sys.stdout = _Tee(sys.stdout)
        if not isinstance(sys.stderr, _Tee):
            sys.stderr = _Tee(sys.stderr)
        try:
            server = ThreadingHTTPServer((HOST, PORT), _Handler)
        except OSError as exc:
            sys.__stdout__.write(f"[hud] web view not bound on port {PORT}: {exc}\n")
            _started = True
            return
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, name="sintra-hud", daemon=True).start()
        _started = True
        refresh_png()
        print(f"[hud] web view http://127.0.0.1:{PORT}")
        _ensure_web_preview()
        refresh_png()


def note_cycle(cycle):
    with STATE.lock:
        STATE.data["cycle"] = int(cycle)
        STATE.data["phase"] = "cycle"
        STATE.data["active"] = None
        STATE.data["summary"] = []
        STATE.data["frames"] = 0
        _touch()


def note_weather(sw):
    status = str(sw.source_status)
    payload = {
        "timestamp_utc": sw.timestamp_utc,
        "bx": _f(sw.bx_nt),
        "by": _f(sw.by_nt),
        "bz": _f(sw.bz_nt),
        "bt": _f(sw.bt_nt),
        "density": _f(sw.proton_density_cm3),
        "speed": _f(sw.bulk_speed_kms),
        "temperature": _f(sw.temperature_k),
        "omega_i": _f(sw.omega_i_rad_s),
        "anisotropy": _f(sw.anisotropy_ratio),
        "status": status,
        "hash": sw.payload_hash,
        "live": "LIVE" in status and "OFFLINE" not in status and "FALLBACK" not in status,
    }
    with STATE.lock:
        STATE.data["weather"] = payload
        STATE.data["phase"] = "space-weather"
        _touch()


def note_catalog(targets, env):
    rows = []
    for tgt in targets:
        rows.append(
            {
                "norad_id": int(tgt.norad_id),
                "name": str(tgt.name),
                "object_type": str(tgt.object_type),
                "inclination": _f(tgt.inclination_deg),
                "altitude_km": _f(tgt.altitude_km),
                "velocity_ms": _f(tgt.orbital_velocity_ms),
                "lat": _f(tgt.sub_lat_deg),
                "lon": _f(tgt.sub_lon_deg),
                "true_sigma_km": _f(tgt.true_wake_sigma_m) / 1000.0
                if _f(tgt.true_wake_sigma_m) is not None
                else None,
                "source": str(tgt.ephemeris_source),
            }
        )
    with STATE.lock:
        STATE.data["catalog"] = rows
        STATE.data["background"] = {
            "name": str(getattr(env, "source_name", "")),
            "hash": str(getattr(env, "file_sha256", "")),
        }
        STATE.data["phase"] = "catalog"
        _touch()


def note_frame(frame):
    spark_sin = [_f(v) for v in frame.get("spark_sin") or []]
    spark_imm = [_f(v) for v in frame.get("spark_imm") or []]
    spark_pf = [_f(v) for v in frame.get("spark_pf") or []]
    payload = {
        "norad_id": int(frame["norad_id"]),
        "name": str(frame["name"]),
        "frame": int(frame["frame"]),
        "frames": int(frame["frames"]),
        "e_sin": _f(frame.get("e_sin")),
        "e_imm": _f(frame.get("e_imm")),
        "e_pf": _f(frame.get("e_pf")),
        "v_track": _f(frame.get("v_track")),
        "v_true": _f(frame.get("v_true")),
        "sigma_km": (_f(frame.get("sigma_m")) or 0.0) / 1000.0,
        "sigma_true_km": (_f(frame.get("sigma_true_m")) or 0.0) / 1000.0,
        "lambda": _f(frame.get("lambda")),
        "mass": _f(frame.get("mass")),
        "klass": str(frame.get("klass") or ""),
        "spark_sin": spark_sin,
        "spark_imm": spark_imm,
        "spark_pf": spark_pf,
    }
    with STATE.lock:
        STATE.data["active"] = payload
        STATE.data["frames"] = int(STATE.data.get("frames") or 0) + 1
        STATE.data["phase"] = "sweep"
        _touch()


def note_target(row):
    payload = {
        "norad_id": int(row["norad_id"]),
        "name": str(row["name"]),
        "altitude_km": _f(row.get("altitude_km")),
        "true_sigma_km": (_f(row.get("true_sigma_m")) or 0.0) / 1000.0,
        "blind_sigma_km": (_f(row.get("blind_sigma_m")) or 0.0) / 1000.0,
        "rmse_sin": _f(row.get("rmse_sin")),
        "rmse_imm": _f(row.get("rmse_imm")),
        "rmse_pf": _f(row.get("rmse_pf")),
        "lambda": _f(row.get("lambda")),
        "mass": _f(row.get("mass")),
        "klass": str(row.get("klass") or ""),
    }
    with STATE.lock:
        STATE.data["summary"] = [
            item for item in STATE.data["summary"] if item["norad_id"] != payload["norad_id"]
        ]
        STATE.data["summary"].append(payload)
        STATE.data["phase"] = "classified"
        _touch()

def note_png(path):
    _ensure_web_preview()
    refresh_png()
    with STATE.lock:
        if path and not STATE.data.get("png"):
            STATE.data["png"] = os.path.basename(path)
        STATE.data["phase"] = "saved"
        _touch()
