#!/usr/bin/env python3
"""ICMP echo pinger for the Sinatra Audit page.

One target, one echo in flight. The gap between sends is the frequency in
milliseconds. Linux unprivileged ICMP datagram sockets are used, so the
process does not need CAP_NET_RAW when ping_group_range allows its group.
"""

import os
import socket
import struct
import threading
import time

MIN_INTERVAL_MS = 100
MAX_INTERVAL_MS = 60_000
DEFAULT_INTERVAL_MS = 1000
_HISTORY = 20

_lock = threading.Lock()
_stop = threading.Event()
_thread = None
_state = {
    "running": False,
    "host": "127.0.0.1",
    "interval_ms": DEFAULT_INTERVAL_MS,
    "sent": 0,
    "received": 0,
    "rtt_ms": None,
    "error": "",
    "samples": [],
}


def _checksum(data):
    if len(data) & 1:
        data += b"\x00"
    total = sum(struct.unpack("!%dH" % (len(data) // 2), data))
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return ~total & 0xFFFF


def _clean_host(host):
    text = str(host or "").strip()
    if not text or len(text) > 253 or any(ch in text for ch in " \t\r\n/\\"):
        raise ValueError("Use a host name or an IPv4 address.")
    if any(ord(ch) < 33 or ord(ch) > 126 for ch in text):
        raise ValueError("Use a host name or an IPv4 address.")
    parts = text.split(".")
    if len(parts) == 4 and all(part.isdigit() for part in parts):
        try:
            socket.inet_aton(text)
        except OSError as exc:
            raise ValueError("Use a host name or an IPv4 address.") from exc
        first = int(parts[0])
        if text == "0.0.0.0" or first >= 224 or first == 0:
            raise ValueError("Use a unicast IPv4 address.")
        return text
    labels = text.split(".")
    for label in labels:
        if not label or len(label) > 63:
            raise ValueError("Use a host name or an IPv4 address.")
        if label.startswith("-") or label.endswith("-"):
            raise ValueError("Use a host name or an IPv4 address.")
        if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-" for ch in label):
            raise ValueError("Use a host name or an IPv4 address.")
    return text


def _clean_interval(value):
    try:
        ms = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Frequency must be a whole number of milliseconds.") from exc
    if ms < MIN_INTERVAL_MS or ms > MAX_INTERVAL_MS:
        raise ValueError(
            f"Frequency must be {MIN_INTERVAL_MS} to {MAX_INTERVAL_MS} ms."
        )
    return ms


def _resolve(host):
    try:
        infos = socket.getaddrinfo(host, 0, socket.AF_INET, socket.SOCK_DGRAM)
    except socket.gaierror as exc:
        raise ValueError("That host did not resolve.") from exc
    if not infos:
        raise ValueError("That host did not resolve.")
    return infos[0][4][0]


def _echo(sock, addr, seq):
    payload = b"sinatra-audit"
    ident = os.getpid() & 0xFFFF
    header = struct.pack("!BBHHH", 8, 0, 0, ident, seq & 0xFFFF)
    check = _checksum(header + payload)
    packet = struct.pack("!BBHHH", 8, 0, check, ident, seq & 0xFFFF) + payload
    started = time.monotonic()
    sock.sendto(packet, (addr, 0))
    while True:
        data, _from = sock.recvfrom(2048)
        if len(data) < 8:
            continue
        kind, _code, _chk, _got_id, got_seq = struct.unpack("!BBHHH", data[:8])
        # Unprivileged ICMP sockets replace the identifier, so match the sequence.
        if kind != 0 or got_seq != (seq & 0xFFFF):
            continue
        return (time.monotonic() - started) * 1000.0


def _record(ok, rtt, error):
    with _lock:
        _state["sent"] += 1
        if ok:
            _state["received"] += 1
            _state["rtt_ms"] = round(rtt, 2)
            _state["error"] = ""
        else:
            _state["error"] = error
        sample = {
            "seq": _state["sent"],
            "ok": ok,
            "rtt_ms": None if rtt is None else round(rtt, 2),
        }
        samples = list(_state["samples"])
        samples.append(sample)
        _state["samples"] = samples[-_HISTORY:]


def _loop():
    seq = 0
    while not _stop.is_set():
        with _lock:
            host = _state["host"]
            interval_ms = _state["interval_ms"]
        seq += 1
        sent_at = time.monotonic()
        try:
            addr = _resolve(host)
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_ICMP)
            sock.settimeout(max(interval_ms, 200) / 1000.0)
            try:
                rtt = _echo(sock, addr, seq)
            finally:
                sock.close()
            _record(True, rtt, "")
        except socket.timeout:
            _record(False, None, "No echo reply.")
        except PermissionError:
            _record(False, None, "ICMP echo is not permitted for this user.")
            break
        except ValueError as exc:
            _record(False, None, str(exc))
        except OSError as exc:
            _record(False, None, str(exc) or "ICMP echo failed.")
        wait = (sent_at + (interval_ms / 1000.0)) - time.monotonic()
        if wait > 0 and _stop.wait(wait):
            break
    with _lock:
        _state["running"] = False


def status():
    with _lock:
        payload = {
            "running": _state["running"] and _thread is not None and _thread.is_alive(),
            "host": _state["host"],
            "interval_ms": _state["interval_ms"],
            "sent": _state["sent"],
            "received": _state["received"],
            "rtt_ms": _state["rtt_ms"],
            "error": _state["error"],
            "samples": list(_state["samples"]),
        }
    sent = payload["sent"]
    payload["loss_pct"] = 0 if not sent else round(100.0 * (sent - payload["received"]) / sent, 1)
    return payload


def configure(body):
    """Apply host, frequency, and up or down. Returns the current status."""
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ValueError("Body must be JSON.")
    host = body.get("host")
    interval = body.get("interval_ms")
    with _lock:
        if host is not None and str(host).strip():
            _state["host"] = _clean_host(host)
        if interval is not None and interval != "":
            _state["interval_ms"] = _clean_interval(interval)
    if "up" in body:
        if body.get("up"):
            start_pinger()
        else:
            stop_pinger()
    return status()


def start_pinger():
    global _thread
    with _lock:
        alive = _thread is not None and _thread.is_alive() and _state["running"]
        if not alive:
            _stop.clear()
            _state["running"] = True
            _state["error"] = ""
            _state["sent"] = 0
            _state["received"] = 0
            _state["rtt_ms"] = None
            _state["samples"] = []
            worker = threading.Thread(target=_loop, name="sintra-icmp", daemon=True)
            _thread = worker
            worker.start()
    return status()


def stop_pinger():
    global _thread
    _stop.set()
    with _lock:
        worker = _thread
        _state["running"] = False
    if worker is not None:
        worker.join(timeout=2)
    return status()
