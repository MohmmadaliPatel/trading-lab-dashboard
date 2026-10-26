# Trading Lab dashboard

A simple, static website showing what Mohmmadali's paper-trading research bots have tested for Indian markets (NSE/BSE), what passed (nothing yet), the exploratory paper test, market news and the bot team.

**Paper trading and research only. Not financial advice. No real orders are placed.**

Live site: https://mohmmadalipatel.github.io/trading-lab-dashboard/

## Sections
| Tab | Shows |
|---|---|
| Overview | Plain-English status, key numbers, current suggestion, best out-of-sample result per strategy family |
| Strategies tried | Every backtest variant (search, filter, sort), family cards, OOS-by-family chart |
| Leaderboard & gate | Validated strategies (empty so far), the validation gate explained simply, near-miss candidates with capital needs |
| Paper trading | Exploratory Nifty weekly strangle journal, running P&L vs stop/retire levels, Trade Planner daily verdicts |
| Market news | Daily news logs by date (tags, impact, fact vs report, tickers, routing), events calendar with filters, FII/DII flows |
| Research pipeline | Rule ideas and their status, week ahead, weekly improvement cycles, every backtest run |
| Bots | Role, schedule, inputs/outputs and latest activity of each bot, flow diagram, Scout hits, Opportunity Hunter ideas |

## How it updates
Plain HTML/CSS/JS (`index.html`, `style.css`, `app.js`) plus generated JSON in `data/`. Chart.js and Mermaid load from jsDelivr.

```bash
/workspace/trading-lab-dashboard/update.sh            # rebuild data, safety scan, commit + push if changed
/workspace/trading-lab-dashboard/update.sh --no-push  # rebuild + scan only
```

`update.sh`:
1. runs `build_site.py`, which reads the bots' shared files **read-only** and writes derived data to `data/*.json`. Missing files are skipped (empty sections), never fatal;
2. scans everything that would be published (HTML/JS/CSS, `data/`, this README) with `rg` for credential-like strings, broker key names, one-time-code seeds, email addresses, phone numbers and personal details (exact patterns are in `update.sh`). **Any hit aborts before commit/push**;
3. commits with an IST timestamp and pushes to `main` only if something changed (GitHub Pages then redeploys in ~1 minute).

Sources (on the research box, never modified): `trading-lab/` (backtests.csv, BACKTEST_LOG.md, news/, scout/hits.csv, backtests/*/report.md), `trading-research/` (rules.md, digests, reports, paper/journal.csv), `india-day-trader/trader/state/` (planner_log.json, flows.json), `trader/journal/`, `groww-bot/reports/`, `opportunities/opportunities.csv`.
Only derived fields are published; raw config files, credentials and personal details are never copied.

## Caveats
- Fact / report labels and impact levels on news items are derived automatically from the wording and source domain of each log line. Always open the source.
- "Max DD" is shown as logged by each bot (percent of capital for most runs, rupees for some option grids).
- Near-miss numbers come from the research reports named on each card.
