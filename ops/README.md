# ops — price refresh and publish

One command refreshes prices and republishes the site:

```bash
rm -f ops/.last-run && ./ops/daily.sh
```

| file | role |
| --- | --- |
| `daily.sh` | guards + `update.py` + publish. The real work. |
| `deploy.sh` | force-replaces the `gh-pages` branch with `docs/` |
| `last_session.py` | prints the most recent US session that should have data |

## Guards — why it's safe to run any time

`daily.sh` is idempotent and cheap to re-run; four guards decide whether there
is real work to do.

1. **Once a day** — `ops/.last-run` holds the last date that completed. Same
   date, immediate exit. `rm -f ops/.last-run` is how you run again today.
2. **Network** — Yahoo must answer and GitHub must return 2xx. On failure it
   does *not* stamp. (Yahoo answers a bare `curl` with 429 even when yfinance's
   session works, so any HTTP response counts as reachable — requiring 2xx
   here would skip every day forever.)
3. **New data exists** — refetches only when the cube's `as_of` is behind the
   last closed US session. Weekends and same-day re-runs cost seconds, not
   minutes.
4. **Site is behind the data** — publish state lives in `ops/.last-deploy`,
   separate from the data stamp, so a refresh whose deploy failed republishes
   on the next run instead of stranding a fresh dataset behind a stale site.

Market holidays are not modelled, so the day after one it fetches, finds
nothing new, and leaves `as_of` behind — cheaper than carrying an exchange
calendar.

## It is not scheduled

A launchd agent was built for this and abandoned. Background agents get no TCC
grant, so reaching `~/Documents` (the repo) and `~/Desktop` (the reports) dies
instantly with `Operation not permitted` — exit 126, before the script can log
anything. Fixing it means a standing Full Disk Access grant for whatever
launchd executes, which for `/bin/bash` would mean every shell script on the
machine. Not worth it for a job that takes one command; run it manually, or via
the `quant-update` skill.

## Why the site is published to an orphan branch

The cube is ~28 MB of dense numeric JS whose values shift wholesale each day,
so git cannot delta it. Measured on a real refresh: **82 of 83 blobs stored in
full even at `--window=250`, 9.4 MB per rebuild**. Committing that daily to
`main` would add roughly **2.3 GB a year** to a public repo GitHub wants under
1 GB.

So `docs/` is gitignored build output, and `deploy.sh` publishes it as a
single force-replaced commit on `gh-pages`. The branch is always exactly one
commit; the published payload costs one snapshot's space, permanently. `main`
carries source only — python, `web/*.html`, README.

Pages serves from `gh-pages` / root. `deploy.sh` refuses to push unless the
site looks whole (both key pages non-empty, ≥80 cube shards, ≥20 MB), so a
half-written build can't replace a working site.

## Operating it

```bash
rm -f ops/.last-run && ./ops/daily.sh      # the normal invocation
tail -20 ops/logs/runs.log                 # one line per decision
cat ops/logs/$(date +%F).log               # full pipeline output for today
./ops/deploy.sh                            # republish without refetching
./.venv/bin/python update.py               # force a full refetch, ignoring guards
```

Failures raise a macOS notification and leave the stamp unwritten, so the next
run retries rather than assuming the day is done. A failed *deploy* after a
successful *refresh* is logged loudly: local data is fresh but the site is
stale — rerun `./ops/deploy.sh`.

Non-fatal `validate.py` findings are copied into `runs.log` as `warn:` lines;
staleness is graded there, so a few thin symbols stalling on Yahoo's side won't
stop the other ~700 from publishing.

Per-day logs older than 30 days are deleted; `runs.log` is kept.
