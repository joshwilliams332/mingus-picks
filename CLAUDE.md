# Mingus Picks: notes for Claude

NFL player-prop picks for Mingus Sports (Josh, joshwilliams332): picks, odds pulls and grading. Moved here from
Mingus Football (`joshwilliams332/mingus`) on Nov 3, 2026. This repo is public.

## Ground rules (Mingus team charter)
- Honest record: picks lock before kickoff and are never edited; losses get posted like wins. Never "lock" or "guaranteed".
- Every public pick post, card or email carries "For entertainment. 21+ · Gamble responsibly · 1-800-GAMBLER".
- Secrets (the Odds API key) live in GitHub Actions secrets only. One account per service.
- The Odds API key is shared with Hoop Lab (500 credits a month). Every request costs credits, so **this repo does all NFL
  Odds API pulls**; Mingus Lab / NFL Lab (repo `nba-research`) only reads the files saved on this repo's `data` branch.
- Work ships as branch, PR into `main`, Josh merges. Check phone layouts (~390px) for anything people look at.

## How it fits with Mingus Football
- The projection model (`projection()`, `chance_over()`, `td_chance()`, the tuned settings) is developed and tested in
  Mingus Football (`scripts/projections.py` there, `scripts/model_review.py`, `scripts/backtest/`). `scripts/nfl_picks.py`
  here is a copy of it plus the picks code. When the model changes there, copy the model functions here too.
- Each picks run reads Mingus Football's live site data (`https://joshwilliams332.github.io/mingus/data/*.json`) and its
  tuned settings (`model/settings.json` on that repo's `data` branch).
- Outputs go to this repo's `data` branch: `picks/` (night), `picks/sun-early/`, `picks/sun-late/`, `odds/props/`,
  `odds/usage.json`, `tool/prop-tool.html`. File formats are relied on by NFL Lab (see the project doc
  `claude/plans/nfl-lab.md`); keep them stable or note changes in the football handoff.

## Picks system (moved from Mingus Football's notes)
- **Night-game best bets** (`scripts/nfl_picks.py`, tested in `tests/test_nfl_picks.py`, run by
  `.github/workflows/mingus-picks.yml`, separate from the deploy; it downloads the live site's data JSON instead of
  rebuilding). Night games only (kickoff 7 PM ET+: TNF, SNF, MNF, late-season Saturdays), Josh's choice so football
  uses little of the Odds API key it shares with Hoop Lab. Props pulled once per night game (4 markets: pass / rush /
  rec yds, receptions; 4 credits; event list free; never pulls below `CREDIT_RESERVE`), on the first run after
  `lock_opens()` (Josh, Nov 3 and 8: lines and picks out earlier): every Sunday game (1 PM, 4 PM and SNF) from 7 PM ET
  Saturday; TNF, MNF and late-season Saturday night games from 9 AM ET that morning; into `data` branch
  `odds/props/<game id>.json`. Files are named by the game's date (a Saturday-night lock writes Sunday's file). Picks lock once into `picks/YYYY-MM-DD.json` (never
  rewritten). Same rules as Hoop Lab: chance = 30% projection + 70% books' no-vig consensus at the most-posted line,
  skip if they differ by 20+ points, >= 54% and >= 3% edge at the best price, prices -200 to +180, one per player, up to
  2 per game, skip anyone Questionable / Doubtful / Out / DNP, regulars only (20 att / 8 car / 3.5 tgt a game), line
  quoted by 2+ books. Projection = opportunities x efficiency, settings tuned Oct 31 on 2021-2025 (Josh's request:
  train on past seasons, test on this one): att / car / tgt per game as a recency-weighted average (4-game half-life)
  x defense allowed to the position (quarter strength, 0.9-1.1) x team implied vs week average (quarter strength,
  0.9-1.1) x injury openings (60% of Out/Doubtful teammates' recent volume, by share, max +25%; not backtestable);
  efficiency = his recency-weighted rate (6-game half-life) steadied toward the position's league rate (20
  opportunities); x `MEAN_ADJ` (1.03; passing yards 0.93). Game script and the defense's per-play effect were tested
  and dropped (no help). So was discounting low-snap games (early injury exits; Nov 1, nflverse snap counts: dropping or
  scaling games under 40-80% of his usual snap share, also only dips he bounced back from) - worse on 2021-2025 and 2026,
  because low-snap games are mostly real role changes and future games carry the same exit risk (`snap` option in
  `scripts/backtest/engine.py`, off). Averaged 50/50 with Sleeper's stat line when players.json has it. Spread = his game-to-game
  spread blended with `PRIOR_CV` (counted as 8 games) x1.15. Chance of the over: log-normal for rush / rec yds and
  catches (yardage is skewed), bell curve for passing yards. Backtest (each game projected only from earlier games,
  vs a "typical" line = floor(his average) + 0.5, since no historical book lines exist): 2021-2025 Brier 0.240
  (21,949 predictions; coin 0.250); held-out 2026 Weeks 5-8 0.238-0.240 (first version 0.259). Over leans (60%+)
  hit 60%, under leans (40%-) 63%. Receiving yards strongest; passing yards about even with a coin. Typical lines
  are easier than real book lines, so real edges are smaller. Backtest scripts: `scripts/backtest/`; the standalone
  over/under tool ("Mingus Prop Model" artifact, not on the site): `scripts/prop_tool/`.
  Each pick's "why" (one post reply) leads with projection vs
  line, then the strongest of matchup rank, injury openings, target share / carries, team total, last-5 hits and a
  top-5 Next Gen Stat; the email adds a not-for-posting "Deep dive" with every factor.
  Grading reads nflverse `stats_player_week` (void if the game's stats exist but he has no row). The morning after each
  night, `picks/YYYY-MM-DD-results.json` (that night's graded picks + season record, written once; Josh wanted results
  the next morning like Hoop Lab, not just weekly). `week-NN-recap.json` is written once a week's night games are all graded; `record.json` holds the season record. Week 8 is a test run
  (`RECORD_START_WEEK = 9`): emailed, graded, marked TEST, not counted. Every post carries the 21+ line.
  Delivery (Josh, Nov 3, 8 and 9: one email per window, sent by GitHub, no Claude tasks): the job's "Email new picks
  and results" step (`scripts/send_emails.py`, tested in `tests/test_send_emails.py`) emails Josh each new file once
  through Gmail SMTP (secrets `SMTP_USER` = the Gmail address, `SMTP_PASS` = its app password, `EMAIL_TO`); sent paths
  are kept in `picks/sent.json` (the first run marks existing files as sent). Emailed: night picks `picks/<day>.json`
  (Thursday / Monday / Saturday, ~9 AM that morning), Sunday picks `picks/sunday/<Sunday>.json` (Saturday night), the
  Sunday-night update `picks/headsup/<day>-night.json` (~7 PM, only when `changed`), Sunday results
  `picks/sunday/<day>-results.json` (after the night game) and night results `picks/<day>-results.json` (next morning).
  Sunday-dated night files are skipped (they're in the Sunday emails); slate and `-quick` files aren't emailed. No model
  backtest exists yet (no historical lines); the public record is the test.
- **Sunday daytime slates** (Josh, Nov 1, 2026: model picks for the 1 PM and 4 PM games, "for tracking"; same script,
  `SLATES` in nfl_picks.py). "early" = Sunday kickoffs noon-3:59 PM ET, "late" = 4-6:59 PM; both lock Saturday night
  with SNF. Not London 9:30 AM or Thanksgiving.
  **One Sunday email** (`sunday_preview`, Josh Nov 3): `picks/sunday/<Sunday>.json`, written once all of Sunday's
  slates have locked (or at 11:30 PM ET Saturday with whatever has), one post per time slot; emailed Saturday ~7:45 PM.
  Files `picks/sun-early/` and `picks/sun-late/` (picks + morning-after results); both
  count in one `picks/sunday-record.json`, never mixed into the night record. Only receiving + rushing yards
  (`DAY_MARKETS`, 2 credits a game, ~22 a Sunday, ~110 a month) to stay inside the ~200/month football budget; same
  pick rules, best 5 by edge per slate (`DAY_MAX_PICKS`). Counts from Week 8 (`DAY_RECORD_START_WEEK`). Locks come
  before inactives (inactive = void). The Monday 8:41 AM results email adds both slates.
  Sunday results (unofficial): `quick_results` grades each Sunday slate (1 PM, 4 PM, night) from ESPN's box scores
  (site.api.espn.com, free; reachable from Actions, not from the cloud sandbox) once its games are final ->
  `picks/sun-*/YYYY-MM-DD-quick.json` / `picks/YYYY-MM-DD-quick.json`, written once, never counted; a player missing from
  ESPN's box score shows as "check". `sunday_results` combines them into `picks/sunday/<day>-results.json` (one post
  per slot) after the night game; emailed ~11:47 PM ET. The records still come from nflverse the next morning, with no
  separate email.

## Other pieces
- **Prop tool** (`scripts/prop_tool/`, `.github/workflows/prop-tool.yml`): the over/under tool page, rebuilt into the data
  branch `tool/prop-tool.html`; a scheduled Claude task republishes it to Josh's private artifact "Mingus Prop Model"
  (https://claude.ai/artifact/1QhH9iBrRdqriGTsrCV5qj). Never on a public site.
- **Game simulator** (`scripts/sim/`, experimental, not wired into picks): snap-by-snap Monte Carlo from nflverse
  play-by-play (`sim2.py`), backtest harness `bt.py` (`python3 scripts/sim/bt.py ROOT SEASON N WEEKS key=value...`, needs
  `ROOT/pbp/pbp_<season>.csv.gz` and `ROOT/hist/games.csv`). 2025 test: margin MAE 10.34 vs the line's 9.92, total
  10.43 vs 9.94, so it doesn't beat the market; anchor it to the line (75% market) and use it for player ranges,
  touchdown and longest-TD chances. Next: 2023-2025 test, weather/rest only if they hold up.

## Odds API
- Odds API key: `ODDS_API_KEY` repo secret, the same free key Hoop Lab uses (500 credits/month shared). Night games
  only ≈ 50-60 credits/month. Hoop Lab's budget spends whatever is left, so it should hold back ~60/month for football.
  If Josh upgrades ($30/month = 20,000 credits), all slates and a pre-kickoff closing-line pull become affordable.

## Open threads
- **Scheduled runs didn't fire** (Nov 3-9, 2026): no `schedule` run ever started under the old file name `nfl-picks.yml`
  (only push runs), while Mingus Football's schedules run daily; the YAML was valid. Renamed to `mingus-picks.yml` on
  Nov 9 so GitHub registers it fresh. If scheduled runs still don't show up, ask GitHub Support; until then runs only
  happen on a push (main or a `run/<time>` branch) or "Run workflow".
