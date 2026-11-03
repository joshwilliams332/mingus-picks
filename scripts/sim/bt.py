"""Backtest the simulator on a season: each game simulated from earlier weeks only.
python3 bt.py ROOT SEASON N WEEKS [key=value sim options...]"""
import csv, json, multiprocessing as mp, statistics, sys
from collections import Counter
ROOT = sys.argv[1]
sys.path.insert(0, ROOT + "/sim")
import sim2 as S

SEASON, N = int(sys.argv[2]), int(sys.argv[3])
WEEKS = [int(w) for w in sys.argv[4].split(",")] if "," in sys.argv[4] else list(range(int(sys.argv[4].split("-")[0]), int(sys.argv[4].split("-")[1]) + 1))
OPTS = {k: float(v) for k, v in (a.split("=") for a in sys.argv[5:])}
FIX = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA"}
GAMES = {}
for g in csv.DictReader(open(f"{ROOT}/hist/games.csv")):
    if g["season"] == str(SEASON) and g["game_type"] == "REG" and g["home_score"] not in ("", "NA"):
        GAMES[(int(g["week"]), FIX.get(g["away_team"], g["away_team"]), FIX.get(g["home_team"], g["home_team"]))] = g

_state = {}
def init():
    plays, specials = S.load(f"{ROOT}/pbp/pbp_{SEASON}.csv.gz")
    prior = None
    if OPTS.get("prior", 0) and SEASON - 1 >= 2021:
        prior = S.load(f"{ROOT}/pbp/pbp_{SEASON - 1}.csv.gz")
    _state.update(plays=plays, specials=specials, prior=prior, models={})

def one(key):
    wk, away, home = key
    st = _state
    if wk not in st["models"]:
        st["models"] = {wk: S.Model(st["plays"], st["specials"], wk, prior=st["prior"], opts=OPTS)}
    m = st["models"][wk]
    gp = [p for p in st["plays"] if p["week"] == wk and {p["off"], p["def"]} == {away, home}]
    if not gp:
        return None
    qbs, active = {}, {}
    for t in (away, home):
        c = Counter(p["qb"] for p in gp if p["off"] == t and p["pass"] and p["qb"])
        qbs[t] = c.most_common(1)[0][0]
        active[t] = {p["rec"] for p in gp if p["off"] == t and p["rec"]} | {p["rusher"] for p in gp if p["off"] == t and p["rusher"]}
    g = GAMES[key]
    ctx = {"wind": float(g["wind"]) if g["wind"] not in ("", "NA") else 0, "temp": float(g["temp"]) if g["temp"] not in ("", "NA") else 60,
           "roof": g["roof"], "away_rest": float(g["away_rest"] or 7), "home_rest": float(g["home_rest"] or 7), "neutral": g["location"] == "Neutral"}
    try:
        sim = S.Sim(m, away, home, qbs, active=active, seed=hash(key) % 10**6, opts=OPTS, ctx=ctx)
        res, _ = sim.run(N)
    except (IndexError, ValueError, KeyError) as e:
        return None
    hs, as_ = int(g["home_score"]), int(g["away_score"])
    mar = [s[home] - s[away] for s in res]
    return {"key": key, "sim_margin": statistics.mean(mar), "sim_sd": statistics.pstdev(mar), "sim_total": statistics.mean(s[home] + s[away] for s in res),
            "sim_win": sum(x > 0 for x in mar) / N, "spread": float(g["spread_line"]), "total": float(g["total_line"]),
            "margin": hs - as_, "act_total": hs + as_}

if __name__ == "__main__":
    keys = sorted(k for k in GAMES if k[0] in WEEKS)
    with mp.Pool(2, initializer=init) as pool:
        out = [o for o in pool.map(one, keys, chunksize=8) if o]
    n = len(out)
    mae = lambda xs: sum(abs(x) for x in xs) / len(xs)
    r = {"season": SEASON, "games": n, "opts": OPTS,
         "margin_mae": round(mae([o["sim_margin"] - o["margin"] for o in out]), 3), "line_margin_mae": round(mae([o["spread"] - o["margin"] for o in out]), 3),
         "total_mae": round(mae([o["sim_total"] - o["act_total"] for o in out]), 3), "line_total_mae": round(mae([o["total"] - o["act_total"] for o in out]), 3),
         "total_bias": round(statistics.mean(o["sim_total"] - o["act_total"] for o in out), 2),
         "margin_bias_vs_line": round(statistics.mean(o["sim_margin"] - o["spread"] for o in out), 2),
         "sim_margin_sd": round(statistics.mean(o["sim_sd"] for o in out), 2),
         "corr_with_line": round(statistics.correlation([o["sim_margin"] for o in out], [o["spread"] for o in out]), 3),
         "brier": round(sum((o["sim_win"] - (o["margin"] > 0)) ** 2 for o in out) / n, 4)}
    ats = [o for o in out if abs(o["sim_margin"] - o["spread"]) >= 3 and o["margin"] != o["spread"]]
    r["ats_3plus"] = f'{sum((o["sim_margin"] > o["spread"]) == (o["margin"] > o["spread"]) for o in ats)}-{sum((o["sim_margin"] > o["spread"]) != (o["margin"] > o["spread"]) for o in ats)}'
    print(json.dumps(r))
    json.dump(out, open(f"{ROOT}/sim/bt_{SEASON}_{'_'.join(f'{k}{v:g}' for k, v in OPTS.items()) or 'base'}.json", "w"))
