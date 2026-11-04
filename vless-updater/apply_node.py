import sys, json, socket

config_path, sub_path = sys.argv[1], sys.argv[2]
raw = open(sub_path).read()

nodes = []
for line in raw.splitlines():
    line = line.strip()
    if not line.startswith("vless://"):
        continue
    try:
        rest = line[len("vless://"):]
        uuid, rest = rest.split("@", 1)
        server_port, params = rest.split("?", 1)
        server, port = server_port.rsplit(":", 1)
        p = dict(x.split("=", 1) for x in params.split("#")[0].split("&") if "=" in x)
        nodes.append({"server": server, "uuid": uuid,
                      "pbk": p.get("pbk", ""), "sid": p.get("sid", ""),
                      "auto": "АВТОВЫБОР" in line})
    except Exception:
        continue

def tcp_ok(server):
    try:
        ip = socket.gethostbyname(server)
        s = socket.create_connection((ip, 443), timeout=6)
        s.close()
        return True
    except Exception:
        return False

nodes.sort(key=lambda n: not n["auto"])
alive = [n for n in nodes if tcp_ok(n["server"])]

if not alive:
    print("NO_ALIVE_NODES")
    sys.exit(2)

target = alive[0]
cfg = json.load(open(config_path))
out = next(o for o in cfg["outbounds"] if o.get("type") == "vless")
same = (out["server"] == target["server"]
        and out["uuid"] == target["uuid"]
        and out["tls"]["reality"]["public_key"] == target["pbk"]
        and out["tls"]["reality"]["short_id"] == target["sid"])

if same:
    print("SAME_CONFIG:" + target["server"])
    sys.exit(3)

out["server"] = target["server"]
out["uuid"] = target["uuid"]
out["tls"]["server_name"] = target["server"]
out["tls"]["reality"]["public_key"] = target["pbk"]
out["tls"]["reality"]["short_id"] = target["sid"]
json.dump(cfg, open(config_path, "w"), indent=2)
print("UPDATED:" + target["server"])
