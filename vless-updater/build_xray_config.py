#!/usr/bin/env python3
import sys, json, urllib.parse

cache_path, out_path = sys.argv[1], sys.argv[2]
want = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else 0
drop_extra = "--no-extra" in sys.argv

links = []
for line in open(cache_path):
    line = line.strip()
    if not line.startswith("vless://"):
        continue
    rest = line[len("vless://"):]
    uuid, rest = rest.split("@", 1)
    sp, params = rest.split("?", 1)
    server, port = sp.rsplit(":", 1)
    q = dict(urllib.parse.parse_qsl(params.split("#")[0]))
    name = urllib.parse.unquote(line.rsplit("#", 1)[-1]) if "#" in line else server
    links.append({"server": server, "port": int(port), "uuid": uuid, "q": q, "name": name})

def eligible(l):
    q = l["q"]
    return q.get("type") == "xhttp" and q.get("security") == "tls" and q.get("sni")

cands = [l for l in links if eligible(l)]
if not cands:
    print("NO_XHTTP_LINKS"); sys.exit(2)

t = links[want - 1] if want else cands[0]
if want and not eligible(t):
    print("SKIP:" + t["name"]); sys.exit(2)
q = t["q"]

tls = {"serverName": q["sni"], "fingerprint": q.get("fp", "firefox")}
if q.get("alpn"):
    tls["alpn"] = [a for a in q["alpn"].split(",") if a]

xs = {"path": q.get("path", "/"), "mode": q.get("mode", "auto")}
if q.get("host"):
    xs["host"] = q["host"]
if q.get("extra") and not drop_extra:
    try:
        xs["extra"] = json.loads(q["extra"])
    except Exception:
        pass

cfg = {
  "log": {"loglevel": "warning"},
  "inbounds": [
    {"tag": "socks-in", "listen": "172.19.0.1", "port": 1080,
     "protocol": "socks", "settings": {"udp": False}},
    {"tag": "http-in", "listen": "172.19.0.1", "port": 1081,
     "protocol": "http"}
  ],
  "outbounds": [
    {"tag": "direct", "protocol": "freedom"},
    {"tag": "proxy", "protocol": "vless",
     "settings": {"vnext": [{"address": t["server"], "port": t["port"],
                  "users": [{"id": t["uuid"], "encryption": "none"}]}]},
     "streamSettings": {"network": "xhttp", "security": "tls",
                        "tlsSettings": tls, "xhttpSettings": xs}}
  ],
  "routing": {"domainStrategy": "AsIs", "rules": [
    {"type": "field", "domain": ["domain:openrouter.ai", "domain:claude.ai", "domain:anthropic.com"], "outboundTag": "proxy"},
    {"type": "field", "domain": ["domain:telegram.org", "domain:t.me", "domain:telesco.pe"], "outboundTag": "proxy"},
    {"type": "field", "domain": ["domain:ithyper.ru"], "outboundTag": "proxy"},
    {"type": "field", "domain": ["domain:openai.com", "domain:chatgpt.com", "domain:oaistatic.com", "domain:oaiusercontent.com", "domain:oaistatsig.com"], "outboundTag": "proxy"}
  ]}
}
json.dump(cfg, open(out_path, "w"), indent=2)
print("BUILT:" + t["server"] + " (" + t["name"] + ") extra=" + ("yes" if "extra" in xs else "no"))
