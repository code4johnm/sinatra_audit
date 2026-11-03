#!/usr/bin/env python3
"""Web HUD for the live sky-catalog loop.

Same process, same continuous cycle, same terminal lines. The page adds
custody, space-weather, and error stats the terminal table does not chart.
The Earth frame draws every catalog satellite live. Existing frames stay.
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
    --track-font: "Segoe UI", Helvetica, Arial, sans-serif;
    --track-num: ui-monospace, Menlo, Consolas, monospace;
  }
  * { box-sizing: border-box; font-family: var(--track-font); }
  html, body { margin: 0; min-height: 100%; background: var(--bg); color: var(--ink); }
  body {
    font-family: var(--track-font);
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
    grid-template-rows: minmax(560px, 64vh) 220px auto 200px 460px auto auto;
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
  .orbit { grid-column: 1 / -1; grid-row: 1; padding: 8px; min-height: 560px; }
  .sky { grid-column: 2; grid-row: 2; padding: 8px; }
  .sky canvas, .spark canvas, .orbit canvas, .bands canvas, .gtrack canvas {
    width: 100%; height: calc(100% - 22px); display: block;
  }
  .orbit canvas, .gtrack canvas { touch-action: none; cursor: grab; }
  .wx { grid-column: 1; grid-row: 2; }
  .active { grid-column: 3; grid-row: 2; }
  .idcard { grid-column: 1; grid-row: 3; overflow: auto; }
  .elem { grid-column: 2; grid-row: 3; overflow: auto; }
  .geom { grid-column: 3; grid-row: 3; overflow: auto; }
  .record { grid-column: 1; grid-row: 4; overflow: auto; }
  .bands { grid-column: 2 / span 2; grid-row: 4; padding: 8px; }
  .gtrack { grid-column: 1 / -1; grid-row: 5; padding: 8px; }
  .table { grid-column: 1 / span 2; grid-row: 6; overflow: auto; }
  .stats { grid-column: 3; grid-row: 6; overflow: auto; }
  .shot { grid-column: 1 / -1; grid-row: 7; overflow: visible; }
  .logs { grid-column: 1 / -1; grid-row: 8; min-height: 220px; }
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
    height: 1px;
    opacity: 0;
    pointer-events: none;
  }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  .wx .row, .active .row, .stats .row, .idcard .row, .elem .row, .geom .row, .record .row {
    display: flex; justify-content: space-between; gap: 12px;
    font-size: 12px; padding: 3px 0; border-bottom: 1px solid #161616;
  }
  .wx .row b, .active .row b, .stats .row b, .idcard .row b, .elem .row b, .geom .row b, .record .row b {
    font-weight: 500; font-variant-numeric: tabular-nums;
    font-family: var(--track-num);
  }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #1c1c1c; white-space: nowrap; font-family: var(--track-font); }
  th { color: var(--dim); font-weight: 500; font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; }
  tr.active-row td { background: #111; }
  .num { font-variant-numeric: tabular-nums; font-family: var(--track-num); }
  .wx .row, .active .row, .stats .row {
    display: flex; justify-content: space-between; gap: 12px;
    font-size: 12px; padding: 3px 0; border-bottom: 1px solid #161616;
  }
  .wx .row b, .active .row b, .stats .row b {
    font-weight: 500; font-variant-numeric: tabular-nums;
    font-family: var(--track-num);
  }
  .big { font-size: 28px; letter-spacing: 0.08em; margin: 4px 0 8px; }
  .klass { font-size: 11px; letter-spacing: 0.14em; }
  .klass.debris { color: var(--red); }
  .klass.station { color: #fff; }
  .klass.payload { color: var(--ice); }
  pre {
    margin: 0; height: 220px; overflow: auto;
    font: 11px/1.45 var(--track-font);
    letter-spacing: 0.04em;
    color: #cfcfcf; white-space: pre-wrap; word-break: break-word;
  }
  .empty { color: var(--dim); font-size: 12px; font-family: var(--track-font); }
  @media (max-width: 1100px) {
    main { grid-template-columns: 1fr; grid-template-rows: auto; height: auto; }
    .sky, .wx, .active, .table, .stats, .logs, .shot,
    .orbit, .idcard, .elem, .geom, .record, .bands, .gtrack {
      grid-column: 1; grid-row: auto; min-height: 180px;
    }
    .orbit { min-height: 420px; }
    .shot, .logs { min-height: 0; }
    .gtrack { min-height: 440px; }
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
    <p class="k" id="orbit-k">Earth view · all positions</p>
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
    <p class="k">Ground track · all positions</p>
    <canvas id="gtrack" width="900" height="440"></canvas>
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
const TRACK_FONT = '"Segoe UI", Helvetica, Arial, sans-serif';
function hudFont(px) { return px + "px " + TRACK_FONT; }
const TRACK_NUM = "ui-monospace, Menlo, Consolas, monospace";
function hudNum(px) { return px + "px " + TRACK_NUM; }
let clockSkew = 0;
const liveState = { catalog: [], active: null };
let pumpOn = false;
function serverNow() { return Date.now() / 1000 + clockSkew; }
function fade(hex, alpha) {
  const raw = String(hex || "#888888").replace("#", "");
  const h = raw.length === 3 ? raw.split("").map((c) => c + c).join("") : raw;
  const n = parseInt(h, 16);
  if (!Number.isFinite(n)) return "rgba(138,138,138," + alpha + ")";
  return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + alpha + ")";
}
function wrap360(d) { return ((Number(d) % 360) + 360) % 360; }
function satNow(t, nowSec) {
  const fallback = {
    lat: Number(t.lat) || 0,
    lon: Number(t.lon) || 0,
    r: Number(t.radius_km) || (RE_KM + Number(t.altitude_km || 0)),
    alt: Number(t.altitude_km) || 0,
    u: Number(t.arg_lat) || 0,
    gmst: Number(t.gmst) || 0
  };
  if (!Number.isFinite(Number(t.inclination)) || !Number.isFinite(Number(t.mean_motion))) return fallback;
  const n = Number(t.mean_motion) || 0;
  const e = Number(t.eccentricity) || 0;
  const a = Number(t.sma_km) || (RE_KM + Number(t.altitude_km || 550));
  const epoch = Number(t.epoch_unix);
  const dt = Number.isFinite(epoch) && epoch > 0 ? (nowSec - epoch) : 0;
  const Mdeg = wrap360((Number(t.mean_anomaly) || 0) + dt * n * 360 / 86400);
  const M = rad(Mdeg);
  let E = M;
  for (let i = 0; i < 6; i++) {
    const den = 1 - e * Math.cos(E);
    if (Math.abs(den) < 1e-9) break;
    E = E - (E - e * Math.sin(E) - M) / den;
  }
  const r = a * (1 - e * Math.cos(E));
  const nu = 2 * Math.atan2(
    Math.sqrt(Math.max(0, 1 + e)) * Math.sin(E / 2),
    Math.sqrt(Math.max(0, 1 - e)) * Math.cos(E / 2)
  );
  const nuDeg = wrap360(deg(nu));
  const argp = Number(t.argp) || 0;
  const u = wrap360(argp + nuDeg);
  const inc = Number(t.inclination) || 0;
  const raan = Number(t.raan) || 0;
  const gmst = wrap360((Number(t.gmst) || 0) + dt * 1.5);
  const lat = deg(Math.asin(Math.max(-1, Math.min(1, Math.sin(rad(inc)) * Math.sin(rad(u))))));
  const dlon = deg(Math.atan2(Math.cos(rad(inc)) * Math.sin(rad(u)), Math.cos(rad(u))));
  const lon = pyLon(raan, dlon, gmst);
  return { lat: lat, lon: lon, r: r, alt: r - RE_KM, u: u, gmst: gmst, nu: nuDeg };
}
function liveFixes(cat) {
  const now = serverNow();
  return (cat || []).map((t) => Object.assign({ src: t }, satNow(t, now)));
}
function startLivePump() {
  if (pumpOn) return;
  pumpOn = true;
  let last = 0;
  function frame(ts) {
    if (ts - last > 50) {
      last = ts;
      drawOrbit(liveState.catalog, liveState.active);
      drawSky(liveState.catalog, liveState.active);
      drawGround(liveState.catalog, liveState.active);
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

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
  if (s.server_unix) clockSkew = Number(s.server_unix) - Date.now() / 1000;
  liveState.catalog = cat;
  liveState.active = act;
  fillOrbitPanels(cat, act);
  drawBands(cat, act);
  startLivePump();
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
function pyLon(raan, dlon, gmst) {
  const x = Number(raan) + Number(dlon) - Number(gmst) + 180;
  return ((x % 360) + 360) % 360 - 180;
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
    pts.push({ lat: lat, lon: pyLon(O, dlon, g), r: r, u: u });
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
const MASK_W = 720;
const MASK_H = 360;
const LAND_B64 = [
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD////+AAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP//////gAAAAH///",
"/////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAB////////gAAB8P/////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAH////////A/////////////8A/8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAx////////B/////////////////AAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/8P//////g//////////",
"///////AAAAAAAAAAAAAAAAAAAAHvgAAAAAAAAAAAAB/8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAD//+gP///8P///////////////+AAAAAAAAAAAB//+AAAAAAHwAAAAAAAAAAAAAH//gAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAB////////gAf///////////////AAAAAAAAAD8/n//AAAAAAAAAAAAAAAAAAAAAB//4AA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABgAAD//3//8AAD///////////////8AAAAAAAAAH//+AAAAA",
"AAAAAAAAAAAAAAAAAAAP/7wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADgA/4+D/////+AP///////////",
"/////4AAAAAAAAAD//+AAAAAAAAAAAAAAAAAAAAAAAAAAH/gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AB+fgHg///8H/////////////////4AAAAAAAAAAf/x+AAAAAAAAAAAAAAAAAAAAAAAAAf+AAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAfwAAAB8AH3//AA/////////////////4AAAAAAAAAAB/h/gAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/wAAAAAAAAD//4AAB////////////////+AAAAAAAAAAD+AAAAAA",
"AAAAAAAAAAAAAAAAAAAAAB/gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH/gAMAAAH/4////AAP///////////",
"/////AAAAAAAAAAAAAAAAAAAAAAAAAAAAB+AAAAAAAAAAH/+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/wfwf",
"AD/4D+AABwAAB////////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAP/+AAAAAAAAAD////+AAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAA//H+D/4A/gA+AAAAAAA/////////////4AAAAAAAAAAAAAAAAAAAAAAAAAH/8AAAAAAAAD/////",
"//gAAAAAAD//AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD///+APx+////wAAAAAAP////////////4AAAAAAAAAAAAAAAAAA",
"AAAAAAD/8AAAAAAAAH////////AAAAAAAD//z+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/wAAAA+P///wAAAAAAB///////",
"/////wAAAAAAAAAAAAAAAAAAAAAAAAH/AAAAAAAAB////////gAAAAAAAAcAAPAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/AAAA",
"AAAAAAAAAAAAAAAAA////////////gAAAAAAAAAAAAAAAAAAAAAAAAf4AAAAAAAAD///////8AAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAH//wAAAAOM/+AYEQAAAAAAAf///////////wAAAAAAAAAAAAAAAAAAAAAAAB/wAAAAAAA/////////",
"/+EAAAAAAAB4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP//mAAHgf5/4fz//4AAAAAAP//////////wAAAAAAAAAAAAAAAAAAA",
"AAAAAB/AAAAAAAB////////////8A/8AAAA/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf//++d+B/8/A///sAAAAAAAD//////",
"////4AAAAAAAAAAAAAAAAAAAAAAAAP+AAAA/xgB////////////////AAADwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//v//+",
"/A/++B///n+AAAAAAH//////////MAAAAAAAAAAAAAAAAAAAAAAAAP4AAAB/xx9////////////////AAAP//8AAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAf/f////gH+eB/////wAAAAAP//////////4AAAAAAAAAAAAAAAAAAAAAAAAf8AAAD/n///////////",
"///////AwAH///gAAAAAAAAA+AAAAAADgAAAAAAAAAD8Af///gAB/g//////gAAAAAf/////////8AAAAAAAAAAAAAAAAAAA",
"AAAAAD+AAAP/v//////////////////x//////8AAAAAAAADAAAAAAD//wAAAAAAAAAAH////4AB/wf/////8AAAAB7/////",
"///9+AAAAAAAAAAAAAAA//gAAAAAAB/gAAf/z////////////////////////////gAAAAAAAAAAAB////+AAAAAAcAAAAf/",
"//gB/4A//////wAAAD/////////wAAAAAAAAAAAAAAAz//gAAAAAAAAAAAP/z////////////////////////////wAAAAAA",
"AAAAAD///////AAB//c8B/////w+fwAPhAf//4AAAD//////////gAAAAAAAAAAAAAP///3AAAAAAAAA8AP/3///////////",
"/////////////////wAAD/+AAAAAAP////////D/////wf////B/v+QP+AH//8AAAAB////////8AAAAAAAAAAAAAB/////4",
"AAAAAAAAf8D/3///////////////////////////////h//+wAAAH////////////////+/4OAAAH/8P/AH//gAAAAB/////",
"///gAAAAAAAAAAAAAH//////8AAAADgOf/h/5///////////////////////////////////+AAAH/////////////////AD",
"/gA/P/8f+AGP/8AAAAf///////gAAAAAAAAAAAAAAf///////gH4A/P/////9///////////////////////////////////",
"/wAAA/////////////////H5//n///8//AfD//4AAAf//////gAAAAAAAAAAAAAAB////////8D8P///////4///////////",
"/////////////////////////8AAAP///////////////////////////AeD//+AAA///////AAAAAAAAAAAAAAAD///////",
"/+Hw////////z/////////////////////////////////////+AAD//////////////////////////8AAH///4AAf/////",
"8AAAAAAAAAAAAAAAP////////+B/////////H//////////////////////////////////////wD4//////////////////",
"///////4AAAP/x/wAA//////gAAA+GfgAAAAAAAAf//////4fx7/////////f///////////////////////////////////",
"v//w///////////////////////////wAAAf/w/gAAf////wAAAB///gAAAAAAAA///4f//8AP//////////////////////",
"////////////////////////gf4Af///////////////////////////AA///8OAAAH///8AAAAAH//4AAAAAAAB///wP//8",
"Af//////////////////////////////////////////////AH4AH/v////////////////////////f4B////AAAAH///4A",
"AAAAf//wAAAAAAAH///g///8fP/////////////////////////////////////////////+AAAAAAf/////////////////",
"//////8f+AwP//wAAAH///4AAAAAH//AAAAAAAAP///j////P//////////////////////////////////////////////4",
"AACAAAP///////////////////////A/vwAB//4AAAD///4AAAAAA/wAAAAAAAA///+P////////////////////////////",
"///////////////////////8AAAeAD///////////////////////+AOAAAA//4AAAB///gAAAAAAAAAAAAAAAH///wf////",
"///////////////////////////////////////////////8AAAAA////////////////////////wAA+AAAH8YAAAAf/+AA",
"AAAAAAAAAAAAAA////A////////////////////////////////////////////////////+AAAAB///////////////////",
"/////gAA4d/cAfAAAAAP/+AAAAAAAAAAAAAAAD////A///////////////////////////////////////////////7///+A",
"AAAAD////////////////////////AAAAY//AAAAAAAH//AAAAAAAAAAAAAAAD///+Af////////////////////////////",
"//////////////////z///gAAAAAD///////////////////////+AAAAA//wAAAAAAD/+AAAAAAAAAAAAAAAD///+A/////",
"////////////////////////////////////////gfH//8AAAAAAB/////+/////////////////8AAAAA//+AAAAAAAH8AA",
"AAAAAAAAAAAAAD////A/////////////////////////////////////////////Acf//wAAAAAAe/////8H////////////",
"////4AAAAA//+AIAAAAAB8AAAAAAAAAAAAAAAD////gP4H/////////////////////////////////////////8AB//HAAA",
"AAAAAB///PwAA///////////////4AAAAAf//AcAAAAAAAAAAAAAAAAAAAAAAD////wAAH//////////////////////////",
"///////////////4AH5AAAAAAAAAAB//+MAAAH//////////////4AAAAB///A+AAAAAAAAAAAAAAAAAAAAAAD/3//gB////",
"////////////////////////////////////w8P8AP4AAAAAAAAAAA3//AAAAB///////////////AAAAB///x/AAAAAAAAA",
"AAAAAAAAAAAAAB/j/8AD///////////////////////////////////////wAAAAA/wAAAAAAAAAAAAP8AAAAAP/////////",
"/////gAAAA/////gAAAAAAAAAAAAAAAAAAfAAAeD/8AA///////////////////////////////////////AAAAAB/gAAAAA",
"AAAAAAAPzwAAAAAP/////////////gAAAAf////wAAAAAAAAAAAAAAAAAA+AAAAB/8AE////////////////////////////",
"//////////+AAAAAf/wAAAAAAAAAAAAfPgAAAAAP/////////////2AAAAP////4AAAAAAAAAAAAAAAAAA/wAAAd/4A+////",
"//////////////////////////////////4AAAAAf/4AAAAAAAAAAAB8GAAAAAAD//////////////4AAAP////4AAAAAAAA",
"AAAAAAAAAB/wAAD4/4A///////////////////////////////////////gAAAAB//4AAAAAAAAAAAHwAAAAAAAB////////",
"//////+AAAP////4AAAAAAAAAAAAAAAAAA/gAAD8fwA///////////////////////////////////////AAAAAB//4AAAAA",
"AAAAAB/AAAAAAAAB///////////////wAAf/////AAAAAAAAAAAAAAAAAA/4AAD3+AA/////////////////////////////",
"/////////8AAAAAB//AAAAAAAAAAAHgAAAAAAAAAf///////////////gB//////gAAAAAAAAAAAAAAAAAP4AADzgAA/////",
"/////////////////////////////////wAAAAAD//AAAAAAAAAAA+AAAAAAAAAAP///////////////8P//////+AAAAAAA",
"AAAAAAAAAfP8AABwADn//////////////////////////////////////gAAAAAB//AAAAAAAAAAAAAAAAAAAAAAH///////",
"////////8H///////AAAAAAAAAAAAAAAB/h/AAB84////////////////////////////////////////8QMAAAB/4AAAAAA",
"AAAAAAAAAAAAAAAHj///////////////8D///////gAAAAAAAAAAAAAAD/B/AAD/////////////////////////////////",
"//////////+EAAAB/4AAAAAAAAAAAAAAAAAAAAADh///////////////8D///////4AAAAAAAAAAAAAAB/P/gD//////////",
"///////////////////////////////////+AAAB/4AAAAAAAAAAAAAAAAAAAAABh///////////////+D///////4AAAAAA",
"AAAAAAAAB/P/8H/////////////////////////////////////////////+AAAA+AAAAAAAAAAAAAAAAAAAAAAAwP//////",
"/////////D///////4AAAAAAAAAAAAAAD+H/8P/////////////////////////////////////////////+AAAA+AAAAAAA",
"AAAAAAAAAAAAAAAAAP///////////////n///////wAAAAAAAAAAAAAABwf/4f//////////////////////////////////",
"///////////eAAAA8AAAAAAAAAAAAAAAAAAAAAAAAP//////////////////////+4AAAAAAAAAAAAAAAAH/5///////////",
"///////////////////////////////////OAAAAYAAAAAAAAAAAAAAAAAAAAAAAAX//////////////////////xwAAAAAA",
"AAAAAAAAAAP+H//////////////////////////////////////////////PAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf//////",
"//////////////B/DwAAAAAAAAAAAAAAAA6AP//////////////////////////////////////////////PAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAD3//////////////////+HAD4AAAAAAAAAAAAAAAAAI////////////////////////////////////",
"//////////+PgAAAAAAAAAAAAAAAAAAAAAAAAAAAAB9//////////////////4A4H/wAAAAAAAAAAAAAAAAP////////////",
"//////////////////////////////////+PgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAe//////////////////v8AP/gAAAAA",
"AAAAAAAAAAH///////////////////////////////////////////////+cAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM/////",
"//////////////4AP/4AAAAAAAAAAAAAAAP///////////////////////////////////////////////8cAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAH///////////////////wAf/4AAAAAAAAAAAAAAAD/////////////////////////////////////",
"//////////4MAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH/////////////////7/4AAP4AAAAAAAAAAAAAAAAf////////////",
"//////////////////////////////////weAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH///////////////////+DAAwAAAAA",
"AAAAAAAAAAAP////////////z/////////////////////////////////gfAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/////",
"///////////////3AAAAAAAAAAAAAAAAAAAH//////////z8D/////////////////////////////////gLAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAD/////////////////////AAAAAAAAAAAAAAAAAAAH//////////g+H///////////////////////",
"//////////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD///////////////////P8AAAAAAAAAAAAAAAAAAAH////n/////B/",
"/////////////////////////////////8AYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH//////////////////8/gAAAAAAAA",
"AAAAAAAAAAAH////h////8A8P////////////////////////////////4AcAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH/////",
"/////////////x8AAAAAAAAAAAAAAAAAAAAH//+/g////8AAB////////////////////////////////wAfIAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAH/////////////////+BwAAAAAAAAAAAAAAAAAAAAP//8P4f///8AAA///////////////////////",
"/////////gA/4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAH/////////////////8AAAAAAAAAAAAAAAAAAAA////xwP8H///4AA",
"AP///////////////////////////////AD/4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/////////////////4AAAAAAAAAAA",
"AAAAAAAAB////gBn+B///wAAAD/////////////////////////////+AAH/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH/////",
"////////////4AAAAAAAAAAAAAAAAAAAB////gBz/Af//wAAAB/////////////////////////////8AAHmAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAH/////////////////+AAAAAAAAAAAAAAAAAAAB////ABg/4H//4D/AB//////////////////////",
"///////wAAHgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH////////////////+AAAAAAAAAAAAAAAAAAAAA///+AAAf8P//8P/",
"4H/////////////////////////////wAABgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH////////////////+AAAAAAAAAAAA",
"AAAAAAAAA///wADwD/P/jn/////////////////////////////////gAADwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH/////",
"///////////wAAAAAAAAAAAAAAAAAAAAA///gADwB9v/j///////////////////////////////n//AAAHwAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAD////////////////wAAAAAAAAAAAAAAAAAAAAB///AADwAcH8B///////////////////////////",
"///+Pn8AAADwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD////////////////gAAAAAAAAAAAAAAAAAAAAB///AADwAeD+D///",
"///////////////////////////8OD4AAAHwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD////////////////AAAAAAAAAAAAA",
"AAAAAAAAD///gAAAAcB+B//////////////////////////////wAD+AAAHgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB/////",
"///////////AAAAAAAAAAAAAAAAAAAAAA///AAAAAYA/D//////////////////////////////wAH/AAAPgAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAA///////////////+AAAAAAAAAAAAAAAAAAAAAA//+AAAA/gA/h///////////////////////////",
"///8YD/AAAfAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf//////////////+AAAAAAAAAAAAAAAAAAAAAA//4AAA4PgA8A///",
"////////////////////////////+AfgAE/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf//////////////+AAAAAAAAAAAAA",
"AAAAAAAAAB/wB//8BgAeAf//////////////////////////////8A/gAP/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP////",
"//////////+AAAAAAAAAAAAAAAAAAAAAABwA///8AAAAABj5////////////////////////////wA/gAP/AAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAH//////////////+AAAAAAAAAAAAAAAAAAAAAAAwD///8AAAAAAAA////////////////////////",
"////AAfgAf/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD//////////////+AAAAAAAAAAAAAAAAAAAAAAB/////8AAAB+ABx",
"///////////////////////////+AA/g//+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD//////////////4AAAAAAAAAAAAA",
"AAAAAAAAAB/////8AAAAAADh///////////////////////////+AA8B//4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf///",
"//////////gAAAAAAAAAAAAAAAAAAAAAAD/////4AAAAAAAB////////////////////////////gAAH+8AAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAH////////////+AAAAAAAAAAAAAAAAAAAAAAAP/////8AAAAAAAD////////////////////////",
"////gAAOf4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD////////////8AAAAAAAAAAAAAAAAAAAAAAA//////+AAAAAAAD",
"////////////////////////////wAA/6AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB////////////4AAAAAAAAAAAAAA",
"AAAAAAAAB///////8AA4AAAH////////////////////////////4AAfYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA///",
"/////////gAAAAAAAAAAAAAAAAAAAAAAB////////gD+AAAH////////////////////////////4AAPAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAA////////////AAAAAAAAAAAAAAAAAAAAAAAD////////wH/4AAH////////////////////////",
"////8AAOAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAef//////////AAAAAAAAAAAAAAAAAAAAAAAD////////4H//x+P",
"////////////////////////////8AAOAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAef//////////AAAAAAAAAAAAAAA",
"AAAAAAAAD/////////n/////////////////////////////////4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAOP/",
"//////wf/AAAAAAAAAAAAAAAAAAAAAAAD///////////////////////////////////////////4AAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAPP///////wG/AAAAAAAAAAAAAAAAAAAAAAAD///////////////////j///////////////////",
"////+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADn/////4HwAfAAAAAAAAAAAAAAAAAAAAAAAH///////////////",
"////h///////////////////////8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB3/////gAAAPgAAAAAAAAAAAAAA",
"AAAAAAAAP///////////////////h///////////////////////8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB7/",
"///+AAAAPgAAAAAAAAAAAAAAAAAAAAAA////////////////////w///////////////////////8AAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAH4////8AAAAPwAAAAAAAAAAAAAAAAAAAAAD///////////////7////wf//////////////////",
"////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD8f///8AAAAPwAAAAAAAAAAAAAAAAAAAAAH///////////////x",
"////4H//////////////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+P///8AAAAHzwAAAAAAAAAAAAA",
"AAAAAAAP///////////////w////+B4/////////////////////gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPH",
"///8AAAADwQAAAAAAAAAAAAAAAAAAAAf///////////////4////+AC/////////////////////AAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAHH///8AAAADwAAAAAAAAAAAAAAAAAAAAA////////////////4f////wG/////////////////",
"////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHj///8AAAABwAAAAAAAAAAAAAAAAAAAAA////////////////8",
"P////wOA/8f////////////////+MAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHh///4AAAAABgAAAAAAAAAAAAA",
"AAAAAAA////////////////+P////gfAAAP////////////////8cAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABw",
"///4AAAAABgAAAAAAAAAAAAAAAAAAAD////////////////+H////w/AAAP////////////////4cAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAA4P//4AAAAAAgAAAAAAAAAAAAAAAAAAAD////////////////+D//////4AAD/////////////",
"///g8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAcH//4AAAAAAAAAAAAAAAAAAAAAAAAAAH/////////////////",
"B//////8AAB////////////////A4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH//4AAAA/4AAAAAAAAAAAAAA",
"AAAAAAH/////////////////B//////+AAA///////////////8A4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"D//4AAABz/gAAAAAAAAAAAAAAAAAAAP/////////////////w///////AAA///////3//////+gAQAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAD//4AAAAAPwAAAAAAAAAAAAAAAAAAAP/////////////////w//////+AAAf/////8D/////",
"/4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB//8AA/gAD4AAAAAAAAAAAAAAAAAAAf/////////////////",
"4//////+AAAP/////AD/////HAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADAAAAAAAAAAAAAAAAB//8AB/gAB+AAAAAAAAAAAAA",
"AAAAAAP/////////////////wf/////8AAAAf////gD////8HAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAAAAAAAAAAAAA",
"D//+AB/AAAfwAAAAAAAAAAAAAAAAAAH/////////////////4P/////wAAAAf////AB////4AAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAB4AAAAAAAAAAAAAAAB///AD+AAAAH4AAAAAAAAAAAAAAAAAH/////////////////4H/////wAAAAf///8AAf///w",
"PAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAwAAAAAAAAAAAAAAAA///AD+AAAAD/AAAAAAAAAAAAAAAAAH/////////////////",
"4D/////wAAAAf///wAAf///wfAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP//gP+AAAAB/gAAAAAAAAAA",
"AAAAAAH/////////////////4D/////AAAAAf///gAAf///weAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AH////8AAB4f8ngAAAAAAAAAAAAAAAH/////////////////+D/////AAAAAP///AAAP///4MAAAeAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAA////8AAAQAwAAAAAAAAAAAAAAAAAH//////////////////B////4AAAAAP//+AAAP///8",
"AAAA+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///8AAAAAAAAAAAAAAAAAAAAAAAH/////////////////",
"/A////4AAAAAP//8AAAH///8AAAA+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD///8AAAAAAAAAAAAAAAAA",
"AAAAAAP//////////////////gf///AAAAAAP//4AAAP///+AAAA+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAf//4AAAAAAAAAAAAAAAAAAAAAAAH//////////////////gf//4AAAAAAP//wAAAPn///gAAB+AAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAADD///AAAAAAAAAAAAAAAAAAAAAAP//////////////////gf//4AAAAAAH/+AAAACH///",
"wAAB8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA///wAAAAAAAAAAAAAAAAAAAAAP/////////////////",
"/4f//gAAAAAAD/+AAAAAH///wAAB8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf//wAAAAAAAAAAAAAAA",
"AAAAAA///////////////////8f/8AAAAAAAD/+AAAAAH///4AAA8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAP//wAAAAAAAAAAAAAAAAAAAAAf//////////////////+P/wAAAAAAAB/+AAAAAH///4AAAfAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAB//wAAAAAAAAAAAAAAAAAAAAAP///////////////////P/AAAAAAAAB/+AAAAAD///",
"4AAAfwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/gAAAAAAAAAAAAAAAAAAAAAP/////////////////",
"//vwAAAAAAAAB/+AAAAAD///4AAA5wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB/wAAAAAAAAAAAAAAA",
"AAAAAAP////////////////////gAAAAAAAAB/+AAAAAD///4AAAYYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAA/gAAAwAAAAAAAAAAAAAAAAAP///////////////////4AAAAAAAAAA/8AAAAADw//4AAAIGAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAfgAAD2AAAAAAAAAAAAAAAAAH///////////////////wADgAAAAAAA/8AAAAABwf/",
"4AAAGHAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPgAAfvgAAAAAAAAAAAAAAAAB/////////////////",
"//4A/gAAAAAAAf8AAAAABwP/wAADDvAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPgAB//wAOAAAAAAAA",
"AAAAAAA///////////////////8P/gAAAAAAAf8AAAAADgP/AAADH+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAPwAD///vuAAAAAAAAAAAAAAA//////////////////////AAAAAAAAP4AAAAABgB+AAAGB2AAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH4AD/f//8AAAAAAAAAAAAAAAP/////////////////////AAAAAAAAP6AAAAADgA8",
"AAAMDyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA8fH////+AAAAAAAAAAAAAAAP////////////////",
"/////AAAAAAAAP/AAAAADgB4AAAYBjgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/7/////+AAAAAAAA",
"AAAAAAAH////////////////////+AAAAAAAAHngAAAAD4AgAAAwAHgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAfx//////gAAAAAAAAAAAAAAH////////////////////+AAAAAAAADHgAAAAD4AAAAAAB/gAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADx//////4AAAAAAAAAAAAAAD////////////////////8AAAAAAAAAHwAAAAA4AA",
"AAAAD/gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAg//////8AAAAAAAAAAAAAAB////////////////",
"////8AAAAAAAAAHwAAAAAcAAAAAAHPwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//////8AAAAAAA",
"AAAAAAAAf///////////////////4AAAAAAAAAHwAAAAAfAAAABgAegAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAf//////AAAAAAAAAAAAAAAP////P//////////////4AAAAAAAAADgAAAAAPgAAADwAPAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf///////gAAAAAAAAAAAAAH///wH//////////////wAAAAAAAAAAAAAAAAPwA",
"AAH4ACAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf///////4AAAAAAAAAAAAAD//+AD//////////",
"////wAAAAAAAAAAAAAAD4P4AAAP+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf///////8AAAAA",
"AAAAAAAAA/AYAD//////////////gAAAAAAAAAAAAAAB8H4AAA/8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAf///////+AAAAAAAAAAAAAAAAAAAx/////////////AAAAAAAAAAAAAAAA+H4AAB/4AAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf////////AAAAAAAAAAAAAAAAAAAA////////////+AAAAAAAAAAAAAAAAfH4A",
"AB/wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/////////gAAAAAAAAAAAAAAAAAAAf////////",
"///8AAAAAAAAAAAAAAAAPz4AAD/gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/////////gAAAA",
"AAAAAAAAAAAAAAAf///////////4AAAAAAAAAAAAAAAAH78AA//wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAD/////////gAAAAAAAAAAAAAAAAAAAf///////////wAAAAAAAAAAAAAAAAH88AA//4AAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/////////wAAAAAAAAAAAAAAAAAAA////////////gAAAAAAAAAAAAAAAAB/+A",
"P//wAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH/////////4AAAAAAAAAAAAAAAAAAA/////////",
"//+AAAAAAAAAAAAAAAAAB/8AP//8YGPAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf/////////wAAAA",
"AAAAAAAAAAAAAAA///////////8AAAAAAAAAAAAAAAAAA/wAf//w/8PAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAf/////////gAAAAAAAAAAAAAAAAAAA///////////4AAAAAAAAAAAAAAAAAA/8Af//xgQGAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf/////////+AAAAAAAAAAAAAAAAAAA///////////wAAAAAAAAAAAAAAAAAAf8A",
"P//hgAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA///////////wAAAAAAAAAAAAAAAAAB/////////",
"//gAAAAAAAAAAAAAAAAAAP8AP//xhgCB8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA///////////+AAA",
"AAAAAAAAAAAAAAB///////////AAAAAAAAAAAAAAAAAAAP+AH//D/AAH+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAA////////////gAAAAAAAAAAAAAAAAA//////////+AAAAAAAAAAAAAAAAAAAH/AD//D8AAB+DgAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA////////////wAAAAAAAAAAAAAAAAA//////////8AAAAAAAAAAAAAAAAAAAD/A",
"D//D8AAAGP8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP////////////AAAAAAAAAAAAAAAAAf////////",
"/4AAAAAAAAAAAAAAAAAAAD/wD/+H+AAA+f/gAAYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf/////////////A",
"AAAAAAAAAAAAAAAP/////////4AAAAAAAAAAAAAAAAAAAB/4Af+H+A/8f//8AAGAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAA//////////////wAAAAAAAAAAAAAAAH/////////wAAAAAAAAAAAAAAAAAAAA/wAAeBuAQEf///gADAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB//////////////4AAAAAAAAAAAAAAAD/////////wAAAAAAAAAAAAAAAAAAAAfw",
"AAABnAAAB///4AHgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB//////////////8AAAAAAAAAAAAAAAB////////",
"/gAAAAAAAAAAAAAAAAAAAAPwAAABlgAAAP//8AHAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB///////////////",
"wAAAAAAAAAAAAAAB/////////AAAAAAAAAAAAAAAAAAAAADwAAADjgAAAB//8B+EAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAA///////////////wAAAAAAAAAAAAAAA/////////AAAAAAAAAAAAAAAAAAAAABwAAAAAAAADA///P4GAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB///////////////wAAAAAAAAAAAAAAA/////////AAAAAAAAAAAAAAAAAAAAAAf",
"AAAAAAAADA///xgHAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf//////////////4AAAAAAAAAAAAAAAf///////",
"/gAAAAAAAAAAAAAAAAAAAAA/xwAAAAAACAf//AADwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP//////////////",
"4AAAAAAAAAAAAAAAf////////gAAAAAAAAAAAAAAAAAAAAAP/8AAAAAAAAf//gAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAP//////////////4AAAAAAAAAAAAAAAf////////gAAAAAAAAAAAAAAAAAAAAAAv/gAAAAAAB//vwAABgAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH//////////////4AAAAAAAAAAAAAAAP////////gAAAAAAAAAAAAAAAAAAAAAA",
"A/4YRAAAAB3+D4AAAwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD//////////////wAAAAAAAAAAAAAAAP///////",
"/gAAAAAAAAAAAAAAAAAAAAAAAAR9+DwAAAB+D8AAAGAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD//////////////",
"wAAAAAAAAAAAAAAAf////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAPAAAAAMB+AAASAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAB//////////////gAAAAAAAAAAAAAAAP////////wAAAAAAAAAAAAAAAAAAAAAAAAADwcAAAAAAA/AAAdAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB//////////////AAAAAAAAAAAAAAAAP////////4AAAAAAAAAAAAAAAAAAAAAA",
"AAAAg4AAAAAAAHwAACAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/////////////+AAAAAAAAAAAAAAAAH///////",
"/4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAMAAAAABgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/////////////8",
"AAAAAAAAAAAAAAAAH////////4AAAAAAAAAAAAAAAAAAAAAAAAAAAAABwAAMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAf////////////8AAAAAAAAAAAAAAAAH////////4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAcAAcAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf////////////4AAAAAAAAAAAAAAAAP////////8AAIAAAAAAAAAAAAAAAAAAA",
"AAAAAAAD/8AeAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP////////////wAAAAAAAAAAAAAAAAP///////",
"/8AAcAAAAAAAAAAAAAAAAAAAAAAAAAAP/8AeAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH////////////g",
"AAAAAAAAAAAAAAAAf////////8AAcAAAAAAAAAAAAAAAAAAAAAAAAAAP/4AfAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAH////////////gAAAAAAAAAAAAAAAA/////////8AB+AAAAAAAAAAAAAAAAAAAAAAAAAAf/4AfAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH////////////gAAAAAAAAAAAAAAAA/////////8AB+AAAAAAAAAAAAAAAAAAA",
"AAAAAB8f/wAfwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD////////////gAAAAAAAAAAAAAAAA////////",
"/8AD+AAAAAAAAAAAAAAAAAAAAAAAAD+f/gAf4AAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB////////////g",
"AAAAAAAAAAAAAAAB/////////8AH+AAAAAAAAAAAAAAAAAAAAAAAAH///wAf4AAAAAAGAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAf///////////gAAAAAAAAAAAAAAAB/////////4AP+AAAAAAAAAAAAAAAAAAAAAAAAP///8A/4AAAAAAAAAAA",
"gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///////////gAAAAAAAAAAAAAAAB/////////wD/8AAAAAAAAAAAAAAAAAAA",
"AAAAAf////A/4AAAAAADAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD///////////AAAAAAAAAAAAAAAAB////////",
"/gD/8AAAAAAAAAAAAAAAAAAAAAAAB/////g/8AAAAAAAAAAGAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA///////////A",
"AAAAAAAAAAAAAAAB////////+AD/4AAAAAAAAAAAAAAAAAAAAAAAD/////5/8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAf//////////AAAAAAAAAAAAAAAAB////////4AH/4AAAAAAAAAAAAAAAAAAAAAAAD///////+AAAAAAAAAA8",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/////////+AAAAAAAAAAAAAAAAB////////wAD/4AAAAAAAAAAAAAAAAAAA",
"AAAAD///////+AAAAAAAAAAYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH/////////+AAAAAAAAAAAAAAAAA////////",
"gAD/4AAAAAAAAAAAAAAAAAAAAAAAH///////+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH/////////+A",
"AAAAAAAAAAAAAAAAf//////+AAD/wAAAAAAAAAAAAAAAAAAAAAAAP////////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAH/////////+AAAAAAAAAAAAAAAAAf//////8AAD/wAAAAAAAAAAAAAAAAAAAAAAAf////////wAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH/////////8AAAAAAAAAAAAAAAAAP//////8AAD/wAAAAAAAAAAAAAAAAAAA",
"AAAH/////////8AAAADAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH/////////4AAAAAAAAAAAAAAAAAP//////8",
"AAH/gAAAAAAAAAAAAAAAAAAAAAB//////////8AAAADgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH/////////4A",
"AAAAAAAAAAAAAAAAH//////+AAH/gAAAAAAAAAAAAAAAAAAAAAH//////////+AAAAB4AAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAH/////////4AAAAAAAAAAAAAAAAAH//////+AAP/gAAAAAAAAAAAAAAAAAAAAAf//////////+AAAAAcAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH/////////gAAAAAAAAAAAAAAAAAD///////AAP/AAAAAAAAAAAAAAAAAAAA",
"AB////////////gAAAAMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH/////////gAAAAAAAAAAAAAAAAAD///////",
"AAP/AAAAAAAAAAAAAAAAAAAAAB////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH////////wAA",
"AAAAAAAAAAAAAAAAD//////+AAH/AAAAAAAAAAAAAAAAAAAAAB////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAH////////AAAAAAAAAAAAAAAAAAAD///////AAH/AAAAAAAAAAAAAAAAAAAAAB////////////4AAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH///////4AAAAAAAAAAAAAAAAAAAD//////+AAH+AAAAAAAAAAAAAAAAAAAA",
"AD////////////8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///////wAAAAAAAAAAAAAAAAAAAB//////4",
"AAH+AAAAAAAAAAAAAAAAAAAAAB////////////+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///////gAAA",
"AAAAAAAAAAAAAAAAB//////gAAB4AAAAAAAAAAAAAAAAAAAAAB/////////////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAP///////AAAAAAAAAAAAAAAAAAAAB//////AAAAAAAAAAAAAAAAAAAAAAAAAAD/////////////gAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP//////+AAAAAAAAAAAAAAAAAAAAA//////AAAAAAAAAAAAAAAAAAAAAAAAA",
"AD/////////////gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP//////+AAAAAAAAAAAAAAAAAAAAA//////A",
"AAAAAAAAAAAAAAAAAAAAAAAAAB/////////////gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///////AAAA",
"AAAAAAAAAAAAAAAAA//////AAAAAAAAAAAAAAAAAAAAAAAAAAB/////////////gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAP//////+AAAAAAAAAAAAAAAAAAAAAf/////AAAAAAAAAAAAAAAAAAAAAAAAAAA/////////////gAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf//////+AAAAAAAAAAAAAAAAAAAAAP////+AAAAAAAAAAAAAAAAAAAAAAAAA",
"AA/////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf//////+AAAAAAAAAAAAAAAAAAAAAP////+A",
"AAAAAAAAAAAAAAAAAAAAAAAAAAf////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf//////4AAAA",
"AAAAAAAAAAAAAAAAAH////8AAAAAAAAAAAAAAAAAAAAAAAAAAAf////////////gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAf//////4AAAAAAAAAAAAAAAAAAAAAH////4AAAAAAAAAAAAAAAAAAAAAAAAAAAP////////////gAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf//////wAAAAAAAAAAAAAAAAAAAAAD////wAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAP////////////gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA///////gAAAAAAAAAAAAAAAAAAAAAB////gA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAP////////////gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA///////gAAAA",
"AAAAAAAAAAAAAAAAAB////AAAAAAAAAAAAAAAAAAAAAAAAAAAAH////////////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAA//////+AAAAAAAAAAAAAAAAAAAAAAA///+AAAAAAAAAAAAAAAAAAAAAAAAAAAAH////B///////AAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf/////8AAAAAAAAAAAAAAAAAAAAAAA///8AAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAH///4AP//////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//////8AAAAAAAAAAAAAAAAAAAAAAB///4AA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAH//+AAD/////+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//////4AAAAA",
"AAAAAAAAAAAAAAAAAA///gAAAAAAAAAAAAAAAAAAAAAAAAAAAAH//4AAB/////8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAA//////wAAAAAAAAAAAAAAAAAAAAAAA//8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAP//wAAA9////4AAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB//////gAAAAAAAAAAAAAAAAAAAAAAAfwAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAP/AAAAA7////4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB////8eAAAAAAAAAAAAAAAAAAAAAAAAGAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAD8AAAAAb////wAAAAAAGAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB/////AAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAE////wAAAAAADgAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAD/////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///gAAAAAABgA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/////gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAH///gAAAAAABwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH/////gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH///gAAAAAAA8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/////AAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH///AAAAAAAAcAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAP/////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD//+AAAAAAAAec",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP////+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAA//gAAAAAAAAf4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH////gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADHAAAAAAAAAf4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH///wAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB/gAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAP///wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/g",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAPAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAYAAAAAAAAMOAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP//wAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf4AAAAAAAP+AAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAf//wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP4AAAAAAAfgA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf//+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAP4AAAAAAA/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAb//8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPwAAAAAAB+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAb//4AAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHgAAAAAAD8AAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAH//wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP+AA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf//wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAA/gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf//wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB/gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//+AAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH/AAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAA//8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH/AAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB//4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAD+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB//+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA///gAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAB///gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB///AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD//8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAABgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD//8AAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAD//4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB//gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB//AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB//gAAMAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAB//gAD+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//wACAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf/wAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAP/4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD8AAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAOAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAA/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD//AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH//AAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAf//AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD+AAAAAAAAAAAAAAA+AADAAAAAABwAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB///AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//gAAAAAAAAAYAAAD/A",
"A/wAAgAP/4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH///AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAD//wAAAAAAAAA8AAAP/////gH///////4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///AAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAA////AIAAAAAf////////////////////+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAAAP///AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/////9//AAAB//////////////////////gAAAAAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf////////gAAP/////////",
"/////////////+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+",
"AH/////////wAA//////////////////////////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAef///AAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAB/8f/////////wAB//////////////////////////+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAAAAAAAAAAA/////AAAAAAAAAAAAAAAAAAAAAEAMP+AAA/////////////wH////////////////////////////wAAAAAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/////AAAAAAAAAAAAAAAAAAAAA/4///w///////////////wP///////////",
"/////////////////+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/////AAAAAAAAAAAAAAAADAAA///////////",
"///////////wf///////////////////////////////gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/////AAAAAAA",
"AAAAAAAAPn//f//////////////////////x/////////////////////////////////AAAAAAAAAAAAAAAAAAAAAAAAAAA",
"AAwAAAAAAAA//////AAAAAAAAAAAAAAAf//////////////////////////z/////////////////////////////////gAA",
"AAAAAAAAAAAAAAAAAAAAAAAAAA//AAAAAAAd/////AAAAAAAAAAAAAAB////////////////////////////////////////",
"/////////////////////gAAAAAAAAAAAAAAAAAAAAAAAAAAAP/AAA4AAAAAA////AAAAAAAAAAAAAAf////////////////",
"/////////////////////////////////////////////gAAAAAAAAAAAAAAAAAAACAAAAAAAP/4f//+A7gH/////AAAAAAA",
"AAAAAAH//////////////////////////////////////////////////////////////gAAAAAAAAAAAAAAAAAAAA4fwDgA",
"AP///////////////AAAAAAAAAAAAAH//////////////////////////////////////////////////////////////gAA",
"AAAAAAAAAAAAAAH///nh//5AAP///////////////AAAAAAAAAAAAAH/////////////////////////////////////////",
"/////////////////////gAAAAAAAAAAAAAAAD/////////+A////////////////AAAAAAAAAAAAAf/////////////////",
"/////////////////////////////////////////////gAAAAAAAAAAAAAe/////////////////////////////AAAAAAA",
"AAAAAD///////////////////////////////////////////////////////////////gAAAAAAAAAAAAAf////////////",
"/////////////////AAAAAAAAAAAD////////////////////////////////////////////////////////////////gAA",
"AAAAAAAAAAAf/////////////////////////////AAAAAAAAAD/////////////////////////////////////////////",
"/////////////////////gAAAAAAAAD4AAP//////////////////////////////AAAAAAAAAf/////////////////////",
"/////////////////////////////////////////////gAAAAAAAAD//////////////////////////////////AAAAAAA",
"AH///////////////////////////////////////////////////////////////////gAAAAAAAAD/////////////////",
"/////////////////AAAAAAAH////////////////////////////////////////////////////////////////////gAA",
"AAAAAGD//////////////////////////////////AAD/gAA////////////////////////////////////////////////",
"/////////////////////gAAAAAAAH///////////////////////////////////AAP/4AA////////////////////////",
"/////////////////////////////////////////////gAAAAAAAB///////////////////////////////////AAf/8AA",
"/////////////////////////////////////////////////////////////////////gAAAAAAAAD/////////////////",
"/////////////////AB//8AA/////////////////////////////////////////////////////////////////////gAA",
"AAAAAAD//////////////////////////////////A///wAA////////////////////////////////////////////////",
"/////////////////////gAAAAAAAAD//////////////////////////////////A//gAAA////////////////////////",
"/////////////////////////////////////////////gAAAAAAAAD//////////////////////////////////AAAAAf/",
"/////////////////////////////////////////////////////////////////////gAAAAAAAAD/////////////////",
"/////////////////AB//5///////////////////////////////////////////////////////////////////////gAA",
"AAAAAAD//////////////////////////////////D//////////////////////////////////////////////////////",
"/////////////////////gAAAAAAAAD/////////////////////////////////////////////////////////////////",
"/////////////////////////////////////////////gAAAAAAAAD/////////////////////////////////////////",
"/////////////////////////////////////////////////////////////////////gAAAAB4AAD/////////////////",
"/////////////////////////////////////////////////////////////////////////////////////////////gAA",
"/+//wAD/////////////////////////////////////////////////////////////////////////////////////////",
"///////////////////////4/////8D/////////////////////////////////////////////////////////////////",
"////////////////////////////////////////////////////////////////////////////////////////////////",
"////////////////////////////////////////////////////////////////////////////////////////////////",
"////////////////////////////////////////////////////////////////////////////////////////////////",
"////////////////////////////////////////////////////////////////////////////////////////////////",
"////////////////////////////////////////////////////////////////////////////////////////////////",
"////////////////////////////////////////////////////////////////////////////////////////////////",
"////////////////////////////////////////////////////////////////////////////////////////////////",
"////////////////////////////////////////////////////////////////////////////////////////////////",
"////////////////////////////////////////////////////////////////////////////////////////////////",
"////////////////////////////////////////////////////////////////////////////////////////////////",
"////////////////////////////////////////////////////////////////////////////////////////////////",
"////////////////////////////////////////////////////////////////////////////////////////////////",
"////////////////////////////////////////////////////////////////////////////////////////////////"
].join("");
let landBits = null;
const earthPlates = {};
let flatEarth = null;
function landBitsOf() {
  if (landBits) return landBits;
  const raw = atob(LAND_B64);
  landBits = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) landBits[i] = raw.charCodeAt(i);
  return landBits;
}
function landAt(lon, lat) {
  const bits = landBitsOf();
  let x = Math.floor(((Number(lon) + 180) / 360) * MASK_W);
  let y = Math.floor(((90 - Number(lat)) / 180) * MASK_H);
  x = ((x % MASK_W) + MASK_W) % MASK_W;
  if (y < 0) y = 0;
  if (y >= MASK_H) y = MASK_H - 1;
  const i = y * MASK_W + x;
  return (bits[i >> 3] >> (7 - (i & 7))) & 1;
}
function iceAt(lon, lat, land) {
  if (!land) return false;
  if (lat <= -60 || lat >= 73) return true;
  return lat > 63 && lon < -22 && lon > -74;
}
const viewCam = { elev: 53, az: 180 / Math.PI * Math.atan2(0.22, 0.55), zoom: 1, drag: false };
function globeSnap() {
  return {
    elev: Math.round(viewCam.elev * 2) / 2,
    az: Math.round(viewCam.az * 2) / 2
  };
}
function earthCamera() {
  const a = globeSnap();
  const elev = rad(a.elev);
  const az = rad(a.az);
  const ce = Math.cos(elev);
  return [ce * Math.cos(az), ce * Math.sin(az), Math.sin(elev)];
}
function earthAxes(cam) {
  let up = [0, 0, 1];
  if (Math.abs(vdot(up, cam)) > 0.92) up = [0, 1, 0];
  const xaxis = vnorm(vcross(up, cam));
  const yaxis = vcross(cam, xaxis);
  return { cam: cam, xaxis: xaxis, yaxis: yaxis };
}
function earthPlate(radiusPx) {
  const snap = globeSnap();
  const drawR = viewCam.drag ? Math.min(radiusPx, 150) : radiusPx;
  const r = Math.max(64, Math.round(drawR / 2) * 2);
  const key = r + "@" + snap.elev + "," + snap.az;
  if (earthPlates[key]) return earthPlates[key];
  const d = r * 2;
  const cnv = document.createElement("canvas");
  cnv.width = d;
  cnv.height = d;
  const ctx = cnv.getContext("2d");
  const img = ctx.createImageData(d, d);
  const data = img.data;
  const ax = earthAxes(earthCamera());
  const re2 = RE_KM * RE_KM;
  for (let y = 0; y < d; y++) {
    const py = -((y + 0.5) - r) / r * RE_KM;
    for (let x = 0; x < d; x++) {
      const px = ((x + 0.5) - r) / r * RE_KM;
      const rho2 = px * px + py * py;
      const o = (y * d + x) * 4;
      if (rho2 > re2) {
        data[o + 3] = 0;
        continue;
      }
      const depth = Math.sqrt(re2 - rho2);
      const p = [
        ax.xaxis[0] * px + ax.yaxis[0] * py + ax.cam[0] * depth,
        ax.xaxis[1] * px + ax.yaxis[1] * py + ax.cam[1] * depth,
        ax.xaxis[2] * px + ax.yaxis[2] * py + ax.cam[2] * depth
      ];
      const lat = deg(Math.asin(Math.max(-1, Math.min(1, p[2] / RE_KM))));
      const lon = deg(Math.atan2(p[1], p[0]));
      const land = landAt(lon, lat);
      const ice = iceAt(lon, lat, land);
      const coast = land && !ice && (
        !landAt(lon + 0.55, lat) || !landAt(lon - 0.55, lat) ||
        !landAt(lon, lat + 0.55) || !landAt(lon, lat - 0.55)
      );
      const nrm = depth / RE_KM;
      const light = 0.36 + 0.64 * nrm;
      const spec = land ? 0 : Math.pow(nrm, 22) * 0.4;
      let r, g, b;
      if (!land) {
        r = 8 * light + 186 * spec;
        g = 44 * light + 214 * spec;
        b = 82 * light + 232 * spec;
      } else if (ice) {
        r = 206 * light;
        g = 220 * light;
        b = 228 * light;
      } else if (coast) {
        r = 196 * light;
        g = 214 * light;
        b = 196 * light;
      } else {
        r = 58 * light;
        g = 108 * light;
        b = 64 * light;
      }
      data[o] = Math.max(0, Math.min(255, r));
      data[o + 1] = Math.max(0, Math.min(255, g));
      data[o + 2] = Math.max(0, Math.min(255, b));
      data[o + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  earthPlates[key] = cnv;
  const keys = Object.keys(earthPlates);
  if (keys.length > 4) delete earthPlates[keys[0]];
  return cnv;
}
function flatEarthCanvas() {
  if (flatEarth) return flatEarth;
  const cnv = document.createElement("canvas");
  cnv.width = MASK_W;
  cnv.height = MASK_H;
  const ctx = cnv.getContext("2d");
  const img = ctx.createImageData(MASK_W, MASK_H);
  const data = img.data;
  for (let y = 0; y < MASK_H; y++) {
    const lat = 90 - ((y + 0.5) / MASK_H) * 180;
    for (let x = 0; x < MASK_W; x++) {
      const lon = -180 + ((x + 0.5) / MASK_W) * 360;
      const land = landAt(lon, lat);
      const ice = iceAt(lon, lat, land);
      const o = (y * MASK_W + x) * 4;
      if (!land) {
        data[o] = 8; data[o + 1] = 28; data[o + 2] = 48;
      } else if (ice) {
        data[o] = 186; data[o + 1] = 204; data[o + 2] = 214;
      } else {
        data[o] = 36; data[o + 1] = 78; data[o + 2] = 46;
      }
      data[o + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  flatEarth = cnv;
  return cnv;
}
function paintFlatEarth(g, w, h) {
  g.drawImage(flatEarthCanvas(), 0, 0, w, h);
}
function drawEarth(g, proj, scale, cx, cy) {
  const radius = RE_KM * scale;
  const plate = earthPlate(radius);
  g.drawImage(plate, cx - radius, cy - radius, radius * 2, radius * 2);
  g.save();
  g.beginPath();
  g.arc(cx, cy, Math.max(1, radius - 0.6), 0, Math.PI * 2);
  g.clip();
  g.strokeStyle = "rgba(215,228,255,0.20)";
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
  g.beginPath();
  g.arc(cx, cy, radius + 2.2, 0, Math.PI * 2);
  g.strokeStyle = "rgba(120,176,214,0.28)";
  g.lineWidth = 4;
  g.stroke();
  g.beginPath();
  g.arc(cx, cy, radius, 0, Math.PI * 2);
  g.strokeStyle = "#d7e4ff";
  g.lineWidth = 1.15;
  g.stroke();
  const pole = proj(ecef(90, 0, RE_KM));
  if (pole.depth > 0) {
    const x = cx + pole.x * scale;
    const y = cy - pole.y * scale;
    g.fillStyle = "#d7e4ff";
    g.font = hudFont(10);
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
    g.font = hudFont(11);
    g.fillText(label, x + arm + 8, y - 6);
  }
}
function drawRoster(g, live, act, x0, y0, width) {
  g.font = hudFont(11);
  g.fillStyle = "#8a8a8a";
  g.fillText("LIVE ROSTER", x0, y0 + 12);
  g.font = hudNum(10);
  g.fillStyle = "#8a8a8a";
  g.fillText("LAT      LON      ALT", x0 + 14, y0 + 26);
  live.forEach((p, i) => {
    const y = y0 + 48 + i * 32;
    const id = Number(p.src.norad_id);
    const on = act && Number(act.norad_id) === id;
    const hero = id === 44713;
    if (on || hero) {
      g.fillStyle = "#111111";
      g.fillRect(x0 - 4, y - 14, Math.max(40, width - 8), 30);
    }
    g.fillStyle = hero ? "#ffffff" : toneOf(p.src);
    g.beginPath();
    g.arc(x0 + 5, y - 4, hero || on ? 3.4 : 2.5, 0, Math.PI * 2);
    g.fill();
    g.font = hudFont(11);
    g.fillStyle = "#f4f4f4";
    g.fillText(String(id) + "  " + String(p.src.name || "").slice(0, 16), x0 + 14, y);
    g.font = hudNum(10);
    g.fillStyle = p.hidden ? "#8a8a8a" : "#cfcfcf";
    g.fillText(
      n(p.lat, 1).padStart(7, " ") + "  " + n(p.lon, 1).padStart(7, " ") + "  " + n(p.alt, 0).padStart(5, " ") + " km",
      x0 + 14,
      y + 13
    );
  });
}
function drawOrbit(cat, act) {
  const c = $("orbit");
  if (!c) return;
  const view = fitCanvas(c, 1100, 560);
  const g = view.g;
  const live = liveFixes(cat);
  const title = $("orbit-k");
  if (!live.length) {
    g.fillStyle = "#8a8a8a";
    g.font = hudFont(12);
    g.fillText("Waiting for the catalog.", 16, 28);
    if (title) title.textContent = "Earth view · all positions";
    return;
  }
  const gmst = live[0].gmst;
  const pubSma = smaFromMotion(PUBLIC_44713.mean_motion);
  const pub = withEcef(ringPoints(
    PUBLIC_44713.inc, PUBLIC_44713.raan, PUBLIC_44713.argp,
    PUBLIC_44713.ecc, pubSma, gmst, 140
  ));
  const rings = live.map((p) => {
    const id = Number(p.src.norad_id);
    return {
      p: p,
      pts: withEcef(ringPoints(
        p.src.inclination, p.src.raan, p.src.argp, p.src.eccentricity,
        p.src.sma_km || p.r, p.gmst, id === 44713 ? 140 : 80
      ))
    };
  });
  const wide = view.w >= 820;
  const rosterW = wide ? Math.min(300, Math.max(228, view.w * 0.28)) : 0;
  const rosterH = wide ? 0 : Math.min(view.h * 0.46, 40 + live.length * 32);
  const plotW = Math.max(160, view.w - rosterW);
  const plotH = Math.max(160, view.h - rosterH);
  let maxR = pubSma || (RE_KM + 550);
  live.forEach((p) => { if (p.r > maxR) maxR = p.r; });
  const scale = Math.min(plotW - 16, plotH - 36) * 0.46 / maxR * viewCam.zoom;
  const cx = plotW * 0.5;
  const cy = plotH * 0.48;
  const proj = projector(earthCamera());
  c.dataset.plotW = String(plotW);
  strokeRing(g, proj, pub, scale, cx, cy, "rgba(255,59,48,0.40)", 1, [4, 4], true);
  rings.forEach((ring) => {
    const hero = Number(ring.p.src.norad_id) === 44713;
    const color = hero ? "rgba(255,255,255,0.30)" : fade(toneOf(ring.p.src), 0.22);
    strokeRing(g, proj, ring.pts, scale, cx, cy, color, 1, [], true);
  });
  drawEarth(g, proj, scale, cx, cy);
  strokeRing(g, proj, pub, scale, cx, cy, "#ff3b30", 1.05, [5, 4], false);
  rings.forEach((ring) => {
    const id = Number(ring.p.src.norad_id);
    const on = act && Number(act.norad_id) === id;
    const hero = id === 44713;
    const color = hero ? "#ffffff" : toneOf(ring.p.src);
    strokeRing(g, proj, ring.pts, scale, cx, cy, color, hero ? 1.7 : (on ? 1.35 : 1.0), [], false);
  });
  const marks = rings.map((ring) => {
    const q = proj(ecef(ring.p.lat, ring.p.lon, ring.p.r));
    ring.p.hidden = occluded(q);
    return { ring: ring, q: q };
  }).sort((a, b) => a.q.depth - b.q.depth);
  marks.forEach((mark) => {
    const p = mark.ring.p;
    const q = mark.q;
    const id = Number(p.src.norad_id);
    const on = act && Number(act.norad_id) === id;
    const hero = id === 44713;
    const color = hero ? "#ffffff" : toneOf(p.src);
    if (!p.hidden) {
      const surf = proj(ecef(p.lat, p.lon, RE_KM));
      g.strokeStyle = color;
      g.globalAlpha = 0.5;
      g.lineWidth = 1;
      g.beginPath();
      if (!occluded(surf) && surf.depth > 0) g.moveTo(cx + surf.x * scale, cy - surf.y * scale);
      else g.moveTo(cx, cy);
      g.lineTo(cx + q.x * scale, cy - q.y * scale);
      g.stroke();
      g.globalAlpha = 1;
    }
    markAt(g, proj, scale, cx, cy, p.lat, p.lon, p.r, color, hero || on ? 7 : 5, String(id));
  });
  const legend = [
    ["#ffffff", false, "sweep orbits"],
    ["#d7e4ff", false, "station / payload"],
    ["#ff3b30", false, "debris"],
    ["#ff3b30", true, "public last plane"]
  ];
  g.font = hudFont(11);
  legend.forEach((item, i) => {
    const y = plotH - 16 - (legend.length - 1 - i) * 14;
    g.strokeStyle = item[0];
    g.lineWidth = 1.4;
    g.setLineDash(item[1] ? [4, 3] : []);
    g.beginPath();
    g.moveTo(12, y - 3);
    g.lineTo(28, y - 3);
    g.stroke();
    g.setLineDash([]);
    g.fillStyle = "#cfcfcf";
    g.fillText(item[2], 34, y);
  });
  if (wide) drawRoster(g, live, act, plotW + 8, 4, rosterW - 8);
  else drawRoster(g, live, act, 12, plotH + 2, view.w - 16);
  if (title) title.textContent = "Earth view · " + live.length + " positions";
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
    g.font = hudFont(12);
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
    g.font = hudFont(11);
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
function strokeTrack(g, pts, xy) {
  let pen = false;
  g.beginPath();
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i];
    const prev = i ? pts[i - 1] : null;
    if (prev && Math.abs(p.lon - prev.lon) > 180) pen = false;
    const pair = xy(p.lon, p.lat);
    if (!pen) { g.moveTo(pair[0], pair[1]); pen = true; }
    else g.lineTo(pair[0], pair[1]);
  }
  g.stroke();
}
function drawGround(cat, act) {
  const c = $("gtrack");
  if (!c) return;
  const view = fitCanvas(c, 900, 440);
  const g = view.g;
  const w = view.w;
  const h = view.h;
  const live = liveFixes(cat);
  if (!live.length) {
    g.fillStyle = "#8a8a8a";
    g.font = hudFont(12);
    g.fillText("Waiting for the catalog.", 8, 24);
    return;
  }
  const radiusPx = Math.max(48, Math.min(w - 28, h - 20) * 0.5 * viewCam.zoom);
  const scale = radiusPx / RE_KM;
  const cx = w * 0.5;
  const cy = h * 0.5;
  const proj = projector(earthCamera());
  drawEarth(g, proj, scale, cx, cy);
  live.forEach((p) => {
    const id = Number(p.src.norad_id);
    const hero = id === 44713;
    const on = act && Number(act.norad_id) === id;
    if (p.src.inclination == null) return;
    const pts = withEcef(ringPoints(
      p.src.inclination, p.src.raan, p.src.argp, p.src.eccentricity,
      p.src.sma_km || p.r, p.gmst, hero || on ? 200 : 96
    ).map((q) => ({ lat: q.lat, lon: q.lon, r: RE_KM + 18 })));
    const color = hero ? "#ffffff" : toneOf(p.src);
    strokeRing(g, proj, pts, scale, cx, cy, color, hero ? 1.6 : 1.05, [], false);
  });
  live.forEach((p) => {
    const id = Number(p.src.norad_id);
    const hero = id === 44713;
    const on = act && Number(act.norad_id) === id;
    const color = hero ? "#ffffff" : toneOf(p.src);
    markAt(g, proj, scale, cx, cy, p.lat, p.lon, RE_KM + 24, color, hero || on ? 6 : 3.5, hero || on ? String(id) : "");
  });
}

function drawSky(cat, act) {
  const c = $("sky");
  if (!c) return;
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
  const live = liveFixes(cat);
  live.forEach((p, i) => {
    const pair = xy(p.lon, p.lat);
    const x = pair[0];
    const y = pair[1];
    const id = Number(p.src.norad_id);
    const on = act && Number(act.norad_id) === id;
    const hero = id === 44713;
    const color = hero ? "#ffffff" : toneOf(p.src);
    g.strokeStyle = on || hero ? "#fff" : color;
    g.lineWidth = on || hero ? 1.6 : 1;
    const arm = on ? 16 : (hero ? 10 : 6);
    g.beginPath();
    g.moveTo(x - arm, y - arm); g.lineTo(x + arm, y + arm);
    g.moveTo(x + arm, y - arm); g.lineTo(x - arm, y + arm);
    g.stroke();
    if (on) {
      g.beginPath(); g.arc(x, y, 22, 0, Math.PI * 2); g.stroke();
    }
    g.font = hudFont(11);
    g.fillStyle = color;
    g.fillText(String(id), x + arm + 6, y - 4 - (i % 2) * 10);
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

function bindGlobe(id) {
  const c = $(id);
  if (!c || c.dataset.bound) return;
  c.dataset.bound = "1";
  let drag = null;
  c.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return;
    const rect = c.getBoundingClientRect();
    const x = ev.clientX - rect.left;
    const plotW = Number(c.dataset.plotW) || rect.width;
    if (id === "orbit" && x > plotW) return;
    drag = { x: ev.clientX, y: ev.clientY, az: viewCam.az, elev: viewCam.elev, id: ev.pointerId };
    viewCam.drag = true;
    c.setPointerCapture(ev.pointerId);
    c.style.cursor = "grabbing";
  });
  c.addEventListener("pointermove", (ev) => {
    if (!drag || drag.id !== ev.pointerId) return;
    viewCam.az = drag.az - (ev.clientX - drag.x) * 0.32;
    viewCam.elev = Math.max(-85, Math.min(85, drag.elev + (ev.clientY - drag.y) * 0.28));
  });
  function endDrag(ev) {
    if (!drag || ev.pointerId !== drag.id) return;
    drag = null;
    viewCam.drag = false;
    c.style.cursor = "grab";
  }
  c.addEventListener("pointerup", endDrag);
  c.addEventListener("pointercancel", endDrag);
  c.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    viewCam.zoom = Math.max(0.6, Math.min(2.8, viewCam.zoom * (ev.deltaY > 0 ? 0.9 : 1.1)));
  }, { passive: false });
  c.addEventListener("dblclick", () => {
    viewCam.elev = 53;
    viewCam.az = 180 / Math.PI * Math.atan2(0.22, 0.55);
    viewCam.zoom = 1;
  });
}
bindGlobe("orbit");
bindGlobe("gtrack");
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
                payload["server_unix"] = datetime.now(timezone.utc).timestamp()
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
                "epoch_unix": _f(getattr(tgt, "epoch_unix", None)),
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
