#!/usr/bin/env python3
"""Web HUD for the live sky-catalog loop.

Same process, same continuous cycle, same terminal lines. The page adds
custody, space-weather, and error stats the terminal table does not chart.
One Earth frame draws every catalog satellite. Text readouts stack under it.
Stdlib only, so the locked-down image does not gain a dependency.
"""

import csv
import fcntl
import getpass
import json
import math
import os
import platform
import re
import socket
import sqlite3
import struct
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import sintra_ftp
import sintra_icmp
import sintra_snmp
import sintra_tftp

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
HOST = os.environ.get("SINTRA_HUD_HOST", "0.0.0.0")
PORT = int(os.environ.get("SINTRA_HUD_PORT", "8080"))
PNG_NAME = "sintra_live_norad_intercept_hud.png"
WEB_PNG_NAME = "sintra_live_norad_intercept_hud_web.png"
PNG_SIG = b"\x89PNG\r\n\x1a\n"
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_LIVE_LINKS = (
    (
        "NOAA SWPC magnetic field",
        "https://services.swpc.noaa.gov/products/solar-wind/mag-5-minute.json",
        "DSCOVR 5-minute magnetic field. The cycle requests this every pass.",
    ),
    (
        "NOAA SWPC solar wind plasma",
        "https://services.swpc.noaa.gov/products/solar-wind/plasma-5-minute.json",
        "DSCOVR 5-minute plasma. The cycle requests this every pass.",
    ),
    (
        "CelesTrak GP 25544 ISS",
        "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=json",
        "NORAD GP elements for ISS. The cycle requests this every pass.",
    ),
    (
        "CelesTrak GP 48274 CSS",
        "https://celestrak.org/NORAD/elements/gp.php?CATNR=48274&FORMAT=json",
        "NORAD GP elements for CSS. The cycle requests this every pass.",
    ),
    (
        "CelesTrak GP 39084 LANDSAT 8",
        "https://celestrak.org/NORAD/elements/gp.php?CATNR=39084&FORMAT=json",
        "NORAD GP elements for LANDSAT 8. The cycle requests this every pass.",
    ),
    (
        "CelesTrak GP 44713 STARLINK-1007",
        "https://celestrak.org/NORAD/elements/gp.php?CATNR=44713&FORMAT=json",
        "NORAD GP elements for STARLINK-1007. The cycle requests this every pass.",
    ),
    (
        "CelesTrak GP 49863 COSMOS 1408 DEB",
        "https://celestrak.org/NORAD/elements/gp.php?CATNR=49863&FORMAT=json",
        "NORAD GP elements for COSMOS 1408 debris. The cycle requests this every pass.",
    ),
    (
        "CelesTrak GP 30934 FENGYUN 1C DEB",
        "https://celestrak.org/NORAD/elements/gp.php?CATNR=30934&FORMAT=json",
        "NORAD GP elements for FENGYUN 1C debris. The cycle requests this every pass.",
    ),
    (
        "CelesTrak GP 55001 CZ-6A DEB",
        "https://celestrak.org/NORAD/elements/gp.php?CATNR=55001&FORMAT=json",
        "NORAD GP elements for CZ-6A debris. The cycle requests this every pass.",
    ),
)


def _star_points(cx, cy, outer):
    inner = outer * 0.382
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        radius = outer if i % 2 == 0 else inner
        pts.append(f"{cx + radius * math.cos(ang):.2f},{cy + radius * math.sin(ang):.2f}")
    return " ".join(pts)


def _flag_data_url():
    """United States flag in shades of black, used as the page background.

    Fills stay near black. The steps are only wide enough to separate the
    thirteen stripes, the canton, and the fifty stars.
    """
    stripe_dark = "#000000"
    stripe_light = "#121212"
    canton_fill = "#080808"
    star_fill = "#1e1e1e"
    stripe_h = 100 / 13
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 190 100" preserveAspectRatio="xMidYMid slice">'
    ]
    for i in range(13):
        fill = stripe_dark if i % 2 == 0 else stripe_light
        parts.append(
            f'<rect y="{i * stripe_h:.3f}" width="190" height="{stripe_h + 0.15:.3f}" fill="{fill}"/>'
        )
    canton_h = 7 * stripe_h
    canton_w = 76
    parts.append(f'<rect width="{canton_w}" height="{canton_h:.3f}" fill="{canton_fill}"/>')
    gap_x = canton_w / 12
    gap_y = canton_h / 10
    outer = min(gap_x, gap_y) * 0.46
    for row in range(9):
        y = gap_y * (row + 1)
        if row % 2 == 0:
            xs = [gap_x * (1 + 2 * col) for col in range(6)]
        else:
            xs = [gap_x * (2 + 2 * col) for col in range(5)]
        for x in xs:
            parts.append(f'<polygon points="{_star_points(x, y, outer)}" fill="{star_fill}"/>')
    parts.append("</svg>")
    from urllib.parse import quote

    return "data:image/svg+xml," + quote("".join(parts), safe="")


_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sinatra Audit</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%23000'/%3E%3Ccircle cx='16' cy='16' r='2.2' fill='%23f4f4f4'/%3E%3Cellipse cx='16' cy='16' rx='12' ry='4.6' fill='none' stroke='%23f4f4f4' stroke-width='1.3'/%3E%3Cellipse cx='16' cy='16' rx='12' ry='4.6' fill='none' stroke='%23f4f4f4' stroke-width='1.3' transform='rotate(60 16 16)'/%3E%3Cellipse cx='16' cy='16' rx='12' ry='4.6' fill='none' stroke='%23f4f4f4' stroke-width='1.3' transform='rotate(120 16 16)'/%3E%3C/svg%3E">
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
  html, body { margin: 0; min-height: 100%; background: #000; color: var(--ink); }
  body {
    font-family: var(--track-font);
    letter-spacing: 0.01em;
    background-color: #000;
    background-image: url("__FLAG_BG__");
    background-repeat: no-repeat;
    background-position: left top;
    background-size: cover;
    background-attachment: fixed;
  }
  .topbar {
    position: sticky;
    top: 0;
    z-index: 8;
    background: rgba(0,0,0,0.92);
  }
  header {
    display: flex; align-items: center; flex-wrap: wrap; gap: 10px 16px;
    padding: 14px 18px; border-bottom: 1px solid var(--line);
    background: transparent;
  }
  .mark { width: 32px; height: 32px; flex: 0 0 32px; display: block; }
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
    display: flex;
    flex-direction: column;
    gap: 14px;
    width: calc(100% - 88px);
    margin: 0 auto;
    padding: 14px 0 32px;
  }
  .card {
    position: relative;
    border: 1px solid var(--line);
    background: rgba(0,0,0,0.78);
    padding: 16px 18px 18px;
    overflow: visible;
  }
  .card:before, .card:after {
    content: ""; position: absolute; width: 9px; height: 9px; border: 1px solid #fff;
  }
  .card:before { top: -1px; left: -1px; border-right: 0; border-bottom: 0; }
  .card:after { right: -1px; bottom: -1px; border-left: 0; border-top: 0; }
  .k {
    font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--dim);
    margin: 0 0 12px;
  }
  .stage {
    position: relative;
    width: 100%;
    overflow: hidden;
  }
  .plot.orbit { background: #000; }
  .orbit .stage { height: 560px; }
  .bands .stage { height: 360px; }
  .spark-stage {
    position: relative;
    height: 240px;
    margin-top: 12px;
    overflow: hidden;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 16px;
    margin: 0 0 12px;
    padding: 0;
    list-style: none;
  }
  .legend li {
    display: flex;
    align-items: center;
    gap: 8px;
    color: #cfcfcf;
    font-size: 13px;
    letter-spacing: 0.03em;
    line-height: 1.3;
  }
  .legend i {
    width: 22px;
    height: 0;
    border-top: 2px solid currentColor;
    flex: 0 0 22px;
  }
  .legend i.dashed { border-top-style: dashed; }
  .legend i.dot {
    width: 9px;
    height: 9px;
    border: 0;
    border-radius: 50%;
    background: currentColor;
    flex-basis: 9px;
  }
  .stage canvas, .spark-stage canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    display: block;
  }
  .orbit canvas { touch-action: none; cursor: grab; }
  .table { overflow: visible; }
  #stack {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 28px;
  }
  #stack .k,
  #stack canvas {
    width: min(720px, 50%);
    margin-left: auto;
    margin-right: auto;
  }
  #stack canvas {
    position: static;
    display: block;
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
  table { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 15px; }
  .field {
    display: block;
    padding: 11px 0 12px;
    border-bottom: 1px solid #1c1c1c;
  }
  .field > span {
    display: block;
    margin: 0 0 4px;
    color: var(--dim);
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }
  .field .line {
    display: block;
    margin: 0;
    color: inherit;
    font-size: inherit;
    font-weight: inherit;
    letter-spacing: inherit;
    text-transform: none;
    line-height: 1.45;
  }
  .field b {
    display: block;
    font-weight: 500;
    font-size: 16px;
    line-height: 1.45;
    letter-spacing: 0.01em;
    font-variant-numeric: tabular-nums;
    font-family: var(--track-num);
    white-space: pre-line;
    word-break: break-word;
  }
  .field.on { box-shadow: inset 2px 0 0 #fff; padding-left: 10px; }
  .note {
    margin: 12px 0 0;
    color: #cfcfcf;
    font-size: 15px;
    line-height: 1.5;
    letter-spacing: 0.01em;
  }
  th, td {
    text-align: left;
    padding: 10px 8px;
    border-bottom: 1px solid #1c1c1c;
    white-space: normal;
    overflow-wrap: anywhere;
    vertical-align: top;
    line-height: 1.4;
    font-family: var(--track-font);
  }
  th { color: var(--dim); font-weight: 500; font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; }
  tr.active-row td { background: #111; }
  .num { font-variant-numeric: tabular-nums; font-family: var(--track-num); }
  .big { font-size: 34px; line-height: 1.15; letter-spacing: 0.04em; margin: 0 0 6px; }
  .klass { font-size: 15px; line-height: 1.4; letter-spacing: 0.06em; margin: 0 0 8px; }
  .klass.debris { color: var(--red); }
  .klass.station { color: #fff; }
  .klass.payload { color: var(--ice); }
  pre {
    margin: 0; height: 280px; overflow: auto;
    font: 14px/1.5 var(--track-font);
    letter-spacing: 0.01em;
    color: #cfcfcf; white-space: pre-wrap; word-break: break-word;
  }
  .empty { color: var(--dim); font-size: 15px; line-height: 1.45; font-family: var(--track-font); }
  .link-form {
    display: flex;
    flex-direction: column;
    gap: 14px;
    margin-top: 18px;
  }
  .link-form label {
    display: flex;
    flex-direction: column;
    gap: 6px;
    color: var(--dim);
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }
  .link-form input {
    width: 100%;
    padding: 10px 12px;
    border: 1px solid var(--line);
    background: #050505;
    color: var(--ink);
    font-size: 16px;
    line-height: 1.4;
    letter-spacing: 0.01em;
  }
  .link-form textarea {
    width: 100%;
    min-height: 160px;
    padding: 10px 12px;
    border: 1px solid var(--line);
    background: #050505;
    color: var(--ink);
    font: 14px/1.45 var(--track-num);
    resize: vertical;
  }
  .ftp-actions { display: flex; flex-wrap: wrap; gap: 8px; }
  .ftp-actions button { margin-top: 0; }
  .ftp-link {
    width: 100%;
    margin: 0;
    text-align: left;
    text-transform: none;
    letter-spacing: 0.01em;
    font-size: 14px;
  }
  .link-form button, .link-remove {
    align-self: flex-start;
    margin-top: 8px;
    padding: 10px 14px;
    border: 1px solid #fff;
    background: transparent;
    color: var(--ink);
    font-size: 12px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    cursor: pointer;
  }
  .link-form button.ftp-link {
    align-self: stretch;
    margin-top: 0;
    text-align: left;
    text-transform: none;
    letter-spacing: 0.01em;
    font-size: 14px;
  }
  .link-msg { min-height: 1.4em; margin: 0; }
  .dash-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 8px;
  }
  .tile {
    min-width: 0;
    border: 1px solid #1c1c1c;
    padding: 8px 10px;
  }
  .tile > span {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--dim);
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }
  .tile b {
    display: block;
    margin-top: 4px;
    font-weight: 500;
    font-size: 14px;
    line-height: 1.35;
    font-family: var(--track-num);
    word-break: break-word;
  }
  .lamp {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--red);
    flex: 0 0 9px;
  }
  .lamp.on { background: #30d158; }
  .k.sub {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0 0 8px;
  }
  .net-group + .net-group { margin-top: 16px; }
  .net-scroll, .link-scroll {
    max-height: 280px;
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .addr, .link-obj {
    display: grid;
    grid-template-columns: 9px minmax(0, 1fr);
    gap: 2px 10px;
    align-items: start;
    border: 1px solid #1c1c1c;
    padding: 8px 10px;
  }
  .addr .addr-main, .link-obj .link-main { min-width: 0; }
  .addr-top, .link-top {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 12px;
    align-items: baseline;
  }
  .addr-top b, .link-top b {
    font-weight: 500;
    font-size: 14px;
    letter-spacing: 0.04em;
  }
  .addr-top em, .link-top em {
    font-style: normal;
    color: var(--dim);
    font-size: 11px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }
  .addr-ip, .link-url {
    display: block;
    margin-top: 3px;
    font-family: var(--track-num);
    font-size: 13px;
    line-height: 1.4;
    word-break: break-all;
  }
  .link-obj .note { margin: 4px 0 0; font-size: 13px; }
  .link-obj .link-remove { margin-top: 8px; }
  .clock-banner {
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 8px;
    width: 100%;
    margin: 0;
    padding: 8px 14px 10px;
    border-bottom: 1px solid #2a2a2a;
    background: rgba(0,0,0,0.92);
    font-family: "Segoe UI", Helvetica, Arial, sans-serif;
  }
  .clock-banner .clock-tile {
    min-width: 0;
    border: 1px solid #1c1c1c;
    background: rgba(0,0,0,0.55);
    padding: 8px 10px;
  }
  .clock-banner .clock-tile span {
    display: block;
    color: #8a8a8a;
    font-size: 11px;
    font-weight: 450;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    line-height: 1.2;
  }
  .clock-banner .clock-tile b {
    display: block;
    margin-top: 4px;
    color: #f4f4f4;
    font-weight: 500;
    font-size: 20px;
    line-height: 1.2;
    letter-spacing: 0.06em;
    font-variant-numeric: tabular-nums;
    font-family: ui-monospace, Menlo, Consolas, monospace;
  }
  .clock-banner .clock-tile em {
    display: block;
    margin-top: 3px;
    color: #8a8a8a;
    font-style: normal;
    font-weight: 400;
    font-size: 12px;
    letter-spacing: 0.04em;
    line-height: 1.3;
  }
  @media (max-width: 900px) {
    .clock-banner { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  }
  @media (max-width: 700px) {
    main { width: calc(100% - 24px); }
    header { padding: 12px; }
    .orbit .stage { height: 420px; }
    .bands .stage { height: 300px; }
    .spark-stage { height: 200px; }
    #stack .k, #stack canvas { width: min(100%, 720px); }
    button, input, select, textarea { font-size: 16px; }
    button { min-height: 44px; }
    .link-form button, .link-remove { font-size: 16px; letter-spacing: 0.04em; }
    pre { height: auto; min-height: 180px; max-height: 50vh; }
  }
  @media (max-width: 560px) {
    .clock-banner { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
</style>
</head>
<body>
<div class="topbar">
<header>
  <svg class="mark" viewBox="0 0 32 32" aria-hidden="true">
    <circle cx="16" cy="16" r="2.2" fill="#f4f4f4"/>
    <ellipse cx="16" cy="16" rx="12" ry="4.6" fill="none" stroke="#f4f4f4" stroke-width="1.3"/>
    <ellipse cx="16" cy="16" rx="12" ry="4.6" fill="none" stroke="#f4f4f4" stroke-width="1.3" transform="rotate(60 16 16)"/>
    <ellipse cx="16" cy="16" rx="12" ry="4.6" fill="none" stroke="#f4f4f4" stroke-width="1.3" transform="rotate(120 16 16)"/>
  </svg>
  <h1>Sinatra Audit</h1>
  <div class="grow"></div>
  <div class="pill" id="sat">44713</div>
  <div class="pill" id="cycle">CYCLE —</div>
  <div class="pill" id="phase">BOOT</div>
  <div class="pill" id="feed">FEED</div>
  <div class="pill" id="clock">—</div>
</header>
<div id="clocks" class="clock-banner" aria-label="Clocks"></div>
</div>
<main>
  <section class="card plot orbit">
    <p class="k" id="orbit-k">Earth view</p>
    <ul class="legend" aria-label="Earth view legend">
      <li><i style="color:#ffffff"></i>Sweep orbits</li>
      <li><i style="color:#d7e4ff"></i>Station / payload</li>
      <li><i style="color:#c084fc"></i>Debris</li>
      <li><i class="dashed" style="color:#c084fc"></i>Public last plane</li>
    </ul>
    <div class="stage"><canvas id="orbit"></canvas></div>
  </section>
  <section class="card">
    <p class="k">Positions</p>
    <div id="roster"><p class="empty">Waiting for the catalog.</p></div>
  </section>
  <section class="card dash">
    <p class="k">System</p>
    <div id="env" class="dash-grid"><p class="empty">Waiting for the HUD.</p></div>
  </section>
  <section class="card dash">
    <p class="k">Network</p>
    <div id="net"><p class="empty">Waiting for the HUD.</p></div>
  </section>
  <section class="card dash">
    <p class="k">API links</p>
    <ul class="legend" aria-label="Link catalog legend">
      <li><i class="dot" style="color:#30d158"></i>Live feed answering</li>
      <li><i class="dot" style="color:#ff3b30"></i>Inactive or fallback</li>
      <li>Added links stay in the catalog and are not requested</li>
    </ul>
    <div id="links" class="link-scroll"><p class="empty">Waiting for the catalog.</p></div>
    <form class="link-form" id="link-form">
      <label>Name<input id="link-name" name="name" maxlength="80" required autocomplete="off"></label>
      <label>URL<input id="link-url" name="url" type="url" maxlength="500" required autocomplete="off" placeholder="https://"></label>
      <label>Note<input id="link-note" name="note" maxlength="240" autocomplete="off"></label>
      <button type="submit">Add link</button>
      <p class="note link-msg" id="link-msg">Added links are stored in the catalog. The cycle still calls the live feeds. An added link is a potential feed.</p>
    </form>
  </section>
  <section class="card plot bands">
    <p class="k">Altitude bands</p>
    <ul class="legend" aria-label="Altitude band legend">
      <li><i style="color:#ffffff"></i>Station</li>
      <li><i style="color:#d7e4ff"></i>Payload</li>
      <li><i style="color:#c084fc"></i>Debris</li>
      <li>Scale 150 to 1500 km. A thicker mark is the object in the sweep.</li>
    </ul>
    <div class="stage"><canvas id="bands"></canvas></div>
  </section>
  <section class="card">
    <p class="k">Space weather</p>
    <ul class="legend" aria-label="Space weather legend">
      <li><i class="dot" style="color:#ffffff"></i>NOAA live</li>
      <li><i class="dot" style="color:#ff3b30"></i>Built-in fallback</li>
      <li>Bx By Bz are nT. Wind is km/s. Southward Bz is negative.</li>
    </ul>
    <div id="wx"><p class="empty">Waiting for the cycle.</p></div>
  </section>
  <section class="card">
    <p class="k">Active track</p>
    <ul class="legend" aria-label="Active track legend">
      <li><i style="color:#ffffff"></i>SINTRA km</li>
      <li><i style="color:#ff3b30"></i>IMM km</li>
      <li><i style="color:#8a8a8a"></i>Particle filter km</li>
      <li>Log scale from 0.01 to about 4000 km</li>
    </ul>
    <div id="active"><p class="empty">No object in the sweep yet.</p></div>
    <div class="spark-stage"><canvas id="spark"></canvas></div>
  </section>
  <section class="card">
    <p class="k">Starlink 1007 · sweep state</p>
    <div id="idcard"><p class="empty">Waiting for the catalog.</p></div>
  </section>
  <section class="card">
    <p class="k" id="elem-k">Keplerian elements</p>
    <div id="elem"><p class="empty">Waiting for the catalog.</p></div>
  </section>
  <section class="card">
    <p class="k" id="geom-k">State · this cycle</p>
    <div id="geom"><p class="empty">Waiting for the catalog.</p></div>
  </section>
  <section class="card">
    <p class="k">Public record · 44713</p>
    <div id="record"></div>
  </section>
  <section class="card table">
    <p class="k">Catalog · same sweep as the terminal</p>
    <ul class="legend" aria-label="Catalog legend">
      <li><i style="color:#ffffff"></i>Station</li>
      <li><i style="color:#d7e4ff"></i>Payload</li>
      <li><i style="color:#ff3b30"></i>Debris class</li>
      <li>SINTRA, IMM, and PF are kilometer error for that object</li>
    </ul>
    <div id="table"></div>
  </section>
  <section class="card">
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
  <section class="card dash">
    <p class="k">Listeners</p>
    <div class="ftp-actions">
      <button type="button" id="listeners-up">Up all</button>
      <button type="button" id="listeners-down">Down all</button>
    </div>
    <p class="note link-msg" id="listeners-msg"></p>
  </section>
  <section class="card dash">
    <p class="k">ICMP</p>
    <p class="note" id="ping-status">ICMP pinger is down.</p>
    <form class="link-form" id="ping-form">
      <label>Target<input id="ping-host" type="text" maxlength="253" autocomplete="off" placeholder="127.0.0.1" value="127.0.0.1"></label>
      <label>Frequency ms<input id="ping-ms" type="number" min="100" max="60000" step="1" value="1000"></label>
      <div class="ftp-actions">
        <button type="button" id="ping-up">Up</button>
        <button type="button" id="ping-down">Down</button>
      </div>
      <p class="note link-msg" id="ping-msg"></p>
    </form>
  </section>
  <section class="card dash">
    <p class="k">Files</p>
    <p class="note" id="ftp-status">FTP server starting.</p>
    <form class="link-form" id="ftp-form">
      <label>FTP link<input id="ftp-url" type="text" maxlength="500" autocomplete="off" placeholder="ftp://127.0.0.1:2121/"></label>
      <div class="ftp-actions">
        <button type="button" id="ftp-server-up">Up</button>
        <button type="button" id="ftp-server-down">Down</button>
        <button type="button" id="ftp-connect">Connect</button>
        <button type="button" id="ftp-refresh">Refresh</button>
        <button type="button" id="ftp-up">Folder up</button>
      </div>
      <div id="ftp-list" class="link-scroll"></div>
      <label>File<input id="ftp-name" type="text" maxlength="180" autocomplete="off" placeholder="notes.txt"></label>
      <label>Text<textarea id="ftp-text" spellcheck="false"></textarea></label>
      <div class="ftp-actions">
        <button type="button" id="ftp-open">Open</button>
        <button type="button" id="ftp-save">Save</button>
      </div>
      <p class="note link-msg" id="ftp-msg"></p>
    </form>
  </section>
  <section class="card dash">
    <p class="k">TFTP</p>
    <p class="note" id="tftp-status">TFTP server starting.</p>
    <form class="link-form" id="tftp-form">
      <label>TFTP link<input id="tftp-url" type="text" maxlength="500" autocomplete="off" placeholder="tftp://127.0.0.1:6969/"></label>
      <div class="ftp-actions">
        <button type="button" id="tftp-up">Up</button>
        <button type="button" id="tftp-down">Down</button>
        <button type="button" id="tftp-connect">Connect</button>
        <button type="button" id="tftp-refresh">Refresh</button>
      </div>
      <div id="tftp-list" class="link-scroll"></div>
      <label>File<input id="tftp-name" type="text" maxlength="180" autocomplete="off" placeholder="notes.txt"></label>
      <label>Text<textarea id="tftp-text" spellcheck="false"></textarea></label>
      <div class="ftp-actions">
        <button type="button" id="tftp-receive">Receive</button>
        <button type="button" id="tftp-send">Send</button>
      </div>
      <p class="note link-msg" id="tftp-msg"></p>
    </form>
  </section>
  <section class="card dash">
    <p class="k">SNMP</p>
    <p class="note" id="snmp-status">SNMP agent starting.</p>
    <form class="link-form" id="snmp-form">
      <label>SNMP link<input id="snmp-url" type="text" maxlength="500" autocomplete="off" placeholder="snmp://127.0.0.1:1161/"></label>
      <label>OID<input id="snmp-oid" type="text" maxlength="200" autocomplete="off" value="1.3.6.1.2.1.1.1.0"></label>
      <label>Value<input id="snmp-value" type="text" maxlength="200" autocomplete="off" placeholder="set value"></label>
      <div class="ftp-actions">
        <button type="button" id="snmp-up">Up</button>
        <button type="button" id="snmp-down">Down</button>
        <button type="button" id="snmp-get">Get</button>
        <button type="button" id="snmp-next">Next</button>
        <button type="button" id="snmp-walk">Walk</button>
        <button type="button" id="snmp-set">Set</button>
      </div>
      <pre id="snmp-out"></pre>
      <p class="note link-msg" id="snmp-msg"></p>
    </form>
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
  d.className = "field";
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
let hostStamp = "";
function lamp(on) {
  const mark = document.createElement("i");
  mark.className = "lamp" + (on ? " on" : "");
  mark.setAttribute("aria-label", on ? "Active" : "Inactive");
  return mark;
}
function tile(label, value, on) {
  const d = document.createElement("div");
  d.className = "tile";
  const s = document.createElement("span");
  if (on !== undefined) s.append(lamp(!!on));
  s.append(document.createTextNode(label));
  const b = document.createElement("b");
  b.textContent = value;
  d.append(s, b);
  return d;
}
function linkIsActive(item, s) {
  if (item.kind !== "live") return false;
  const url = String(item.url || "");
  const weather = s.weather || {};
  if (url.includes("swpc.noaa.gov")) return !!weather.live;
  const match = url.match(/CATNR=(\\d+)/i);
  if (!match) return false;
  const id = Number(match[1]);
  const row = (s.catalog || []).find((entry) => Number(entry.norad_id) === id);
  if (!row) return false;
  const source = String(row.source || "").toUpperCase();
  return source.includes("LIVE") && !source.includes("FALLBACK");
}
function addrObject(item) {
  const d = document.createElement("div");
  d.className = "addr";
  const main = document.createElement("div");
  main.className = "addr-main";
  const top = document.createElement("div");
  top.className = "addr-top";
  const name = document.createElement("b");
  name.textContent = item.iface || "—";
  const state = document.createElement("em");
  const bits = [item.up ? "Active" : "Inactive"];
  if (item.gateway) bits.push("gateway " + item.gateway);
  if (item.source) bits.push(item.source);
  state.textContent = bits.join(" · ");
  top.append(name, state);
  const ip = document.createElement("span");
  ip.className = "addr-ip";
  const prefix = item.prefix === null || item.prefix === undefined || item.prefix === "" ? "" : "/" + item.prefix;
  ip.textContent = (item.address || "—") + prefix;
  main.append(top, ip);
  d.append(lamp(!!item.up), main);
  return d;
}
function netGroup(title, rows, emptyText) {
  const wrap = document.createElement("div");
  wrap.className = "net-group";
  const head = document.createElement("p");
  head.className = "k sub";
  const up = rows.some((item) => item.up);
  head.append(lamp(rows.length > 0 && up), document.createTextNode(title));
  const scroll = document.createElement("div");
  scroll.className = "net-scroll";
  if (!rows.length) {
    scroll.append(Object.assign(document.createElement("p"), {className: "empty", textContent: emptyText}));
  } else {
    rows.forEach((item) => scroll.append(addrObject(item)));
  }
  wrap.append(head, scroll);
  return wrap;
}
function fillHost(s) {
  const weather = s.weather || {};
  const catalogStamp = (s.catalog || []).map((entry) => [entry.norad_id, entry.source]);
  const stamp = JSON.stringify({
    environment: s.environment || {},
    network: s.network || {},
    links: s.links || [],
    live: !!weather.live,
    catalog: catalogStamp
  });
  if (stamp === hostStamp) return;
  const linkBox = $("links");
  const savedLink = linkBox.scrollTop;
  const savedNet = [...document.querySelectorAll("#net .net-scroll")].map((el) => el.scrollTop);
  hostStamp = stamp;
  const env = s.environment || {};
  const envBox = $("env");
  envBox.replaceChildren();
  if (!env.host) {
    envBox.append(Object.assign(document.createElement("p"), {className: "empty", textContent: "Waiting for the HUD."}));
  } else {
    const facts = [
      ["User", env.user || "—"],
      ["UID", String(env.uid) + " / " + String(env.gid)],
      ["Host", env.host || "—"],
      ["System", env.platform || "—"],
      ["Python", env.python || "—"],
      ["Working directory", env.cwd || "—"],
      ["Output directory", env.output || "—"],
      ["HUD", env.hud || "—"],
      ["Process", String(env.pid || "—"), true],
      ["Link catalog", env.links_db || "—"]
    ];
    facts.forEach((item) => envBox.append(tile(item[0], item[1], item[2])));
    Object.keys(env.env || {}).forEach((key) => envBox.append(tile(key, env.env[key])));
  }
  const net = s.network || {};
  const netBox = $("net");
  netBox.replaceChildren();
  netBox.append(netGroup("All network addresses", net.interfaces || [], "No addresses on this host."));
  netBox.append(netGroup("Docker addresses", net.docker || [], "No Docker address."));
  netBox.append(netGroup("Kubernetes addresses", net.kubernetes || [], "No Kubernetes address."));
  netBox.append(netGroup("Host computer LAN", net.host_lan || [], "No host LAN address."));
  const wan = net.wan || {};
  const wanUp = !!wan.address;
  const wanRow = {
    iface: "WAN",
    address: wan.address || wan.error || "Looking up",
    up: wanUp
  };
  const wanBits = [wanUp ? "Active" : "Inactive"];
  if (wan.source) wanBits.push(wan.source);
  if (wan.checked) wanBits.push(wan.checked);
  const wanWrap = netGroup("WAN", [wanRow], "Looking up the WAN address.");
  const wanState = wanWrap.querySelector("em");
  if (wanState) wanState.textContent = wanBits.join(" · ");
  netBox.append(wanWrap);
  [...netBox.querySelectorAll(".net-scroll")].forEach((el, index) => {
    if (index < savedNet.length) el.scrollTop = savedNet[index];
  });
  linkBox.replaceChildren();
  const links = s.links || [];
  if (!links.length) {
    linkBox.append(Object.assign(document.createElement("p"), {className: "empty", textContent: "No links in the catalog yet."}));
  } else {
    links.forEach((item) => {
      const active = linkIsActive(item, s);
      const obj = document.createElement("div");
      obj.className = "link-obj";
      const main = document.createElement("div");
      main.className = "link-main";
      const top = document.createElement("div");
      top.className = "link-top";
      const name = document.createElement("b");
      name.textContent = item.name || "Link";
      const state = document.createElement("em");
      state.textContent = active ? "Active" : "Inactive";
      top.append(name, state);
      const url = document.createElement("span");
      url.className = "link-url";
      url.textContent = item.url || "—";
      main.append(top, url);
      if (item.note) {
        main.append(Object.assign(document.createElement("p"), {className: "note", textContent: item.note}));
      }
      if (item.kind === "added") {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "link-remove";
        btn.dataset.id = String(item.id);
        btn.textContent = "Remove";
        main.append(btn);
      }
      obj.append(lamp(active), main);
      linkBox.append(obj);
    });
  }
  linkBox.scrollTop = savedLink;
}
function render(s) {
  fillHost(s);
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
  paintClocks();
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
  const frag = document.createDocumentFragment();
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
    frag.append(label, canvas);
  });
  stack.replaceChildren(frag);
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
  if (c.includes("DEBRIS") || c.includes("DEB")) return "#c084fc";
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
  const w = Math.max(1, Math.round(c.clientWidth || fallbackW));
  const h = Math.max(1, Math.round(c.clientHeight || fallbackH));
  const bw = Math.max(1, Math.floor(w * dpr));
  const bh = Math.max(1, Math.floor(h * dpr));
  if (c.width !== bw || c.height !== bh) {
    c.width = bw;
    c.height = bh;
  }
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
      const border = land !== landAt(lon + 0.5, lat)
        || land !== landAt(lon - 0.5, lat)
        || land !== landAt(lon, lat + 0.5)
        || land !== landAt(lon, lat - 0.5);
      let cr, cg, cb;
      if (border) {
        cr = 255; cg = 59; cb = 48;
      } else {
        cr = 0; cg = 0; cb = 0;
      }
      data[o] = Math.max(0, Math.min(255, cr));
      data[o + 1] = Math.max(0, Math.min(255, cg));
      data[o + 2] = Math.max(0, Math.min(255, cb));
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
      const border = land !== landAt(lon + 0.5, lat)
        || land !== landAt(lon - 0.5, lat)
        || land !== landAt(lon, lat + 0.5)
        || land !== landAt(lon, lat - 0.5);
      const o = (y * MASK_W + x) * 4;
      if (border) {
        data[o] = 255; data[o + 1] = 59; data[o + 2] = 48;
      } else {
        data[o] = 0; data[o + 1] = 0; data[o + 2] = 0;
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
  g.strokeStyle = "rgba(255,59,48,0.16)";
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
  g.strokeStyle = "rgba(255,59,48,0.18)";
  g.lineWidth = 4;
  g.stroke();
  g.beginPath();
  g.arc(cx, cy, radius, 0, Math.PI * 2);
  g.strokeStyle = "#ff3b30";
  g.lineWidth = 1.15;
  g.stroke();
  const pole = proj(ecef(90, 0, RE_KM));
  if (pole.depth > 0) {
    const x = cx + pole.x * scale;
    const y = cy - pole.y * scale;
    g.fillStyle = "#ff3b30";
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
    if (title) title.textContent = "Earth view";
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
  const plotW = view.w;
  const plotH = view.h;
  let maxR = pubSma || (RE_KM + 550);
  live.forEach((p) => { if (p.r > maxR) maxR = p.r; });
  const scale = Math.min(plotW - 28, plotH - 48) * 0.46 / maxR * viewCam.zoom;
  const cx = plotW * 0.5;
  const cy = plotH * 0.46;
  const proj = projector(earthCamera());
  c.dataset.plotW = String(plotW);
  c.dataset.plotH = String(plotH);
  c.dataset.globeCx = String(cx);
  c.dataset.globeCy = String(cy);
  c.dataset.globeR = String(RE_KM * scale);
  strokeRing(g, proj, pub, scale, cx, cy, "rgba(192,132,252,0.40)", 1, [4, 4], true);
  rings.forEach((ring) => {
    const hero = Number(ring.p.src.norad_id) === 44713;
    const color = hero ? "rgba(255,255,255,0.30)" : fade(toneOf(ring.p.src), 0.22);
    strokeRing(g, proj, ring.pts, scale, cx, cy, color, 1, [], true);
  });
  drawEarth(g, proj, scale, cx, cy);
  strokeRing(g, proj, pub, scale, cx, cy, "#c084fc", 1.05, [5, 4], false);
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
    ["#c084fc", false, "debris"],
    ["#c084fc", true, "public last plane"]
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
    if (pair[0] === "_note") box.append(Object.assign(document.createElement("p"), { className: "note", textContent: pair[1] }));
    else box.append(row(pair[0], pair[1]));
  });
}
function apsis(t) {
  const a = Number(t && t.sma_km);
  const e = Number(t && t.eccentricity);
  if (!Number.isFinite(a) || !Number.isFinite(e)) return [null, null];
  return [a * (1 - e) - RE_KM, a * (1 + e) - RE_KM];
}
function fillRoster(cat, act) {
  const box = $("roster");
  if (!box) return;
  box.replaceChildren();
  if (!cat || !cat.length) {
    box.append(Object.assign(document.createElement("p"), { className: "empty", textContent: "Waiting for the catalog." }));
    return;
  }
  cat.forEach((t) => {
    const on = act && Number(act.norad_id) === Number(t.norad_id);
    const d = document.createElement("div");
    d.className = "field" + (on ? " on" : "");
    const s = document.createElement("span");
    s.textContent = String(t.norad_id) + "  " + (t.name || "");
    const b = document.createElement("b");
    [n(t.lat, 2) + "° latitude", n(t.lon, 2) + "° longitude", n(t.altitude_km, 1) + " km altitude"].forEach((line) => {
      const p = document.createElement("span");
      p.className = "line";
      p.textContent = line;
      b.append(p);
    });
    d.append(s, b);
    box.append(d);
  });
}
function fillOrbitPanels(cat, act) {
  fillRoster(cat, act);
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
  const right = 64;
  const top = 8;
  const rowH = (view.h - 16) / cat.length;
  g.font = hudFont(13);
  let labelW = 96;
  cat.forEach((t) => {
    const label = String(t.norad_id) + "  " + String(t.name || "");
    labelW = Math.max(labelW, g.measureText(label).width + 18);
  });
  labelW = Math.min(labelW, Math.max(120, view.w - right - 96));
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
    g.fillStyle = "#cfcfcf";
    g.font = hudFont(13);
    g.fillText(String(t.norad_id) + "  " + String(t.name || ""), 8, y + rowH * 0.62);
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
function drawSpark(act) {
  const c = $("spark");
  if (!c) return;
  const view = fitCanvas(c, 900, 88);
  const g = view.g;
  const w = view.w;
  const h = view.h;
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
    const rect = c.getBoundingClientRect();
    const gx = Number(c.dataset.globeCx);
    const gy = Number(c.dataset.globeCy);
    const gr = Number(c.dataset.globeR);
    if (!gr) return;
    const x = ev.clientX - rect.left;
    const y = ev.clientY - rect.top;
    const dx = x - gx;
    const dy = y - gy;
    if (dx * dx + dy * dy > gr * gr) return;
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
$("link-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const msg = $("link-msg");
  msg.textContent = "";
  const body = {
    name: $("link-name").value,
    url: $("link-url").value,
    note: $("link-note").value
  };
  try {
    const res = await fetch("/api/links", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)
    });
    const data = await res.json();
    if (!res.ok) {
      msg.textContent = data.error || "Could not add that link.";
      return;
    }
    if (data.existed) msg.textContent = "That URL is already in the catalog.";
    else {
      $("link-name").value = "";
      $("link-url").value = "";
      $("link-note").value = "";
      msg.textContent = "Saved in the link catalog.";
    }
    tick();
  } catch (err) {
    msg.textContent = "Could not reach the HUD.";
  }
});
let ftpDir = "";
function ftpMsg(text) {
  $("ftp-msg").textContent = text || "";
}
function ftpQuery() {
  return "dir=" + encodeURIComponent(ftpDir) + "&name=" + encodeURIComponent($("ftp-name").value || "");
}
function paintFtp(data) {
  const box = $("ftp-list");
  const status = $("ftp-status");
  if (!data) {
    box.replaceChildren();
    return;
  }
  ftpDir = data.dir || "";
  const where = data.target || data.url || "FTP offline";
  const root = data.running ? "listening" : "offline";
  status.textContent = root + " · " + where + (ftpDir ? " · " + ftpDir : "");
  if (data.url && !$("ftp-url").value) $("ftp-url").value = data.url;
  box.replaceChildren();
  const entries = data.entries || [];
  if (!entries.length) {
    box.append(Object.assign(document.createElement("p"), {className: "empty", textContent: "No files yet. Type a name and Save."}));
    return;
  }
  entries.forEach((item) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "link-remove ftp-link";
    btn.dataset.name = item.name;
    btn.dataset.dir = item.dir ? "1" : "";
    btn.textContent = (item.dir ? "Folder · " : "File · ") + item.name;
    box.append(btn);
  });
}
async function ftpList() {
  const res = await fetch("/api/ftp?dir=" + encodeURIComponent(ftpDir), {cache: "no-store"});
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Could not list that folder.");
  paintFtp(data);
}
$("ftp-connect").addEventListener("click", async () => {
  ftpMsg("");
  try {
    const res = await fetch("/api/ftp/connect", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url: $("ftp-url").value})
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not use that FTP link.");
    ftpDir = "";
    $("ftp-url").value = data.target || data.url || $("ftp-url").value;
    await ftpList();
    ftpMsg("Connected.");
  } catch (err) {
    ftpMsg(err.message || "Could not connect.");
  }
});
$("ftp-refresh").addEventListener("click", async () => {
  ftpMsg("");
  try { await ftpList(); }
  catch (err) { ftpMsg(err.message || "Could not refresh."); }
});
$("ftp-up").addEventListener("click", async () => {
  ftpMsg("");
  const parts = ftpDir.split("/").filter(Boolean);
  parts.pop();
  ftpDir = parts.join("/");
  try { await ftpList(); }
  catch (err) { ftpMsg(err.message || "Could not open that folder."); }
});
$("ftp-list").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-name]");
  if (!btn) return;
  if (btn.dataset.dir) {
    ftpDir = (ftpDir ? ftpDir + "/" : "") + btn.dataset.name;
    ftpMsg("");
    try { await ftpList(); }
    catch (err) { ftpMsg(err.message || "Could not open that folder."); }
    return;
  }
  $("ftp-name").value = btn.dataset.name;
  ftpMsg(btn.dataset.name);
});
$("ftp-open").addEventListener("click", async () => {
  ftpMsg("");
  try {
    const res = await fetch("/api/ftp/open?" + ftpQuery(), {cache: "no-store"});
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not open that file.");
    $("ftp-name").value = data.name || $("ftp-name").value;
    $("ftp-text").value = data.text || "";
    ftpMsg("Opened " + (data.name || "file") + ".");
  } catch (err) {
    ftpMsg(err.message || "Could not open that file.");
  }
});
$("ftp-save").addEventListener("click", async () => {
  ftpMsg("");
  try {
    const res = await fetch("/api/ftp/save", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({dir: ftpDir, name: $("ftp-name").value, text: $("ftp-text").value})
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not save that file.");
    await ftpList();
    ftpMsg("Saved " + (data.name || "file") + ".");
  } catch (err) {
    ftpMsg(err.message || "Could not save that file.");
  }
});
$("ftp-form").addEventListener("submit", (ev) => ev.preventDefault());
ftpList().catch((err) => ftpMsg(err.message || "FTP server is not ready."));
async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body || {})
  });
  let data = {};
  try { data = await res.json(); } catch (err) { data = {}; }
  if (!res.ok) throw new Error(data.error || "Request failed.");
  return data;
}
$("ftp-server-up").addEventListener("click", async () => {
  ftpMsg("");
  try {
    const data = await postJson("/api/ftp/start", {});
    if (data.url) $("ftp-url").value = data.url;
    await ftpList();
    ftpMsg("FTP server is up.");
  } catch (err) { ftpMsg(err.message || "Could not start FTP."); }
});
$("ftp-server-down").addEventListener("click", async () => {
  ftpMsg("");
  try {
    const data = await postJson("/api/ftp/stop", {});
    paintFtp(data);
    ftpMsg("FTP server is down.");
  } catch (err) { ftpMsg(err.message || "Could not stop FTP."); }
});
function paintPing(data) {
  if (!data) return;
  const rtt = data.rtt_ms == null ? "" : " · " + data.rtt_ms + " ms";
  $("ping-status").textContent = (data.running ? "up" : "down")
    + " · " + (data.host || "")
    + " · " + data.interval_ms + " ms"
    + " · sent " + (data.sent || 0)
    + " · received " + (data.received || 0)
    + rtt
    + " · loss " + (data.loss_pct == null ? "0" : data.loss_pct) + "%"
    + (data.error ? " · " + data.error : "");
}
$("ping-up").addEventListener("click", async () => {
  $("ping-msg").textContent = "";
  try {
    paintPing(await postJson("/api/ping", {
      host: $("ping-host").value,
      interval_ms: Number($("ping-ms").value),
      up: true
    }));
    $("ping-msg").textContent = "Pinger is up.";
  } catch (err) { $("ping-msg").textContent = err.message || "Could not start the pinger."; }
});
$("ping-down").addEventListener("click", async () => {
  $("ping-msg").textContent = "";
  try {
    paintPing(await postJson("/api/ping", {up: false}));
    $("ping-msg").textContent = "Pinger is down.";
  } catch (err) { $("ping-msg").textContent = err.message || "Could not stop the pinger."; }
});
$("ping-form").addEventListener("submit", (ev) => ev.preventDefault());
async function pingStatus() {
  try {
    const res = await fetch("/api/ping", {cache: "no-store"});
    if (res.ok) paintPing(await res.json());
  } catch (err) { /* leave the last line */ }
}
pingStatus();
setInterval(pingStatus, 1000);
function paintTftp(data) {
  const box = $("tftp-list");
  const status = $("tftp-status");
  if (!data) { box.replaceChildren(); return; }
  const where = data.target || data.url || "TFTP offline";
  status.textContent = (data.running ? "up" : "down") + " · " + where + (data.note ? " · " + data.note : "");
  if (data.url && !$("tftp-url").value) $("tftp-url").value = data.url;
  box.replaceChildren();
  const entries = data.entries || [];
  if (!entries.length) {
    box.append(Object.assign(document.createElement("p"), {className: "empty", textContent: data.note || "No files yet. Type a name and Send."}));
    return;
  }
  entries.forEach((item) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "link-remove ftp-link";
    btn.dataset.name = item.name;
    btn.textContent = item.name;
    box.append(btn);
  });
}
async function tftpList() {
  const res = await fetch("/api/tftp", {cache: "no-store"});
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Could not list TFTP files.");
  paintTftp(data);
}
function tftpMsg(text) { $("tftp-msg").textContent = text || ""; }
$("tftp-up").addEventListener("click", async () => {
  tftpMsg("");
  try {
    const data = await postJson("/api/tftp/start", {});
    if (data.url) $("tftp-url").value = data.url;
    await tftpList();
    tftpMsg("TFTP server is up.");
  } catch (err) { tftpMsg(err.message || "Could not start TFTP."); }
});
$("tftp-down").addEventListener("click", async () => {
  tftpMsg("");
  try { paintTftp(await postJson("/api/tftp/stop", {})); tftpMsg("TFTP server is down."); }
  catch (err) { tftpMsg(err.message || "Could not stop TFTP."); }
});
$("tftp-connect").addEventListener("click", async () => {
  tftpMsg("");
  try {
    const data = await postJson("/api/tftp/connect", {url: $("tftp-url").value});
    $("tftp-url").value = data.target || data.url || $("tftp-url").value;
    await tftpList();
    tftpMsg("Connected.");
  } catch (err) { tftpMsg(err.message || "Could not connect."); }
});
$("tftp-refresh").addEventListener("click", async () => {
  tftpMsg("");
  try { await tftpList(); } catch (err) { tftpMsg(err.message || "Could not refresh."); }
});
$("tftp-list").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button[data-name]");
  if (!btn) return;
  $("tftp-name").value = btn.dataset.name;
  tftpMsg(btn.dataset.name);
});
$("tftp-receive").addEventListener("click", async () => {
  tftpMsg("");
  try {
    const res = await fetch("/api/tftp/open?name=" + encodeURIComponent($("tftp-name").value || ""), {cache: "no-store"});
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not receive that file.");
    $("tftp-name").value = data.name || $("tftp-name").value;
    $("tftp-text").value = data.text || "";
    tftpMsg("Received " + (data.name || "file") + ".");
  } catch (err) { tftpMsg(err.message || "Could not receive that file."); }
});
$("tftp-send").addEventListener("click", async () => {
  tftpMsg("");
  try {
    const data = await postJson("/api/tftp/save", {name: $("tftp-name").value, text: $("tftp-text").value});
    await tftpList();
    tftpMsg("Sent " + (data.name || "file") + ".");
  } catch (err) { tftpMsg(err.message || "Could not send that file."); }
});
$("tftp-form").addEventListener("submit", (ev) => ev.preventDefault());
tftpList().catch((err) => tftpMsg(err.message || "TFTP server is not ready."));
function paintSnmp(data) {
  if (!data) return;
  const where = data.target || data.url || "SNMP offline";
  $("snmp-status").textContent = (data.running ? "up" : "down") + " · " + where;
  if (data.url && !$("snmp-url").value) $("snmp-url").value = data.url;
  const rows = data.rows || [];
  if (!rows.length) return;
  $("snmp-out").textContent = rows.map((row) => row.oid + "  " + row.type + "  " + row.value).join("\\n");
}
function snmpMsg(text) { $("snmp-msg").textContent = text || ""; }
async function snmpAct(path, extra) {
  snmpMsg("");
  try {
    const data = await postJson(path, Object.assign({
      url: $("snmp-url").value,
      oid: $("snmp-oid").value,
      value: $("snmp-value").value
    }, extra || {}));
    if (data.target) $("snmp-url").value = data.target;
    paintSnmp(data);
  } catch (err) { snmpMsg(err.message || "SNMP request failed."); }
}
$("snmp-up").addEventListener("click", () => snmpAct("/api/snmp/start", {}));
$("snmp-down").addEventListener("click", () => snmpAct("/api/snmp/stop", {}));
$("snmp-get").addEventListener("click", () => snmpAct("/api/snmp/get", {}));
$("snmp-next").addEventListener("click", () => snmpAct("/api/snmp/next", {}));
$("snmp-walk").addEventListener("click", () => snmpAct("/api/snmp/walk", {}));
$("snmp-set").addEventListener("click", () => snmpAct("/api/snmp/set", {}));
$("snmp-form").addEventListener("submit", (ev) => ev.preventDefault());
fetch("/api/snmp", {cache: "no-store"}).then((res) => res.json()).then(paintSnmp).catch(() => {});
$("listeners-up").addEventListener("click", async () => {
  $("listeners-msg").textContent = "";
  try {
    const data = await postJson("/api/listeners/up", {});
    if (data.ftp && data.ftp.url) $("ftp-url").value = data.ftp.url;
    if (data.tftp && data.tftp.url) $("tftp-url").value = data.tftp.url;
    if (data.snmp && data.snmp.url) $("snmp-url").value = data.snmp.url;
    await ftpList();
    await tftpList();
    paintSnmp(data.snmp || {});
    $("listeners-msg").textContent = "FTP, TFTP, and SNMP are up.";
  } catch (err) { $("listeners-msg").textContent = err.message || "Could not start the listeners."; }
});
$("listeners-down").addEventListener("click", async () => {
  $("listeners-msg").textContent = "";
  try {
    const data = await postJson("/api/listeners/down", {});
    paintFtp(data.ftp || {});
    paintTftp(data.tftp || {});
    paintSnmp(data.snmp || {});
    paintPing(data.icmp || {});
    $("listeners-msg").textContent = "Listeners are down.";
  } catch (err) { $("listeners-msg").textContent = err.message || "Could not stop the listeners."; }
});
$("links").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-id]");
  if (!btn) return;
  const msg = $("link-msg");
  try {
    const res = await fetch("/api/links/" + btn.dataset.id, {method: "DELETE"});
    const data = await res.json();
    msg.textContent = res.ok ? "Removed from the catalog." : (data.error || "Could not remove that link.");
    if (res.ok) tick();
  } catch (err) {
    msg.textContent = "Could not reach the HUD.";
  }
});
const CLOCKS = [
  {id: "local", label: "User local", zone: ""},
  {id: "zulu", label: "Zulu", zone: "UTC", suffix: "Z"},
  {id: "eastern", label: "Eastern", zone: "America/New_York"},
  {id: "gmt", label: "GMT", zone: "UTC"},
  {id: "jerusalem", label: "Jerusalem", zone: "Asia/Jerusalem"},
  {id: "tehran", label: "Tehran", zone: "Asia/Tehran"},
  {id: "tokyo", label: "Tokyo", zone: "Asia/Tokyo"}
];
function militaryParts(date, zone) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: zone,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZoneName: "short"
  }).formatToParts(date);
  const get = (type) => {
    const found = parts.find((part) => part.type === type);
    return found ? found.value : "";
  };
  let hour = get("hour");
  if (hour === "24") hour = "00";
  return {
    time: hour + ":" + get("minute") + ":" + get("second"),
    date: get("day") + " " + get("month") + " " + get("year"),
    name: get("timeZoneName")
  };
}
function paintClocks() {
  const box = $("clocks");
  if (!box) return;
  const now = new Date(serverNow() * 1000);
  if (!box.childElementCount) {
    CLOCKS.forEach((spec) => {
      const tile = document.createElement("div");
      tile.className = "clock-tile";
      tile.dataset.clock = spec.id;
      const label = document.createElement("span");
      label.textContent = spec.label;
      tile.append(label, document.createElement("b"), document.createElement("em"));
      box.append(tile);
    });
  }
  CLOCKS.forEach((spec) => {
    const zone = spec.zone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    const parts = militaryParts(now, zone);
    const tile = box.querySelector('[data-clock="' + spec.id + '"]');
    tile.querySelector("b").textContent = parts.time + (spec.suffix || "");
    const where = spec.id === "local" ? zone : parts.name;
    tile.querySelector("em").textContent = parts.date + " · " + where;
  });
}
tick();
setInterval(tick, 700);
paintClocks();
setInterval(paintClocks, 250);
</script>
</body>
</html>
"""
PAGE = _PAGE.replace("__FLAG_BG__", _flag_data_url())


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
        step = max(1, int(math.ceil(max(image.shape[0], image.shape[1]) / 700)))
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


def _links_db_path():
    override = os.environ.get("SINTRA_LINKS_DB")
    if override:
        return override
    return os.path.join(_output_dir(), "sintra_links.sqlite")


_db_lock = threading.Lock()


def _db():
    conn = sqlite3.connect(_links_db_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def init_links():
    """Create the link catalog and keep the live feeds in it."""
    path = _links_db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with _db_lock:
        conn = _db()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS links (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_utc TEXT NOT NULL
                )
                """
            )
            for name, url, note in _LIVE_LINKS:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO links (name, url, kind, note, created_utc)
                    VALUES (?, ?, 'live', ?, ?)
                    """,
                    (name, url, note, _now()),
                )
            conn.commit()
        finally:
            conn.close()


def list_links():
    init_links()
    with _db_lock:
        conn = _db()
        try:
            rows = conn.execute(
                """
                SELECT id, name, url, kind, note, created_utc
                FROM links
                ORDER BY CASE kind WHEN 'live' THEN 0 ELSE 1 END, id
                """
            ).fetchall()
        finally:
            conn.close()
    return [dict(row) for row in rows]


def _clean_link(payload):
    if not isinstance(payload, dict):
        raise ValueError("Link must be an object.")
    name = str(payload.get("name") or "").strip()
    url = str(payload.get("url") or "").strip()
    note = str(payload.get("note") or "").strip()
    if not name or len(name) > 80:
        raise ValueError("Name must be 1 to 80 characters.")
    if len(note) > 240:
        raise ValueError("Note must be 240 characters or less.")
    if (
        len(url) > 500
        or not url.startswith(("https://", "http://"))
        or any(ch in url for ch in (" ", "\n", "\r"))
    ):
        raise ValueError("URL must start with http:// or https://.")
    return name, url, note


def add_link(payload):
    name, url, note = _clean_link(payload)
    init_links()
    with _db_lock:
        conn = _db()
        try:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO links (name, url, kind, note, created_utc)
                    VALUES (?, ?, 'added', ?, ?)
                    """,
                    (name, url, note, _now()),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT id, name, url, kind, note, created_utc FROM links WHERE id = ?",
                    (cur.lastrowid,),
                ).fetchone()
                return dict(row), False
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT id, name, url, kind, note, created_utc FROM links WHERE url = ?",
                    (url,),
                ).fetchone()
                return dict(row), True
        finally:
            conn.close()


def delete_link(link_id):
    init_links()
    with _db_lock:
        conn = _db()
        try:
            row = conn.execute(
                "SELECT id, kind FROM links WHERE id = ?", (int(link_id),)
            ).fetchone()
            if row is None:
                return "missing"
            if row["kind"] != "added":
                return "live"
            conn.execute("DELETE FROM links WHERE id = ?", (int(link_id),))
            conn.commit()
            return "deleted"
        finally:
            conn.close()


def _env_value(name):
    value = os.environ.get(name)
    if not value:
        return None
    upper = name.upper()
    if any(word in upper for word in ("KEY", "TOKEN", "SECRET", "PASS", "PASSWORD")):
        return None
    return value


def environment_info():
    shown = {}
    for name in (
        "SINTRA_HUD",
        "SINTRA_HUD_HOST",
        "SINTRA_HUD_PORT",
        "SINTRA_OUTPUT",
        "SINTRA_LINKS_DB",
        "MPLBACKEND",
        "HOME",
    ):
        value = _env_value(name)
        if value:
            shown[name] = value
    return {
        "user": getpass.getuser(),
        "uid": os.getuid(),
        "gid": os.getgid(),
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cwd": os.getcwd(),
        "output": _output_dir(),
        "hud": f"{HOST}:{PORT}",
        "pid": os.getpid(),
        "links_db": _links_db_path(),
        "env": shown,
    }


def _ipv4_ok(text):
    parts = text.split(".")
    if len(parts) != 4:
        return False
    try:
        nums = [int(part) for part in parts]
    except ValueError:
        return False
    return all(0 <= num <= 255 for num in nums)


def _public_ipv4(text):
    for match in _IPV4.findall(text or ""):
        if not _ipv4_ok(match):
            continue
        parts = [int(part) for part in match.split(".")]
        if parts[0] in (0, 10, 127):
            continue
        if parts[0] == 192 and parts[1] == 168:
            continue
        if parts[0] == 172 and 16 <= parts[1] <= 31:
            continue
        if parts[0] == 169 and parts[1] == 254:
            continue
        return match
    return None


def _virtual_iface(name):
    text = name.lower()
    return text.startswith(
        ("docker", "veth", "br-", "virbr", "vmnet", "kube", "cali", "dummy", "ifb", "flannel", "cni", "tun", "tap")
    )


def _iface_kind(name):
    text = name.lower()
    if text == "lo":
        return "loopback"
    if text.startswith(("docker", "br-")):
        return "docker"
    if text.startswith(
        ("cni", "flannel", "cali", "kube", "cilium", "weave", "tunl", "vxlan", "lxc")
    ):
        return "kubernetes"
    if _virtual_iface(name):
        return "other"
    return "host"


def _iface_active(name, flags):
    oper = ""
    try:
        with open(f"/sys/class/net/{name}/operstate", encoding="utf-8") as handle:
            oper = handle.read().strip().lower()
    except OSError:
        oper = ""
    if oper == "up":
        return True
    if oper in ("down", "lowerlayerdown", "notpresent"):
        return False
    return bool(flags & 0x1) and bool(flags & 0x40)


def _prefix_len(raw):
    return sum(bin(byte).count("1") for byte in raw)


def interface_addresses():
    """Every IPv4 address on the host, tagged docker, kubernetes, host, or other."""
    found = []
    try:
        names = sorted(os.listdir("/sys/class/net"))
    except OSError:
        names = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for name in names:
            packed = struct.pack("256s", name.encode("utf-8")[:15])
            try:
                addr_res = fcntl.ioctl(sock.fileno(), 0x8915, packed)
                mask_res = fcntl.ioctl(sock.fileno(), 0x891B, packed)
                flag_res = fcntl.ioctl(sock.fileno(), 0x8913, packed)
            except OSError:
                continue
            ip = socket.inet_ntoa(addr_res[20:24])
            if not ip:
                continue
            flags = struct.unpack_from("<H", flag_res, 16)[0]
            found.append(
                {
                    "iface": name,
                    "address": ip,
                    "prefix": _prefix_len(mask_res[20:24]),
                    "up": _iface_active(name, flags),
                    "kind": _iface_kind(name),
                }
            )
    finally:
        sock.close()
    return found


def default_gateway():
    try:
        with open("/proc/net/route", encoding="utf-8") as handle:
            lines = handle.read().splitlines()[1:]
    except OSError:
        return None
    best = None
    for line in lines:
        parts = line.split()
        if len(parts) < 7 or parts[1] != "00000000":
            continue
        try:
            flags = int(parts[3], 16)
            metric = int(parts[6])
            packed = struct.pack("<I", int(parts[2], 16))
        except ValueError:
            continue
        if not flags & 0x2:
            continue
        ip = socket.inet_ntoa(packed)
        if best is None or metric < best["metric"]:
            best = {"iface": parts[0], "address": ip, "metric": metric}
    if not best:
        return None
    return {"iface": best["iface"], "address": best["address"]}


def _wan_tool_path():
    return os.environ.get("WAN_IP_TOOL", "/home/user/git/utils/wan-ip-checker.sh")


def _wan_log_paths():
    paths = []
    home = os.environ.get("HOME")
    if home:
        paths.append(os.path.join(home, ".local", "share", "wan-ip", "wan-ip.csv"))
        paths.append(os.path.join(home, "scripts", "logs", "wan.ip.csv"))
    paths.extend(
        (
            "/home/user/.local/share/wan-ip/wan-ip.csv",
            "/home/user/scripts/logs/wan.ip.csv",
        )
    )
    unique = []
    for path in paths:
        if path not in unique:
            unique.append(path)
    return unique


def _net_from_row(row):
    if len(row) < 3 or row[0].strip().lower() == "date":
        return None
    wan = _public_ipv4(row[2])
    lan = row[3].strip() if len(row) > 3 else ""
    iface = row[4].strip() if len(row) > 4 else ""
    if not _ipv4_ok(lan):
        lan = ""
    if not wan and not lan:
        return None
    return {
        "address": wan,
        "source": "wan-ip-checker",
        "checked": (row[0].strip() + " " + row[1].strip()).strip(),
        "error": "" if wan else "No WAN address in the wan-ip log",
        "lan_address": lan,
        "lan_iface": iface,
        "lan_prefix": None,
        "lan_gateway": "",
    }


def _wan_relay_paths():
    paths = []
    for key in ("WAN_IP_FILE", "SINTRA_WAN_FILE"):
        override = os.environ.get(key)
        if override:
            paths.append(override)
    home = os.environ.get("HOME")
    if home:
        paths.append(os.path.join(home, ".local", "share", "wan-ip", "wan-ip.json"))
    paths.extend(
        (
            "/var/lib/wan-ip/wan-ip.json",
            "/output/wan-ip.json",
            "/home/user/sinatra-sandbox/wan-ip/wan-ip.json",
            "/home/user/sinatra-sandbox/output/wan-ip.json",
            "/home/user/.local/share/wan-ip/wan-ip.json",
        )
    )
    unique = []
    for path in paths:
        if path and path not in unique:
            unique.append(path)
    return unique


def _read_wan_relay():
    for path in _wan_relay_paths():
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and (payload.get("wan") or payload.get("lan")):
            return payload
    return None


def _wan_from_log():
    for path in _wan_log_paths():
        try:
            with open(path, newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
        except OSError:
            continue
        for row in reversed(rows):
            parsed = _net_from_row(row)
            if parsed:
                return parsed
    return None


_net_lock = threading.Lock()
_net_cache = {
    "address": None,
    "source": "",
    "checked": "",
    "error": "",
    "lan_address": "",
    "lan_iface": "",
    "lan_prefix": None,
    "lan_gateway": "",
}
_wan_started = False


def _apply_tool_payload(payload):
    wan = _public_ipv4(str(payload.get("wan") or ""))
    lan = str(payload.get("lan") or "")
    prefix = payload.get("prefix")
    try:
        prefix = int(prefix)
    except (TypeError, ValueError):
        prefix = None
    checked = str(payload.get("checked") or "").strip()
    _net_cache["checked"] = checked or _now()
    if wan:
        _net_cache["address"] = wan
        _net_cache["source"] = "wan-ip-checker"
        _net_cache["error"] = ""
    elif not _net_cache["address"]:
        _net_cache["error"] = str(payload.get("error") or "wan-ip-checker failed")
    if _ipv4_ok(lan):
        _net_cache["lan_address"] = lan
        _net_cache["lan_iface"] = str(payload.get("iface") or "")
        _net_cache["lan_prefix"] = prefix
        _net_cache["lan_gateway"] = str(payload.get("gateway") or "")


def _lookup_wan():
    """Read the shared wan-ip relay. Run the checker when this host has it."""
    payload = None
    tool = _wan_tool_path()
    if os.path.isfile(tool) and os.access(tool, os.X_OK):
        try:
            proc = subprocess.run(
                [tool, "--dry-run", "--json", "--ipv4", "--quiet"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            text = (proc.stdout or "").strip()
            payload = json.loads(text.splitlines()[-1]) if text else None
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, IndexError):
            payload = None
    if not isinstance(payload, dict):
        payload = _read_wan_relay()
    with _net_lock:
        if isinstance(payload, dict):
            _apply_tool_payload(payload)
        elif not _net_cache["address"]:
            _net_cache["error"] = "wan-ip-checker failed"
            _net_cache["checked"] = _now()


def _wan_loop():
    while True:
        _lookup_wan()
        threading.Event().wait(600)


def ensure_wan():
    global _wan_started
    with _net_lock:
        if _wan_started:
            return
        _wan_started = True
        relay = _read_wan_relay()
        if isinstance(relay, dict):
            _apply_tool_payload(relay)
        else:
            logged = _wan_from_log()
            if logged and not _net_cache["address"]:
                _net_cache.update(logged)
    threading.Thread(target=_wan_loop, name="sintra-wan", daemon=True).start()


def network_info():
    ensure_wan()
    with _net_lock:
        wan = {
            "address": _net_cache.get("address"),
            "source": _net_cache.get("source") or "",
            "checked": _net_cache.get("checked") or "",
            "error": _net_cache.get("error") or "",
        }
        lan_tool = {
            "address": _net_cache.get("lan_address") or "",
            "iface": _net_cache.get("lan_iface") or "",
            "prefix": _net_cache.get("lan_prefix"),
            "gateway": _net_cache.get("lan_gateway") or "",
        }
    rows = interface_addresses()
    gateway = default_gateway()
    if gateway:
        for row in rows:
            if row["iface"] == gateway["iface"]:
                row["gateway"] = gateway["address"]

    def of_kind(kind):
        return [row for row in rows if row["kind"] == kind]

    host = of_kind("host")
    if lan_tool["address"]:
        match = None
        for row in rows:
            if lan_tool["iface"] and row["iface"] == lan_tool["iface"]:
                match = row
                break
            if row["address"] == lan_tool["address"]:
                match = row
        host = [
            {
                "iface": lan_tool["iface"] or (match or {}).get("iface") or "lan",
                "address": lan_tool["address"],
                "prefix": lan_tool["prefix"]
                if lan_tool["prefix"] is not None
                else (match or {}).get("prefix"),
                "up": bool(match["up"]) if match else True,
                "kind": "host",
                "gateway": lan_tool["gateway"] or (match or {}).get("gateway") or "",
                "source": "wan-ip-checker",
            }
        ]
    return {
        "interfaces": rows,
        "docker": of_kind("docker"),
        "kubernetes": of_kind("kubernetes"),
        "host_lan": host,
        "gateway": gateway or {},
        "wan": wan,
    }


def _snmp_merge(result):
    payload = sintra_snmp.status()
    if isinstance(result, dict):
        payload.update(result)
    return payload


def _snmp_action(path, body):
    if not isinstance(body, dict):
        body = {}
    if body.get("url"):
        sintra_snmp.set_target(body.get("url"))
    if path.endswith("/start"):
        return sintra_snmp.start_server()
    if path.endswith("/stop"):
        return sintra_snmp.stop_server()
    if path.endswith("/connect"):
        return sintra_snmp.set_target(body.get("url") or "")
    if path.endswith("/get"):
        return _snmp_merge(sintra_snmp.get_oid(body))
    if path.endswith("/next"):
        return _snmp_merge(sintra_snmp.next_oid(body))
    if path.endswith("/walk"):
        return _snmp_merge(sintra_snmp.walk_oid(body))
    if path.endswith("/set"):
        return _snmp_merge(sintra_snmp.set_oid(body))
    raise ValueError("Unknown SNMP request.")


def _listeners_up():
    return {
        "ftp": sintra_ftp.start_server(_output_dir()),
        "tftp": sintra_tftp.start_server(_output_dir()),
        "snmp": sintra_snmp.start_server(),
    }


def _listeners_down():
    return {
        "ftp": sintra_ftp.stop_server(),
        "tftp": sintra_tftp.stop_server(),
        "snmp": sintra_snmp.stop_server(),
        "icmp": sintra_icmp.stop_pinger(),
    }


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
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
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
            try:
                payload["environment"] = environment_info()
                payload["network"] = network_info()
                payload["links"] = list_links()
            except Exception:
                payload["environment"] = payload.get("environment") or {}
                payload["network"] = payload.get("network") or {}
                payload["links"] = payload.get("links") or []
            self._send(200, json.dumps(payload), "application/json")
            return
        if path == "/api/links":
            self._send(200, json.dumps(list_links()), "application/json")
            return
        if path == "/api/ftp":
            self._call_json(lambda: sintra_ftp.listing(query), "FTP")
            return
        if path == "/api/ftp/open":
            self._call_json(lambda: sintra_ftp.open_text(query), "FTP")
            return
        if path == "/api/tftp":
            self._call_json(sintra_tftp.listing, "TFTP")
            return
        if path == "/api/tftp/open":
            self._call_json(lambda: sintra_tftp.open_text(query), "TFTP")
            return
        if path == "/api/ping":
            self._call_json(sintra_icmp.status, "ICMP")
            return
        if path == "/api/snmp":
            self._call_json(sintra_snmp.status, "SNMP")
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

    def _call_json(self, call, label):
        try:
            payload = call()
        except ValueError as exc:
            self._send(400, json.dumps({"error": str(exc)}), "application/json")
            return
        except Exception:
            self._send(500, json.dumps({"error": label + " request failed."}), "application/json")
            return
        self._send(200, json.dumps(payload), "application/json")

    def _optional_json(self, limit=4096):
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        return self._json_body(limit)

    def _json_body(self, limit=4096):
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > limit:
            raise ValueError("Body is too large.")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            raise ValueError("Body is empty.")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Body must be JSON.") from exc

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/ftp/connect":
            try:
                body = self._json_body()
                self._call_json(lambda: sintra_ftp.set_target(body.get("url") if isinstance(body, dict) else ""), "FTP")
            except ValueError as exc:
                self._send(400, json.dumps({"error": str(exc)}), "application/json")
            return
        if path == "/api/ftp/save":
            try:
                body = self._json_body(1_200_000)
            except ValueError as exc:
                self._send(400, json.dumps({"error": str(exc)}), "application/json")
                return
            self._call_json(lambda: sintra_ftp.save_text(body), "FTP")
            return
        if path in ("/api/ftp/start", "/api/ftp/stop"):
            try:
                self._optional_json()
            except ValueError as exc:
                self._send(400, json.dumps({"error": str(exc)}), "application/json")
                return
            if path.endswith("/start"):
                self._call_json(lambda: sintra_ftp.start_server(_output_dir()), "FTP")
            else:
                self._call_json(sintra_ftp.stop_server, "FTP")
            return
        if path == "/api/tftp/connect":
            try:
                body = self._json_body()
            except ValueError as exc:
                self._send(400, json.dumps({"error": str(exc)}), "application/json")
                return
            self._call_json(lambda: sintra_tftp.set_target(body.get("url") if isinstance(body, dict) else ""), "TFTP")
            return
        if path == "/api/tftp/save":
            try:
                body = self._json_body(1_200_000)
            except ValueError as exc:
                self._send(400, json.dumps({"error": str(exc)}), "application/json")
                return
            self._call_json(lambda: sintra_tftp.save_text(body), "TFTP")
            return
        if path == "/api/tftp/start":
            self._call_json(lambda: sintra_tftp.start_server(_output_dir()), "TFTP")
            return
        if path == "/api/tftp/stop":
            self._call_json(sintra_tftp.stop_server, "TFTP")
            return
        if path == "/api/ping":
            try:
                body = self._optional_json()
            except ValueError as exc:
                self._send(400, json.dumps({"error": str(exc)}), "application/json")
                return
            self._call_json(lambda: sintra_icmp.configure(body), "ICMP")
            return
        if path in (
            "/api/snmp/connect",
            "/api/snmp/get",
            "/api/snmp/next",
            "/api/snmp/walk",
            "/api/snmp/set",
            "/api/snmp/start",
            "/api/snmp/stop",
        ):
            try:
                body = self._optional_json(8192)
            except ValueError as exc:
                self._send(400, json.dumps({"error": str(exc)}), "application/json")
                return
            self._call_json(lambda: _snmp_action(path, body), "SNMP")
            return
        if path == "/api/listeners/up":
            self._call_json(_listeners_up, "Listeners")
            return
        if path == "/api/listeners/down":
            self._call_json(_listeners_down, "Listeners")
            return
        if path != "/api/links":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        try:
            row, existed = add_link(self._json_body())
        except ValueError as exc:
            self._send(400, json.dumps({"error": str(exc)}), "application/json")
            return
        except Exception:
            self._send(500, json.dumps({"error": "Could not save the link."}), "application/json")
            return
        body = dict(row)
        body["existed"] = existed
        self._send(200, json.dumps(body), "application/json")

    def do_DELETE(self):
        path = self.path.split("?", 1)[0]
        match = re.fullmatch(r"/api/links/(\d+)", path)
        if not match:
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        try:
            result = delete_link(match.group(1))
        except Exception:
            self._send(500, json.dumps({"error": "Could not remove the link."}), "application/json")
            return
        if result == "missing":
            self._send(404, json.dumps({"error": "That link is not in the catalog."}), "application/json")
            return
        if result == "live":
            self._send(403, json.dumps({"error": "Live feeds stay in the catalog."}), "application/json")
            return
        self._send(200, json.dumps({"ok": True}), "application/json")


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
        try:
            init_links()
        except Exception as exc:
            sys.__stdout__.write(f"[hud] link catalog not opened: {exc}\n")
        ensure_wan()
        for name, starter in (
            ("ftp", lambda: sintra_ftp.ensure_server(_output_dir())),
            ("tftp", lambda: sintra_tftp.ensure_server(_output_dir())),
            ("snmp", lambda: sintra_snmp.ensure_server(_output_dir())),
        ):
            try:
                info = starter()
                if info.get("running"):
                    print(f"[hud] {name} {info.get('url')}")
                elif info.get("error"):
                    print(f"[hud] {name} not bound: {info.get('error')}")
            except Exception as exc:
                sys.__stdout__.write(f"[hud] {name} not bound: {exc}\n")
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
