#!/usr/bin/env python3
"""Build only the proxy outbound; never print subscription values."""
import argparse
import base64
import json
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


def build(line, cfg, drop_extra=False):
    u = urlsplit(line)
    q = parse_qs(u.query, keep_blank_values=True)
    get = lambda key: q.get(key, [""])[0]
    if not u.hostname or not u.port or not u.username:
        raise ValueError("missing_endpoint")
    uid = str(uuid.UUID(unquote(u.username)))
    if not get("sni"):
        raise ValueError("missing_sni")
    user = {"id": uid, "encryption": "none"}
    kind = (get("type"), get("security"))
    if kind == ("xhttp", "tls"):
        tls = {"serverName": get("sni"), "fingerprint": get("fp") or "firefox"}
        if get("alpn"):
            tls["alpn"] = [v for v in get("alpn").split(",") if v]
        xs = {"path": get("path") or "/", "mode": get("mode") or "auto"}
        if get("host"):
            xs["host"] = get("host")
        if get("extra") and not drop_extra:
            xs["extra"] = json.loads(get("extra"))
            if not isinstance(xs["extra"], dict):
                raise ValueError("invalid_extra")
        stream = {"network": "xhttp", "security": "tls", "tlsSettings": tls, "xhttpSettings": xs}
        label = "xhttp_tls"
    elif kind in (("tcp", "reality"), ("raw", "reality")):
        key = get("pbk")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", key):
            raise ValueError("invalid_public_key")
        if len(base64.urlsafe_b64decode(key + "=")) != 32:
            raise ValueError("invalid_public_key")
        sid = get("sid")
        if len(sid) > 16 or len(sid) % 2 or not re.fullmatch(r"[0-9a-fA-F]*", sid):
            raise ValueError("invalid_short_id")
        if get("flow") not in ("", "xtls-rprx-vision"):
            raise ValueError("unsupported_flow")
        if get("flow"):
            user["flow"] = get("flow")
        stream = {"network": "tcp", "security": "reality", "realitySettings": {
            "serverName": get("sni"), "fingerprint": get("fp") or "firefox",
            "publicKey": key, "shortId": sid}}
        label = "tcp_reality"
    else:
        raise ValueError("unsupported_transport")
    out = {"tag": "proxy", "protocol": "vless", "settings": {"vnext": [{
        "address": u.hostname, "port": u.port, "users": [user]}]}, "streamSettings": stream}
    if sum(o.get("tag") == "proxy" for o in cfg.get("outbounds", [])) != 1:
        raise ValueError("expected_one_proxy_outbound")
    cfg = dict(cfg)
    cfg["outbounds"] = [out if o.get("tag") == "proxy" else o for o in cfg["outbounds"]]
    return cfg, label


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cache")
    p.add_argument("output")
    p.add_argument("index", nargs="?", type=int, default=0)
    p.add_argument("--base", default="/usr/local/etc/xray/config.json")
    p.add_argument("--no-extra", action="store_true")
    a = p.parse_args()
    try:
        cfg = json.loads(Path(a.base).read_text())
        lines = [s.strip() for s in Path(a.cache).read_text().splitlines() if s.strip().startswith("vless://")]
        if a.index < 0 or a.index > len(lines):
            raise ValueError("index_out_of_range")
        candidates = [(a.index, lines[a.index - 1])] if a.index else list(enumerate(lines, 1))
        for index, line in candidates:
            try:
                result, label = build(line, cfg, a.no_extra)
            except (ValueError, KeyError, TypeError) as exc:
                reason = str(exc) if str(exc) in {"missing_endpoint", "missing_sni", "invalid_extra", "invalid_public_key", "invalid_short_id", "unsupported_flow", "unsupported_transport", "expected_one_proxy_outbound"} else "invalid_parameters"
                if a.index:
                    print("SKIP:entry_%d_%s" % (index, reason))
                    return 2
                continue
            Path(a.output).write_text(json.dumps(result, indent=2) + "\n")
            print("BUILT:entry_%d_%s" % (index, label))
            return 0
        print("SKIP:no_supported_candidates")
        return 2
    except Exception:
        print("ERROR:configuration_or_input_invalid")
        return 2


if __name__ == "__main__":
    sys.exit(main())
