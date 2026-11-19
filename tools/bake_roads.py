"""関東の高速道路（motorway / motorway_link）を OpenStreetMap から取得し、
ゲーム用のタイル（data/roads/<ty>_<tx>.json）に分割して保存する。
GitHub Actions から実行される。"""
import json, os, time, urllib.request, urllib.parse, math

ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter",
             "https://overpass.private.coffee/api/interpreter"]
DT_LAT, DT_LON = 0.04, 0.05           # index.html と同じタイルサイズ
BBOX = (34.90, 138.40, 37.20, 140.90)  # 関東一円
STEP = 0.5
KEEP = ["highway", "name", "ref", "oneway", "lanes", "layer", "bridge", "tunnel",
        "covered", "maxspeed", "destination", "destination:ref"]

def fetch(q, tries=3):
    data = urllib.parse.urlencode({"data": q}).encode()
    last = None
    for attempt in range(tries):
        ep = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            req = urllib.request.Request(ep, data=data, headers={"User-Agent": "shutoko-drive-bake/1.0"})
            with urllib.request.urlopen(req, timeout=200) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa
            last = e
            print("  retry", attempt, ep, e, flush=True)
            time.sleep(8 + attempt * 8)
    raise RuntimeError(last)

def grab(ways, s, w, n, e, depth, missing):
    bb = f"{s:.4f},{w:.4f},{n:.4f},{e:.4f}"
    q = f'[out:json][timeout:180];way["highway"~"^(motorway|motorway_link)$"]({bb});out geom qt;'
    print("fetch", bb, "depth", depth, flush=True)
    try:
        js = fetch(q, 3 if depth < 2 else 4)
    except Exception as ex:  # noqa
        if depth < 2:
            ms, mw = (s + n) / 2, (w + e) / 2
            for a, b, c, d in ((s, w, ms, mw), (s, mw, ms, e), (ms, w, n, mw), (ms, mw, n, e)):
                grab(ways, a, b, c, d, depth + 1, missing)
        else:
            print("  SKIP", bb, ex, flush=True)
            missing.append([s, w, n, e])
        return
    for el in js.get("elements", []):
        if el.get("type") != "way" or not el.get("geometry") or not el.get("nodes"):
            continue
        if any(g is None for g in el["geometry"]):
            continue
        ways[el["id"]] = el
    print("  ways so far", len(ways), flush=True)
    time.sleep(3)

def main():
    ways, missing = {}, []
    s0, w0, n0, e0 = BBOX
    lat = s0
    while lat < n0 - 1e-9:
        lon = w0
        while lon < e0 - 1e-9:
            grab(ways, lat, lon, min(lat + STEP, n0), min(lon + STEP, e0), 0, missing)
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
                   "tiles": sorted(f"{a}_{b}" for a, b in tiles), "ways": len(ways), "missing": missing,
                   "updated": time.strftime("%Y-%m-%d")}, fh)
    print("done:", len(ways), "ways,", len(tiles), "tiles,", len(missing), "skipped areas")

if __name__ == "__main__":
    main()
