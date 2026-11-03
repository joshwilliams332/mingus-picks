"""Mingus Football game simulator v1: snap-by-snap Monte Carlo from this season's nflverse play-by-play.

v1 vs v0: players act like themselves. The ball carrier / target is picked first (recent shares), then the play is
drawn partly from his own plays, partly from what the defense allows, partly from the league in that part of the field.
Sacks and scrambles come from the starting QB's own dropbacks blended with the defense's pressure; designed QB runs
only from the starter's own games. Home field = the home offense gets a second try at a failed snap with prob HFA.
"""
import csv, gzip, math, random, statistics
from collections import Counter, defaultdict

W_OWN, W_DEF = 0.4, 0.3        # rest: league, same part of the field
HFA = 0.05


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def zone(yl):
    return 0 if yl <= 10 else 1 if yl <= 20 else 2


def load(path):
    """All plays + special-teams samples from one nflverse pbp file."""
    rows = list(csv.DictReader(gzip.open(path, "rt")))
    plays, specials = [], []
    for i, r in enumerate(rows):
        pt, wk = r["play_type"], int(r["week"]) if r["week"] else 0
        if r["season_type"] != "REG":
            continue
        if pt == "kickoff" and i + 1 < len(rows) and rows[i + 1]["game_id"] == r["game_id"] and rows[i + 1]["yardline_100"]:
            specials.append(("kick", wk, num(rows[i + 1]["yardline_100"])))
        if pt == "punt" and r["yardline_100"]:
            yl = num(r["yardline_100"])
            start = 80 if r["touchback"] == "1" else 100 - (yl - num(r["kick_distance"]) + num(r["return_yards"]))
            specials.append(("punt", wk, max(1, min(99, yl - (100 - start)))))
        if pt == "field_goal" and r["kick_distance"]:
            specials.append(("fg", wk, (num(r["kick_distance"]), r["field_goal_result"] == "made")))
        if r["down"] == "4" and pt in ("run", "pass", "punt", "field_goal") and r["yardline_100"]:
            specials.append(("4th", wk, (num(r["ydstogo"]), num(r["yardline_100"]), "go" if pt in ("run", "pass") else pt)))
        if pt not in ("run", "pass") or not r["down"] or not r["yardline_100"]:
            continue
        plays.append({"g": r["game_id"], "week": wk, "off": r["posteam"], "def": r["defteam"], "home": r["home_team"],
                      "down": int(num(r["down"])), "togo": num(r["ydstogo"]), "yl": num(r["yardline_100"]),
                      "pass": r["pass"] == "1", "scr": r["qb_scramble"] == "1", "sack": r["sack"] == "1",
                      "yds": num(r["yards_gained"]), "comp": r["complete_pass"] == "1", "int": r["interception"] == "1",
                      "fum": r["fumble_lost"] == "1", "epa": num(r["epa"]), "diff": num(r["score_differential"]), "secs": num(r["game_seconds_remaining"]),
                      "qb": r["passer_player_name"] or (r["rusher_player_name"] if r["qb_scramble"] == "1" else ""),
                      "rec": r["receiver_player_name"], "rusher": r["rusher_player_name"]})
    return plays, specials


class Model:
    def __init__(self, plays, specials, before_week, prior=None, opts=None):
        opts = opts or {}
        self.opts = opts
        P = [p for p in plays if p["week"] < before_week]
        S = [s for s in specials if s[1] < before_week]
        if prior:   # last season, down-weighted: a random share of its plays joins the pools
            keep = random.Random(before_week)
            frac = opts.get("prior", 0.0) * max(0.0, 1 - (before_week - 1) / 12)
            P = [dict(p, week=0, old=True) for p in prior[0] if keep.random() < frac] + P
            S = [s for s in prior[1] if keep.random() < frac] + S
        self.P = P
        self.kick = [s[2] for s in S if s[0] == "kick"]
        self.punt = [s[2] for s in S if s[0] == "punt"]
        self.fg = [s[2] for s in S if s[0] == "fg"]
        self.fourth = [s[2] for s in S if s[0] == "4th"]
        self.lg_pr, self.team_pr = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
        for p in P:
            b = self.bucket(p["down"], p["togo"], p["diff"], p["secs"])
            self.lg_pr[b][0] += p["pass"]; self.lg_pr[b][1] += 1
            self.team_pr[p["off"]][0] += p["pass"]; self.team_pr[p["off"]][1] += 1
        self.lg_all = sum(v[0] for v in self.lg_pr.values()) / sum(v[1] for v in self.lg_pr.values())
        # pools
        self.throws = defaultdict(list)    # ("rec", name) / ("def", team, zone) / ("lg", zone)
        self.runs = defaultdict(list)
        self.sacks, self.scr = [], defaultdict(list)
        self.qb_db, self.def_db = defaultdict(lambda: [0, 0, 0]), defaultdict(lambda: [0, 0])   # dropbacks, sacks, scrambles
        for p in P:
            z = zone(p["yl"])
            if p["pass"]:
                if p["qb"]:
                    q = self.qb_db[p["qb"]]; q[0] += 1; q[1] += p["sack"]; q[2] += p["scr"]
                d = self.def_db[p["def"]]; d[0] += 1; d[1] += p["sack"]
                if p["sack"]:
                    self.sacks.append(p["yds"])
                elif p["scr"]:
                    self.scr[p["qb"]].append(p); self.scr["_lg"].append(p)
                else:
                    if p["rec"]:
                        self.throws[("rec", p["off"], p["rec"], p["qb"])].append(p)   # his catches from this QB only
                    self.throws[("def", p["def"], z)].append(p); self.throws[("def", p["def"])].append(p)
                    self.throws[("lg", z)].append(p)
            else:
                if p["rusher"]:
                    self.runs[("ru", p["off"], p["rusher"])].append(p)
                self.runs[("def", p["def"], z)].append(p); self.runs[("def", p["def"])].append(p)
                self.runs[("lg", z)].append(p)
        n = sum(v[0] for v in self.qb_db.values())
        self.lg_sack = sum(v[1] for v in self.qb_db.values()) / n
        self.lg_scr = sum(v[2] for v in self.qb_db.values()) / n
        self.ratings = self.fit_ratings([p for p in P if not p.get("old")], [p for p in P if p.get("old")], opts.get("ridge", 300.0))

    @staticmethod
    def fit_ratings(cur, old, lam):
        """Opponent-adjusted EPA per play, separately for pass and run: epa = league + offense + defense (ridge),
        last season's plays (if any) at a third of the weight. Returns {(kind, 'off'|'def', team): EPA/play vs avg}."""
        import numpy as np
        out = {}
        for kind in ("pass", "run"):
            rows = [(p, 1.0) for p in cur if p["pass"] == (kind == "pass")] + [(p, 0.33) for p in old if p["pass"] == (kind == "pass")]
            if not rows:
                continue
            teams = sorted({p["off"] for p, _ in rows} | {p["def"] for p, _ in rows})
            ix = {t: i for i, t in enumerate(teams)}
            k = len(teams)
            A = np.zeros((2 * k, 2 * k)); bvec = np.zeros(2 * k)
            mu = sum(p["epa"] * w for p, w in rows) / sum(w for _, w in rows)
            for p, w in rows:
                i, j = ix[p["off"]], k + ix[p["def"]]
                y = max(-4.0, min(4.0, p["epa"])) - mu
                A[i, i] += w; A[j, j] += w; A[i, j] += w; A[j, i] += w
                bvec[i] += w * y; bvec[j] += w * y
            A += lam * np.eye(2 * k)
            x = np.linalg.solve(A, bvec)
            for t in teams:
                out[(kind, "off", t)] = float(x[ix[t]]); out[(kind, "def", t)] = float(x[k + ix[t]])
        return out

    @staticmethod
    def bucket(down, togo, diff, secs):
        return (min(down, 3), 0 if togo <= 2 else 1 if togo <= 6 else 2, 0 if diff <= -9 else 1 if diff < 9 else 2, 1 if secs < 600 else 0)

    def pass_prob(self, team, down, togo, diff, secs):
        a, n = self.lg_pr[self.bucket(down, togo, diff, secs)]
        base = (a + 5 * self.lg_all) / (n + 5)
        ta, tn = self.team_pr[team]
        t = (ta + 50 * self.lg_all) / (tn + 50)
        odds = base / (1 - base) * (t / (1 - t)) / (self.lg_all / (1 - self.lg_all))
        return odds / (1 + odds)

    def roles(self, team, qb, active=None, out=()):
        """Target and designed-carry shares over the team's last 4 games before the cutoff. active: if given, only these
        players (a backtest knows who played). QB designed runs only from games the starter played."""
        wks = sorted({p["week"] for p in self.P if p["off"] == team and not p.get("old")})[-4:]   # this season only
        qb_games = {p["g"] for p in self.P if p["off"] == team and p["qb"] == qb}
        qbs = {n for n, v in self.qb_db.items() if v[0] >= 20} | {qb}   # real QBs, not trick-play passers
        tg, ca = Counter(), Counter()
        for p in self.P:
            if p["off"] != team or p["week"] not in wks or p.get("old"):
                continue
            if p["pass"] and not p["sack"] and not p["scr"] and p["rec"] and p["rec"] not in qbs:
                tg[p["rec"]] += 1
            if not p["pass"] and p["rusher"]:
                if p["rusher"] in qbs:
                    if p["rusher"] == qb and p["g"] in qb_games:
                        ca[qb] += 1
                else:
                    ca[p["rusher"]] += 1
        for c in (tg, ca):
            for n in list(c):
                if n in out or (active is not None and n not in active):
                    c.pop(n)
        return tg, ca


class Sim:
    def __init__(self, model, away, home, qbs, out=None, active=None, seed=1, opts=None, ctx=None):
        self.m, self.away, self.home, self.qb = model, away, home, qbs
        self.rnd = random.Random(seed)
        self.o, self.ctx = opts or model.opts or {}, ctx or {}
        self.w_own, self.w_def = self.o.get("wown", W_OWN), self.o.get("wdef", W_DEF)
        # backup / new QBs: pass rating pulled toward a backup baseline when he has few dropbacks
        self.qb_adj = {}
        for t in (away, home):
            n = model.qb_db[qbs[t]][0]
            share = min(1.0, n / 150)
            self.qb_adj[t] = (1 - share) * self.o.get("backup", 0.0)
        self.roles = {t: model.roles(t, qbs[t], (active or {}).get(t), (out or {}).get(t, ())) for t in (away, home)}

    def draw_throw(self, off, de, rec, yl):
        m, r, z = self.m, self.rnd, zone(yl)
        u = r.random()
        own = m.throws.get(("rec", off, rec, self.qb[off])) or []
        if u < self.w_own and len(own) >= 12:
            return r.choice(own)
        if u < self.w_own + self.w_def:
            pz = m.throws.get(("def", de, z)) or []
            pl = pz if len(pz) >= 15 else m.throws.get(("def", de)) or []
            if pl:
                return r.choice(pl)
        return r.choice(m.throws[("lg", z)])

    def draw_run(self, off, de, rusher, yl):
        m, r, z = self.m, self.rnd, zone(yl)
        u = r.random()
        own = m.runs.get(("ru", off, rusher)) or []
        if u < self.w_own and len(own) >= 12:
            return r.choice(own)
        if u < self.w_own + self.w_def:
            pz = m.runs.get(("def", de, z)) or []
            pl = pz if len(pz) >= 15 else m.runs.get(("def", de)) or []
            if pl:
                return r.choice(pl)
        return r.choice(m.runs[("lg", z)])

    def snap(self, off, de, kind, yl):
        """One offensive snap -> event dict (nothing recorded yet)."""
        m, r = self.m, self.rnd
        tg, ca = self.groles[off] if getattr(self, "groles", None) else self.roles[off]
        qb = self.qb[off]
        if kind == "pass":
            q, d = m.qb_db[qb], m.def_db[de]
            p_sack = 0.5 * (q[1] + 40 * m.lg_sack) / (q[0] + 40) + 0.5 * (d[1] + 40 * m.lg_sack) / (d[0] + 40)
            p_scr = (q[2] + 40 * m.lg_scr) / (q[0] + 40)
            u = r.random()
            if u < p_sack:
                return {"t": "sack", "y": r.choice(m.sacks), "qb": qb, "fum": False, "int": False, "ok": False}
            if u < p_sack + p_scr:
                pool = m.scr.get(qb) if len(m.scr.get(qb, [])) >= 8 else m.scr["_lg"]
                p = r.choice(pool)
                return {"t": "scr", "y": min(p["yds"], yl), "qb": qb, "fum": p["fum"], "int": False, "ok": True, "who": qb}
            rec = r.choices(list(tg), weights=list(tg.values()))[0]
            p = self.draw_throw(off, de, rec, yl)
            if p["int"]:
                return {"t": "int", "y": p["yds"], "qb": qb, "rec": rec, "fum": False, "int": True, "ok": False}
            if not p["comp"]:
                return {"t": "inc", "y": 0, "qb": qb, "rec": rec, "fum": False, "int": False, "ok": False}
            return {"t": "comp", "y": min(p["yds"], yl), "qb": qb, "rec": rec, "fum": p["fum"], "int": False, "ok": True, "who": rec}
        ru = r.choices(list(ca), weights=list(ca.values()))[0]
        p = self.draw_run(off, de, ru, yl)
        return {"t": "run", "y": min(p["yds"], yl), "ru": ru, "fum": p["fum"], "int": False, "ok": True, "who": ru}

    @staticmethod
    def success(ev, down, togo):
        need = togo * (0.4 if down == 1 else 0.6 if down == 2 else 1.0)
        return ev["ok"] and not ev["fum"] and ev["y"] >= need

    def commit(self, ev, b):
        t = ev["t"]
        if t == "sack":
            b[ev["qb"]]["sacked"] += 1
        elif t == "scr":
            b[ev["qb"]]["car"] += 1; b[ev["qb"]]["rush_yds"] += ev["y"]
        elif t in ("int", "inc", "comp"):
            b[ev["qb"]]["att"] += 1; b[ev["rec"]]["tgt"] += 1
            if t == "int":
                b[ev["qb"]]["int"] += 1
            if t == "comp":
                b[ev["qb"]]["cmp"] += 1; b[ev["qb"]]["pass_yds"] += ev["y"]; b[ev["rec"]]["rec"] += 1; b[ev["rec"]]["rec_yds"] += ev["y"]
        else:
            b[ev["ru"]]["car"] += 1; b[ev["ru"]]["rush_yds"] += ev["y"]

    def tilt(self, off, de, kind, form):
        """How much this offense's snap leans good (+) or bad (-): home field, ratings, backup QB, this game's form,
        weather, rest. Applied as: with prob |tilt| a failed (+) or successful (-) snap is played again."""
        o, c, m = self.o, self.ctx, self.m
        t = 0.0
        if not c.get("neutral"):
            t += o.get("hfa", HFA) * (1 if off == self.home else -1)
        if o.get("rate"):
            r = m.ratings.get((kind, "off", off), 0) + m.ratings.get((kind, "def", de), 0)
            if kind == "pass":
                r += self.qb_adj[off]
            t += o["rate"] * r
        t += form[off]
        t += (o.get("adj") or {}).get(off, 0.0) if isinstance(o.get("adj"), dict) else 0.0   # anchor to the betting line
        wind = c.get("wind", 0) if c.get("roof") not in ("dome", "closed") else 0
        if o.get("wind") and kind == "pass" and wind > 12:
            t -= o["wind"] * (wind - 12) / 10
        if o.get("rest"):
            mine, theirs = (c.get("home_rest", 7), c.get("away_rest", 7)) if off == self.home else (c.get("away_rest", 7), c.get("home_rest", 7))
            t += o["rest"] * max(-1, min(1, (mine - theirs) / 7))
        return max(-0.6, min(0.6, t))

    def fourth_choice(self, togo, yl, diff, secs):
        r = self.rnd
        if secs < 300 and diff < 0:
            return "go"
        if yl + 17 <= 35 and r.random() < 0.85 and not (togo <= 1 and yl <= 3):
            return "field_goal"
        near = [c for t, y, c in self.m.fourth if abs(t - togo) <= (1 if togo <= 3 else 3) and abs(y - yl) <= 10]
        return r.choice(near) if len(near) >= 10 else ("punt" if yl > 40 else "field_goal" if yl < 30 else "go")

    def fg_good(self, dist):
        near = [mk for d, mk in self.m.fg if abs(d - dist) <= 3]
        return self.rnd.random() < (sum(near) / len(near) if len(near) >= 10 else max(0.3, 1 - 0.012 * max(0, dist - 30)))

    def game(self):
        m, r = self.m, self.rnd
        A, H = self.away, self.home
        other = lambda t: H if t == A else A
        score = {A: 0, H: 0}
        box = {t: defaultdict(lambda: defaultdict(float)) for t in (A, H)}
        self.longest = (0, None, None)
        sd = self.o.get("form", 0.0)
        form = {A: r.gauss(0, sd), H: r.gauss(0, sd)}
        k = self.o.get("share_k", 0)
        if k:   # this game's roles: each player's share swings game to game (some weeks he just isn't involved)
            self.groles = {t: tuple(Counter({n: w * r.gammavariate(k, 1 / k) for n, w in c.items()}) for c in self.roles[t]) for t in (A, H)}
        secs, half2 = 3600, False
        poss = A if r.random() < 0.5 else H
        recv2 = other(poss)
        st = {"yl": r.choice(m.kick), "down": 1, "togo": 10}

        def new(team, yl):
            nonlocal poss
            poss = team
            st.update(yl=max(1, min(99, yl)), down=1, togo=min(10, max(1, yl)))

        for _ in range(400):
            if secs <= 1800 and not half2:
                half2 = True
                new(recv2, r.choice(m.kick))
            if secs <= 0:
                break
            off, de = poss, other(poss)
            diff, yl = score[off] - score[de], st["yl"]
            if st["down"] == 4:
                ch = self.fourth_choice(st["togo"], yl, diff, secs)
                if ch == "punt":
                    secs -= 8
                    net = r.choice(m.punt)
                    new(de, 100 - (yl - net) if yl - net > 0 else 80)
                    continue
                if ch == "field_goal":
                    secs -= 5
                    if self.fg_good(yl + 17):
                        score[off] += 3
                        new(de, r.choice(m.kick))
                    else:
                        new(de, 100 - (yl + 7))
                    continue
            kind = "pass" if r.random() < m.pass_prob(off, st["down"], st["togo"], diff, secs) else "run"
            b = box[off]
            ev = self.snap(off, de, kind, yl)
            tl = self.tilt(off, de, kind, form)
            good = self.success(ev, st["down"], st["togo"])
            if (tl > 0 and not good and r.random() < tl) or (tl < 0 and good and r.random() < -tl):
                ev = self.snap(off, de, kind, yl)
            self.commit(ev, b)
            y, ok, picked, fum, who = ev["y"], ev["ok"], ev["int"], ev["fum"], ev.get("who")
            # defensive / return touchdowns
            if self.o.get("dst"):
                if picked and r.random() < 0.08:
                    score[de] += 7; self.longest = max(self.longest, (yl, de, "DEF")); new(off, r.choice(m.kick)); secs -= 6; continue
                if fum and r.random() < 0.05:
                    score[de] += 7; self.longest = max(self.longest, (100 - yl, de, "DEF")); new(off, r.choice(m.kick)); secs -= 6; continue
            stops = kind == "pass" and not ok and not picked
            hurry = (secs % 1800) < 120 or (secs < 300 and diff < 0)
            secs -= 6 if stops else (18 if hurry else self.o.get("clock", 37))
            if picked:
                new(de, 100 - (yl - max(y, 8)))
                continue
            if fum:
                new(de, 100 - (yl - y))
                continue
            if y >= yl:
                if who and yl > self.longest[0]:
                    self.longest = (yl, off, who)
                if who:
                    b[who]["td"] += 1
                    if kind == "pass" and who != self.qb[off]:
                        b[self.qb[off]]["pass_td"] += 1
                score[off] += 6 + (1 if r.random() < 0.94 else 0)
                new(de, r.choice(m.kick))
                continue
            yl -= y
            if yl >= 100:
                score[de] += 2
                new(de, r.choice(m.kick))
                continue
            if y >= st["togo"]:
                st.update(yl=yl, down=1, togo=min(10, yl))
            else:
                st.update(yl=yl, down=st["down"] + 1, togo=st["togo"] - y)
                if st["down"] > 4:
                    new(de, 100 - yl)
        if score[A] == score[H]:
            t = A if r.random() < 0.5 else H
            for _ in range(6):
                score[t] += r.choices([0, 3, 7], weights=[0.55, 0.22, 0.23])[0]
                if score[A] != score[H]:
                    break
                t = other(t)
        return score, box

    def run(self, n):
        res, boxes = [], []
        self.longs = []
        for _ in range(n):
            s, b = self.game()
            res.append(s); boxes.append(b); self.longs.append(self.longest)
        return res, boxes
