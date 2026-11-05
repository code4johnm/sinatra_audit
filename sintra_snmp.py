#!/usr/bin/env python3
"""Local SNMP agent and the client the Sinatra Audit handlers use.

The agent listens on 127.0.0.1 port 1161 and answers SNMPv2c Get, Get Next,
and Set. Contact, name, and location can be set. The other objects are
read-only. Run this file alone to serve the agent without the HUD.
"""

import os
import random
import socket
import threading
import time
from urllib.parse import urlparse

DEFAULT_PORT = 1161
_GET, _NEXT, _RESPONSE, _SET = 0xA0, 0xA1, 0xA2, 0xA3
_STARTED = time.monotonic()

_lock = threading.Lock()
_state = {
    "running": False,
    "host": "127.0.0.1",
    "port": DEFAULT_PORT,
    "url": "",
    "error": "",
}
_target = {"url": ""}
_server = None
_writable = {
    (1, 3, 6, 1, 2, 1, 1, 4, 0): "sinatra_audit",
    (1, 3, 6, 1, 2, 1, 1, 5, 0): socket.gethostname(),
    (1, 3, 6, 1, 2, 1, 1, 6, 0): "sinatra_audit",
}


def _community():
    return os.environ.get("SINTRA_SNMP_COMMUNITY", "public").strip() or "public"


def _public_url(host, port):
    shown = host if host not in ("0.0.0.0", "::") else "127.0.0.1"
    return f"snmp://{shown}:{port}/"


def _enc_len(n):
    if n < 128:
        return bytes([n])
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _tlv(tag, body):
    return bytes([tag]) + _enc_len(len(body)) + body


def _int_body(n):
    if n == 0:
        return b"\x00"
    if n > 0:
        raw = n.to_bytes((n.bit_length() + 8) // 8, "big")
        if raw[0] & 0x80:
            raw = b"\x00" + raw
        return raw
    return n.to_bytes((n.bit_length() + 8) // 8, "big", signed=True)


def _enc_int(n):
    return _tlv(0x02, _int_body(n))


def _enc_str(text):
    raw = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    return _tlv(0x04, raw)


def _base128(number):
    if number < 0:
        raise ValueError("Use a numeric OID.")
    chunk = [number & 0x7F]
    number >>= 7
    while number:
        chunk.append(0x80 | (number & 0x7F))
        number >>= 7
    return bytes(reversed(chunk))


def _enc_oid_parts(parts):
    if len(parts) < 2:
        raise ValueError("Use a numeric OID.")
    body = bytearray([parts[0] * 40 + parts[1]])
    for number in parts[2:]:
        body.extend(_base128(number))
    return _tlv(0x06, bytes(body))


def _oid_tuple(text):
    raw = str(text or "").strip().strip(".")
    if not raw or any(not part.isdigit() for part in raw.split(".")):
        raise ValueError("Use a numeric OID.")
    return tuple(int(part) for part in raw.split("."))


def _oid_text(parts):
    return ".".join(str(part) for part in parts)


def _dec_tlv(buf, index):
    if index >= len(buf):
        raise ValueError("Short SNMP packet.")
    tag = buf[index]
    index += 1
    if index >= len(buf):
        raise ValueError("Short SNMP packet.")
    length = buf[index]
    index += 1
    if length & 0x80:
        count = length & 0x7F
        if not count or count > 4 or index + count > len(buf):
            raise ValueError("Bad SNMP length.")
        length = int.from_bytes(buf[index:index + count], "big")
        index += count
    end = index + length
    if end > len(buf):
        raise ValueError("Short SNMP packet.")
    return tag, buf[index:end], end


def _dec_int(body):
    return int.from_bytes(body or b"\x00", "big", signed=True)


def _dec_oid(body):
    if not body:
        raise ValueError("Use a numeric OID.")
    parts = [body[0] // 40, body[0] % 40]
    number = 0
    for byte in body[1:]:
        number = (number << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(number)
            number = 0
    return tuple(parts)


def _mib():
    with _lock:
        contact = _writable[(1, 3, 6, 1, 2, 1, 1, 4, 0)]
        name = _writable[(1, 3, 6, 1, 2, 1, 1, 5, 0)]
        location = _writable[(1, 3, 6, 1, 2, 1, 1, 6, 0)]
    ticks = int((time.monotonic() - _STARTED) * 100)
    return [
        ((1, 3, 6, 1, 2, 1, 1, 1, 0), "string", "sinatra_audit snmp"),
        ((1, 3, 6, 1, 2, 1, 1, 2, 0), "oid", (1, 3, 6, 1, 4, 1, 55555, 1)),
        ((1, 3, 6, 1, 2, 1, 1, 3, 0), "ticks", ticks),
        ((1, 3, 6, 1, 2, 1, 1, 4, 0), "string", contact),
        ((1, 3, 6, 1, 2, 1, 1, 5, 0), "string", name),
        ((1, 3, 6, 1, 2, 1, 1, 6, 0), "string", location),
        ((1, 3, 6, 1, 2, 1, 1, 7, 0), "int", 72),
    ]


def _value_tlv(kind, value):
    if kind == "string":
        return _enc_str(value)
    if kind == "oid":
        return _enc_oid_parts(value)
    if kind == "ticks":
        return _tlv(0x43, _int_body(int(value)))
    if kind == "int":
        return _enc_int(int(value))
    if kind == "nosuch":
        return _tlv(0x81, b"")
    if kind == "end":
        return _tlv(0x82, b"")
    return _enc_str(str(value))


def _bind(oid, kind, value):
    return _tlv(0x30, _enc_oid_parts(oid) + _value_tlv(kind, value))


def _lookup(oid):
    for key, kind, value in _mib():
        if key == oid:
            return kind, value
    return None


def _next_after(oid):
    for key, kind, value in _mib():
        if key > oid:
            return key, kind, value
    return None


def _parse_message(packet):
    tag, body, _end = _dec_tlv(packet, 0)
    if tag != 0x30:
        raise ValueError("That packet is not SNMP.")
    _vtag, version, index = _dec_tlv(body, 0)
    _ctag, community, index = _dec_tlv(body, index)
    ptag, pdu, _index = _dec_tlv(body, index)
    if _dec_int(version) != 1:
        raise ValueError("Use SNMPv2c.")
    req_tag, req_raw, index = _dec_tlv(pdu, 0)
    err_tag, _err, index = _dec_tlv(pdu, index)
    idx_tag, _idx, index = _dec_tlv(pdu, index)
    _btag, binds_raw, _index = _dec_tlv(pdu, index)
    if req_tag != 0x02 or err_tag != 0x02 or idx_tag != 0x02:
        raise ValueError("Bad SNMP request.")
    items = []
    cursor = 0
    while cursor < len(binds_raw):
        btag, bind, cursor = _dec_tlv(binds_raw, cursor)
        if btag != 0x30:
            continue
        _otag, oid_raw, at = _dec_tlv(bind, 0)
        oid = _dec_oid(oid_raw)
        if ptag == _SET:
            vtag, value, _at = _dec_tlv(bind, at)
            items.append((oid, vtag, value))
        else:
            items.append(oid)
    return community.decode("utf-8", "replace"), ptag, _dec_int(req_raw), items


def _response(community, req_id, binds):
    pdu = _tlv(
        _RESPONSE,
        _enc_int(req_id) + _enc_int(0) + _enc_int(0) + _tlv(0x30, b"".join(binds)),
    )
    return _tlv(0x30, _enc_int(1) + _enc_str(community) + pdu)


def _handle(packet):
    community, ptag, req_id, items = _parse_message(packet)
    if community != _community():
        return None
    binds = []
    if ptag == _GET:
        for oid in items:
            found = _lookup(oid)
            if found:
                binds.append(_bind(oid, found[0], found[1]))
            else:
                binds.append(_bind(oid, "nosuch", None))
    elif ptag == _NEXT:
        for oid in items:
            found = _next_after(oid)
            if found:
                binds.append(_bind(found[0], found[1], found[2]))
            else:
                binds.append(_bind(oid, "end", None))
    elif ptag == _SET:
        for oid, vtag, raw in items:
            if oid not in _writable or vtag != 0x04:
                binds.append(_bind(oid, "nosuch", None))
                continue
            text = raw.decode("utf-8")
            if len(text) > 200 or "\x00" in text:
                raise ValueError("That value is too long.")
            with _lock:
                _writable[oid] = text
            binds.append(_bind(oid, "string", text))
    else:
        raise ValueError("That SNMP request is not supported.")
    return _response(community, req_id, binds)


class _SnmpServer(threading.Thread):
    def __init__(self, host, port):
        super().__init__(daemon=True, name="sintra-snmp")
        self._stop = threading.Event()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.settimeout(0.5)

    def stop(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass

    def run(self):
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                reply = _handle(data)
            except (ValueError, UnicodeError):
                continue
            if reply:
                try:
                    self.sock.sendto(reply, addr)
                except OSError:
                    break


def _redact(url):
    parsed = urlparse(str(url or ""))
    if not parsed.hostname:
        return ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"snmp://{parsed.hostname}{port}{parsed.path or '/'}"


def status():
    with _lock:
        payload = dict(_state)
        payload["target"] = _redact(_target["url"] or payload.get("url") or "")
        payload["url"] = _redact(payload.get("url") or "")
    return payload


def set_target(url):
    text = str(url or "").strip()
    if not text:
        with _lock:
            text = _state.get("url") or ""
    parsed = urlparse(text)
    if parsed.scheme != "snmp" or not parsed.hostname:
        raise ValueError("Use an snmp:// link.")
    with _lock:
        _target["url"] = text
    return status()


def _endpoint():
    with _lock:
        url = _target["url"] or _state.get("url") or ""
    parsed = urlparse(url)
    if parsed.scheme != "snmp" or not parsed.hostname:
        raise ValueError("The SNMP agent is not running.")
    community = parsed.username or _community()
    return parsed.hostname, parsed.port or DEFAULT_PORT, community


def _rows_from(packet):
    _tag, body, _end = _dec_tlv(packet, 0)
    _v, _version, index = _dec_tlv(body, 0)
    _c, _community, index = _dec_tlv(body, index)
    ptag, pdu, _index = _dec_tlv(body, index)
    _r, _req, index = _dec_tlv(pdu, 0)
    _e, err_raw, index = _dec_tlv(pdu, index)
    _i, _idx, index = _dec_tlv(pdu, index)
    _b, binds_raw, _index = _dec_tlv(pdu, index)
    if ptag != _RESPONSE or _dec_int(err_raw):
        raise ValueError("The SNMP agent refused that request.")
    rows = []
    cursor = 0
    while cursor < len(binds_raw):
        _bt, bind, cursor = _dec_tlv(binds_raw, cursor)
        _ot, oid_raw, at = _dec_tlv(bind, 0)
        vtag, value, _at = _dec_tlv(bind, at)
        oid = _oid_text(_dec_oid(oid_raw))
        if vtag == 0x04:
            shown, kind = value.decode("utf-8", "replace"), "string"
        elif vtag == 0x02:
            shown, kind = str(_dec_int(value)), "int"
        elif vtag == 0x06:
            shown, kind = _oid_text(_dec_oid(value)), "oid"
        elif vtag == 0x43:
            shown, kind = str(int.from_bytes(value or b"\x00", "big")), "ticks"
        elif vtag == 0x81:
            shown, kind = "no such object", "none"
        elif vtag == 0x82:
            shown, kind = "end of mib", "end"
        else:
            shown, kind = value.hex(), "hex"
        rows.append({"oid": oid, "type": kind, "value": shown})
    return rows


def _request(tag, oids, value=None):
    host, port, community = _endpoint()
    binds = []
    for oid in oids:
        if tag == _SET:
            binds.append(_tlv(0x30, _enc_oid_parts(_oid_tuple(oid)) + _enc_str(value or "")))
        else:
            binds.append(_tlv(0x30, _enc_oid_parts(_oid_tuple(oid)) + _tlv(0x05, b"")))
    req_id = random.randint(1, 2_000_000_000)
    pdu = _tlv(tag, _enc_int(req_id) + _enc_int(0) + _enc_int(0) + _tlv(0x30, b"".join(binds)))
    packet = _tlv(0x30, _enc_int(1) + _enc_str(community) + pdu)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
    try:
        sock.sendto(packet, (host, port))
        data, _addr = sock.recvfrom(8192)
    except socket.timeout as exc:
        raise ValueError("The SNMP agent did not answer.") from exc
    finally:
        sock.close()
    return _rows_from(data)


def get_oid(body):
    if not isinstance(body, dict):
        raise ValueError("Body must be JSON.")
    oid = _oid_text(_oid_tuple(body.get("oid")))
    return {"rows": _request(_GET, [oid])}


def next_oid(body):
    if not isinstance(body, dict):
        raise ValueError("Body must be JSON.")
    oid = _oid_text(_oid_tuple(body.get("oid")))
    return {"rows": _request(_NEXT, [oid])}


def walk_oid(body):
    if not isinstance(body, dict):
        raise ValueError("Body must be JSON.")
    start = _oid_tuple(body.get("oid") or "1.3.6.1.2.1.1")
    prefix = start[:-1] if start[-1:] == (0,) else start
    current = prefix[:-1] if prefix else (0,)
    rows = []
    for _ in range(32):
        found = _request(_NEXT, [_oid_text(current)])
        if not found or found[0]["type"] == "end":
            break
        got = _oid_tuple(found[0]["oid"])
        if got[:len(prefix)] != prefix:
            break
        rows.append(found[0])
        current = got
    return {"rows": rows}


def set_oid(body):
    if not isinstance(body, dict):
        raise ValueError("Body must be JSON.")
    oid = _oid_text(_oid_tuple(body.get("oid")))
    value = body.get("value")
    if not isinstance(value, str):
        raise ValueError("Value is required.")
    return {"rows": _request(_SET, [oid], value)}


def start_server(output_dir=None):
    del output_dir
    global _server
    if os.environ.get("SINTRA_SNMP", "1") == "0":
        with _lock:
            _state["running"] = False
            _state["error"] = "SINTRA_SNMP is off"
        return status()
    with _lock:
        if _state.get("running") and _server is not None and _server.is_alive():
            alive = True
        else:
            alive = False
            host = os.environ.get("SINTRA_SNMP_HOST", "127.0.0.1").strip() or "127.0.0.1"
            try:
                port = int(os.environ.get("SINTRA_SNMP_PORT", str(DEFAULT_PORT)))
            except ValueError:
                port = DEFAULT_PORT
            try:
                server = _SnmpServer(host, port)
                server.start()
            except OSError as exc:
                _state["running"] = False
                _state["error"] = str(exc)
                return dict(_state)
            _server = server
            _state.update(
                {
                    "running": True,
                    "host": host,
                    "port": port,
                    "url": _public_url(host, port),
                    "error": "",
                }
            )
            if not _target["url"]:
                _target["url"] = _state["url"]
    if alive:
        return status()
    return status()


def stop_server():
    global _server
    with _lock:
        server = _server
        _server = None
        _state["running"] = False
        _state["error"] = ""
    if server is not None:
        server.stop()
        server.join(timeout=2)
    return status()


def ensure_server(output_dir=None):
    try:
        return start_server(output_dir)
    except Exception as exc:
        with _lock:
            _state["running"] = False
            _state["error"] = str(exc)
        return status()


def main():
    info = start_server()
    print(info.get("url") or info.get("error") or "snmp stopped")
    threading.Event().wait()


if __name__ == "__main__":
    main()
