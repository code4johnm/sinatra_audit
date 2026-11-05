#!/usr/bin/env python3
"""Local TFTP server and the client the Sinatra Audit page uses.

The server listens on 127.0.0.1 and stays inside one directory. The page
sends and receives file text with RRQ and WRQ. Run this file alone to
serve that directory without the HUD.
"""

import os
import socket
import struct
import threading
from urllib.parse import urlparse

DEFAULT_PORT = 6969
MAX_BYTES = 1_048_576
BLOCK = 512
_RRQ, _WRQ, _DATA, _ACK, _ERROR = 1, 2, 3, 4, 5

_lock = threading.Lock()
_state = {
    "running": False,
    "host": "127.0.0.1",
    "port": DEFAULT_PORT,
    "root": "",
    "url": "",
    "error": "",
}
_target = {"url": ""}
_server = None


def _root(output_dir):
    override = os.environ.get("SINTRA_TFTP_ROOT")
    if override:
        return os.path.abspath(override)
    return os.path.abspath(os.path.join(output_dir or ".", "tftp"))


def _public_url(host, port):
    shown = host if host not in ("0.0.0.0", "::") else "127.0.0.1"
    return f"tftp://{shown}:{port}/"


def _file_name(name):
    text = str(name or "").strip()
    if not text or "/" in text or "\\" in text or "\x00" in text or text in (".", ".."):
        raise ValueError("Use a file name without a path.")
    if len(text) > 180:
        raise ValueError("That file name is too long.")
    return text


def _inside(root, name):
    safe = _file_name(name)
    path = os.path.realpath(os.path.join(root, safe))
    base = os.path.realpath(root)
    if os.path.dirname(path) != base:
        raise PermissionError("That path leaves the TFTP root.")
    return path


def _error_packet(code, message):
    return struct.pack("!HH", _ERROR, code) + str(message).encode("utf-8", "replace") + b"\x00"


def _parse_rq(data):
    if len(data) < 4:
        return None
    op = struct.unpack("!H", data[:2])[0]
    parts = data[2:].split(b"\x00")
    if len(parts) < 2:
        return None
    try:
        name = parts[0].decode("utf-8")
    except UnicodeError:
        return None
    mode = parts[1].decode("ascii", "ignore").lower()
    return op, name, mode


def _xfer_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(2.0)
    return sock


def _wait(sock, peer, want_op, want_block):
    for _ in range(5):
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            return None
        if peer is not None and addr != peer:
            continue
        if len(data) < 4:
            continue
        op, block = struct.unpack("!HH", data[:4])
        if op == _ERROR:
            msg = data[4:].split(b"\x00", 1)[0].decode("utf-8", "replace")
            raise ValueError(msg or "TFTP error.")
        if op == want_op and block == want_block:
            return data, addr
    return None


def _serve_rrq(sock, peer, root, name):
    try:
        path = _inside(root, name)
    except (ValueError, PermissionError) as exc:
        sock.sendto(_error_packet(2, str(exc)), peer)
        return
    if not os.path.isfile(path):
        sock.sendto(_error_packet(1, "File not found."), peer)
        return
    with open(path, "rb") as handle:
        blob = handle.read(MAX_BYTES + 1)
    if len(blob) > MAX_BYTES:
        sock.sendto(_error_packet(3, "File is too large."), peer)
        return
    block = 1
    offset = 0
    while True:
        chunk = blob[offset:offset + BLOCK]
        pkt = struct.pack("!HH", _DATA, block) + chunk
        sock.sendto(pkt, peer)
        got = _wait(sock, peer, _ACK, block)
        if got is None:
            return
        offset += BLOCK
        if len(chunk) < BLOCK:
            return
        block = (block + 1) & 0xFFFF


def _serve_wrq(sock, peer, root, name):
    try:
        path = _inside(root, name)
    except (ValueError, PermissionError) as exc:
        sock.sendto(_error_packet(2, str(exc)), peer)
        return
    sock.sendto(struct.pack("!HH", _ACK, 0), peer)
    block = 1
    buf = bytearray()
    while True:
        got = _wait(sock, peer, _DATA, block)
        if got is None:
            return
        data, addr = got
        peer = addr
        chunk = data[4:]
        if len(buf) + len(chunk) > MAX_BYTES:
            sock.sendto(_error_packet(3, "File is too large."), peer)
            return
        buf += chunk
        if len(chunk) < BLOCK:
            tmp = path + ".part"
            with open(tmp, "wb") as handle:
                handle.write(buf)
            os.replace(tmp, path)
            sock.sendto(struct.pack("!HH", _ACK, block), peer)
            return
        sock.sendto(struct.pack("!HH", _ACK, block), peer)
        block = (block + 1) & 0xFFFF


def _serve(data, addr, root):
    parsed = _parse_rq(data)
    if not parsed:
        return
    op, name, mode = parsed
    if mode not in ("octet", "binary", "netascii"):
        return
    sock = _xfer_socket()
    try:
        if op == _RRQ:
            _serve_rrq(sock, addr, root, name)
        elif op == _WRQ:
            _serve_wrq(sock, addr, root, name)
    except (OSError, ValueError):
        return
    finally:
        sock.close()


class _TftpServer(threading.Thread):
    def __init__(self, host, port, root):
        super().__init__(daemon=True, name="sintra-tftp")
        self.root = root
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
                data, addr = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(data) >= 4 and struct.unpack("!H", data[:2])[0] in (_RRQ, _WRQ):
                threading.Thread(
                    target=_serve, args=(data, addr, self.root), daemon=True
                ).start()


def _redact(url):
    parsed = urlparse(str(url or ""))
    if not parsed.hostname:
        return ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"tftp://{parsed.hostname}{port}{parsed.path or '/'}"


def status():
    with _lock:
        payload = dict(_state)
        payload["target"] = _redact(_target["url"] or payload.get("url") or "")
        payload["url"] = _redact(payload.get("url") or "")
    return payload


def _endpoint():
    with _lock:
        url = _target["url"] or _state.get("url") or ""
    parsed = urlparse(url)
    if parsed.scheme != "tftp" or not parsed.hostname:
        raise ValueError("The TFTP server is not running.")
    return parsed.hostname, parsed.port or DEFAULT_PORT


def _local_root():
    with _lock:
        if not _state.get("running"):
            return ""
        target = urlparse(_target["url"] or _state.get("url") or "")
        host = _state.get("host")
        port = _state.get("port")
        root = _state.get("root") or ""
    shown = host if host not in ("0.0.0.0", "::") else "127.0.0.1"
    if target.hostname in (shown, host) and (target.port or DEFAULT_PORT) == port:
        return root
    return ""


def set_target(url):
    text = str(url or "").strip()
    if not text:
        with _lock:
            text = _state.get("url") or ""
    parsed = urlparse(text)
    if parsed.scheme != "tftp" or not parsed.hostname:
        raise ValueError("Use a tftp:// link.")
    with _lock:
        _target["url"] = text
    return status()


def listing(_query=None):
    payload = status()
    root = _local_root()
    entries = []
    if root and os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if os.path.isfile(path):
                entries.append({"name": name, "dir": False, "bytes": os.path.getsize(path)})
    payload["entries"] = entries
    payload["note"] = "" if root else "Type a file name. TFTP does not list a remote folder."
    return payload


def _read_remote(host, port, name):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)
    try:
        req = struct.pack("!H", _RRQ) + name.encode("utf-8") + b"\x00octet\x00"
        dest = (host, port)
        block = 1
        buf = bytearray()
        pkt = req
        while True:
            got = None
            for _ in range(5):
                sock.sendto(pkt, dest)
                try:
                    data, addr = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                if len(data) < 4:
                    continue
                op, num = struct.unpack("!HH", data[:4])
                if op == _ERROR:
                    msg = data[4:].split(b"\x00", 1)[0].decode("utf-8", "replace")
                    raise ValueError(msg or "TFTP error.")
                if op == _DATA and num == block:
                    got = (data, addr)
                    break
            if got is None:
                raise ValueError("The TFTP server did not answer.")
            data, dest = got
            chunk = data[4:]
            if len(buf) + len(chunk) > MAX_BYTES:
                raise ValueError("That file is too large.")
            buf += chunk
            pkt = struct.pack("!HH", _ACK, block)
            sock.sendto(pkt, dest)
            if len(chunk) < BLOCK:
                return bytes(buf)
            block = (block + 1) & 0xFFFF
    finally:
        sock.close()


def _write_remote(host, port, name, blob):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)
    try:
        req = struct.pack("!H", _WRQ) + name.encode("utf-8") + b"\x00octet\x00"
        dest = (host, port)
        got = None
        for _ in range(5):
            sock.sendto(req, dest)
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            if len(data) < 4:
                continue
            op, num = struct.unpack("!HH", data[:4])
            if op == _ERROR:
                msg = data[4:].split(b"\x00", 1)[0].decode("utf-8", "replace")
                raise ValueError(msg or "TFTP error.")
            if op == _ACK and num == 0:
                got = addr
                break
        if got is None:
            raise ValueError("The TFTP server did not answer.")
        dest = got
        block = 1
        offset = 0
        while True:
            chunk = blob[offset:offset + BLOCK]
            pkt = struct.pack("!HH", _DATA, block) + chunk
            acked = False
            for _ in range(5):
                sock.sendto(pkt, dest)
                try:
                    data, addr = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                if addr != dest or len(data) < 4:
                    continue
                op, num = struct.unpack("!HH", data[:4])
                if op == _ERROR:
                    msg = data[4:].split(b"\x00", 1)[0].decode("utf-8", "replace")
                    raise ValueError(msg or "TFTP error.")
                if op == _ACK and num == block:
                    acked = True
                    break
            if not acked:
                raise ValueError("The TFTP server did not answer.")
            offset += BLOCK
            if len(chunk) < BLOCK:
                return
            block = (block + 1) & 0xFFFF
    finally:
        sock.close()


def open_text(query):
    name = _file_name((query or {}).get("name", [""])[0] if isinstance(query, dict) else "")
    host, port = _endpoint()
    blob = _read_remote(host, port, name)
    if b"\x00" in blob:
        raise ValueError("That file is not text.")
    try:
        text = blob.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("That file is not text.") from exc
    return {"name": name, "text": text, "bytes": len(blob)}


def save_text(body):
    if not isinstance(body, dict):
        raise ValueError("Body must be JSON.")
    name = _file_name(body.get("name"))
    text = body.get("text")
    if not isinstance(text, str):
        raise ValueError("Text is required.")
    if "\x00" in text:
        raise ValueError("That file is not text.")
    blob = text.encode("utf-8")
    if len(blob) > MAX_BYTES:
        raise ValueError("That file is too large.")
    host, port = _endpoint()
    _write_remote(host, port, name, blob)
    return {"ok": True, "name": name, "bytes": len(blob)}


def start_server(output_dir):
    global _server
    if os.environ.get("SINTRA_TFTP", "1") == "0":
        with _lock:
            _state["running"] = False
            _state["error"] = "SINTRA_TFTP is off"
        return status()
    with _lock:
        if _state.get("running") and _server is not None and _server.is_alive():
            return dict(_state)
        host = os.environ.get("SINTRA_TFTP_HOST", "127.0.0.1").strip() or "127.0.0.1"
        try:
            port = int(os.environ.get("SINTRA_TFTP_PORT", str(DEFAULT_PORT)))
        except ValueError:
            port = DEFAULT_PORT
        root = _root(output_dir)
        try:
            os.makedirs(root, exist_ok=True)
            server = _TftpServer(host, port, root)
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
                "root": root,
                "url": _public_url(host, port),
                "error": "",
            }
        )
        if not _target["url"]:
            _target["url"] = _state["url"]
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


def ensure_server(output_dir):
    try:
        return start_server(output_dir)
    except Exception as exc:
        with _lock:
            _state["running"] = False
            _state["error"] = str(exc)
        return status()


def main():
    root = _root(os.environ.get("SINTRA_OUTPUT") or os.getcwd())
    info = start_server(os.path.dirname(root) if os.environ.get("SINTRA_TFTP_ROOT") else (os.environ.get("SINTRA_OUTPUT") or os.getcwd()))
    print(info.get("url") or info.get("error") or "tftp stopped")
    threading.Event().wait()


if __name__ == "__main__":
    main()
