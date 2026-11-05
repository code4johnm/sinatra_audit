#!/usr/bin/env python3
"""Local FTP server and the client the HUD uses to open and save files.

The server listens on 127.0.0.1 and stays inside one directory. The client
speaks FTP with the standard library and is what the dashboard buttons call.
"""

import os
import socket
import threading
from datetime import datetime
from ftplib import FTP, error_perm
from urllib.parse import unquote, urlparse

DEFAULT_PORT = 2121
MAX_BYTES = 1_048_576

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
_started = False
_server = None


def _ftp_root(output_dir):
    override = os.environ.get("SINTRA_FTP_ROOT")
    if override:
        return os.path.abspath(override)
    return os.path.abspath(os.path.join(output_dir, "ftp"))


def _public_url(host, port):
    shown = host if host not in ("0.0.0.0", "::") else "127.0.0.1"
    return f"ftp://{shown}:{port}/"


class _FtpSession:
    def __init__(self, request, root, advertise):
        self.request = request
        self.root = os.path.realpath(root)
        self.advertise = advertise
        self.cwd = ""
        self.pasv = None
        self.port_addr = None
        self.user_ok = False

    def close(self):
        sock = self.pasv
        self.pasv = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def send(self, line):
        self.request.sendall((line + "\r\n").encode("utf-8", "replace"))

    def resolve(self, name):
        raw = (name or "").strip().replace("\\", "/")
        if raw in ("", "."):
            rel = self.cwd
        elif raw == "..":
            rel = os.path.dirname(self.cwd)
        elif raw.startswith("/"):
            rel = os.path.normpath(raw.lstrip("/"))
        else:
            rel = os.path.normpath(os.path.join(self.cwd, raw))
        if rel in (".",):
            rel = ""
        if rel == ".." or rel.startswith("../") or "/../" in f"/{rel}/":
            raise PermissionError("That path leaves the FTP root.")
        full = self.root if not rel else os.path.realpath(os.path.join(self.root, rel))
        root = self.root
        if full != root and not full.startswith(root + os.sep):
            raise PermissionError("That path leaves the FTP root.")
        return rel, full

    def open_data(self):
        if self.pasv is not None:
            self.pasv.settimeout(10)
            conn, _addr = self.pasv.accept()
            self.pasv.close()
            self.pasv = None
            return conn
        if self.port_addr:
            peer = self.request.getpeername()[0]
            host, port = self.port_addr
            if host != peer:
                raise PermissionError("PORT must use the same host as the control connection.")
            conn = socket.create_connection((host, port), timeout=10)
            self.port_addr = None
            return conn
        return None

    def handle(self):
        self.send("220 SINTRA FTP ready")
        file = self.request.makefile("rb")
        try:
            while True:
                raw = file.readline(4096)
                if not raw:
                    break
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                if " " in line:
                    verb, arg = line.split(" ", 1)
                else:
                    verb, arg = line, ""
                verb = verb.upper()
                if not self.dispatch(verb, arg):
                    break
        finally:
            file.close()
            self.close()

    def dispatch(self, verb, arg):
        if verb in ("QUIT", "BYE"):
            self.send("221 Goodbye")
            return False
        if verb == "USER":
            self.user_ok = True
            self.send("331 Password please")
            return True
        if verb == "PASS":
            if not self.user_ok:
                self.send("503 Login with USER first")
                return True
            self.send("230 Logged in")
            return True
        if verb in ("NOOP", "SYST"):
            self.send("215 UNIX Type: L8" if verb == "SYST" else "200 OK")
            return True
        if verb == "FEAT":
            self.send("211-Features:")
            self.send(" UTF8")
            self.send(" SIZE")
            self.send("211 End")
            return True
        if verb == "OPTS":
            self.send("200 OK")
            return True
        if verb == "TYPE":
            self.send("200 Type set")
            return True
        if verb in ("STRU", "MODE"):
            self.send("200 OK")
            return True
        if verb == "PWD" or verb == "XPWD":
            shown = "/" + self.cwd if self.cwd else "/"
            self.send(f'257 "{shown}" is the current directory')
            return True
        if verb in ("CWD", "XCWD"):
            return self._cwd(arg)
        if verb == "CDUP":
            return self._cwd("..")
        if verb == "PASV":
            return self._pasv()
        if verb == "PORT":
            return self._port(arg)
        if verb == "LIST":
            return self._list(arg, names_only=False)
        if verb in ("NLST", "NLIST"):
            return self._list(arg, names_only=True)
        if verb == "RETR":
            return self._retr(arg)
        if verb == "STOR":
            return self._stor(arg)
        if verb == "SIZE":
            return self._size(arg)
        self.send("502 Command not implemented")
        return True

    def _cwd(self, arg):
        try:
            rel, full = self.resolve(arg)
        except PermissionError as exc:
            self.send(f"550 {exc}")
            return True
        if not os.path.isdir(full):
            self.send("550 Not a directory")
            return True
        self.cwd = rel
        self.send("250 Directory changed")
        return True

    def _pasv(self):
        self.close()
        self.port_addr = None
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.advertise, 0))
        sock.listen(1)
        host, port = sock.getsockname()
        if host in ("0.0.0.0", "::"):
            host = self.advertise or "127.0.0.1"
        numbers = [int(part) for part in host.split(".")]
        numbers.extend((port // 256, port % 256))
        self.pasv = sock
        self.send("227 Entering Passive Mode (" + ",".join(str(n) for n in numbers) + ")")
        return True

    def _port(self, arg):
        self.close()
        try:
            parts = [int(part) for part in arg.split(",")]
            if len(parts) != 6 or any(part < 0 or part > 255 for part in parts):
                raise ValueError
        except ValueError:
            self.send("501 Bad PORT")
            return True
        host = ".".join(str(part) for part in parts[:4])
        port = parts[4] * 256 + parts[5]
        peer = self.request.getpeername()[0]
        if host != peer:
            self.send("504 PORT must use the client address")
            return True
        self.port_addr = (host, port)
        self.send("200 PORT command successful")
        return True

    def _list(self, arg, names_only):
        try:
            _rel, full = self.resolve(arg)
        except PermissionError as exc:
            self.send(f"550 {exc}")
            return True
        if not os.path.isdir(full):
            self.send("550 Not a directory")
            return True
        conn = self.open_data()
        if conn is None:
            self.send("425 Use PASV first")
            return True
        self.send("150 Here comes the listing")
        try:
            lines = []
            for name in sorted(os.listdir(full)):
                path = os.path.join(full, name)
                if names_only:
                    lines.append(name)
                    continue
                lines.append(_list_line(path, name))
            payload = ("\r\n".join(lines) + ("\r\n" if lines else "")).encode("utf-8", "replace")
            conn.sendall(payload)
        finally:
            conn.close()
        self.send("226 Listing complete")
        return True

    def _retr(self, arg):
        try:
            _rel, full = self.resolve(arg)
        except PermissionError as exc:
            self.send(f"550 {exc}")
            return True
        if not os.path.isfile(full):
            self.send("550 Not a file")
            return True
        if os.path.getsize(full) > MAX_BYTES:
            self.send("552 File is too large for this server")
            return True
        conn = self.open_data()
        if conn is None:
            self.send("425 Use PASV first")
            return True
        self.send("150 Opening data connection")
        try:
            with open(full, "rb") as handle:
                while True:
                    chunk = handle.read(65536)
                    if not chunk:
                        break
                    conn.sendall(chunk)
        finally:
            conn.close()
        self.send("226 Transfer complete")
        return True

    def _stor(self, arg):
        try:
            _rel, full = self.resolve(arg)
        except PermissionError as exc:
            self.send(f"550 {exc}")
            return True
        if os.path.isdir(full):
            self.send("550 That name is a directory")
            return True
        parent = os.path.dirname(full)
        if not os.path.isdir(parent):
            self.send("550 Directory does not exist")
            return True
        conn = self.open_data()
        if conn is None:
            self.send("425 Use PASV first")
            return True
        self.send("150 Ok to send data")
        data = bytearray()
        too_big = False
        try:
            while len(data) <= MAX_BYTES:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data.extend(chunk)
            else:
                too_big = True
        finally:
            conn.close()
        if too_big:
            self.send("552 File is too large for this server")
            return True
        with open(full, "wb") as handle:
            handle.write(data)
        self.send("226 Transfer complete")
        return True

    def _size(self, arg):
        try:
            _rel, full = self.resolve(arg)
        except PermissionError as exc:
            self.send(f"550 {exc}")
            return True
        if not os.path.isfile(full):
            self.send("550 Not a file")
            return True
        self.send(f"213 {os.path.getsize(full)}")
        return True


def _list_line(path, name):
    try:
        st = os.stat(path)
    except OSError:
        st = None
    kind = "d" if st and os.path.isdir(path) else "-"
    size = st.st_size if st else 0
    when = datetime.fromtimestamp(st.st_mtime) if st else datetime.now()
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    stamp = f"{months[when.month - 1]} {when.day:02d} {when.hour:02d}:{when.minute:02d}"
    return f"{kind}rw-r--r-- 1 sintra sintra {size} {stamp} {name}"


class _FtpServer(threading.Thread):
    def __init__(self, host, port, root):
        super().__init__(name="sintra-ftp", daemon=True)
        self.host = host
        self.port = port
        self.root = root
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.listen(8)
        self.sock.settimeout(0.5)
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                conn, _addr = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            advertise = conn.getsockname()[0]
            if advertise in ("0.0.0.0", "::"):
                advertise = "127.0.0.1"
            threading.Thread(
                target=_serve_client,
                args=(conn, self.root, advertise),
                name="sintra-ftp-client",
                daemon=True,
            ).start()

    def stop(self):
        self._stop.set()
        sock = self.sock
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def _serve_client(conn, root, advertise):
    try:
        _FtpSession(conn, root, advertise).handle()
    except OSError:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def start_server(output_dir):
    """Bind the local FTP server. Safe to call again after stop."""
    global _started, _server
    if os.environ.get("SINTRA_FTP", "1") == "0":
        with _lock:
            _state["running"] = False
            _state["error"] = "SINTRA_FTP is off"
        return status()
    with _lock:
        if _state.get("running") and _server is not None and _server.is_alive():
            running = True
        else:
            running = False
            host = os.environ.get("SINTRA_FTP_HOST", "127.0.0.1").strip() or "127.0.0.1"
            try:
                port = int(os.environ.get("SINTRA_FTP_PORT", str(DEFAULT_PORT)))
            except ValueError:
                port = DEFAULT_PORT
            root = _ftp_root(output_dir)
            try:
                os.makedirs(root, exist_ok=True)
                server = _FtpServer(host, port, root)
                server.start()
            except OSError as exc:
                _state["running"] = False
                _state["error"] = str(exc)
                _started = False
                return dict(_state)
            _server = server
            _started = True
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
    if running:
        return status()
    for _ in range(20):
        try:
            probe = socket.create_connection((host if host != "0.0.0.0" else "127.0.0.1", port), timeout=0.2)
            probe.close()
            break
        except OSError:
            threading.Event().wait(0.05)
    else:
        with _lock:
            _state["running"] = False
            _state["error"] = f"FTP port {port} did not open"
    return status()


def stop_server():
    """Close the local FTP listener. The page stays up."""
    global _started, _server
    with _lock:
        server = _server
        _server = None
        _started = False
        _state["running"] = False
        _state["error"] = ""
    if server is not None:
        server.stop()
        server.join(timeout=2)
    return status()


def ensure_server(output_dir):
    """Start the local FTP server. Never raises into the HUD loop."""
    try:
        return start_server(output_dir)
    except Exception as exc:
        with _lock:
            _state["running"] = False
            _state["error"] = str(exc)
        return status()


def _redact(url):
    parsed = urlparse(str(url or ""))
    if not parsed.hostname:
        return ""
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path or "/"
    return f"ftp://{parsed.hostname}{port}{path}"


def status():
    with _lock:
        payload = dict(_state)
        payload["target"] = _redact(_target["url"] or payload.get("url") or "")
        payload["url"] = _redact(payload.get("url") or "")
    return payload


def set_target(url):
    cleaned = _clean_url(url)
    with _lock:
        _target["url"] = cleaned
    return status()


def _clean_url(url):
    text = str(url or "").strip()
    if not text:
        with _lock:
            fallback = _state.get("url") or ""
        if not fallback:
            raise ValueError("The FTP link is empty.")
        return fallback
    parsed = urlparse(text)
    if parsed.scheme != "ftp" or not parsed.hostname:
        raise ValueError("Use an ftp:// link.")
    if parsed.username or parsed.password:
        # Keep the connection details, but the dashboard status hides them.
        pass
    return text


def _target_url():
    with _lock:
        url = _target["url"] or _state.get("url") or ""
    if not url:
        raise ValueError("The FTP server is not running.")
    return url


def _clean_dir(path):
    text = str(path or "").strip().replace("\\", "/")
    parts = []
    for part in text.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("That folder is outside the FTP root.")
        parts.append(part)
    return "/".join(parts)


def _clean_name(name):
    text = str(name or "").strip()
    if not text or text in (".", "..") or "/" in text or "\\" in text or "\x00" in text:
        raise ValueError("Use a file name without a path.")
    if len(text) > 180:
        raise ValueError("That file name is too long.")
    return text


def _connect(directory):
    url = _target_url()
    parsed = urlparse(url)
    if parsed.scheme != "ftp" or not parsed.hostname:
        raise ValueError("Use an ftp:// link.")
    port = parsed.port or 21
    user = unquote(parsed.username) if parsed.username else "anonymous"
    password = unquote(parsed.password) if parsed.password else "sintra"
    ftp = FTP()
    try:
        ftp.connect(parsed.hostname, port, timeout=8)
        ftp.login(user, password)
    except (OSError, error_perm) as exc:
        try:
            ftp.close()
        except OSError:
            pass
        raise ValueError("Could not reach that FTP server.") from exc
    ftp.set_pasv(True)
    home = unquote(parsed.path or "").strip("/")
    folder = _clean_dir(directory)
    target = "/".join(part for part in (home, folder) if part)
    ftp.cwd("/" + target if target else "/")
    return ftp


def _entries(ftp):
    lines = []
    ftp.retrlines("LIST", lines.append)
    found = []
    for line in lines:
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        name = parts[8]
        if name in (".", ".."):
            continue
        size = int(parts[4]) if parts[4].isdigit() else 0
        found.append({"name": name, "dir": line.startswith("d"), "size": size})
    found.sort(key=lambda item: (not item["dir"], item["name"].lower()))
    return found


def listing(query):
    directory = _clean_dir((query.get("dir") or [""])[0] if isinstance(query, dict) else "")
    if isinstance(query, dict) and "dir" not in query:
        directory = ""
    ftp = _connect(directory)
    try:
        entries = _entries(ftp)
    finally:
        try:
            ftp.quit()
        except (OSError, error_perm):
            ftp.close()
    payload = status()
    payload["dir"] = directory
    payload["entries"] = entries
    return payload


def open_text(query):
    directory = _clean_dir((query.get("dir") or [""])[0])
    name = _clean_name((query.get("name") or [""])[0])
    ftp = _connect(directory)
    try:
        chunks = []

        def collect(data):
            chunks.append(data)
            if sum(len(part) for part in chunks) > MAX_BYTES:
                raise ValueError("That file is too large to open here.")

        ftp.retrbinary("RETR " + name, collect)
    except error_perm as exc:
        raise ValueError("Could not open that file.") from exc
    finally:
        try:
            ftp.quit()
        except (OSError, error_perm):
            ftp.close()
    raw = b"".join(chunks)
    if b"\x00" in raw:
        raise ValueError("That file is not text.")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("That file is not text.") from exc
    return {"name": name, "dir": directory, "text": text, "bytes": len(raw)}


def save_text(body):
    if not isinstance(body, dict):
        raise ValueError("Body must be JSON.")
    directory = _clean_dir(body.get("dir") or "")
    name = _clean_name(body.get("name"))
    text = body.get("text")
    if not isinstance(text, str):
        raise ValueError("Text must be a string.")
    raw = text.encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("That file is too large to save here.")
    ftp = _connect(directory)
    try:
        from io import BytesIO

        ftp.storbinary("STOR " + name, BytesIO(raw))
    except error_perm as exc:
        raise ValueError("Could not save that file.") from exc
    finally:
        try:
            ftp.quit()
        except (OSError, error_perm):
            ftp.close()
    return {"ok": True, "name": name, "dir": directory, "bytes": len(raw)}
