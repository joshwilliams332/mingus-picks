# Mingus Picks

NFL player-prop picks for Mingus Sports: locked before kickoff, graded after, with an honest record.

- **Night games** (Thursday, Sunday and Monday night, late-season Saturdays): props pulled from
  [The Odds API](https://the-odds-api.com) within 4 hours of kickoff, compared with the Mingus Football projection model,
  and up to 2 picks a game locked when our chance (30% model + 70% the books' no-vig price) is 54%+ with a 3%+ edge.
- **Sunday 1 PM and 4 PM slates:** receiving and rushing yards, the best 5 per slate, tracked in their own Sunday record.
- **Grading:** same-day unofficial results from ESPN box scores, then the official grade from nflverse the next morning.
  Locked picks are never edited; a player who doesn't play is a void.

Projections come from [Mingus Football](https://github.com/joshwilliams332/mingus) (the fantasy site); this repo only
handles picks, odds and grading. Details for maintainers are in `CLAUDE.md`.

For entertainment. 21+ · Gamble responsibly · 1-800-GAMBLER

```sh
python3 -m unittest discover -s tests                                   # tests
python3 scripts/nfl_picks.py --data DATA --store STORE --no-odds        # local run without spending credits
```
Needs the `ODDS_API_KEY` repository secret.
