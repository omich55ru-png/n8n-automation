import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("builder", ROOT / "vless-updater/build_xray_config.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def link(**changes):
    q = dict(type="tcp", security="reality", sni="example.invalid", pbk="A" * 43,
             sid="0123", fp="firefox", flow="xtls-rprx-vision")
    q.update(changes)
    return "vless://00000000-0000-4000-8000-000000000001@example.invalid:443?" + urlencode(q)


def base():
    return {"inbounds": [{"tag": "test"}], "routing": {"rules": []}, "dns": {},
            "outbounds": [{"tag": "direct", "protocol": "freedom"}, {"tag": "proxy"}]}


class BuilderTests(unittest.TestCase):
    def test_preserves_base(self):
        old = base()
        saved = copy.deepcopy(old)
        cfg, label = builder.build(link(), old)
        self.assertEqual(old, saved)
        self.assertEqual(label, "tcp_reality")
        for key in ("inbounds", "routing", "dns"):
            self.assertEqual(cfg[key], saved[key])
        self.assertEqual(cfg["outbounds"][0], saved["outbounds"][0])

    def test_reality_fields(self):
        cfg, _ = builder.build(link(), base())
        proxy = cfg["outbounds"][1]
        self.assertEqual(proxy["settings"]["vnext"][0]["users"][0]["flow"], "xtls-rprx-vision")
        self.assertEqual(proxy["streamSettings"]["realitySettings"]["shortId"], "0123")

    def test_raw_alias(self):
        cfg, _ = builder.build(link(type="raw"), base())
        self.assertEqual(cfg["outbounds"][1]["streamSettings"]["network"], "tcp")

    def test_xhttp(self):
        cfg, label = builder.build(link(type="xhttp", security="tls", extra='{"x":1}', alpn="h2,http/1.1"), base())
        stream = cfg["outbounds"][1]["streamSettings"]
        self.assertEqual(label, "xhttp_tls")
        self.assertEqual(stream["xhttpSettings"]["extra"], {"x": 1})
        self.assertEqual(stream["tlsSettings"]["alpn"], ["h2", "http/1.1"])

    def test_no_extra(self):
        cfg, _ = builder.build(link(type="xhttp", security="tls", extra="bad"), base(), True)
        self.assertNotIn("extra", cfg["outbounds"][1]["streamSettings"]["xhttpSettings"])

    def test_invalid_parameters(self):
        for changes in ({"pbk": ""}, {"sid": "1"}, {"sni": ""}, {"flow": "bad"}, {"security": "none"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                builder.build(link(**changes), base())

    def test_empty_sid(self):
        cfg, _ = builder.build(link(sid=""), base())
        self.assertEqual(cfg["outbounds"][1]["streamSettings"]["realitySettings"]["shortId"], "")

    def test_requires_proxy(self):
        with self.assertRaises(ValueError):
            builder.build(link(), {"outbounds": []})

    def test_cli_index_and_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "base.json").write_text(json.dumps(base()))
            (d / "nodes").write_text("vless://malformed\n" + link() + "\n")
            args = ["python3", str(ROOT / "vless-updater/build_xray_config.py"), str(d / "nodes"), str(d / "out.json")]
            for index, expected in (("1", 2), ("2", 0), ("99", 2)):
                r = subprocess.run(args + [index, "--base", str(d / "base.json")], capture_output=True, text=True)
                self.assertEqual(r.returncode, expected)
                for value in ("vless://", "example.invalid", "00000000-0000-4000-8000-000000000001"):
                    self.assertNotIn(value, r.stdout + r.stderr)


class ApplyTests(unittest.TestCase):
    def exercise(self, mode):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            binaries = d / "bin"
            binaries.mkdir()
            scripts = {
                "runuser": 'shift 3\nexec "$@"\n',
                "xray": '[ "$MODE" != invalid ]\n',
                "sleep": 'exit 0\n',
                "curl": 'if [ "$MODE" = unhealthy ]; then printf 000; exit 28; fi\nprintf 200\n',
                "systemctl": 'if [ "$1" = show ]; then id -un; exit 0; fi\nif [ "$1" = restart ]; then\n echo restart >> "$TRACE"\n [ "$MODE" != rollback_fail ] || exit 1\n if [ "$MODE" = restart_fail ] && [ ! -f "$ONCE" ]; then touch "$ONCE"; exit 1; fi\nfi\nexit 0\n',
            }
            for name, body in scripts.items():
                p = binaries / name
                p.write_text("#!/bin/bash\n" + body)
                p.chmod(0o755)
            target = d / "config.json"
            target.write_text('{"old":true}\n')
            target.chmod(0o640)
            candidate = d / "new.json"
            candidate.write_text('{"new":true}\n')
            metadata = (target.stat().st_uid, target.stat().st_gid, target.stat().st_mode)
            env = dict(os.environ, PATH=str(binaries) + ":" + os.environ["PATH"], XCONFIG=str(target),
                       PROXY="http://127.0.0.1:1", MODE=mode, TRACE=str(d / "trace"), ONCE=str(d / "once"))
            r = subprocess.run(["bash", str(ROOT / "vless-updater/apply_candidate.sh"), str(candidate)],
                               env=env, capture_output=True, text=True)
            expected = 0 if mode == "ok" else (2 if mode == "rollback_fail" else 1)
            self.assertEqual(r.returncode, expected, r.stdout + r.stderr)
            self.assertEqual(target.read_text(), candidate.read_text() if mode == "ok" else '{"old":true}\n')
            self.assertEqual(metadata, (target.stat().st_uid, target.stat().st_gid, target.stat().st_mode))
            self.assertFalse(list(d.glob(".candidate.*")))
            if mode == "invalid":
                self.assertFalse((d / "trace").exists())
            if mode in ("unhealthy", "restart_fail"):
                self.assertIn("APPLY:rolled_back", r.stdout)

    def test_success(self):
        self.exercise("ok")

    def test_validation_failure(self):
        self.exercise("invalid")

    def test_health_failure(self):
        self.exercise("unhealthy")

    def test_restart_failure(self):
        self.exercise("restart_fail")

    def test_rollback_failure(self):
        self.exercise("rollback_fail")


if __name__ == "__main__":
    unittest.main()
