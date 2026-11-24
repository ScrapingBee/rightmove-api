"""Log new listings, price cuts and sold STC moves for one Rightmove search.

Each round reads the newest N result pages of a search (sold STC included, so a
listing that goes under offer stays visible and its status change is logged),
compares every listing with the previous round and appends one CSV row per
change:

  _new            first time this id is seen
  price           asking price or rent changed
  status          e.g. "" -> "Sold STC", or "" -> "Under Offer"
  update_reason   Rightmove's own label moved, e.g. new -> price_reduced
  _gone           the id dropped out of the pages read

State lives in a JSON file, so `--rounds 1` from cron behaves like a loop.
A listing can also leave the pages read because newer ones pushed it down, so
read enough pages to cover the area, or treat _gone as "out of view", not "sold".

Usage:
    export SCRAPINGBEE_API_KEY=...
    python price_watch.py SE15 --pages 3 --rounds 2 --every 1800
    python price_watch.py Manchester --rent --pages 2 --max-price 1500
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone

from rightmove_client import Listing, RightmoveClient

WATCHED = ("amount", "status", "update_reason")


def snapshot(items: list[Listing]) -> dict[str, dict]:
    # amount is rent per calendar month for lettings (weekly rents are converted
    # by Rightmove's own pcm display string) and the asking price for sales.
    return {str(x.id): {"amount": x.rent_pcm or x.price, "status": x.status,
                        "update_reason": x.update_reason, "address": x.address,
                        "bedrooms": x.bedrooms} for x in items}


def diff(old: dict[str, dict], new: dict[str, dict]) -> list[tuple[str, str, object, object]]:
    rows = []
    if not old:
        return [(pid, "_new", "", rec["amount"]) for pid, rec in new.items()]
    for pid, rec in new.items():
        before = old.get(pid)
        if before is None:
            rows.append((pid, "_new", "", rec["amount"]))
            continue
        for f in WATCHED:
            if before.get(f) != rec.get(f):
                rows.append((pid, "price" if f == "amount" else f, before.get(f), rec.get(f)))
    for pid in old.keys() - new.keys():
        rows.append((pid, "_gone", old[pid].get("status") or "listed", ""))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Rightmove listing change log")
    ap.add_argument("area")
    ap.add_argument("--rent", action="store_true")
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--every", type=int, default=3600, help="seconds between rounds")
    ap.add_argument("--min-beds", type=int)
    ap.add_argument("--max-price", type=int)
    ap.add_argument("--state", default="rightmove_state.json")
    ap.add_argument("--log", default="rightmove_changes.csv")
    a = ap.parse_args()

    rm = RightmoveClient()
    state = {}
    if os.path.exists(a.state):
        with open(a.state, encoding="utf-8") as f:
            state = json.load(f)

    new_file = not os.path.exists(a.log)
    with open(a.log, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["checked_at", "id", "field", "before", "after", "bedrooms", "address"])
        for rnd in range(a.rounds):
            if rnd:
                time.sleep(a.every)
            spent = rm.credits
            first, items = rm.listings(a.area, a.pages, rent=a.rent, sort="newest", sstc=True,
                                       min_beds=a.min_beds, max_price=a.max_price)
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            snap = snapshot(items)
            changes = diff(state, snap)
            for pid, fld, before, after in changes:
                rec = snap.get(pid) or state.get(pid) or {}
                w.writerow([now, pid, fld, before, after, rec.get("bedrooms"), rec.get("address")])
            f.flush()
            state = snap
            with open(a.state, "w", encoding="utf-8") as sf:
                json.dump(state, sf, ensure_ascii=False)
            total = first.result_count if first else 0
            print(f"{now}: {len(items)} listings of {total}, {len(changes)} changes, "
                  f"{rm.credits - spent} credits")
            for pid, fld, before, after in changes[:12]:
                rec = snap.get(pid) or {}
                print(f"  {pid} | {fld} | {before} | {after} | {(rec.get('address') or '')[:40]}")
            if len(changes) > 12:
                print(f"  ... {len(changes) - 12} more in {a.log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
