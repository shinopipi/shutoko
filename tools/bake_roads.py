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


SURF_RAW = "data/surface_raw"
SURF_OUT = "data/surface"
SURF_HW = "^(trunk|primary|secondary|tertiary|unclassified|residential|trunk_link|primary_link|secondary_link)$"
SURF_KEEP = ["highway", "name", "name:en", "ref", "lanes", "oneway"]
EXTRA_SURF = [(35.551859, 139.745543)]  # 羽田入口（都心方面）: 一般道と交差するランプの点

def surface_points():
    """一般道とつながるランプの端（ほかの高速道路とつながっていない端）"""
    import glob, collections
    ways = {}
    for f in glob.glob(os.path.join(OUT, "*_*.json")):
        with open(f, encoding="utf-8") as fh:
            for r in json.load(fh)["w"]:
                ways[r[0]] = r
    deg = collections.Counter()
    for r in ways.values():
        for n in set(r[1]):
            deg[n] += 1
    pts = set()
    for r in ways.values():
        if r[4].get("highway") != "motorway_link":
            continue
        for k in (0, -1):
            if deg[r[1][k]] == 1:
                pts.add((r[2][k] / 1e6, r[3][k] / 1e6))
    pts |= set(EXTRA_SURF)
    return sorted(pts)

def bake_surface():
    """ランプ出入口のまわり（半径350m）の一般道を data/surface/<ty>_<tx>.json に保存"""
    pts = surface_points()
    print("surface points:", len(pts), flush=True)
    os.makedirs(SURF_RAW, exist_ok=True)
    B = 30
    batches = [pts[i:i + B] for i in range(0, len(pts), B)]
    complete = True
    for bi, b in enumerate(batches):
        path = os.path.join(SURF_RAW, f"b{bi:04d}.json")
        if os.path.exists(path):
            continue
        if time.time() > DEADLINE:
            complete = False
            break
        body = "".join(f'way(around:350,{la:.6f},{lo:.6f})["highway"~"{SURF_HW}"];' for la, lo in b)
        q = f"[out:json][timeout:170];({body});out geom qt;"
        try:
            js = fetch(q, 2)
        except Exception as ex:  # noqa
            print("surface batch failed", bi, ex, flush=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"pts": b, "w": [], "err": 1}, fh)
            continue
        out = []
        for el in js.get("elements", []):
            if el.get("type") != "way" or not el.get("geometry"):
                continue
            tags = {k: v for k, v in (el.get("tags") or {}).items() if k in SURF_KEEP}
            out.append([el["id"], el["nodes"], [round(g["lat"] * 1e6) for g in el["geometry"]],
                        [round(g["lon"] * 1e6) for g in el["geometry"]], tags])
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump({"pts": b, "w": out}, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(path + ".tmp", path)
        print("surface batch", bi, "/", len(batches), "ways", len(out), flush=True)
        if bi % 8 == 7:
            commit("一般道データ途中保存")
    # trim each street to the parts within 420 m of a ramp end, then tile
    import glob
    near = {}
    for f in sorted(glob.glob(os.path.join(SURF_RAW, "b*.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                js = json.load(fh)
        except Exception:  # noqa  壊れたファイルは消して次回取り直す
            os.remove(f)
            complete = False
            continue
        for la, lo in js["pts"]:
            near.setdefault((round(la / 0.005), round(lo / 0.006)), []).append((la, lo))
        for r in js["w"]:
            near.setdefault("_w", {})[r[0]] = r
    wl = near.pop("_w", {})
    def close(la, lo):
        ci, cj = round(la / 0.005), round(lo / 0.006)
        for a in (-1, 0, 1):
            for b in (-1, 0, 1):
                for pa, po in near.get((ci + a, cj + b), []):
                    if math.hypot((la - pa) * 111000, (lo - po) * 91000) < 420:
                        return True
        return False
    tiles = {}
    for wid, (id_, nodes, la, lo, tags) in wl.items():
        keep = [close(la[i] / 1e6, lo[i] / 1e6) for i in range(len(nodes))]
        seg = []
        segs = []
        for i in range(len(nodes)):
            if keep[i] or (i > 0 and keep[i - 1]) or (i + 1 < len(nodes) and keep[i + 1]):
                seg.append(i)
            elif seg:
                segs.append(seg); seg = []
        if seg:
            segs.append(seg)
        for k, sg in enumerate(segs):
            if len(sg) < 2:
                continue
            rec = [id_ * 100 + k, [nodes[i] for i in sg], [la[i] for i in sg], [lo[i] for i in sg], tags]
            keys = {(math.floor(la[i] / 1e6 / DT_LAT), math.floor(lo[i] / 1e6 / DT_LON)) for i in sg}
            for key in keys:
                tiles.setdefault(key, []).append(rec)
    os.makedirs(SURF_OUT, exist_ok=True)
    names = []
    for (ty, tx), recs in tiles.items():
        nm = f"{ty}_{tx}"
        names.append(nm)
        with open(os.path.join(SURF_OUT, nm + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"v": 1, "w": recs}, fh, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(SURF_OUT, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"v": 1, "tiles": sorted(names), "complete": complete}, fh, separators=(",", ":"))
    print("surface tiles:", len(names), "complete", complete, flush=True)
    commit("ランプ周辺の一般道データを更新")


BLD_OUT = "data/bld"

def bld_query(bb):
    return (f'[out:json][timeout:120][maxsize:268435456];way["highway"~"^(motorway|motorway_link)$"]({bb})->.r;'
            f'way["building"](around.r:150);out geom qt;')

def fetch_one(q, ep, timeout=140):
    data = urllib.parse.urlencode({"data": q}).encode()
    req = urllib.request.Request(ep, data=data, headers={"User-Agent": "shutoko-drive-bake/1.3"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

_MW = None

def motorway_grid():
    """高速道路の点（約20m間隔）を100mグリッドに登録（建物の距離判定用）"""
    global _MW
    if _MW is not None:
        return _MW
    import glob
    g = {}
    for f in glob.glob(os.path.join(OUT, "*_*.json")):
        with open(f, encoding="utf-8") as fh:
            for r in json.load(fh)["w"]:
                la, lo = r[2], r[3]
                for i in range(len(la)):
                    pts = [(la[i], lo[i])]
                    if i + 1 < len(la):
                        d = math.hypot((la[i + 1] - la[i]) * 0.111, (lo[i + 1] - lo[i]) * 0.091)
                        m = int(d // 20)
                        for k in range(1, m + 1):
                            t = k / (m + 1)
                            pts.append((la[i] + (la[i + 1] - la[i]) * t, lo[i] + (lo[i + 1] - lo[i]) * t))
                    for pa, po in pts:
                        x, z = pa * 0.111, po * 0.091  # metres
                        g.setdefault((int(x // 100), int(z // 100)), []).append((x, z))
    _MW = g
    return g

def near_motorway(la, lo, r=150):
    g = motorway_grid()
    x, z = la * 0.111, lo * 0.091
    cx, cz = int(x // 100), int(z // 100)
    for a in (-2, -1, 0, 1, 2):
        for b in (-2, -1, 0, 1, 2):
            for px, pz in g.get((cx + a, cz + b), ()):
                if (px - x) ** 2 + (pz - z) ** 2 < r * r:
                    return True
    return False

def bld_tile(k, wi):
    """1タイルを4x4に分け、高速道路が近い区画だけ bbox で建物を取得し、150m以内に絞る"""
    ty, tx = map(int, k.split("_"))
    s0, w0 = ty * DT_LAT, tx * DT_LON
    n = 4
    hl, hw = DT_LAT / n, DT_LON / n
    els = {}
    err = False
    for a in range(n):
        for b in range(n):
            sa, wa = s0 + a * hl, w0 + b * hw
            # skip sub-boxes with no motorway within ~250 m of their centre/corners
            probe = [(sa + hl * u, wa + hw * v) for u in (0, 0.5, 1) for v in (0, 0.5, 1)]
            if not any(near_motorway(pa * 1e6, po * 1e6, 600) for pa, po in probe):
                continue
            q = f'[out:json][timeout:90];way["building"]({sa:.5f},{wa:.5f},{sa + hl:.5f},{wa + hw:.5f});out geom qt;'
            ok = False
            for t in range(3):
                try:
                    js = fetch_one(q, ENDPOINTS[(wi + a * n + b + t) % len(ENDPOINTS)], 100)
                    for el in js.get("elements", []):
                        g = el.get("geometry")
                        if not g:
                            continue
                        cla = sum(p["lat"] for p in g) / len(g) * 1e6
                        clo = sum(p["lon"] for p in g) / len(g) * 1e6
                        if near_motorway(cla, clo, 150):
                            els[el["id"]] = el
                    ok = True
                    break
                except Exception as ex:  # noqa
                    print("  retry", k, a, b, ex, flush=True)
                    time.sleep(4 + t * 4)
            err = err or not ok
    return els, err

def bld_pack(k, els):
    ty, tx = map(int, k.split("_"))
    la0, lo0 = round(ty * DT_LAT * 1e6), round(tx * DT_LON * 1e6)
    out = []
    for el in els.values():
        g = el.get("geometry")
        if el.get("type") != "way" or not g or len(g) < 4:
            continue
        la = [round(p["lat"] * 1e6) for p in g]
        lo = [round(p["lon"] * 1e6) for p in g]
        xs = [(v - la[0]) * 0.111 for v in la]
        zs = [(v - lo[0]) * 0.091 for v in lo]
        a = 0.0
        for i in range(len(xs) - 1):
            a += xs[i] * zs[i + 1] - xs[i + 1] * zs[i]
        if abs(a) / 2 < 30:
            continue
        t = el.get("tags") or {}
        def num(key):
            try:
                return round(float(str(t.get(key, "0")).split(";")[0].replace("m", "").strip()), 1)
            except ValueError:
                return 0
        out.append([el["id"], [v - la0 for v in la], [v - lo0 for v in lo],
                    [t.get("building", "yes"), num("height"), num("building:levels"), num("min_height"),
                     t.get("building:colour", ""), t.get("roof:shape", "")]])
    return {"v": 1, "o": [la0, lo0], "b": out}

def bake_buildings():
    """高速道路から150m以内の建物を data/bld/<ty>_<tx>.json に保存（3並列・再開可能）"""
    from concurrent.futures import ThreadPoolExecutor
    import threading
    with open(os.path.join(OUT, "index.json"), encoding="utf-8") as fh:
        tiles = sorted(json.load(fh)["tiles"])
    os.makedirs(BLD_OUT, exist_ok=True)
    def state(k):
        path = os.path.join(BLD_OUT, k + ".json")
        if not os.path.exists(path):
            return 0
        try:
            with open(path, encoding="utf-8") as fh:
                js = json.load(fh)
        except Exception:  # noqa
            return 0
        if js.get("err"):
            return 1 if js.get("try", 1) < 2 else 2
        return 2
    todo = [k for k in tiles if state(k) == 0] + [k for k in tiles if state(k) == 1]
    lock = threading.Lock()
    cnt = [0]
    def work(args):
        i, k = args
        if time.time() > DEADLINE:
            return
        prev = state(k)
        els, err = bld_tile(k, i)
        path = os.path.join(BLD_OUT, k + ".json")
        js = bld_pack(k, els)
        if err:
            js["err"] = 1
            js["try"] = 2 if prev == 1 else 1
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(js, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(path + ".tmp", path)
        print("bld", k, len(js["b"]), "ERR" if err else "", flush=True)
        with lock:
            cnt[0] += 1
            if cnt[0] % 20 == 0:
                commit("建物データ途中保存")
    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(work, list(enumerate(todo))))
    have = sorted(f[:-5] for f in os.listdir(BLD_OUT) if f.endswith(".json") and f != "index.json")
    complete = all(state(k) == 2 for k in tiles)
    with open(os.path.join(BLD_OUT, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"v": 1, "tiles": have, "complete": complete}, fh, separators=(",", ":"))
    commit("建物データを更新" + ("" if complete else "（続きは次回）"))
    return complete

def main():
    import shutil
    if not os.path.exists("data/tolls.json"):
        bake_tolls()
    si = os.path.join(SURF_OUT, "index.json")
    if not os.path.exists(si) or not json.load(open(si)).get("complete"):
        try:
            bake_surface()
        except Exception as ex:  # noqa
            print("surface step failed:", ex, flush=True)
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
    bi = os.path.join(BLD_OUT, "index.json")
    bdone = os.path.exists(bi) and json.load(open(bi)).get("complete")
    if complete and not bdone and time.time() < DEADLINE:
        bdone = bake_buildings()
    si = os.path.join(SURF_OUT, "index.json")
    sdone = os.path.exists(si) and json.load(open(si)).get("complete")
    if not (complete and bdone and sdone):
        with open("bake_more", "w") as fh:
            fh.write("1")

if __name__ == "__main__":
    main()
