#!/usr/bin/env python3
"""Web HUD for the live sky-catalog loop.

Same process, same continuous cycle, same terminal lines. The page adds
custody, space-weather, and error stats the terminal table does not chart.
An orbit frame draws NORAD 44713 above Earth. Existing frames stay.
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
    grid-template-rows: 220px 520px auto 200px auto auto auto;
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
  .sky canvas, .spark canvas, .orbit canvas, .bands canvas, .gtrack canvas {
    width: 100%; height: calc(100% - 22px); display: block;
  }
  .wx { grid-column: 1; grid-row: 1; }
  .active { grid-column: 3; grid-row: 1; }
  .orbit { grid-column: 1 / span 2; grid-row: 2; padding: 8px; }
  .idcard { grid-column: 3; grid-row: 2; overflow: auto; }
  .elem { grid-column: 1; grid-row: 3; overflow: auto; }
  .geom { grid-column: 2; grid-row: 3; overflow: auto; }
  .record { grid-column: 3; grid-row: 3; overflow: auto; }
  .bands { grid-column: 1 / span 2; grid-row: 4; padding: 8px; }
  .gtrack { grid-column: 3; grid-row: 4; padding: 8px; }
  .table { grid-column: 1 / span 2; grid-row: 5; overflow: auto; }
  .stats { grid-column: 3; grid-row: 5; overflow: auto; }
  .shot { grid-column: 1 / -1; grid-row: 6; overflow: visible; }
  .logs { grid-column: 1 / -1; grid-row: 7; min-height: 220px; }
  #stack { display: flex; flex-direction: column; gap: 36px; }
  #stack canvas {
    display: block;
    width: 50%;
    height: auto;
    background: #070a12;
  }
  #shot {
    position: absolute;
    width: 1px;
    height: 1px;, .idcard .row, .elem .row, .geom .row, .record .row {
    display: flex; justify-content: space-between; gap: 12px;
    font-size: 12px; padding: 3px 0; border-bottom: 1px solid #161616;
  }
  .wx .row b, .active .row b, .stats .row b, .idcard .row b, .elem .row b, .geom .row b, .recordse: collapse; font-size: 12px; }
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
    .sky, .wx, .active, .table, .stats, .logs, .shot,
    .orbit, .idcard, .elem, .geom, .record, .bands, .gtrack {
      grid-column: 1; grid-row: auto; min-height: 180px;
    }
    .orbit { min-height: 420px; }
    .shot, .logs { min-height: 0; }
  }
</style>
</head>
<body>
<header>
  <div class="xmark" aria-hidden="true"></div>
  <h1>SINTRA <span>X HUD</span></h1>
  <div class="grow"></div>
  <div class="pill" id="sat">44713</div>
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
  <section class="card orbit">
    <p class="k" id="orbit-k">Orbit above Earth · 44713</p>
    <canvas id="orbit" width="1100" height="640"></canvas>
  </section>
  <section class="card idcard">
    <p class="k">Starlink 1007 · sweep state</p>
    <div id="idcard"><p class="empty">Waiting for the catalog.</p></div>
  </section>
  <section class="card elem">
    <p class="k" id="elem-k">Keplerian elements</p>
    <div id="elem"><p class="empty">Waiting for the catalog.</p></div>
  </section>
  <section class="card geom">
    <p class="k" id="geom-k">State · this cycle</p>
    <div id="geom"><p class="empty">Waiting for the catalog.</p></div>
  </section>
  <section class="card record">
    <p class="k">Public record · 44713</p>
    <div id="record"></div>
  </section>
  <section class="card bands">
    <p class="k">Altitude bands</p>
    <canvas id="bands" width="1100" height="160"></canvas>
  </section>
  <section class="card gtrack">
    <p class="k">Ground track · 44713</p>
    <canvas id="gtrack" width="420" height="160"></canvas>
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
  drawOrbit(cat, act);
  fillOrbitPanels(cat, act);
  drawBands(cat, act);
  drawGround(cat, act);
}
function paintStack(img) {
  const stack = $("stack");
  const nw = img.naturalWidth;
  const nh = img.naturalHeight;
  if (!nw || !nh) return;
  const panels = [
    ["1. Live intercept", 0.02, 0.088, 0.50, 0.422],
    ["2. Kernel gate", 0.02, 0.535, 0.50, 0.445],
    ["3. Track error", 0.545, 0.088, 0.435, 0.422],
    ["4. Mass fingerprint", 0.545, 0.535, 0.435, 0.445]
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
const RE_KM = 6378.137;
const MU_KM = 398600.4418;
const PUBLIC_44713 = {
  norad_id: 44713,
  name: "STARLINK-1007",
  intl: "2019-074A",
  owner: "SPXS / US",
  constellation: "Starlink v1.0",
  kind: "Internet",
  launch: "2019-11-11",
  vehicle: "Falcon 9",
  decay: "2024-10-02",
  status: "Re-entered",
  mass_kg: 260,
  dry_kg: 248,
  length_m: 0.2,
  span_m: 9.0,
  shape: "Box + panel",
  bus: "Starlink",
  maker: "SPXS",
  inc: 53.0382,
  raan: 329.7306,
  ecc: 0.0008324,
  argp: 5.1336,
  mean_anomaly: 119.9714,
  mean_motion: 16.29877576,
  epoch: "2024-10-02",
  source: "satellitemap.space/sat/44713"
};
function rad(d) { return Number(d) * Math.PI / 180; }
function deg(r) { return r * 180 / Math.PI; }
function wrap180(lon) {
  return ((Number(lon) + 180) % 360 + 360) % 360 - 180;
}
function byId(cat, id) {
  return (cat || []).find((t) => Number(t.norad_id) === Number(id)) || null;
}
function subjectOf(cat, act) {
  if (act) {
    const hit = byId(cat, act.norad_id);
    if (hit) return hit;
  }
  return byId(cat, 44713) || (cat && cat[0]) || null;
}
function smaFromMotion(mm) {
  const n = Number(mm) * 2 * Math.PI / 86400;
  if (!n) return null;
  return Math.cbrt(MU_KM / (n * n));
}
function regimeOf(alt) {
  const a = Number(alt);
  if (!Number.isFinite(a)) return "—";
  if (a < 200) return "REENTRY / VLEO";
  if (a < 600) return "LEO";
  if (a < 1200) return "UPPER LEO";
  if (a < 2000) return "LEO EDGE";
  return "ABOVE LEO";
}
function toneOf(t) {
  const c = String((t && (t.object_type || t.name)) || "").toUpperCase();
  if (c.includes("DEBRIS") || c.includes("DEB")) return "#ff3b30";
  if (c.includes("STATION")) return "#ffffff";
  return "#d7e4ff";
}
function vadd(a, b) { return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]; }
function vscale(a, s) { return [a[0] * s, a[1] * s, a[2] * s]; }
function vdot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
function vcross(a, b) {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}
function vnorm(a) {
  const m = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / m, a[1] / m, a[2] / m];
}
function ecef(lat, lon, r) {
  const cl = Math.cos(rad(lat));
  const sl = Math.sin(rad(lat));
  const co = Math.cos(rad(lon));
  const so = Math.sin(rad(lon));
  return [r * cl * co, r * cl * so, r * sl];
}
function ringPoints(inc, raan, argp, ecc, sma, gmst, steps) {
  const pts = [];
  const e = Number(ecc) || 0;
  const a = Number(sma) || (RE_KM + 550);
  const w = Number(argp) || 0;
  const i = Number(inc) || 0;
  const O = Number(raan) || 0;
  const g = Number(gmst) || 0;
  for (let k = 0; k <= steps; k++) {
    const u = (k / steps) * 360;
    const nu = u - w;
    const r = a * (1 - e * e) / (1 + e * Math.cos(rad(nu)));
    const lat = deg(Math.asin(Math.max(-1, Math.min(1, Math.sin(rad(i)) * Math.sin(rad(u))))));
    const dlon = deg(Math.atan2(Math.cos(rad(i)) * Math.sin(rad(u)), Math.cos(rad(u))));
    pts.push({ lat: lat, lon: wrap180(O + dlon - g + 180), r: r, u: u });
  }
  return pts;
}
function projector(cam) {
  let up = [0, 0, 1];
  if (Math.abs(vdot(up, cam)) > 0.92) up = [0, 1, 0];
  const xaxis = vnorm(vcross(up, cam));
  const yaxis = vcross(cam, xaxis);
  return function (p) {
    return { x: vdot(p, xaxis), y: vdot(p, yaxis), depth: vdot(p, cam) };
  };
}
function cameraFor(pts) {
  const a = pts[0].ecef;
  const b = pts[Math.floor(pts.length / 3)].ecef;
  const c = pts[Math.floor((2 * pts.length) / 3)].ecef;
  let normal = vnorm(vcross(vadd(b, vscale(a, -1)), vadd(c, vscale(a, -1))));
  if (normal[2] < 0) normal = vscale(normal, -1);
  let side = vcross(normal, [0, 0, 1]);
  if (Math.hypot(side[0], side[1], side[2]) < 1e-6) side = [1, 0, 0];
  side = vnorm(side);
  return vnorm(vadd(vscale(normal, 1.35), vscale(side, 0.42)));
}
function withEcef(pts) {
  return pts.map((p) => Object.assign({}, p, { ecef: ecef(p.lat, p.lon, p.r) }));
}
function fitCanvas(c, fallbackW, fallbackH) {
  const dpr = window.devicePixelRatio || 1;
  const w = c.clientWidth || fallbackW;
  const h = c.clientHeight || fallbackH;
  c.width = Math.floor(w * dpr);
  c.height = Math.floor(h * dpr);
  const g = c.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  return { g: g, w: w, h: h };
}
function occluded(q) {
  const rho = Math.hypot(q.x, q.y);
  if (rho >= RE_KM - 8) return false;
  const front = Math.sqrt(Math.max(RE_KM * RE_KM - rho * rho, 0));
  return q.depth < front - 8;
}
function strokeRing(g, proj, pts, scale, cx, cy, color, width, dash, back) {
  g.beginPath();
  let pen = false;
  let any = false;
  pts.forEach((p) => {
    const q = proj(p.ecef);
    const hide = occluded(q) || (back ? q.depth >= 0 : q.depth < 0);
    if (hide) { pen = false; return; }
    const x = cx + q.x * scale;
    const y = cy - q.y * scale;
    if (!pen) { g.moveTo(x, y); pen = true; any = true; }
    else g.lineTo(x, y);
  });
  if (!any) return;
  g.strokeStyle = color;
  g.lineWidth = width;
  g.setLineDash(dash);
  g.stroke();
  g.setLineDash([]);
}
function drawEarth(g, proj, scale, cx, cy) {
  g.beginPath();
  g.arc(cx, cy, RE_KM * scale, 0, Math.PI * 2);
  const grd = g.createRadialGradient(
    cx - RE_KM * scale * 0.28, cy - RE_KM * scale * 0.32, RE_KM * scale * 0.08,
    cx, cy, RE_KM * scale
  );
  grd.addColorStop(0, "#2a3d5c");
  grd.addColorStop(0.62, "#121a28");
  grd.addColorStop(1, "#070b12");
  g.fillStyle = grd;
  g.fill();
  g.strokeStyle = "#d7e4ff";
  g.lineWidth = 1.15;
  g.stroke();
  g.save();
  g.beginPath();
  g.arc(cx, cy, RE_KM * scale - 0.6, 0, Math.PI * 2);
  g.clip();
  g.strokeStyle = "#2c3a4e";
  g.lineWidth = 1;
  for (let lon = -180; lon < 180; lon += 30) {
    g.beginPath();
    let pen = false;
    for (let lat = -90; lat <= 90; lat += 4) {
      const q = proj(ecef(lat, lon, RE_KM));
      if (q.depth <= 0) { pen = false; continue; }
      const x = cx + q.x * scale;
      const y = cy - q.y * scale;
      if (!pen) { g.moveTo(x, y); pen = true; }
      else g.lineTo(x, y);
    }
    g.stroke();
  }
  for (let lat = -60; lat <= 60; lat += 30) {
    g.beginPath();
    let pen = false;
    for (let lon = -180; lon <= 180; lon += 4) {
      const q = proj(ecef(lat, lon, RE_KM));
      if (q.depth <= 0) { pen = false; continue; }
      const x = cx + q.x * scale;
      const y = cy - q.y * scale;
      if (!pen) { g.moveTo(x, y); pen = true; }
      else g.lineTo(x, y);
    }
    g.stroke();
  }
  g.restore();
  const pole = proj(ecef(90, 0, RE_KM));
  if (pole.depth > 0) {
    const x = cx + pole.x * scale;
    const y = cy - pole.y * scale;
    g.fillStyle = "#d7e4ff";
    g.font = "10px sans-serif";
    g.fillText("N", x + 4, y - 2);
  }
}
function markAt(g, proj, scale, cx, cy, lat, lon, r, color, arm, label) {
  const q = proj(ecef(lat, lon, r));
  if (occluded(q)) return;
  const x = cx + q.x * scale;
  const y = cy - q.y * scale;
  g.strokeStyle = color;
  g.lineWidth = 1.4;
  g.beginPath();
  g.moveTo(x - arm, y - arm); g.lineTo(x + arm, y + arm);
  g.moveTo(x + arm, y - arm); g.lineTo(x - arm, y + arm);
  g.stroke();
  g.beginPath();
  g.arc(x, y, arm + 4, 0, Math.PI * 2);
  g.stroke();
  if (label) {
    g.fillStyle = color;
    g.font = "11px sans-serif";
    g.fillText(label, x + arm + 8, y - 6);
  }
}
function drawOrbit(cat, act) {
  const c = $("orbit");
  if (!c) return;
  const view = fitCanvas(c, 900, 480);
  const g = view.g;
  const hero = byId(cat, 44713);
  const gmst = (hero && hero.gmst != null) ? hero.gmst : ((cat[0] && cat[0].gmst) || 0);
  const pubSma = smaFromMotion(PUBLIC_44713.mean_motion);
  const pub = withEcef(ringPoints(
    PUBLIC_44713.inc, PUBLIC_44713.raan, PUBLIC_44713.argp,
    PUBLIC_44713.ecc, pubSma, gmst, 180
  ));
  const heroRing = hero ? withEcef(ringPoints(
    hero.inclination, hero.raan, hero.argp, hero.eccentricity,
    hero.sma_km || (RE_KM + Number(hero.altitude_km || 550)),
    hero.gmst, 180
  )) : [];
  const active = act ? byId(cat, act.norad_id) : null;
  const activeRing = (active && Number(active.norad_id) !== 44713) ? withEcef(ringPoints(
    active.inclination, active.raan, active.argp, active.eccentricity,
    active.sma_km || (RE_KM + Number(active.altitude_km || 550)),
    active.gmst, 140
  )) : [];
  const camPts = heroRing.length ? heroRing : pub;
  const proj = projector(cameraFor(camPts));
  let maxR = pubSma || (RE_KM + 550);
  heroRing.forEach((p) => { if (p.r > maxR) maxR = p.r; });
  activeRing.forEach((p) => { if (p.r > maxR) maxR = p.r; });
  const scale = Math.min(view.w, view.h - 48) * 0.46 / maxR;
  const cx = view.w * 0.5;
  const cy = (view.h - 40) * 0.48;
  strokeRing(g, proj, pub, scale, cx, cy, "rgba(255,59,48,0.55)", 1, [4, 4], true);
  if (heroRing.length) strokeRing(g, proj, heroRing, scale, cx, cy, "rgba(255,255,255,0.35)", 1, [], true);
  if (activeRing.length) strokeRing(g, proj, activeRing, scale, cx, cy, "rgba(215,228,255,0.35)", 1, [], true);
  drawEarth(g, proj, scale, cx, cy);
  strokeRing(g, proj, pub, scale, cx, cy, "#ff3b30", 1.15, [5, 4], false);
  if (heroRing.length) strokeRing(g, proj, heroRing, scale, cx, cy, "#ffffff", 1.7, [], false);
  if (activeRing.length) strokeRing(g, proj, activeRing, scale, cx, cy, "#d7e4ff", 1.2, [], false);
  cat.forEach((t) => {
    if (Number(t.norad_id) === 44713) return;
    if (act && Number(t.norad_id) === Number(act.norad_id)) return;
    const q = proj(ecef(t.lat, t.lon, RE_KM + 1));
    if (q.depth <= 0) return;
    const x = cx + q.x * scale;
    const y = cy - q.y * scale;
    g.fillStyle = toneOf(t);
    g.beginPath();
    g.arc(x, y, 2.4, 0, Math.PI * 2);
    g.fill();
  });
  if (hero) {
    const r = Number(hero.radius_km) || (RE_KM + Number(hero.altitude_km || 0));
    const surf = proj(ecef(hero.lat, hero.lon, RE_KM));
    const sat = proj(ecef(hero.lat, hero.lon, r));
    if (!occluded(sat)) {
      g.strokeStyle = "rgba(255,255,255,0.7)";
      g.lineWidth = 1;
      g.beginPath();
      if (!occluded(surf) && surf.depth > 0) {
        g.moveTo(cx + surf.x * scale, cy - surf.y * scale);
      } else {
        g.moveTo(cx, cy);
      }
      g.lineTo(cx + sat.x * scale, cy - sat.y * scale);
      g.stroke();
    }
    markAt(g, proj, scale, cx, cy, hero.lat, hero.lon, r, "#ffffff", 8, "44713");
  }
  if (active && Number(active.norad_id) !== 44713) {
    const r = Number(active.radius_km) || (RE_KM + Number(active.altitude_km || 0));
    markAt(g, proj, scale, cx, cy, active.lat, active.lon, r, "#d7e4ff", 6, String(active.norad_id));
  }
  g.font = "11px sans-serif";
  g.fillStyle = "#8a8a8a";
  const legend = [
    ["#ffffff", "44713 sweep ephemeris"],
    ["#ff3b30", "public last plane"],
    ["#d7e4ff", "other catalog"]
  ];
  legend.forEach((item, i) => {
    const y = view.h - 18 - (legend.length - 1 - i) * 14;
    g.strokeStyle = item[0];
    g.lineWidth = 1.4;
    g.beginPath();
    g.moveTo(12, y - 3);
    g.lineTo(28, y - 3);
    g.stroke();
    g.fillStyle = "#cfcfcf";
    g.fillText(item[1], 34, y);
  });
  const title = $("orbit-k");
  if (title) {
    const alt = hero ? n(hero.altitude_km, 0) + " km" : "waiting";
    title.textContent = "Orbit above Earth · 44713 · " + alt;
  }
}
function fillBox(id, rows) {
  const box = $(id);
  if (!box) return;
  box.replaceChildren();
  if (!rows.length) {
    box.append(Object.assign(document.createElement("p"), { className: "empty", textContent: "Waiting for the catalog." }));
    return;
  }
  rows.forEach((pair) => {
    if (pair[0] === "_note") box.append(Object.assign(document.createElement("p"), { className: "empty", textContent: pair[1] }));
    else box.append(row(pair[0], pair[1]));
  });
}
function apsis(t) {
  const a = Number(t && t.sma_km);
  const e = Number(t && t.eccentricity);
  if (!Number.isFinite(a) || !Number.isFinite(e)) return [null, null];
  return [a * (1 - e) - RE_KM, a * (1 + e) - RE_KM];
}
function fillOrbitPanels(cat, act) {
  const hero = byId(cat, 44713);
  const subj = subjectOf(cat, act);
  const sat = $("sat");
  if (sat) sat.textContent = hero ? "44713 LIVE" : "44713";
  const idRows = [];
  if (hero) {
    idRows.push(
      ["NORAD", String(hero.norad_id)],
      ["Name", hero.name || "STARLINK-1007"],
      ["Intl des", PUBLIC_44713.intl],
      ["Class", hero.object_type || "—"],
      ["Altitude", n(hero.altitude_km, 1) + " km"],
      ["Velocity", n(hero.velocity_ms, 1) + " m/s"],
      ["Latitude", n(hero.lat, 2) + " deg"],
      ["Longitude", n(hero.lon, 2) + " deg"],
      ["Inclination", n(hero.inclination, 2) + " deg"],
      ["RAAN", n(hero.raan, 2) + " deg"],
      ["Source", hero.source || "—"],
      ["_note", "Public catalog lists this object re-entered " + PUBLIC_44713.decay + ". The ring is the sweep ephemeris."]
    );
  }
  fillBox("idcard", idRows);
  const elemK = $("elem-k");
  const geomK = $("geom-k");
  if (subj) {
    if (elemK) elemK.textContent = "Elements · " + subj.norad_id;
    if (geomK) geomK.textContent = "State · " + subj.norad_id;
    const ends = apsis(subj);
    fillBox("elem", [
      ["Inclination", n(subj.inclination, 3) + " deg"],
      ["RAAN", n(subj.raan, 3) + " deg"],
      ["Eccentricity", n(subj.eccentricity, 7)],
      ["Arg perigee", n(subj.argp, 2) + " deg"],
      ["Mean anomaly", n(subj.mean_anomaly, 2) + " deg"],
      ["True anomaly", n(subj.true_anomaly, 2) + " deg"],
      ["Arg latitude", n(subj.arg_lat, 2) + " deg"],
      ["Mean motion", n(subj.mean_motion, 4) + " rev/d"],
      ["Period", n(subj.period_min, 2) + " min"],
      ["SMA", n(subj.sma_km, 1) + " km"],
      ["Perigee alt", n(ends[0], 1) + " km"],
      ["Apogee alt", n(ends[1], 1) + " km"]
    ]);
    const on = act && Number(act.norad_id) === Number(subj.norad_id);
    fillBox("geom", [
      ["Regime", regimeOf(subj.altitude_km)],
      ["Radius", n(subj.radius_km, 1) + " km"],
      ["Speed", n(subj.velocity_ms, 1) + " m/s"],
      ["Radial accel", n(subj.radial_accel, 2) + " m/s2"],
      ["Sub-lat", n(subj.lat, 2) + " deg"],
      ["Sub-lon", n(subj.lon, 2) + " deg"],
      ["Wake sigma", n(subj.true_sigma_km, 2) + " km"],
      ["GMST", n(subj.gmst, 2) + " deg"],
      ["Frame", on ? (act.frame + " / " + act.frames) : "—"],
      ["Track class", on ? (act.klass || "—") : (subj.object_type || "—")],
      ["Ephemeris", subj.source || "—"]
    ]);
  } else {
    fillBox("elem", []);
    fillBox("geom", []);
  }
  const pubAlt = (pubSma) => n(pubSma - RE_KM, 1);
  const pubSma = smaFromMotion(PUBLIC_44713.mean_motion);
  const pubPeriod = 1440 / PUBLIC_44713.mean_motion;
  const rec = [
    ["Status", PUBLIC_44713.status + " " + PUBLIC_44713.decay],
    ["Name", PUBLIC_44713.name],
    ["Intl des", PUBLIC_44713.intl],
    ["Owner", PUBLIC_44713.owner],
    ["Constellation", PUBLIC_44713.constellation],
    ["Type", PUBLIC_44713.kind],
    ["Launch", PUBLIC_44713.launch + " · " + PUBLIC_44713.vehicle],
    ["Mass", PUBLIC_44713.mass_kg.toFixed(0) + " kg"],
    ["Dry mass", PUBLIC_44713.dry_kg.toFixed(0) + " kg"],
    ["Span", n(PUBLIC_44713.span_m, 1) + " m"],
    ["Length", n(PUBLIC_44713.length_m, 2) + " m"],
    ["Shape", PUBLIC_44713.shape],
    ["Bus", PUBLIC_44713.bus],
    ["Epoch", PUBLIC_44713.epoch],
    ["Inc", n(PUBLIC_44713.inc, 4) + " deg"],
    ["RAAN", n(PUBLIC_44713.raan, 4) + " deg"],
    ["Ecc", n(PUBLIC_44713.ecc, 7)],
    ["Mean motion", n(PUBLIC_44713.mean_motion, 5) + " rev/d"],
    ["Period", n(pubPeriod, 2) + " min"],
    ["Derived alt", pubAlt(pubSma) + " km"]
  ];
  if (hero) rec.push(["Sweep alt", n(hero.altitude_km, 1) + " km"]);
  rec.push(["_note", "Last public elements from " + PUBLIC_44713.source + ". Position there is unavailable. Sweep alt is the interceptor state, not the decay TLE."]);
  fillBox("record", rec);
}
function drawBands(cat, act) {
  const c = $("bands");
  if (!c) return;
  const view = fitCanvas(c, 900, 150);
  const g = view.g;
  if (!cat.length) {
    g.fillStyle = "#8a8a8a";
    g.font = "12px sans-serif";
    g.fillText("Waiting for the catalog.", 8, 24);
    return;
  }
  const lo = 150;
  const hi = 1500;
  const labelW = 168;
  const right = 64;
  const top = 8;
  const rowH = (view.h - 16) / cat.length;
  cat.forEach((t, i) => {
    const y = top + i * rowH;
    const alt = Number(t.altitude_km);
    const x0 = labelW;
    const x1 = view.w - right;
    const x = x0 + ((Math.min(Math.max(alt, lo), hi) - lo) / (hi - lo)) * (x1 - x0);
    const on = act && Number(act.norad_id) === Number(t.norad_id);
    const hero = Number(t.norad_id) === 44713;
    g.fillStyle = hero ? "#161616" : "transparent";
    if (hero || on) {
      g.fillStyle = "#111";
      g.fillRect(0, y, view.w, rowH - 2);
    }
    g.fillStyle = "#8a8a8a";
    g.font = "11px sans-serif";
    g.fillText(String(t.norad_id) + "  " + String(t.name || "").slice(0, 16), 8, y + rowH * 0.62);
    g.strokeStyle = "#2a2a2a";
    g.lineWidth = 4;
    g.beginPath();
    g.moveTo(x0, y + rowH * 0.55);
    g.lineTo(x1, y + rowH * 0.55);
    g.stroke();
    g.strokeStyle = hero ? "#ffffff" : toneOf(t);
    g.lineWidth = on ? 2 : 1.2;
    g.beginPath();
    g.moveTo(x0, y + rowH * 0.55);
    g.lineTo(x, y + rowH * 0.55);
    g.stroke();
    g.fillStyle = hero ? "#ffffff" : toneOf(t);
    g.beginPath();
    g.arc(x, y + rowH * 0.55, on ? 4 : 3, 0, Math.PI * 2);
    g.fill();
    g.fillStyle = "#cfcfcf";
    g.fillText(n(alt, 0), x1 + 8, y + rowH * 0.62);
  });
}
function drawGround(cat, act) {
  const c = $("gtrack");
  if (!c) return;
  const view = fitCanvas(c, 360, 150);
  const g = view.g;
  const w = view.w;
  const h = view.h;
  g.strokeStyle = "#2a2a2a";
  g.lineWidth = 1;
  for (let lon = -180; lon <= 180; lon += 60) {
    const x = ((lon + 180) / 360) * w;
    g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke();
  }
  for (let lat = -60; lat <= 60; lat += 30) {
    const y = ((90 - lat) / 180) * h;
    g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke();
  }
  const xy = (lon, lat) => [((Number(lon) + 180) / 360) * w, ((90 - Number(lat)) / 180) * h];
  const hero = byId(cat, 44713);
  if (hero && hero.inclination != null) {
    const pts = ringPoints(
      hero.inclination, hero.raan, hero.argp, hero.eccentricity,
      hero.sma_km || (RE_KM + Number(hero.altitude_km || 550)),
      hero.gmst, 240
    );
    g.strokeStyle = "#ffffff";
    g.lineWidth = 1.3;
    let pen = false;
    g.beginPath();
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i];
      const prev = i ? pts[i - 1] : null;
      if (prev && Math.abs(p.lon - prev.lon) > 180) pen = false;
      const [x, y] = xy(p.lon, p.lat);
      if (!pen) { g.moveTo(x, y); pen = true; }
      else g.lineTo(x, y);
    }
    g.stroke();
    const [x, y] = xy(hero.lon, hero.lat);
    g.strokeStyle = "#ffffff";
    g.beginPath();
    g.moveTo(x - 6, y - 6); g.lineTo(x + 6, y + 6);
    g.moveTo(x + 6, y - 6); g.lineTo(x - 6, y + 6);
    g.stroke();
  } else {
    g.fillStyle = "#8a8a8a";
    g.font = "12px sans-serif";
    g.fillText("Waiting for 44713.", 8, 20);
  }
  cat.forEach((t) => {
    if (Number(t.norad_id) === 44713) return;
    const [x, y] = xy(t.lon, t.lat);
    const on = act && Number(act.norad_id) === Number(t.norad_id);
    g.fillStyle = on ? "#ffffff" : toneOf(t);
    g.beginPath();
    g.arc(x, y, on ? 3.2 : 2, 0, Math.PI * 2);
    g.fill();
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
                "raan": _f(getattr(tgt, "raan_deg", None)),
                "eccentricity": _f(getattr(tgt, "eccentricity", None)),
                "mean_motion": _f(getattr(tgt, "mean_motion_rev_day", None)),
                "argp": _f(getattr(tgt, "argp_deg", None)),
                "mean_anomaly": _f(getattr(tgt, "mean_anomaly_deg", None)),
                "true_anomaly": _f(getattr(tgt, "true_anomaly_deg", None)),
                "arg_lat": _f(getattr(tgt, "arg_lat_deg", None)),
                "sma_km": _f(getattr(tgt, "sma_km", None)),
                "radius_km": _f(getattr(tgt, "radius_km", None)),
                "period_min": _f(getattr(tgt, "period_min", None)),
                "gmst": _f(getattr(tgt, "gmst_deg", None)),
                "radial_accel": _f(getattr(tgt, "radial_accel_ms2", None)),
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
