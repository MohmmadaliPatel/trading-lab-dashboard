#!/usr/bin/env python3
"""Build data/lab.json for the 'Paper lab (live)' tab from Paper Desk's exploratory paper lab.

Reads (read-only): /workspace/trading-lab/paper-lab/trades.csv and /workspace/trading-lab/paper-lab/YYYY-MM-DD.md
Missing files are fine: the tab then says the lab has not logged anything yet.
Usage: python3 build_lab.py [OUT_PATH]   (default data/lab.json)
"""
import csv, datetime, glob, json, os, re, sys

LAB = os.environ.get("PAPER_LAB_DIR", "/workspace/trading-lab/paper-lab")
CFG = "/workspace/india-day-trader/trader/config.json"
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
NOW = datetime.datetime.now(IST)
HERE = os.path.dirname(os.path.abspath(__file__))
try:
    sys.path.insert(0, HERE)
    from build_site import scrub
except Exception:  # never publish unscrubbed text if the scrubber is unavailable
    def scrub(s):
        return re.sub(r"\S+@\S+", "[removed]", str(s or ""))

ALIASES = {
    "date": ["date", "day", "trade_date"],
    "time": ["time", "entry_time", "entry_ist", "time_ist", "logged_ist", "signal_time"],
    "exit_time": ["exit_time", "exit_ist", "closed_ist"],
    "symbol": ["symbol", "ticker", "instrument", "tradingsymbol"],
    "setup": ["setup", "strategy", "signal", "pattern"],
    "side": ["side", "direction", "action", "transaction_type"],
    "qty": ["qty", "quantity", "shares"],
    "entry": ["entry", "entry_price", "fill", "buy_price"],
    "stop": ["stop", "stop_loss", "sl", "stop_price"],
    "target": ["target", "tp", "target_price"],
    "exit": ["exit", "exit_price", "close_price"],
    "status": ["status", "event", "state", "outcome"],
    "r": ["r", "r_multiple", "rmult", "r_mult"],
    "gross": ["gross", "gross_pnl", "pnl_gross"],
    "costs": ["costs", "charges", "cost", "fees"],
    "net": ["net", "net_pnl", "pnl", "pnl_net", "net_after_costs"],
    "reason": ["reason", "notes", "note", "skip_reason", "exit_reason", "comment"],
}


def num(v):
    try:
        v = str(v).replace(",", "").replace("₹", "").strip()
        return None if v in ("", "-", "nan", "None") else round(float(v), 2)
    except Exception:
        return None


def norm(row):
    low = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
    t = {}
    for key, names in ALIASES.items():
        t[key] = next((low[n] for n in names if low.get(n)), "")
    for k in ("qty", "entry", "stop", "target", "exit", "r", "gross", "costs", "net"):
        t[k] = num(t[k])
    t["date"] = t["date"][:10]
    if not t["date"] and re.match(r"\d{4}-\d{2}-\d{2}", t["time"]):
        t["date"] = t["time"][:10]
    t["time"] = (re.search(r"\d{1,2}:\d{2}", t["time"]) or [""])[0]
    t["exit_time"] = (re.search(r"\d{1,2}:\d{2}", t["exit_time"]) or [""])[0]
    t["symbol"] = scrub(t["symbol"]).upper()
    t["setup"] = scrub(t["setup"]) or "unlabelled"
    t["reason"] = scrub(t["reason"])[:300]
    st = t["status"].upper()
    if "SKIP" in st or "REJECT" in st or "VETO" in st:
        t["kind"] = "skipped"
    elif "OPEN" in st or (t["exit"] is None and t["net"] is None and "CLOS" not in st and "EXIT" not in st):
        t["kind"] = "open"
    else:
        t["kind"] = "closed"
    long_ = not re.search(r"sell|short", t["side"], re.I)
    if t["net"] is None and t["gross"] is not None:
        t["net"] = round(t["gross"] - (t["costs"] or 0), 2)
    if t["gross"] is None and None not in (t["entry"], t["exit"], t["qty"]):
        t["gross"] = round((t["exit"] - t["entry"]) * t["qty"] * (1 if long_ else -1), 2)
        if t["net"] is None:
            t["net"] = round(t["gross"] - (t["costs"] or 0), 2)
    if t["r"] is None and t["kind"] == "closed" and None not in (t["entry"], t["stop"], t["exit"]) and t["entry"] != t["stop"]:
        risk = abs(t["entry"] - t["stop"])
        t["r"] = round(((t["exit"] - t["entry"]) if long_ else (t["entry"] - t["exit"])) / risk, 2)
    t.pop("status", None)
    t["status"] = st.title() if st else t["kind"]
    return t


def lessons_from(md):
    out, on = [], False
    for line in md.splitlines():
        h = re.match(r"#+\s*(.*)", line)
        if h:
            on = bool(re.search(r"lesson|learn|takeaway|what (went|to)", h.group(1), re.I))
            continue
        m = re.match(r"\s*[-*\d.]+\s+(.*)", line)
        if on and m:
            out.append(m.group(1))
        elif re.match(r"\s*[-*]?\s*(lesson|learned|takeaway)s?\s*[:\-]", line, re.I):
            out.append(re.sub(r"^\s*[-*]?\s*", "", line))
    return [scrub(x)[:300] for x in out][:20]


def summary_from(md):
    lines = [l.strip() for l in md.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    return [scrub(l.lstrip("-* "))[:240] for l in lines[:8]]


def daily_stop():
    try:
        cfg = json.load(open(CFG))
        def find(d):
            if isinstance(d, dict):
                for k, v in d.items():
                    if k == "max_daily_loss_inr":
                        return v
                    r = find(v)
                    if r is not None:
                        return r
        v = find(cfg)
        if v:
            return float(v)
    except Exception:
        pass
    return 3000.0


def build():
    stop = daily_stop()
    capital = round(stop / 0.03)
    trades = []
    p = os.path.join(LAB, "trades.csv")
    if os.path.exists(p):
        with open(p, newline="", encoding="utf-8", errors="replace") as f:
            trades = [norm(r) for r in csv.DictReader(f)]
    mds = {os.path.basename(x)[:10]: x for x in glob.glob(os.path.join(LAB, "????-??-??.md"))}
    dates = sorted({t["date"] for t in trades if t["date"]} | set(mds), reverse=True)
    days = []
    for d in dates:
        ts = [t for t in trades if t["date"] == d]
        closed = [t for t in ts if t["kind"] == "closed"]
        net = round(sum(t["net"] or 0 for t in closed), 2)
        curve, cum = [], 0.0
        for t in sorted(closed, key=lambda x: x["exit_time"] or x["time"]):
            cum += t["net"] or 0
            curve.append({"t": t["exit_time"] or t["time"], "cum": round(cum, 2), "symbol": t["symbol"]})
        md = open(mds[d], encoding="utf-8", errors="replace").read() if d in mds else ""
        days.append({
            "date": d, "trades": [t for t in ts if t["kind"] != "skipped"], "skipped": [t for t in ts if t["kind"] == "skipped"],
            "open": [t for t in ts if t["kind"] == "open"], "closed": len(closed),
            "wins": sum(1 for t in closed if (t["net"] or 0) > 0), "net": net,
            "gross": round(sum(t["gross"] or 0 for t in closed), 2), "costs": round(sum(t["costs"] or 0 for t in closed), 2),
            "stop_hit": net <= -stop, "stop_used_pct": round(max(0.0, -net) / stop * 100, 1) if stop else None,
            "curve": curve, "lessons": lessons_from(md), "summary": summary_from(md) if md else [],
        })
    setups = {}
    for t in trades:
        s = setups.setdefault(t["setup"], {"setup": t["setup"], "trades": 0, "wins": 0, "net": 0.0, "rs": [], "skipped": 0, "open": 0})
        if t["kind"] == "skipped":
            s["skipped"] += 1
        elif t["kind"] == "open":
            s["open"] += 1
        else:
            s["trades"] += 1
            s["wins"] += (t["net"] or 0) > 0
            s["net"] += t["net"] or 0
            if t["r"] is not None:
                s["rs"].append(t["r"])
    st = []
    for s in setups.values():
        rs = s.pop("rs")
        s["win_pct"] = round(100 * s["wins"] / s["trades"], 1) if s["trades"] else None
        s["avg_r"] = round(sum(rs) / len(rs), 2) if rs else None
        s["net"] = round(s["net"], 2)
        st.append(s)
    st.sort(key=lambda s: -s["trades"])
    closed_all = [t for t in trades if t["kind"] == "closed"]
    return {
        "as_of_ist": NOW.strftime("%d %b %Y, %H:%M IST"), "as_of_iso": NOW.isoformat(),
        "label": "EXPLORATORY, NOT VALIDATION",
        "note": "Paper Desk's exploratory paper lab: unvalidated setups traded on paper to learn. Separate from the official book; results here never count as evidence for the leaderboard.",
        "capital": capital, "daily_stop": -stop, "has_data": bool(trades or mds),
        "totals": {"closed": len(closed_all), "wins": sum(1 for t in closed_all if (t["net"] or 0) > 0),
                   "net": round(sum(t["net"] or 0 for t in closed_all), 2),
                   "skipped": sum(1 for t in trades if t["kind"] == "skipped"), "days": len(days)},
        "setups": st, "days": days,
    }


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "data", "lab.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    data = build()
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"lab: {data['totals']['closed']} closed, {data['totals']['skipped']} skipped, {len(data['days'])} days -> {out}")
