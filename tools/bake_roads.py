"""関東の高速道路（motorway / motorway_link）を OpenStreetMap から取得し、
ゲーム用のタイル（data/roads/<ty>_<tx>.json）に分割して保存する。
GitHub Actions から実行。取得済みの範囲は data/roads_raw に保存して途中から再開でき、
時間切れになっても取れた分はコミットされる。"""
import json, os, time, urllib.request, urllib.parse, math, subprocess

ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter",
             "https://overpass.private.coffee/api/interpreter"]
DT_LAT, DT_LON = 0.04, 0.05
BBOX = (34.90, 138.40, 37.20, 140.90)
STEP = 0.5
RAW = "data/roads_raw2"
RAW_OLD = "data/roads_raw"
OUT = "data/roads"
DEADLINE = time.time() + float(os.environ.get("BAKE_MINUTES", "95")) * 60
KEEP = ["highway", "name", "name:en", "ref", "oneway", "lanes", "layer", "bridge", "tunnel",
        "covered", "maxspeed", "destination", "destination:ref", "destination:en", "junction:ref"]
JKEEP = ["name", "name:en", "ref"]

def fetch(q, tries):
    data = urllib.parse.urlencode({"data": q}).encode()
    last = None
    for attempt in range(tries):
        ep = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            req = urllib.request.Request(ep, data=data, headers={"User-Agent": "shutoko-drive-bake/1.2"})
            with urllib.request.urlopen(req, timeout=150) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa
            last = e
            print("  retry", attempt, ep, e, flush=True)
            time.sleep(8 + attempt * 8)
    raise RuntimeError(last)

def box_name(s, w, n, e):
    return f"{s:.4f}_{w:.4f}_{n:.4f}_{e:.4f}"

def compact(el):
    tags = {k: v for k, v in (el.get("tags") or {}).items() if k in KEEP}
    return [el["id"], el["nodes"], [round(g["lat"] * 1e6) for g in el["geometry"]],
            [round(g["lon"] * 1e6) for g in el["geometry"]], tags]

def grab(s, w, n, e, depth, missing):
    name = box_name(s, w, n, e)
    path = os.path.join(RAW, name + ".json")
    if os.path.exists(path):
        return True
    if time.time() > DEADLINE:
        return False
    bb = f"{s:.4f},{w:.4f},{n:.4f},{e:.4f}"
    q = f'[out:json][timeout:120];(way["highway"~"^(motorway|motorway_link)$"]({bb});node["highway"="motorway_junction"]({bb}););out geom qt;'
    print("fetch", name, "depth", depth, flush=True)
    try:
        js = fetch(q, 2 if depth < 2 else 3)
    except Exception as ex:  # noqa
        if depth < 2:
            ms, mw = (s + n) / 2, (w + e) / 2
            ok = True
            for a, b, c, d in ((s, w, ms, mw), (s, mw, ms, e), (ms, w, n, mw), (ms, mw, n, e)):
                ok = grab(a, b, c, d, depth + 1, missing) and ok
            return ok
        print("  SKIP", name, ex, flush=True)
        missing.append([s, w, n, e])
        return True
    els = js.get("elements", [])
    recs = [compact(el) for el in els
            if el.get("type") == "way" and el.get("geometry") and el.get("nodes")
            and not any(g is None for g in el["geometry"])]
    jcts = [[round(el["lat"] * 1e6), round(el["lon"] * 1e6),
             {k: v for k, v in (el.get("tags") or {}).items() if k in JKEEP}]
            for el in els if el.get("type") == "node" and (el.get("tags") or {}).get("name")]
    os.makedirs(RAW, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"w": recs, "j": jcts}, fh, ensure_ascii=False, separators=(",", ":"))
    print("  saved", len(recs), "ways", len(jcts), "junctions", flush=True)
    time.sleep(2)
    return True

def build_tiles(missing, complete):
    # 旧形式（v1）のデータがある間は、全範囲そろうまで差し替えない（遊べる状態を保つ）
    idx = os.path.join(OUT, "index.json")
    if not complete and os.path.exists(idx):
        try:
            if json.load(open(idx)).get("v", 1) < 2:
                print("keep old v1 tiles until complete", flush=True)
                return
        except Exception:  # noqa
            pass
    ways, jcts = {}, {}
    for f in os.listdir(RAW):
        if f.endswith(".json"):
            d = json.load(open(os.path.join(RAW, f), encoding="utf-8"))
            for rec in d.get("w", []):
                ways[rec[0]] = rec
            for j in d.get("j", []):
                jcts[(j[0], j[1])] = j
    tiles = {}
    for rec in ways.values():
        keys = {(math.floor(la / 1e6 / DT_LAT), math.floor(lo / 1e6 / DT_LON)) for la, lo in zip(rec[2], rec[3])}
        for k in keys:
            tiles.setdefault(k, []).append(rec)
    jt = {}
    for j in jcts.values():
        jt.setdefault((math.floor(j[0] / 1e6 / DT_LAT), math.floor(j[1] / 1e6 / DT_LON)), []).append(j)
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        os.remove(os.path.join(OUT, f))
    for k in set(tiles) | set(jt):
        ty, tx = k
        with open(os.path.join(OUT, f"{ty}_{tx}.json"), "w", encoding="utf-8") as fh:
            json.dump({"v": 2, "w": tiles.get(k, []), "j": jt.get(k, [])}, fh, ensure_ascii=False, separators=(",", ":"))
    tiles = {k: 1 for k in set(tiles) | set(jt)}
    # 未取得の範囲は「missing」としてゲームに伝え、地図サーバーから補ってもらう
    s0, w0, n0, e0 = BBOX
    todo = []
    lat = s0
    while lat < n0 - 1e-9:
        lon = w0
        while lon < e0 - 1e-9:
            b = (lat, lon, min(lat + STEP, n0), min(lon + STEP, e0))
            if not os.path.exists(os.path.join(RAW, box_name(*b) + ".json")) and not any(
                    os.path.exists(os.path.join(RAW, box_name(*sb) + ".json")) for sb in sub_boxes(b)):
                todo.append(list(b))
            lon += STEP
        lat += STEP
    with open(os.path.join(OUT, "index.json"), "w") as fh:
        json.dump({"v": 2, "dtLat": DT_LAT, "dtLon": DT_LON, "bbox": BBOX,
                   "tiles": sorted(f"{a}_{b}" for a, b in tiles), "ways": len(ways),
                   "missing": missing + todo, "complete": complete,
                   "updated": time.strftime("%Y-%m-%d %H:%M")}, fh)
    print("tiles:", len(ways), "ways,", len(tiles), "tiles, missing", len(missing) + len(todo), flush=True)

def sub_boxes(b):
    s, w, n, e = b
    ms, mw = (s + n) / 2, (w + e) / 2
    return [(s, w, ms, mw), (s, mw, ms, e), (ms, w, n, mw), (ms, mw, n, e)]

def commit(msg):
    subprocess.run(["git", "add", "data"], check=False)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode != 0:
        subprocess.run(["git", "commit", "-q", "-m", msg], check=False)
        subprocess.run(["git", "pull", "-q", "--rebase", "origin", "main"], check=False)
        subprocess.run(["git", "push", "-q"], check=False)

def bake_tolls():
    """料金所（barrier=toll_booth）の位置を data/tolls.json に保存（1回の軽い問い合わせ）"""
    s0, w0, n0, e0 = BBOX
    q = f'[out:json][timeout:180];node["barrier"="toll_booth"]({s0},{w0},{n0},{e0});out;'
    try:
        js = fetch(q, 4)
    except Exception as ex:  # noqa
        print("tolls skipped:", ex, flush=True)
        return
    out = [[round(el["lat"] * 1e6), round(el["lon"] * 1e6), (el.get("tags") or {}).get("name", "")]
           for el in js.get("elements", []) if el.get("type") == "node"]
    os.makedirs("data", exist_ok=True)
    with open("data/tolls.json", "w", encoding="utf-8") as fh:
        json.dump({"v": 1, "t": out}, fh, ensure_ascii=False, separators=(",", ":"))
    print("tolls:", len(out), flush=True)
    commit("料金所データを更新")

def main():
    import shutil
    if not os.path.exists("data/tolls.json"):
        bake_tolls()
    if os.path.isdir(RAW_OLD):
        shutil.rmtree(RAW_OLD)
    missing = []
    complete = True
    s0, w0, n0, e0 = BBOX
    lat = s0
    while lat < n0 - 1e-9:
        lon = w0
        while lon < e0 - 1e-9:
            if not grab(lat, lon, min(lat + STEP, n0), min(lon + STEP, e0), 0, missing):
                complete = False
            lon += STEP
        build_tiles(missing, False)
        commit(f"道路データ途中保存（緯度 {lat:.1f}〜）")
        lat += STEP
        if time.time() > DEADLINE:
            complete = False
            break
    build_tiles(missing, complete)
    commit("関東の高速道路データを更新" + ("" if complete else "（一部。続きは次回実行で取得）"))

if __name__ == "__main__":
    main()
