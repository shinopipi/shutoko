"""関東の高速道路（motorway / motorway_link）を OpenStreetMap から取得し、
ゲーム用のタイル（data/roads/<ty>_<tx>.json）に分割して保存する。
GitHub Actions から実行される。"""
import json, os, time, urllib.request, urllib.parse, math

ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter",
             "https://overpass.private.coffee/api/interpreter"]
DT_LAT, DT_LON = 0.04, 0.05           # index.html と同じタイルサイズ
BBOX = (34.90, 138.40, 37.20, 140.95)  # 関東一円
STEP = 0.5
KEEP = ["highway", "name", "ref", "oneway", "lanes", "layer", "bridge", "tunnel",
        "covered", "maxspeed", "destination", "destination:ref"]

def fetch(q):
    data = urllib.parse.urlencode({"data": q}).encode()
    last = None
    for attempt in range(6):
        ep = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            req = urllib.request.Request(ep, data=data, headers={"User-Agent": "shutoko-drive-bake/1.0"})
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa
            last = e
            print("  retry", attempt, ep, e, flush=True)
            time.sleep(10 + attempt * 10)
    raise RuntimeError(last)

def main():
    ways = {}
    s0, w0, n0, e0 = BBOX
    lat = s0
    while lat < n0 - 1e-9:
        lon = w0
        while lon < e0 - 1e-9:
            bb = f"{lat:.3f},{lon:.3f},{min(lat+STEP,n0):.3f},{min(lon+STEP,e0):.3f}"
            q = f'[out:json][timeout:240];way["highway"~"^(motorway|motorway_link)$"]({bb});out geom qt;'
            print("fetch", bb, flush=True)
            js = fetch(q)
            for el in js.get("elements", []):
                if el.get("type") != "way" or not el.get("geometry") or not el.get("nodes"):
                    continue
                if any(g is None for g in el["geometry"]):
                    continue
                ways[el["id"]] = el
            print("  ways so far", len(ways), flush=True)
            time.sleep(3)
            lon += STEP
        lat += STEP

    tiles = {}
    for wid, el in ways.items():
        tags = {k: v for k, v in (el.get("tags") or {}).items() if k in KEEP}
        lats = [round(g["lat"] * 1e6) for g in el["geometry"]]
        lons = [round(g["lon"] * 1e6) for g in el["geometry"]]
        rec = [wid, el["nodes"], lats, lons, tags]
        keys = set()
        for g in el["geometry"]:
            keys.add((math.floor(g["lat"] / DT_LAT), math.floor(g["lon"] / DT_LON)))
        for k in keys:
            tiles.setdefault(k, []).append(rec)

    out = "data/roads"
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):
        os.remove(os.path.join(out, f))
    for (ty, tx), recs in tiles.items():
        with open(os.path.join(out, f"{ty}_{tx}.json"), "w", encoding="utf-8") as fh:
            json.dump({"v": 1, "w": recs}, fh, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(out, "index.json"), "w") as fh:
        json.dump({"v": 1, "dtLat": DT_LAT, "dtLon": DT_LON, "bbox": BBOX,
                   "tiles": sorted(f"{a}_{b}" for a, b in tiles), "ways": len(ways),
                   "updated": time.strftime("%Y-%m-%d")}, fh)
    print("done:", len(ways), "ways,", len(tiles), "tiles")

if __name__ == "__main__":
    main()
