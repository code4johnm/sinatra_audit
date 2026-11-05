#!/usr/bin/env python3
"""Mock the Sinatra Audit FTP, TFTP, SNMP, and ICMP handlers on localhost.

Each listener binds 127.0.0.1 on a free high port and a temporary directory.
The run does not use port 8080, 2121, 6969, or 1161, and it does not start
the HUD.
"""

import os
import socket
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import sintra_ftp
import sintra_icmp
import sintra_snmp
import sintra_tftp


def _say(line):
    print(line, flush=True)


def _free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _expect(label, exc_type, call):
    try:
        call()
    except exc_type as exc:
        _say(f"  reject {label}: {exc}")
        return str(exc)
    raise AssertionError(f"{label} did not raise {exc_type.__name__}")


class ProtocolHandlerMock(unittest.TestCase):
    def test_ftp_handler(self):
        port = _free_port()
        saved = {key: os.environ.get(key) for key in (
            "SINTRA_FTP", "SINTRA_FTP_HOST", "SINTRA_FTP_PORT", "SINTRA_FTP_ROOT"
        )}
        try:
            with tempfile.TemporaryDirectory(prefix="sintra-ftp-mock-") as root:
                os.environ["SINTRA_FTP"] = "1"
                os.environ["SINTRA_FTP_HOST"] = "127.0.0.1"
                os.environ["SINTRA_FTP_PORT"] = str(port)
                os.environ["SINTRA_FTP_ROOT"] = root
                started = sintra_ftp.start_server(root)
                _say(f"FTP start {started['url']} running={started['running']} root={started['root']}")
                self.assertTrue(started["running"])
                self.assertEqual(started["port"], port)
                self.assertTrue(started["url"].startswith("ftp://127.0.0.1:"))
                again = sintra_ftp.ensure_server(root)
                self.assertTrue(again["running"])
                sintra_ftp.set_target(started["url"])

                saved_file = sintra_ftp.save_text({
                    "name": "note.txt",
                    "dir": "",
                    "text": "sinatra audit ftp mock\n",
                })
                _say(f"FTP save {saved_file}")
                self.assertTrue(saved_file["ok"])
                self.assertEqual(saved_file["bytes"], len("sinatra audit ftp mock\n".encode()))
                with open(os.path.join(root, "note.txt"), encoding="utf-8") as handle:
                    on_disk = handle.read()
                self.assertEqual(on_disk, "sinatra audit ftp mock\n")

                listed = sintra_ftp.listing({})
                names = [item["name"] for item in listed["entries"]]
                _say(f"FTP list {names}")
                self.assertIn("note.txt", names)

                opened = sintra_ftp.open_text({"name": ["note.txt"], "dir": [""]})
                _say(f"FTP open {opened['name']} bytes={opened['bytes']} text={opened['text']!r}")
                self.assertEqual(opened["text"], "sinatra audit ftp mock\n")

                path_error = _expect(
                    "ftp path",
                    ValueError,
                    lambda: sintra_ftp.save_text({"name": "../note.txt", "text": "nope"}),
                )
                self.assertIn("without a path", path_error)
                folder_error = _expect(
                    "ftp folder",
                    ValueError,
                    lambda: sintra_ftp.listing({"dir": ["../secret"]}),
                )
                self.assertIn("outside the FTP root", folder_error)
                scheme_error = _expect(
                    "ftp scheme",
                    ValueError,
                    lambda: sintra_ftp.set_target("http://127.0.0.1/"),
                )
                self.assertIn("ftp://", scheme_error)
                missing = _expect(
                    "ftp missing",
                    ValueError,
                    lambda: sintra_ftp.open_text({"name": ["missing.txt"], "dir": [""]}),
                )
                self.assertIn("Could not open", missing)

                stopped = sintra_ftp.stop_server()
                _say(f"FTP stop running={stopped['running']}")
                self.assertFalse(stopped["running"])
                os.environ["SINTRA_FTP"] = "0"
                disabled = sintra_ftp.start_server(root)
                _say(f"FTP disabled error={disabled['error']!r} running={disabled['running']}")
                self.assertFalse(disabled["running"])
                self.assertEqual(disabled["error"], "SINTRA_FTP is off")
        finally:
            sintra_ftp.stop_server()
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_tftp_handler(self):
        port = _free_port()
        saved = {key: os.environ.get(key) for key in (
            "SINTRA_TFTP", "SINTRA_TFTP_HOST", "SINTRA_TFTP_PORT", "SINTRA_TFTP_ROOT"
        )}
        try:
            with tempfile.TemporaryDirectory(prefix="sintra-tftp-mock-") as root:
                os.environ["SINTRA_TFTP"] = "1"
                os.environ["SINTRA_TFTP_HOST"] = "127.0.0.1"
                os.environ["SINTRA_TFTP_PORT"] = str(port)
                os.environ["SINTRA_TFTP_ROOT"] = root
                started = sintra_tftp.start_server(root)
                _say(f"TFTP start {started['url']} running={started['running']} root={started['root']}")
                self.assertTrue(started["running"])
                self.assertEqual(started["port"], port)
                sintra_tftp.set_target(started["url"])

                saved_file = sintra_tftp.save_text({"name": "note.txt", "text": "sinatra audit tftp mock\n"})
                _say(f"TFTP save {saved_file}")
                self.assertTrue(saved_file["ok"])
                with open(os.path.join(root, "note.txt"), encoding="utf-8") as handle:
                    on_disk = handle.read()
                self.assertEqual(on_disk, "sinatra audit tftp mock\n")

                listed = sintra_tftp.listing({})
                names = [item["name"] for item in listed["entries"]]
                _say(f"TFTP list {names} note={listed['note']!r}")
                self.assertEqual(names, ["note.txt"])
                self.assertEqual(listed["note"], "")

                opened = sintra_tftp.open_text({"name": ["note.txt"]})
                _say(f"TFTP open {opened['name']} bytes={opened['bytes']} text={opened['text']!r}")
                self.assertEqual(opened["text"], "sinatra audit tftp mock\n")

                path_error = _expect(
                    "tftp path",
                    ValueError,
                    lambda: sintra_tftp.save_text({"name": "a/b.txt", "text": "nope"}),
                )
                self.assertIn("without a path", path_error)
                missing = _expect(
                    "tftp missing",
                    ValueError,
                    lambda: sintra_tftp.open_text({"name": ["missing.txt"]}),
                )
                self.assertIn("File not found", missing)
                scheme_error = _expect(
                    "tftp scheme",
                    ValueError,
                    lambda: sintra_tftp.set_target("ftp://127.0.0.1/"),
                )
                self.assertIn("tftp://", scheme_error)

                sintra_tftp.set_target("tftp://127.0.0.1:9/")
                remote = sintra_tftp.listing({})
                _say(f"TFTP remote note={remote['note']!r} entries={remote['entries']}")
                self.assertEqual(remote["entries"], [])
                self.assertIn("does not list", remote["note"])

                stopped = sintra_tftp.stop_server()
                _say(f"TFTP stop running={stopped['running']}")
                self.assertFalse(stopped["running"])
                os.environ["SINTRA_TFTP"] = "0"
                disabled = sintra_tftp.start_server(root)
                _say(f"TFTP disabled error={disabled['error']!r} running={disabled['running']}")
                self.assertFalse(disabled["running"])
                self.assertEqual(disabled["error"], "SINTRA_TFTP is off")
        finally:
            sintra_tftp.stop_server()
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_snmp_handler(self):
        port = _free_port()
        saved = {key: os.environ.get(key) for key in (
            "SINTRA_SNMP", "SINTRA_SNMP_HOST", "SINTRA_SNMP_PORT", "SINTRA_SNMP_COMMUNITY"
        )}
        contact = (1, 3, 6, 1, 2, 1, 1, 4, 0)
        location = (1, 3, 6, 1, 2, 1, 1, 6, 0)
        original_contact = sintra_snmp._writable[contact]
        original_location = sintra_snmp._writable[location]
        try:
            os.environ["SINTRA_SNMP"] = "1"
            os.environ["SINTRA_SNMP_HOST"] = "127.0.0.1"
            os.environ["SINTRA_SNMP_PORT"] = str(port)
            os.environ["SINTRA_SNMP_COMMUNITY"] = "public"
            started = sintra_snmp.start_server()
            _say(f"SNMP start {started['url']} running={started['running']}")
            self.assertTrue(started["running"])
            self.assertEqual(started["port"], port)
            self.assertNotIn("@", started["url"])
            sintra_snmp.set_target(started["url"])

            descr = sintra_snmp.get_oid({"oid": "1.3.6.1.2.1.1.1.0"})["rows"][0]
            _say(f"SNMP get sysDescr {descr}")
            self.assertEqual(descr["type"], "string")
            self.assertEqual(descr["value"], "sinatra_audit snmp")

            step = sintra_snmp._request(sintra_snmp._NEXT, ["1.3.6.1.2.1.1.1.0"])[0]
            _say(f"SNMP next {step}")
            self.assertEqual(step["oid"], "1.3.6.1.2.1.1.2.0")
            self.assertEqual(step["type"], "oid")
            self.assertEqual(step["value"], "1.3.6.1.4.1.55555.1")

            walked = sintra_snmp.walk_oid({"oid": "1.3.6.1.2.1.1"})
            _say(f"SNMP walk count={len(walked['rows'])}")
            for row in walked["rows"]:
                _say(f"  {row['oid']} {row['type']} {row['value']}")
            self.assertEqual(len(walked["rows"]), 7)
            self.assertEqual(walked["rows"][0]["oid"], "1.3.6.1.2.1.1.1.0")
            self.assertEqual(walked["rows"][2]["type"], "ticks")
            self.assertEqual(walked["rows"][6]["oid"], "1.3.6.1.2.1.1.7.0")
            self.assertEqual(walked["rows"][6]["value"], "72")

            placed = sintra_snmp.set_oid({
                "oid": "1.3.6.1.2.1.1.6.0",
                "value": "mock bench",
            })["rows"][0]
            _say(f"SNMP set sysLocation {placed}")
            self.assertEqual(placed["value"], "mock bench")
            read_back = sintra_snmp.get_oid({"oid": "1.3.6.1.2.1.1.6.0"})["rows"][0]
            _say(f"SNMP get sysLocation {read_back}")
            self.assertEqual(read_back["value"], "mock bench")

            readonly = sintra_snmp.set_oid({
                "oid": "1.3.6.1.2.1.1.1.0",
                "value": "rewritten",
            })["rows"][0]
            _say(f"SNMP set read-only {readonly}")
            self.assertEqual(readonly["type"], "none")
            self.assertEqual(readonly["value"], "no such object")
            still = sintra_snmp.get_oid({"oid": "1.3.6.1.2.1.1.1.0"})["rows"][0]
            self.assertEqual(still["value"], "sinatra_audit snmp")

            oid_error = _expect(
                "snmp oid",
                ValueError,
                lambda: sintra_snmp.get_oid({"oid": "sysDescr"}),
            )
            self.assertIn("numeric OID", oid_error)
            scheme_error = _expect(
                "snmp scheme",
                ValueError,
                lambda: sintra_snmp.set_target("http://127.0.0.1/"),
            )
            self.assertIn("snmp://", scheme_error)

            sintra_snmp.set_target(f"snmp://wrong@{started['host']}:{started['port']}/")
            quiet = _expect(
                "snmp community",
                ValueError,
                lambda: sintra_snmp.get_oid({"oid": "1.3.6.1.2.1.1.1.0"}),
            )
            self.assertIn("did not answer", quiet)

            stopped = sintra_snmp.stop_server()
            _say(f"SNMP stop running={stopped['running']}")
            self.assertFalse(stopped["running"])
            os.environ["SINTRA_SNMP"] = "0"
            disabled = sintra_snmp.start_server()
            _say(f"SNMP disabled error={disabled['error']!r} running={disabled['running']}")
            self.assertFalse(disabled["running"])
            self.assertEqual(disabled["error"], "SINTRA_SNMP is off")
        finally:
            sintra_snmp.stop_server()
            sintra_snmp._writable[contact] = original_contact
            sintra_snmp._writable[location] = original_location
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class IcmpPingerMock(unittest.TestCase):
    def tearDown(self):
        sintra_icmp.stop_pinger()

    def test_icmp_handler(self):
        refused = _expect(
            "icmp frequency",
            ValueError,
            lambda: sintra_icmp.configure({"host": "127.0.0.1", "interval_ms": 1, "up": True}),
        )
        self.assertIn("100", refused)
        refused_host = _expect(
            "icmp broadcast",
            ValueError,
            lambda: sintra_icmp.configure({"host": "255.255.255.255", "interval_ms": 200}),
        )
        self.assertIn("unicast", refused_host)
        started = sintra_icmp.configure({
            "host": "127.0.0.1",
            "interval_ms": 100,
            "up": True,
        })
        _say(f"ICMP start running={started['running']} host={started['host']} interval_ms={started['interval_ms']}")
        self.assertTrue(started["running"])
        self.assertEqual(started["interval_ms"], 100)
        deadline = time.monotonic() + 3
        latest = started
        while time.monotonic() < deadline and latest["received"] < 1:
            time.sleep(0.15)
            latest = sintra_icmp.status()
        _say(
            f"ICMP sample sent={latest['sent']} received={latest['received']} "
            f"rtt_ms={latest['rtt_ms']} error={latest['error']!r}"
        )
        self.assertGreaterEqual(latest["received"], 1)
        stopped = sintra_icmp.stop_pinger()
        _say(f"ICMP stop running={stopped['running']}")
        self.assertFalse(stopped["running"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
