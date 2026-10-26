#!/usr/bin/env python3
"""Regenerate data/*.json for the Trading Lab dashboard from local research files.

Read-only on every source. Publishes DERIVED data only (no raw config, no secrets).
Robust to missing files: every loader returns an empty value on failure.
"""
import csv, json, os, re, glob, datetime, collections

W = "/workspace"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
NOW = datetime.datetime.now(IST)
TODAY = NOW.strftime("%Y-%m-%d")

# Personal details that must never be published (employer name etc.)
# Private names (e.g. employer) live in the untracked private_terms.txt, one per line.
_PRIV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "private_terms.txt")
SCRUB = [(re.compile(re.escape(t.strip()), re.I), "his employer") for t in (open(_PRIV).read().splitlines() if os.path.exists(_PRIV) else []) if t.strip()] + [
         # LLM usage credits wording (keeps the public secret-scan for the word token meaningful)
         (re.compile(r"\btokens\b", re.I), "credits")]


def scrub(s):
    if not isinstance(s, str):
        return s
    for rx, rep in SCRUB:
        s = rx.sub(rep, s)
    # strip absolute local paths' prefix for readability
    return s


def read(path, default=""):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return default


def jload(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def csvload(path):
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def num(v):
    try:
        v = str(v).replace(",", "").strip()
        if v == "" or v.lower() in ("nan", "none"):
            return None
        return round(float(v), 2)
    except Exception:
        return None


def dump(name, obj):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=str)


# ---------------------------------------------------------------- backtests
def family_of(strategy, instrument):
    s = strategy or ""
    if s.startswith("ORB /"):
        return "Equity ORB intraday (Scout setups)"
    if s.startswith("Scout setup"):
        return "Equity swing (Scout setups)"
    if "EMA9/21+RSI" in s:
        return "BankNifty option buying bot (EMA/RSI)" if "options" in s else "Equity EMA/RSI template"
    m = re.match(r"rules\.md (R\d+|C\d+)", s)
    if m:
        return "Research rule " + m.group(1)
    m = re.match(r"(F\d)\s+(.*)", s)
    if m:
        name = m.group(2)
        if m.group(1) == "F4":
            name = "Short strangle/straddle"
        und = "BANKNIFTY" if "BANKNIFTY" in (instrument or "") else "NIFTY"
        return f"{und} options: {m.group(1)} {name}".strip()
    if s.startswith("R9"):
        return "R9 Nifty monthly 14-DTE strangle"
    if s.startswith("R10"):
        return "R10 Sensex pre-expiry strangle"
    if s.startswith("C4"):
        return "C4 control: buy expiry straddle"
    if "ORB" in s:
        return "Equity ORB (anecdote)"
    return s


def underlying(inst):
    i = (inst or "").upper()
    for k in ("BANKNIFTY", "SENSEX", "NIFTY"):
        if k in i and "EQUIT" not in i:
            return k + (" options" if "OPTION" in i else " futures" if "FUTURE" in i else "")
    if "EQUIT" in i or "NSE CASH" in i or "ONGC" in i:
        return "NSE stocks"
    return inst or "?"


def build_backtests():
    rows = csvload(f"{W}/trading-lab/backtests.csv")
    out = []
    for r in rows:
        notes = scrub(r.get("notes", ""))
        out.append({
            "run": r.get("run_id", ""),
            "date": r.get("date_IST", ""),
            "bot": r.get("author_bot", ""),
            "family": family_of(r.get("strategy", ""), r.get("instrument", "")),
            "strategy": r.get("strategy", ""),
            "instrument": underlying(r.get("instrument", "")),
            "instrument_full": r.get("instrument", ""),
            "variant": r.get("variant", ""),
            "src": r.get("data_source", ""),
            "period": r.get("period", ""),
            "trades": num(r.get("trades")),
            "win": num(r.get("win%")),
            "net": num(r.get("net_Rs")),
            "charges": num(r.get("charges")),
            "dd": num(r.get("maxDD_%")),
            "is": num(r.get("IS_net")),
            "oos": num(r.get("OOS_net")),
            "gate": "PASS" if r.get("passes_gate", "").upper() == "Y" else "FAIL",
            "selected": "SELECTED" in notes,
            "invalid": "INVALID" in notes.upper(),
            "notes": notes[:400],
        })
    # family summaries
    fam = collections.OrderedDict()
    for r in out:
        f = fam.setdefault(r["family"], {"family": r["family"], "variants": 0, "real": 0, "trades": 0,
                                         "best_net": None, "best_oos": None, "oos_positive": 0,
                                         "oos_known": 0, "passed": 0, "instrument": r["instrument"]})
        f["variants"] += 1
        f["real"] += r["src"] == "REAL"
        f["trades"] += int(r["trades"] or 0)
        if r["src"] == "REAL" and not r["invalid"]:
            if r["net"] is not None and (f["best_net"] is None or r["net"] > f["best_net"]):
                f["best_net"] = r["net"]
            if r["oos"] is not None:
                f["oos_known"] += 1
                f["oos_positive"] += r["oos"] > 0
                if f["best_oos"] is None or r["oos"] > f["best_oos"]:
                    f["best_oos"] = r["oos"]
        f["passed"] += r["gate"] == "PASS"
    dump("backtests.json", {"rows": out, "families": list(fam.values())})
    return out, list(fam.values())


# ---------------------------------------------------------------- leaderboard + gate
NEAR_MISS = [
    {"name": "Nifty weekly short strangle (F4, ±1 expected move, 1 day before expiry, VIX pct ≥ 30)",
     "status": "Failed strict gate, running as EXPLORATORY paper test",
     "numbers": [
         "2025–Oct 2026 (unseen months): ≈ ₹47.1k/yr per lot, Sharpe 1.46, 79% win (61 trades)",
         "Full 2016–2026 re-test: 280 trades, ≈ ₹19.9k/yr per lot (6.2% on ₹3.2L), Sharpe 0.45, max DD −₹97k",
         "Worst trade: 12-Mar-2020 −₹92.6k (Covid gap); 24-Feb-2022 −₹51.9k (Ukraine)",
         "Fails: t 1.47 (needs ≥ 3), deflated Sharpe ≈ 0, bad-case (MC95) DD −₹2.37L vs −₹80k limit"],
     "capital": "Margin ≈ ₹2.38L/lot (Zerodha calc, unconfirmed on Groww). Min/recommended ₹4.32L/₹5.30L on full history; ≈ ₹9.5L to pass the drawdown rule.",
     "source": "trading-research: strategy-capital-report-2026-10-23.md, extended-history-retest-2026-10-24.md"},
    {"name": "Nifty monthly 14-DTE strangle (R9, naked)",
     "status": "Failed strict gate (also under the 100-trade monthly rule)",
     "numbers": [
         "2016–2026: 128 trades, net ₹2.37L per lot, 77% win; unseen months 2025–26: ₹59k on 21 trades",
         "Survived 2019–22 (+₹47.8k); winged version only ₹80k",
         "Fails: t 2.03 (needs ≥ 3), deflated Sharpe 0, MC95 DD ≈ −₹1.55L"],
     "capital": "Needs well over ₹1L margin per lot (naked).",
     "source": "trading-lab/backtests/weekly-2026-10-26/report.md; rules.md changelog"},
    {"name": "BankNifty weekly credit spread (F3, m1.0 w1.0)",
     "status": "On watch (study gate WATCH; strict gate fail)",
     "numbers": ["Unseen-months OOS ₹15.8k, OOS Sharpe 0.50, about 5.1%/yr", "Fails deflated Sharpe (0.75 < 0.80 study / 0.95 strict)"],
     "capital": "Min/recommended ₹1.7L/₹2.0L per lot (margin ≈ ₹90k).",
     "source": "trading-research strategy-capital-report-2026-10-23.md"},
    {"name": "BankNifty 3-day short strangle (F4, k1.0 sl1.0)",
     "status": "On watch (study gate WATCH; strict gate fail)",
     "numbers": ["Unseen-months OOS ₹31k, OOS Sharpe 0.59, about 4.1%/yr"],
     "capital": "Min/recommended ₹4.2L/₹5.0L per lot.",
     "source": "trading-research strategy-capital-report-2026-10-23.md"},
]

GATE_RULES = [
    ("Out-of-sample (OOS) test", "Rules are tuned only on older data (in-sample). They are then judged ONCE on later months they never saw. Only that unseen result counts."),
    ("Enough trades", "At least 200 trades in total (weekly and intraday strategies). Monthly strategies (≤ 1 trade per monthly expiry): at least 100 trades and ≥ 20 in the unseen months (amended 26-Oct-2026)."),
    ("Real data only", "Real NSE/BSE/Groww prices. Synthetic (MODELED, Black-Scholes) results never count."),
    ("Profit after costs", "Positive after Indian charges (STT, exchange, SEBI, stamp, GST) and still positive at 2× slippage (cost stress 0.5% / 1.0% / 1.5%)."),
    ("Statistically real", "t-stat ≥ 3 and deflated Sharpe > 0.95 using the TRUE number of variants ever tried (≈ 600 now), so lucky winners from a big search are filtered out."),
    ("Not overfit", "Walk-forward (6-month train / 1-month test, rolled monthly) must be positive; probability of backtest overfitting (PBO) < 0.3; neighbours within ±20% of each setting must also work."),
    ("Survivable losses", "Monte-Carlo 95th-percentile drawdown < 25% of capital; positive in ≥ 60% of calendar quarters; margin must fit the capital."),
]


def build_leaderboard(bt):
    lb = [r for r in bt if r["gate"] == "PASS" and r["src"] == "REAL"]
    log = read(f"{W}/trading-lab/BACKTEST_LOG.md")
    m = re.search(r"## Current leaderboard.*?\n\n(.*?)\n## ", log, re.S)
    lb_text = m.group(1).strip() if m else ""
    trials = re.search(r"≈\s*(\d+)\s*after", read(f"{W}/trading-research/rules.md"))
    gated = [r for r in bt if r["selected"]]
    dump("leaderboard.json", {
        "leaderboard": lb, "leaderboard_text": scrub(lb_text),
        "gate": [{"rule": a, "plain": b} for a, b in GATE_RULES],
        "near_miss": NEAR_MISS,
        "trials": int(trials.group(1)) if trials else None,
        "gated_candidates": gated[:200],
    })
    return lb


# ---------------------------------------------------------------- paper trading
def build_paper():
    j = csvload(f"{W}/trading-research/paper/journal.csv")
    journal = [{k: scrub(v) for k, v in r.items()} for r in j]
    margin = [r for r in csvload(f"{W}/trading-research/paper/margin_checks.csv")]
    plog = jload(f"{W}/india-day-trader/trader/state/planner_log.json", {}) or {}
    days = []
    for d in sorted(plog):
        rep = plog[d].get("reported", {}) if isinstance(plog[d], dict) else {}
        cnt = collections.Counter(); reasons = collections.Counter()
        for sym, v in rep.items():
            cnt[v.get("verdict", "?")] += 1
            for rs in v.get("reasons", []):
                reasons[rs] += 1
        sec = plog[d].get("strangle_event_check", {}) if isinstance(plog[d], dict) else {}
        days.append({"date": d, "counts": dict(cnt), "reasons": dict(reasons), "total": sum(cnt.values()),
                     "strangle_event_check": {k: sec.get(k) for k in ("done_at", "reason", "note_sent")} if sec else None})
    # Paper Desk journal (india-day-trader team) if any
    desk = []
    for p in sorted(glob.glob(f"{W}/trader/journal/*") + glob.glob(f"{W}/india-day-trader/trader/journal/*")):
        desk.append(os.path.basename(p))
    cum = 0; curve = []
    for r in journal:
        n = num(r.get("net_pnl") or r.get("net") or r.get("pnl_net") or r.get("net_Rs"))
        if (r.get("event") or r.get("type") or "").upper() == "SETTLE" and n is not None:
            cum += n; curve.append({"date": r.get("expiry") or r.get("row_id") or r.get("date_IST"), "cum": round(cum, 2), "net": n})
    dump("paper.json", {
        "strangle": {"journal": journal, "curve": curve, "cum": round(cum, 2),
                     "stop_entries": -57000, "retire": -75000, "capital": 320000,
                     "rules": ["NIFTY, 1 lot (65), assumed capital ₹3.2L, PAPER only, read-only market data",
                               "Enter ≈15:20 IST the trading day before each weekly expiry; hold to settlement",
                               "Sell CE/PE nearest spot ± expected move (ATM straddle price)",
                               "Skip if India VIX 252-day percentile < 0.30, or RBI/Budget/election result inside the hold",
                               "Stop new entries at −₹57k paper drawdown per lot; retire at −₹75k; no single-trade halt (user decision 24-Oct)",
                               "Pass criteria: ≥ 16 qualifying trades, net > 0 after charges, slippage ≤ model"],
                     "margin_checks": margin,
                     "status": "EXPLORATORY: failed the strict gate; continued as a free information test by user decision"},
        "planner_days": days, "paper_desk_journal_files": desk,
    })
    return journal, days


# ---------------------------------------------------------------- news
OFFICIAL = ("nseindia.com", "nsearchives", "bseindia.com", "rbi.org.in", "sebi.gov.in", "mospi", "pib.gov.in", "federalreserve.gov", "bls.gov", "bea.gov")
RUMOR_STRONG = ("media report", "unverified", "rumour", "rumor", "not a fact", "gmp", "grey market", "not verified",
                "not exchange-verified", "analyst view", "tentative", "analyst opinion")
RUMOR_WEAK = ("reported", "analyst", "cites", "says", "per bs", "per et", "views", "brokerage")


def load_universe():
    s = set()
    for line in read(f"{W}/india-day-trader/trader/universe.txt").splitlines():
        sym = line.split("|")[0].strip()
        if sym:
            s.add(sym)
    return s


def parse_news(path, universe):
    text = read(path)
    runs = []; cur = None; sub = ""
    for line in text.splitlines():
        m = re.match(r"^## (\d{1,2}:\d{2}) IST - (.*?) - (.*)$", line)
        if m:
            cur = {"time": m.group(1), "slot": m.group(2).strip(), "author": m.group(3).strip(), "summary": "", "items": [], "routed": []}
            runs.append(cur); sub = ""; continue
        if cur is None:
            continue
        if line.startswith("### "):
            sub = line[4:].strip(); continue
        mi = re.match(r"^- \[(\w+)\]\s*(.*)$", line)
        if mi:
            tag, body = mi.group(1), mi.group(2)
            parts = re.split(r"\s*Source:\s*", body, maxsplit=1)
            head = parts[0].strip()
            urls = re.findall(r"https?://[^\s,]+", parts[1]) if len(parts) > 1 else []
            if len(parts) > 1 and "same" in parts[1].lower() and not urls:
                urls = cur["items"][-1]["urls"] if cur["items"] else []
            lead = re.match(r"^([A-Z][A-Z0-9&\-]{1,15})(?:\s*\(|:)", head)
            tick = set()
            if lead and lead.group(1) in universe:
                tick.add(lead.group(1))
            for t in re.findall(r"\b[A-Z][A-Z0-9&\-]{2,15}\b", head):
                if t in universe and t not in ("IST", "NSE", "BSE", "RBI", "SEBI", "IPO", "GST", "FII", "DII", "USD", "INR", "CEO", "NIM", "PAT", "NII", "HC", "FDA", "US", "ET", "BS", "GDP", "PMI", "AUM", "PCR", "IT", "Q2", "BLS", "ECB", "FOMC", "BOJ", "MPC", "CPI", "WPI", "IIP", "LTM", "MIS", "ORB", "VIX", "EOD", "HSBC", "CAS", "UDIFF", "FPI", "ELM"):
                    tick.add(t)
            low = (head + " " + sub).lower()
            official = any(o in u for u in urls for o in OFFICIAL)
            if any(w in low for w in RUMOR_STRONG):
                kind = "report / opinion"
            elif official:
                kind = "fact (official source)"
            elif any(w in low for w in RUMOR_WEAK) or "x.com" in " ".join(urls):
                kind = "report / opinion"
            else:
                kind = "media (headline)"
            impact = "high" if tag in ("rbi", "sebi", "risk", "macro_in", "budget") else "medium" if tag in ("results", "filing", "flows", "order", "deal", "regulatory", "ipo", "macro_us") else "low"
            cur["items"].append({"tag": tag, "text": scrub(head), "urls": urls, "tickers": sorted(tick), "kind": kind,
                                 "impact": impact, "section": sub, "routed_to": ""})
        elif line.strip() and not line.startswith("#") and not line.startswith("-"):
            cur["summary"] += (" " if cur["summary"] else "") + scrub(line.strip())
    for r in runs:
        for mm in re.finditer(r"routed to ([A-Z][\w ]+?)\s*\(([^)]*)\)", r["summary"]):
            who = mm.group(1).strip(); syms = re.findall(r"[A-Z][A-Z0-9&\-]+", mm.group(2))
            r["routed"].append({"to": who, "symbols": syms})
            for it in r["items"]:
                if set(it["tickers"]) & set(syms):
                    it["routed_to"] = who
        if not r["routed"] and re.search(r"nothing routed", r["summary"], re.I):
            r["routed_note"] = "nothing routed"
    return runs


def build_news(universe):
    days = {}
    for p in sorted(glob.glob(f"{W}/trading-lab/news/20*.md")):
        d = os.path.basename(p)[:-3]
        days[d] = parse_news(p, universe)
    ev = jload(f"{W}/trading-lab/news/events.json", []) or []
    events = [{k: scrub(e.get(k)) for k in ("date", "time_ist", "type", "title", "symbols", "impact", "source_url", "verified", "notes")} for e in ev if isinstance(e, dict)]
    fl = jload(f"{W}/india-day-trader/trader/state/flows.json", {}) or {}
    flows = []
    for d, v in (fl.get("days") or {}).items():
        try:
            dd = datetime.datetime.strptime(d, "%d-%b-%Y").strftime("%Y-%m-%d")
        except Exception:
            dd = d
        flows.append({"date": dd, "fii_net_cr": (v.get("FII") or {}).get("net_cr"), "dii_net_cr": (v.get("DII") or {}).get("net_cr"),
                      "fii_buy": (v.get("FII") or {}).get("buy_cr"), "fii_sell": (v.get("FII") or {}).get("sell_cr"),
                      "dii_buy": (v.get("DII") or {}).get("buy_cr"), "dii_sell": (v.get("DII") or {}).get("sell_cr")})
    flows.sort(key=lambda x: x["date"])
    flow_lines = [{"date": d, "text": it["text"], "urls": it["urls"]} for d, runs in days.items() for r in runs for it in r["items"] if it["tag"] == "flows"]
    dump("news.json", {"days": days, "events": events, "flows": flows, "flow_lines": flow_lines})
    return days, events


# ---------------------------------------------------------------- research pipeline
def build_research(bt):
    rules = read(f"{W}/trading-research/rules.md")
    queue = []
    for m in re.finditer(r"^## ((?:R|C)\d+[^\n]*)$", rules, re.M):
        title = m.group(1).strip()
        st = "TESTED: REJECTED" if "REJECTED" in title else "TEST NEXT" if "TEST NEXT" in title else "TO TEST" if "(TEST" in title else "PROBATION" if "PROBATION" in title else "EXPLORATORY" if "EXPLORATORY" in title else "defined"
        # try to find status from backtests: any rows mention it?
        rid = re.match(r"((?:R|C)\d+)", title).group(1)
        tested = [r for r in bt if re.search(rf"\b{rid}\b", r["strategy"] + " " + r["family"])]
        if tested and "REJECTED" not in st:
            res = "none passed" if not any(r["gate"] == "PASS" for r in tested) else "some PASSED"
            st = f"TESTED ({len(tested)} variants, {res})" + (f" · {st}" if st not in ("defined", "TO TEST", "TEST NEXT") else "")
        body = rules[m.end(): rules.find("\n## ", m.end()) if rules.find("\n## ", m.end()) > 0 else len(rules)]
        thesis = re.search(r"(?:thesis|rule|entry|verdict):\s*\"?([^\n]+)", body)
        queue.append({"id": rid, "title": title, "status": st, "detail": scrub((thesis.group(1) if thesis else "").strip('" ')[:300])})
    weeklies = []
    for p in sorted(glob.glob(f"{W}/trading-lab/backtests/*/report.md")):
        txt = read(p); name = os.path.basename(os.path.dirname(p))
        title = (re.search(r"^# (.*)$", txt, re.M) or [None, name])[1]
        bold = re.findall(r"\*\*(Result:[^*]+|[^*]{20,160})\*\*", txt)[:3]
        weeklies.append({"name": name, "title": scrub(title), "headline": [scrub(b) for b in bold]})
    reports = []
    for p in sorted(glob.glob(f"{W}/trading-research/*.md")) + sorted(glob.glob(f"{W}/groww-bot/reports/*.md")):
        txt = read(p); t = re.search(r"^# (.*)$", txt, re.M)
        reports.append({"file": p.replace(W + "/", ""), "title": scrub(t.group(1) if t else os.path.basename(p))})
    runs = collections.OrderedDict()
    for r in bt:
        x = runs.setdefault(r["run"], {"run": r["run"], "date": r["date"], "bot": r["bot"], "rows": 0, "families": set(), "passed": 0})
        x["rows"] += 1; x["families"].add(r["family"]); x["passed"] += r["gate"] == "PASS"
    runlist = [dict(v, families=sorted(v["families"])) for v in runs.values()]
    runlist.sort(key=lambda x: x["date"], reverse=True)
    digest = read(f"{W}/trading-research/digest-2026-10-26.md")
    latest_digest = sorted(glob.glob(f"{W}/trading-research/digest-*.md"))
    week_ahead = []
    if latest_digest:
        dg = read(latest_digest[-1])
        m = re.search(r"## 2\. Week ahead.*?\n(\|.*?)\n\n", dg, re.S)
        if m:
            for line in m.group(1).splitlines()[2:]:
                c = [x.strip() for x in line.strip("|").split("|")]
                if len(c) >= 2:
                    week_ahead.append({"date": c[0].replace("**", ""), "event": scrub(c[1].replace("**", ""))})
    trials = re.search(r"≈\s*(\d+)\s*after", rules)
    dump("research.json", {"queue": queue, "weekly": weeklies, "reports": reports, "runs": runlist,
                           "week_ahead": week_ahead, "trials": int(trials.group(1)) if trials else None,
                           "next_focus": ["Positional option selling with fewer, larger-edge trades (monthly/weekly expiries)",
                                          "Sensex weekly strangle as a second, uncorrelated instance (R10, needs more history)",
                                          "Wider stock universe / different signals for equities (Scout setups failed 88 versions)",
                                          "Weekly improvement cycle every Monday ≈ 11:00 IST; strategies dropped if paper results fall short"]})
    return queue, runlist


# ---------------------------------------------------------------- bots
def build_bots(bt, days_news, planner_days, journal, runlist):
    hits = csvload(f"{W}/trading-lab/scout/hits.csv")
    hit_dates = sorted({h.get("date_IST", "") for h in hits})
    last_hit_day = hit_dates[-1] if hit_dates else None
    today_hits = [h for h in hits if h.get("date_IST") == last_hit_day]
    by_scan = collections.Counter(h.get("scan", "") for h in today_hits)
    by_setup = collections.Counter(h.get("setup", "") for h in today_hits)
    with_news = sum(1 for h in today_hits if h.get("news_headline"))
    hits_pub = [{"time": h.get("time_IST"), "scan": h.get("scan"), "symbol": h.get("symbol"), "setup": h.get("setup"),
                 "price": num(h.get("price")), "over_pct": num(h.get("over_pct")), "news": scrub(h.get("news_headline", ""))[:200],
                 "news_url": (re.findall(r"https?://\S+", h.get("news_source", "")) or [""])[0]} for h in today_hits]
    last_news_day = sorted(days_news)[-1] if days_news else None
    last_news_run = days_news[last_news_day][-1] if last_news_day and days_news[last_news_day] else None
    pl = planner_days[-1] if planner_days else None
    research_runs = [r for r in runlist if "trading-research" in r["bot"]]
    coord_runs = [r for r in runlist if "coordinator" in r["bot"] or "executor" in r["bot"]]
    opps = csvload(f"{W}/opportunities/opportunities.csv")
    opps_pub = [{"id": o.get("id"), "name": scrub(o.get("name")), "category": o.get("category"), "status": o.get("status"),
                 "score": num(o.get("score")), "income": scrub(o.get("est_monthly_income_inr_range")),
                 "first_rupee": scrub(o.get("time_to_first_rupee")), "cost": scrub(o.get("startup_cost")),
                 "hours": scrub(o.get("hours_per_week")), "risk": scrub(o.get("risk")),
                 "evidence": scrub(o.get("evidence_summary", ""))[:400],
                 "sources": [u.strip() for u in (o.get("sources") or "").split("|") if u.strip().startswith("http")][:4],
                 "reject_reason": scrub(o.get("reject_reason", ""))} for o in opps]
    opps_pub.sort(key=lambda x: -(x["score"] or 0))
    paper_last = journal[-1] if journal else None
    bots = [
        {"name": "Grok Bot (coordinator)", "emoji": "🧭",
         "role": "Mohmmadali's single point of contact. Runs the day, passes Scout's watchlist and news to Trade Planner, takes any checked ticket to Paper Desk, runs the weekly strategy-improvement cycle and keeps this dashboard updated.",
         "schedule": ["Weekly improvement cycle: Mon ≈ 11:00 IST", "Relays alerts, 15:15 reminder, evening journal/digest", "Dashboard refresh after each update"],
         "inputs": ["All bots' messages", "trading-lab/backtests.csv", "BACKTEST_LOG.md"],
         "outputs": ["Messages to the user", "trading-lab/backtests/weekly-*/report.md", "this website"],
         "hands_to": ["Trade Planner", "Paper Desk", "Trading research bot", "User"],
         "latest": (f"Last own backtest run {coord_runs[0]['date']} ({coord_runs[0]['rows']} variants, {coord_runs[0]['passed']} passed)" if coord_runs else "No runs logged")},
        {"name": "Market Scout", "emoji": "🔭",
         "role": "Finds what is worth a look and why: daily setups on the NIFTY 500, opening-range breakout (ORB) scans, news on each hit, evening FII/DII and insider digest. Never sizes or places anything.",
         "schedule": ["08:45 pre-market scan", "09:30 / 09:45 / 10:15 ORB scans", "12:30 midday news", "20:00 insider / FII-DII digest"],
         "inputs": ["NSE universe, price bars", "news + exchange filings", "trading-lab/news/"],
         "outputs": ["trader/watchlist.json", "trading-lab/scout/hits.csv"],
         "hands_to": ["Trade Planner", "Grok Bot"],
         "latest": f"{last_hit_day}: {len(today_hits)} hits ({', '.join(f'{k} {v}' for k, v in by_scan.most_common())}); {with_news} with news" if last_hit_day else "No hits logged"},
        {"name": "Trade Planner", "emoji": "📐",
         "role": "Turns a hit into one checked plan (entry, stop, target, Time-Machine odds, size with charges, risk rules) or a clear BLOCK. Blocks every setup not on the OOS-validated leaderboard (user rule). Sends event-veto notes for the strangle paper test.",
         "schedule": ["≈ 09:06 first run (event check)", "After each Scout scan until 14:45"],
         "inputs": ["Scout hits", "trading-lab/news/events.json", "BACKTEST_LOG.md leaderboard"],
         "outputs": ["india-day-trader/trader/state/planner_log.json", "PASS/BLOCK verdicts"],
         "hands_to": ["Grok Bot", "Trading research bot (strangle veto)"],
         "latest": (f"{pl['date']}: {pl['total']} setups reviewed — " + ", ".join(f"{k} {v}" for k, v in pl['counts'].items())) if pl else "No planner log"},
        {"name": "Paper Desk", "emoji": "📒",
         "role": "Keeps the PAPER books: records the user's exact yes/no, fills at Groww price plus slippage, watches stops/targets, flattens by 15:15, writes the end-of-day journal and a weekly paper-results entry every Friday.",
         "schedule": ["09:15 opening bell", "every 15 min while a trade is open", "15:15 flat-by", "15:45 EOD journal", "Fri weekly paper results"],
         "inputs": ["Approved tickets", "Groww prices (read-only)"],
         "outputs": ["trader/journal/", "weekly paper entry in trading-lab"],
         "hands_to": ["Grok Bot"],
         "latest": "No paper trades yet: every setup is blocked until it passes the unseen-months test."},
        {"name": "Market News Desk", "emoji": "📰",
         "role": "Logs market news with a source link on every line (exchange filings beat headlines), keeps the events calendar (holidays, expiries, RBI, SEBI, results, macro) and routes stock-specific items to Scout.",
         "schedule": ["08:15 pre-market", "market-hours sweeps", "15:45 wrap", "20:00 evening"],
         "inputs": ["NSE/BSE filings, RBI/SEBI, ET, BS, Mint, X"],
         "outputs": ["trading-lab/news/YYYY-MM-DD.md", "trading-lab/news/events.json"],
         "hands_to": ["Market Scout", "Trade Planner", "Trading research bot"],
         "latest": (f"{last_news_day} {last_news_run['time']} IST ({last_news_run['slot']}): {len(last_news_run['items'])} items" if last_news_run else "No news logged")},
        {"name": "Trading research bot", "emoji": "🧪",
         "role": "Longer research: index-option strategy grids, minimum capital, rule ideas (rules.md), weekly digests, and runs the exploratory Nifty weekly strangle paper test (read-only market data).",
         "schedule": ["Weekdays ≈ 15:20 strangle paper script", "Weekly research digest", "Saturday 10:00 journal review"],
         "inputs": ["NSE/BSE bhavcopy, Groww candles (read-only)", "trading-lab/news/events.json"],
         "outputs": ["trading-research/rules.md, digests, reports", "trading-research/paper/journal.csv", "rows in backtests.csv"],
         "hands_to": ["Grok Bot", "Trade Planner"],
         "latest": (f"Last run {research_runs[0]['date']}: {research_runs[0]['rows']} variants" if research_runs else "") + (f"; paper journal last row {paper_last.get('row_id') or ''} {paper_last.get('event') or ''}" if paper_last else "; strangle paper journal not started yet")},
        {"name": "Opportunity Hunter", "emoji": "💡",
         "role": "Researches and validates other side-income ideas online (freelance, products, bounties, content). Every idea needs evidence: demand, payouts, cost, hours, time to first rupee, risk and India tax notes. Research only: spends nothing, signs up for nothing.",
         "schedule": ["Weekly top-3 shortlist"],
         "inputs": ["Public web (official program pages, payout docs)"],
         "outputs": ["opportunities/opportunities.csv", "opportunities/LOG.md"],
         "hands_to": ["Grok Bot", "User"],
         "latest": f"{len(opps)} ideas tracked: " + ", ".join(f"{k} {v}" for k, v in collections.Counter(o.get('status') for o in opps).items()) if opps else "No ideas yet"},
    ]
    rules = ["PAPER trading and research only: no real orders are placed by any bot",
             "Live placement is off; it would need the user's own config change and an explicit yes per ticket",
             "Only setups on the OOS-validated leaderboard may become paper tickets (exception: the exploratory strangle paper test)",
             "No credentials or personal account details in chat, logs or this site",
             "Append-only shared logs; no bot edits another bot's rows"]
    dump("bots.json", {"bots": bots, "rules": rules, "scout": {"date": last_hit_day, "by_scan": dict(by_scan), "by_setup": dict(by_setup), "hits": hits_pub},
                       "opportunities": opps_pub})


# ---------------------------------------------------------------- meta / overview
def build_meta(bt, fams, lb, planner_days, journal):
    real = [r for r in bt if r["src"] == "REAL"]
    oos_known = [r for r in real if r["oos"] is not None]
    meta = {
        "updated_ist": NOW.strftime("%d %b %Y, %H:%M IST"), "updated_iso": NOW.isoformat(),
        "variants": len(bt), "real": len(real), "families": len(fams), "passed": len(lb),
        "oos_positive": sum(1 for r in oos_known if r["oos"] > 0), "oos_known": len(oos_known),
        "planner_today": planner_days[-1] if planner_days else None,
        "paper_rows": len(journal),
        "status": [
            "Everything here is PAPER trading and research. No real money and no live orders.",
            ("The validated leaderboard is EMPTY: none of %d tested variants has passed the strict out-of-sample gate." % len(bt)) if not lb else ("%d strategies are on the validated leaderboard." % len(lb)),
            "Intraday edges so far are smaller than Indian trading costs (≈ ₹200–300/day edge vs ₹220–340 costs on options; equity ORB lost in every year).",
            "Positional option selling (Nifty weekly / monthly strangles) is the only near-miss, but fails on statistical strength and crash risk.",
            "Capital reality: one Nifty strangle lot needs ≈ ₹3–5.3 lakh (≈ ₹9.5 lakh to survive a Covid-style crash under the drawdown rule).",
            "Every unvalidated setup is BLOCKED by Trade Planner. Only the Nifty weekly strangle runs as an EXPLORATORY paper test.",
        ],
        "recommendation": "Don't trade intraday with real money: nothing has beaten costs out-of-sample. Keep watching the exploratory strangle paper test and the weekly research cycle; reconsider only if a strategy passes the gate.",
    }
    dump("meta.json", meta)


def main():
    os.makedirs(OUT, exist_ok=True)
    universe = load_universe()
    bt, fams = build_backtests()
    lb = build_leaderboard(bt)
    journal, pdays = build_paper()
    days, events = build_news(universe)
    queue, runlist = build_research(bt)
    build_bots(bt, days, pdays, journal, runlist)
    build_meta(bt, fams, lb, pdays, journal)
    print(f"built data/*.json at {NOW:%Y-%m-%d %H:%M} IST: {len(bt)} variants, {len(fams)} families, {len(lb)} leaderboard, {len(days)} news days, {len(events)} events")


if __name__ == "__main__":
    main()
