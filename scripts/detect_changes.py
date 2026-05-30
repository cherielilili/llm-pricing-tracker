#!/usr/bin/env python3
"""Compare last two snapshot dates in history.csv and push alerts.

Threshold: ±10% on input_cost_per_token or output_cost_per_token.
Also alerts on new model listings and model removals.
"""
from __future__ import annotations

import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "data" / "history.csv"

THRESHOLD = 0.10
ALERT_FIELDS = {"input_cost_per_token", "output_cost_per_token"}
WEBHOOK_ENV = "DISCORD_WEBHOOK_TRACKING"
PROXIES = {"https": "http://127.0.0.1:7890", "http": "http://127.0.0.1:7890"}
REPORT_URL = "https://cherielilili.github.io/llm-pricing-tracker/"


def load_rows() -> list[dict]:
    with HIST.open() as f:
        return list(csv.DictReader(f))


def latest_two_dates(rows: list[dict]) -> tuple[str, str] | None:
    dates = sorted({r["date"] for r in rows})
    if len(dates) < 2:
        return None
    return dates[-2], dates[-1]


def snapshot(rows: list[dict], date: str) -> dict[tuple[str, str, str], float]:
    out: dict[tuple[str, str, str], float] = {}
    for r in rows:
        if r["date"] != date or r["field"] not in ALERT_FIELDS:
            continue
        try:
            price = float(r["price_usd_per_mtoken"])
        except (TypeError, ValueError):
            continue
        key = (r["model"], r["provider"], r["field"])
        out[key] = price
    return out


def detect(prev: dict, curr: dict) -> dict:
    changes = []
    added = []
    removed = []
    for key, new_price in curr.items():
        if key not in prev:
            added.append((key, new_price))
            continue
        old_price = prev[key]
        if old_price == 0:
            continue
        pct = (new_price - old_price) / old_price
        if abs(pct) >= THRESHOLD:
            changes.append((key, old_price, new_price, pct))
    for key, old_price in prev.items():
        if key not in curr:
            removed.append((key, old_price))
    return {"changes": changes, "added": added, "removed": removed}


def format_message(prev_date: str, curr_date: str, diff: dict) -> str | None:
    changes = diff["changes"]
    added = diff["added"]
    removed = diff["removed"]
    if not changes and not added and not removed:
        return None

    lines = [f"🧮 **LLM 价格异动** {curr_date} (vs {prev_date})"]

    if changes:
        changes.sort(key=lambda x: abs(x[3]), reverse=True)
        lines.append("")
        lines.append("**价格变化 (±10%+)**")
        for (model, provider, field), old_p, new_p, pct in changes[:15]:
            arrow = "↓" if pct < 0 else "↑"
            field_label = "in" if field == "input_cost_per_token" else "out"
            lines.append(
                f"• {model} [{provider}] {field_label}: "
                f"${old_p:.2f} → ${new_p:.2f} ({arrow}{abs(pct)*100:.0f}%)"
            )
        if len(changes) > 15:
            lines.append(f"… 另有 {len(changes)-15} 条变化")

    if added:
        lines.append("")
        unique_added=len({(m,p) for (m,p,_),_ in added}); lines.append(f"**新上线 ({unique_added})**")
        # de-dupe by (model, provider)
        seen = set()
        for (model, provider, field), price in added:
            mp = (model, provider)
            if mp in seen:
                continue
            seen.add(mp)
            lines.append(f"• {model} [{provider}]")
            if len(seen) >= 10:
                break
        if len(seen) < len({(m, p) for (m, p, _), _ in added}):
            extra = len({(m, p) for (m, p, _), _ in added}) - len(seen)
            lines.append(f"… 另有 {extra} 个新模型")

    if removed:
        lines.append("")
        unique_removed=len({(m,p) for (m,p,_),_ in removed}); lines.append(f"**下线 ({unique_removed})**")
        seen = set()
        for (model, provider, field), price in removed:
            mp = (model, provider)
            if mp in seen:
                continue
            seen.add(mp)
            lines.append(f"• {model} [{provider}]")
            if len(seen) >= 10:
                break

    lines.append("")
    lines.append(f"→ {REPORT_URL}")
    return "\n".join(lines)


def push(text: str) -> bool:
    url = os.environ.get(WEBHOOK_ENV, "")
    if not url:
        print(f"[detect_changes] {WEBHOOK_ENV} not set — skipping push", file=sys.stderr)
        print(text)
        return False
    try:
        r = requests.post(url, json={"content": text}, proxies=PROXIES, timeout=10)
        ok = r.status_code in (200, 204)
        print(f"[detect_changes] discord push status={r.status_code}", file=sys.stderr)
        return ok
    except Exception as e:
        print(f"[detect_changes] push failed: {e}", file=sys.stderr)
        return False


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    rows = load_rows()
    pair = latest_two_dates(rows)
    if not pair:
        print("[detect_changes] not enough dates to compare", file=sys.stderr)
        return 0
    prev_date, curr_date = pair
    prev = snapshot(rows, prev_date)
    curr = snapshot(rows, curr_date)
    diff = detect(prev, curr)
    msg = format_message(prev_date, curr_date, diff)
    if msg is None:
        print("[detect_changes] no material changes", file=sys.stderr)
        return 0
    if dry_run:
        print(msg)
        return 0
    push(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
