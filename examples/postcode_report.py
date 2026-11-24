"""Answer six questions about one Rightmove area from its public pages.

  1. What does it cost to buy here?          asking prices by bedrooms, price per sq ft
  2. What does it cost to rent here?         rent pcm by bedrooms
  3. What gross yield does that imply?       median rent x 12 / median asking, per bedroom count
  4. How fast do listings move?              share sold STC, days on Rightmove, share reduced
  5. Who holds the stock?                    agents by number of listings
  6. What did homes sell for?                recent sold prices by property type

Every number comes from three page types that robots.txt allows:
/property-for-sale/<AREA>.html, /property-to-rent/<AREA>.html and
/house-prices/<area>.html. Each page is one 1 credit request.

Usage:
    export SCRAPINGBEE_API_KEY=...
    python postcode_report.py SE15                       # every result page, about 40 credits for SE15
    python postcode_report.py SE15 --pages 3 --sold-pages 2 --json se15.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict

from rightmove_client import Listing, RightmoveClient, SoldHome, write_csv

MAX_PAGES = 42


def median(xs: list[float]) -> float | None:
    xs = [x for x in xs if x]
    return statistics.median(xs) if xs else None


def money(x: float | None) -> str:
    return f"£{x:,.0f}" if x else "-"


def by_beds(items: list[Listing], value) -> dict[str, list[float]]:
    out: dict[str, list[float]] = defaultdict(list)
    for it in items:
        if it.bedrooms is None:
            continue
        key = "studio" if it.bedrooms == 0 else ("4+" if it.bedrooms >= 4 else str(it.bedrooms))
        v = value(it)
        if v:
            out[key].append(v)
    return out


ORDER = ["studio", "1", "2", "3", "4+"]


def report(area: str, pages: int, sold_pages: int) -> dict:
    rm = RightmoveClient()

    # Count of homes still available (one page, no SSTC) versus all listed incl. sold STC.
    available_first, _ = rm.listings(area, 1)
    sale_first, sale = rm.listings(area, pages, sort="newest", sstc=True)
    rent_first, rent = rm.listings(area, pages, rent=True, sort="newest", sstc=True)
    sold: list[SoldHome] = []
    summary: list[str] = []
    for page in rm.sold(area, sold_pages):
        summary = summary or page.summary
        sold.extend(page.homes)

    # Residential only: plots, land and commercial units would skew the medians,
    # and a shared ownership "price" is the cost of a share (£88,125 for a two
    # bed flat in our SE15 run), not of the whole home.
    skip = {"Land", "Plot", "Parking", "Garages", "Commercial Property"}
    homes = [x for x in sale if x.property_type not in skip and x.price
             and x.price_qualifier != "Shared ownership"]
    lets = [x for x in rent if x.rent_pcm]

    ask = by_beds(homes, lambda x: x.price)
    pcm = by_beds(lets, lambda x: x.rent_pcm)
    sqft = [x.price / x.size_sqft for x in homes if x.size_sqft and x.size_sqft > 150]

    # Sale cards show either "Sold STC" or "Under offer" once a buyer is found.
    sstc = [x for x in homes if x.status in ("Sold STC", "Under offer")]
    live = [x for x in homes if not x.status]
    reduced = [x for x in live if x.update_reason == "price_reduced"]
    agents = Counter(x.agent for x in sale + rent if x.agent)

    sold_types: dict[str, list[int]] = defaultdict(list)
    for h in sold:
        if h.last_price:
            sold_types[h.property_type or "Unknown"].append(h.last_price)

    out = {
        "area": area,
        "sale_description": sale_first.description if sale_first else "",
        "for_sale_available": available_first.result_count if available_first else None,
        "for_sale_incl_sstc": sale_first.result_count if sale_first else None,
        "to_rent_incl_let_agreed": rent_first.result_count if rent_first else None,
        "sale_listings_read": len(sale),
        "rent_listings_read": len(rent),
        "sold_records_read": len(sold),
        "ask_by_beds": {k: [len(ask[k]), median(ask[k])] for k in ORDER if k in ask},
        "price_per_sqft": [len(sqft), median(sqft)],
        "rent_by_beds": {k: [len(pcm[k]), median(pcm[k])] for k in ORDER if k in pcm},
        "gross_yield_pct": {k: round(median(pcm[k]) * 12 / median(ask[k]) * 100, 1)
                            for k in ORDER if k in pcm and k in ask},
        "status_counts": dict(Counter(x.status or "available" for x in homes)),
        "left_out": len(sale) - len(homes),
        "qualifiers": dict(Counter(x.price_qualifier or "(none)" for x in sale).most_common()),
        "share_sstc_pct": round(len(sstc) / len(homes) * 100, 1) if homes else None,
        "days_listed_available": median([x.days_listed for x in live if x.days_listed is not None]),
        "days_listed_sstc": median([x.days_listed for x in sstc if x.days_listed is not None]),
        "share_reduced_pct": round(len(reduced) / len(live) * 100, 1) if live else None,
        "top_agents": agents.most_common(8),
        "sold_summary": summary,
        "sold_by_type": {t: [len(v), median(v)] for t, v in sorted(sold_types.items(), key=lambda kv: -len(kv[1]))},
        "sold_date_range": [min((h.last_sold for h in sold if h.last_sold), default=None),
                            max((h.last_sold for h in sold if h.last_sold), default=None)],
        "credits": rm.credits,
    }
    return out, sale + rent


def print_report(r: dict) -> None:
    p = print
    p(f"# {r['area']}: {r['sale_description']}")
    p(f"read {r['sale_listings_read']} sale, {r['rent_listings_read']} rent, "
      f"{r['sold_records_read']} sold records for {r['credits']} credits\n")
    p(f"1. What does it cost to buy? ({r['left_out']} land, plot, commercial or shared ownership listings left out)")
    for k, (n, m) in r["ask_by_beds"].items():
        p(f"   {k:>6} bed  {money(m):>11} median asking  (n={n})")
    n, m = r["price_per_sqft"]
    p(f"   price per sq ft {money(m)} (n={n}, only listings that state a size)")
    p(f"   price qualifiers: {r['qualifiers']}")
    p("2. What does it cost to rent?")
    for k, (n, m) in r["rent_by_beds"].items():
        p(f"   {k:>6} bed  {money(m):>8} pcm median  (n={n})")
    p("3. Gross yield, median rent x 12 / median asking")
    for k, v in r["gross_yield_pct"].items():
        p(f"   {k:>6} bed  {v}%")
    p("4. How fast do listings move?")
    p(f"   {r['for_sale_available']} available, {r['for_sale_incl_sstc']} incl. sold STC; "
      f"{r['share_sstc_pct']}% of the homes read are sold STC or under offer")
    p(f"   status of the homes read: {r['status_counts']}")
    p(f"   median days on Rightmove: {r['days_listed_available']} (available), "
      f"{r['days_listed_sstc']} (sold STC or under offer)")
    p(f"   {r['share_reduced_pct']}% of available listings were last updated by a price reduction")
    p("5. Who holds the stock? (sale + rent listings)")
    for name, c in r["top_agents"]:
        p(f"   {c:>4}  {name}")
    p(f"6. What did homes sell for? ({r['sold_date_range'][0]} to {r['sold_date_range'][1]})")
    for t, (n, m) in r["sold_by_type"].items():
        p(f"   {t:<16} {money(m):>11} median  (n={n})")
    for line in r["sold_summary"]:
        p(f"   rightmove: {line}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("area", help="outcode, postcode or town slug, e.g. SE15, M20, Bath")
    ap.add_argument("--pages", type=int, default=MAX_PAGES, help="result pages per channel (24 listings each)")
    ap.add_argument("--sold-pages", type=int, default=4, help="sold price pages (25 addresses each)")
    ap.add_argument("--json", help="also write the numbers to this file")
    ap.add_argument("--csv", help="also write every sale and rent listing read to this file")
    a = ap.parse_args()
    r, listings = report(a.area, min(a.pages, MAX_PAGES), a.sold_pages)
    print_report(r)
    if a.csv:
        write_csv(a.csv, listings)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
