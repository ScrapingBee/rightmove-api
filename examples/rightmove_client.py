"""Rightmove API client built on ScrapingBee.

Reads three kinds of public, logged out rightmove.co.uk pages and nothing else:

  /property-for-sale/<AREA>.html     search results for sale, 24 listings per page
  /property-to-rent/<AREA>.html      search results to rent, same shape
  /properties/<ID>                   one listing page
  /house-prices/<area>.html          sold prices for an area, 25 addresses per page

All of them are server rendered, so a classic request with render_js=false
(1 credit) returns the full data. Search pages carry a Next.js __NEXT_DATA__
JSON blob, listing pages carry window.__PAGE_MODEL, and sold price pages are
plain HTML read with extract_rules.

Paths that robots.txt disallows (map.html, draw-a-search, /api/*,
/house-prices/details/*, contactBranch, print views) are never requested.

Usage:
    export SCRAPINGBEE_API_KEY=...
    python rightmove_client.py search SE15 --pages 2 --csv se15_sale.csv
    python rightmove_client.py search SE15 --rent --sort newest --json se15_rent.json
    python rightmove_client.py listing 90625020 --json listing.json
    python rightmove_client.py sold SE15 --pages 2 --csv se15_sold.csv
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Any, Iterator
from urllib.parse import urlencode

import requests

API = "https://app.scrapingbee.com/api/v1/"
SITE = "https://www.rightmove.co.uk"
PER_PAGE = 24          # Rightmove's page size; each page also carries one featured slot
MAX_INDEX = 984        # index=1008 redirects to /page-not-found, so 42 pages is the ceiling
SORTS = {"price_low": "1", "price_high": "2", "newest": "6"}   # the three values we verified

# Only the __NEXT_DATA__ script comes back, about 420 KB instead of 1.1 to 1.3 MB.
# "output": "html" because "text" on a <script> returned an empty string.
SEARCH_RULES = {"next": {"selector": "script#__NEXT_DATA__", "output": "html"}}

# Sold price pages: CSS module class names are hashed (_title_1h056_50), so the
# rules lean on data-testid, aria-label and plain tags instead.
SOLD_RULES = {
    "summary": {"selector": "p[class*=explainer]", "type": "list"},
    "count": "div[class*=numberOfResults]",
    "pager": "div.rmds_pagination",
    "cards": {
        "selector": "a[data-testid=propertyCard]",
        "type": "list",
        "output": {
            "address": "h2",
            "href": {"selector": "a[data-testid=propertyCard]", "output": "@href"},
            "type": {"selector": "div[aria-label^='Property Type']", "output": "text"},
            "beds": {"selector": "div[aria-label^='Bedrooms']", "output": "text"},
            "tenure": {"selector": "div[aria-label^='Tenure']", "output": "text"},
            "rows": {
                "selector": "tr",
                "type": "list",
                "output": {"date": "td:nth-child(1)", "price": "td:nth-child(2) div[aria-label]"},
            },
        },
    },
}


class RightmoveError(RuntimeError):
    pass


class EmptyPage(RightmoveError):
    """HTTP 200, but the data blob we expected is missing. ScrapingBee bills it."""


class NotFound(RightmoveError):
    """Rightmove redirected to /page-not-found or returned 404/410."""


# ---------- small parsers ----------

def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def _strip_html(text: str | None) -> str:
    t = re.sub(r"<br\s*/?>", "\n", text or "")
    t = re.sub(r"<[^>]+>", "", t)
    return "\n".join(_clean(line) for line in html.unescape(t).split("\n") if line.strip())


def _int(text: Any) -> int | None:
    m = re.search(r"\d[\d,]*", str(text or ""))
    return int(m.group(0).replace(",", "")) if m else None


def _date(iso: str | None) -> str | None:
    return iso[:10] if iso else None


def _days_since(iso: str | None, now: datetime) -> int | None:
    if not iso:
        return None
    then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (now - then).days


POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b")
OUTCODE_END = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*$")


def _outcode(address: str) -> str | None:
    a = address.upper()
    m = POSTCODE.search(a) or OUTCODE_END.search(a)
    return m.group(1) if m else None


def _rent_pcm(price: dict) -> int | None:
    """Rents arrive as monthly or weekly amounts; the pcm display string is always there."""
    for p in price.get("displayPrices") or []:
        if p.get("displayPrice", "").endswith("pcm"):
            return _int(p["displayPrice"])
    if price.get("frequency") == "monthly":
        return price.get("amount")
    if price.get("frequency") == "weekly" and price.get("amount"):
        return round(price["amount"] * 52 / 12)
    return None


# ---------- records ----------

@dataclass
class Listing:
    """One row of a search results page (__NEXT_DATA__ props.pageProps.searchResults.properties[])."""
    id: int
    channel: str
    url: str
    price: int | None
    price_qualifier: str
    rent_pcm: int | None
    currency: str
    bedrooms: int | None
    bathrooms: int | None
    property_type: str
    size_sqft: int | None
    tenure: str | None
    address: str
    outcode: str | None
    latitude: float | None
    longitude: float | None
    agent: str
    branch_id: int | None
    first_visible: str | None
    days_listed: int | None
    update_reason: str
    update_date: str | None
    added_or_reduced: str
    status: str
    featured: bool
    let_available: str | None
    key_features: list[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, p: dict, now: datetime) -> "Listing":
        price = p.get("price") or {}
        shown = (price.get("displayPrices") or [{}])[0]
        address = _clean(p.get("displayAddress"))
        rent = p.get("channel") == "RENT" or p.get("transactionType") == "rent"
        update = p.get("listingUpdate") or {}
        loc = p.get("location") or {}
        cust = p.get("customer") or {}
        return cls(
            id=p["id"],
            channel=p.get("channel") or "",
            url=SITE + "/properties/" + str(p["id"]),
            price=price.get("amount"),
            price_qualifier=shown.get("displayPriceQualifier") or "",
            rent_pcm=_rent_pcm(price) if rent else None,
            currency=price.get("currencyCode") or "",
            bedrooms=p.get("bedrooms"),
            bathrooms=p.get("bathrooms"),
            property_type=p.get("propertySubType") or "",
            size_sqft=_int(p.get("displaySize")) if "sq. ft" in (p.get("displaySize") or "") else None,
            tenure=(p.get("tenure") or {}).get("tenureType"),
            address=address,
            outcode=_outcode(address),
            latitude=loc.get("latitude"),
            longitude=loc.get("longitude"),
            agent=cust.get("branchDisplayName") or "",
            branch_id=cust.get("branchId"),
            first_visible=_date(p.get("firstVisibleDate")),
            days_listed=_days_since(p.get("firstVisibleDate"), now),
            update_reason=update.get("listingUpdateReason") or "",
            update_date=_date(update.get("listingUpdateDate")),
            added_or_reduced=p.get("addedOrReduced") or "",
            status=p.get("displayStatus") or "",
            featured=bool(p.get("featuredProperty")),
            let_available=_date(p.get("letAvailableDate")),
            key_features=[k.get("description", "") for k in p.get("keyFeatures") or []],
        )


@dataclass
class SearchPage:
    description: str
    result_count: int
    page: int
    pages: int
    location_id: str
    listings: list[Listing]


@dataclass
class PropertyDetail:
    """One listing page (window.__PAGE_MODEL propertyData)."""
    id: int
    url: str
    published: bool
    archived: bool
    tags: list[str]
    channel: str
    title: str
    price: str
    price_qualifier: str
    price_per_sqft: str
    address: str
    outcode: str | None
    incode: str | None
    bedrooms: int | None
    bathrooms: int | None
    property_type: str
    tenure: str | None
    lease_years_left: int | None
    council_tax_band: str | None
    service_charge: Any
    ground_rent: Any
    size_sqft: int | None
    size_sqm: int | None
    latitude: float | None
    longitude: float | None
    agent: str
    branch_id: int | None
    listing_history: str
    images: int
    floorplans: int
    virtual_tours: int
    epc_graphs: int
    key_features: list[str]
    stations: list[str]
    parking: str
    garden: str
    lettings: dict | None
    nearby_sold_url: str | None
    description: str

    @classmethod
    def from_model(cls, d: dict) -> "PropertyDetail":
        pd = d["propertyData"]
        prices = pd.get("prices") or {}
        addr = pd.get("address") or {}
        tenure = pd.get("tenure") or {}
        costs = pd.get("livingCosts") or {}
        loc = pd.get("location") or {}
        cust = pd.get("customer") or {}
        sizes = {s.get("unit"): s.get("maximumSize") for s in pd.get("sizings") or []}
        feats = pd.get("features") or {}

        def feat(name: str) -> str:
            return ", ".join(f.get("displayText", "") for f in feats.get(name) or [])

        status = pd.get("status") or {}
        return cls(
            id=int(pd["id"]),
            url=SITE + "/properties/" + str(pd["id"]),
            published=bool(status.get("published")),
            archived=bool(status.get("archived")),
            tags=list(pd.get("tags") or []),                      # e.g. ["SOLD_STC"]
            channel=pd.get("channel") or "",
            title=(pd.get("text") or {}).get("propertyPhrase") or "",
            price=prices.get("primaryPrice") or "",
            price_qualifier=prices.get("displayPriceQualifier") or "",
            price_per_sqft=prices.get("pricePerSqFt") or "",
            address=_clean(addr.get("displayAddress")),
            outcode=addr.get("outcode"),
            incode=addr.get("incode"),
            bedrooms=pd.get("bedrooms"),
            bathrooms=pd.get("bathrooms"),
            property_type=pd.get("propertySubType") or "",
            tenure=tenure.get("tenureType"),
            lease_years_left=tenure.get("yearsRemainingOnLease"),
            council_tax_band=costs.get("councilTaxBand"),
            service_charge=costs.get("annualServiceCharge"),
            ground_rent=costs.get("annualGroundRent"),
            size_sqft=sizes.get("sqft"),
            size_sqm=sizes.get("sqm"),
            latitude=loc.get("latitude"),
            longitude=loc.get("longitude"),
            agent=cust.get("branchDisplayName") or "",
            branch_id=cust.get("branchId"),
            listing_history=(pd.get("listingHistory") or {}).get("listingUpdateReason") or "",
            images=len(pd.get("images") or []),
            floorplans=len(pd.get("floorplans") or []),
            virtual_tours=len(pd.get("virtualTours") or []),
            epc_graphs=len(pd.get("epcGraphs") or []),
            key_features=list(pd.get("keyFeatures") or []),
            stations=[f"{s.get('name')} ({s.get('distance', 0):.1f} {s.get('unit', '')})"
                      for s in pd.get("nearestStations") or []],
            parking=feat("parking"),
            garden=feat("garden"),
            lettings=pd.get("lettings"),
            nearby_sold_url=(pd.get("propertyUrls") or {}).get("nearbySoldPropertiesUrl"),
            description=_strip_html((pd.get("text") or {}).get("description")),
        )


@dataclass
class SoldHome:
    """One card on /house-prices/<area>.html with every sale it lists."""
    address: str
    postcode: str | None
    property_type: str
    bedrooms: int | None
    tenure: str
    last_sold: str | None
    last_price: int | None
    previous: list[tuple[str, int]]
    record_id: str

    @classmethod
    def from_card(cls, c: dict) -> "SoldHome":
        sales = []
        for row in c.get("rows") or []:
            price = _int(row.get("price"))
            if price and row.get("date"):
                sales.append((row["date"], price))
        address = _clean(c.get("address"))
        m = POSTCODE.search(address.upper())
        first = sales[0] if sales else (None, None)
        return cls(
            address=address,
            postcode=" ".join(m.groups()) if m else None,
            property_type=_clean(c.get("type")),
            bedrooms=_int(c.get("beds")),
            tenure=_clean(c.get("tenure")),
            last_sold=_iso_day(first[0]) if first[0] else None,
            last_price=first[1],
            previous=[(_iso_day(d), p) for d, p in sales[1:]],
            # The card links to /house-prices/details/<uuid>, which robots.txt
            # disallows. We keep the uuid as an id and never request it.
            record_id=(c.get("href") or "").rstrip("/").split("/")[-1],
        )


def _iso_day(text: str) -> str:
    return datetime.strptime(text, "%d %b %Y").date().isoformat()


@dataclass
class SoldPage:
    summary: list[str]
    result_count: int | None
    page: int
    pages: int | None
    homes: list[SoldHome]


# ---------- client ----------

class RightmoveClient:
    def __init__(self, api_key: str | None = None, timeout: int = 90, attempts: int = 3):
        self.api_key = api_key or os.environ.get("SCRAPINGBEE_API_KEY")
        if not self.api_key:
            raise RightmoveError("set SCRAPINGBEE_API_KEY")
        self.timeout = timeout
        self.attempts = attempts
        self.credits = 0
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {self.api_key}"

    def _get(self, url: str, rules: dict | None = None) -> requests.Response:
        """One ScrapingBee call. Retries its HTTP 500s, which are not billed."""
        params = {"url": url, "render_js": "false", "country_code": "gb"}
        if rules:
            params["extract_rules"] = json.dumps(rules)
        for attempt in range(1, self.attempts + 1):
            r = self.session.get(API, params=params, timeout=self.timeout)
            self.credits += int(r.headers.get("spb-cost") or 0)
            if r.status_code >= 500 and attempt < self.attempts:
                time.sleep(2 * attempt)
                continue
            initial = r.headers.get("spb-initial-status-code", "")
            resolved = r.headers.get("spb-resolved-url", "")
            if r.status_code in (404, 410) or initial in ("404", "410") or "page-not-found" in resolved:
                raise NotFound(url)
            if r.status_code != 200:
                raise RightmoveError(f"HTTP {r.status_code} for {url}: {r.text[:300]}")
            return r
        raise RightmoveError(f"gave up on {url}")

    def _retry_empty(self, fn, *args):
        """A 200 without the data blob is billed; try it again a couple of times."""
        for attempt in range(1, self.attempts + 1):
            try:
                return fn(*args)
            except EmptyPage:
                if attempt == self.attempts:
                    raise
                time.sleep(2)

    # ----- search -----

    @staticmethod
    def search_url(area: str, rent: bool = False, index: int = 0, sort: str | None = None,
                   sstc: bool = False, min_beds: int | None = None, max_price: int | None = None,
                   min_price: int | None = None) -> str:
        channel = "property-to-rent" if rent else "property-for-sale"
        q: dict[str, Any] = {}
        if "^" in area:                      # a raw locationIdentifier, e.g. OUTCODE^2315
            path = f"/{channel}/find.html"
            q["locationIdentifier"] = area
        else:                                # an outcode, postcode or town slug: SE15, SE15-6NJ, Manchester
            path = f"/{channel}/{area}.html"
        if sort:
            q["sortType"] = SORTS[sort]
        if sstc and not rent:
            q["includeSSTC"] = "true"
        if sstc and rent:
            q["includeLetAgreed"] = "true"
        for k, v in (("minBedrooms", min_beds), ("minPrice", min_price), ("maxPrice", max_price)):
            if v is not None:
                q[k] = v
        if index:
            q["index"] = index
        return SITE + path + ("?" + urlencode(q) if q else "")

    def _search_page(self, url: str) -> SearchPage:
        r = self._get(url, SEARCH_RULES)
        blob = re.sub(r"^<script[^>]*>|</script>$", "", (r.json().get("next") or "").strip())
        if not blob:
            raise EmptyPage(url)
        sr = json.loads(blob)["props"]["pageProps"].get("searchResults")
        if not sr or "properties" not in sr:
            raise EmptyPage(url)
        now = datetime.fromtimestamp(sr.get("timestamp", time.time() * 1000) / 1000, tz=timezone.utc)
        pag = sr.get("pagination") or {}
        loc = sr.get("location") or {}
        return SearchPage(
            description=sr.get("searchParametersDescription") or "",
            result_count=_int(sr.get("resultCount")) or 0,
            page=int(pag.get("page") or 1),
            pages=int(pag.get("total") or 1),
            location_id=f"{loc.get('locationType')}^{loc.get('id')}",
            listings=[Listing.from_json(p, now) for p in sr["properties"]],
        )

    def search(self, area: str, pages: int = 1, **kw) -> Iterator[SearchPage]:
        """Yield up to `pages` result pages. Stops at the last page Rightmove reports."""
        for n in range(pages):
            index = n * PER_PAGE
            if index > MAX_INDEX:
                break
            page = self._retry_empty(self._search_page, self.search_url(area, index=index, **kw))
            yield page
            if page.page >= page.pages:
                break

    def listings(self, area: str, pages: int = 1, **kw) -> tuple[SearchPage | None, list[Listing]]:
        """All listings over `pages`, de-duplicated (the featured slot repeats on every page)."""
        seen: dict[int, Listing] = {}
        first = None
        for page in self.search(area, pages, **kw):
            first = first or page
            for item in page.listings:
                seen.setdefault(item.id, item)
        return first, list(seen.values())

    # ----- one listing -----

    def _listing(self, prop_id: int) -> PropertyDetail:
        url = f"{SITE}/properties/{prop_id}"
        page = self._get(url).text
        start = page.find("window.__PAGE_MODEL = ")
        if start < 0:
            raise EmptyPage(url)
        model, _ = json.JSONDecoder().raw_decode(page, start + len("window.__PAGE_MODEL = "))
        data = model.get("data")
        if isinstance(data, str):
            data = unflatten(json.loads(data))
        if not data or "propertyData" not in data:
            raise EmptyPage(url)
        return PropertyDetail.from_model(data)

    def listing(self, prop_id: int) -> PropertyDetail | None:
        try:
            return self._retry_empty(self._listing, prop_id)
        except NotFound:
            return None

    # ----- sold prices -----

    def _sold_page(self, url: str, page_no: int) -> SoldPage:
        d = self._get(url, SOLD_RULES).json()
        cards = d.get("cards") or []
        if not cards and not d.get("count"):
            raise EmptyPage(url)
        pages = re.search(r"of (\d+)", d.get("pager") or "")
        return SoldPage(
            summary=[_clean(s) for s in d.get("summary") or []],
            result_count=_int(d.get("count")),
            page=page_no,
            pages=int(pages.group(1)) if pages else None,
            homes=[SoldHome.from_card(c) for c in cards],
        )

    def sold(self, area: str, pages: int = 1) -> Iterator[SoldPage]:
        for n in range(1, pages + 1):
            url = f"{SITE}/house-prices/{area.lower()}.html" + (f"?pageNumber={n}" if n > 1 else "")
            page = self._retry_empty(self._sold_page, url, n)
            yield page
            if page.pages is not None and n >= page.pages:
                break


def unflatten(arr: list) -> Any:
    """window.__PAGE_MODEL.data is a flattened graph: every value in an object or
    list is an index into the top level array. Index 0 is the root."""
    def build(i: int) -> Any:
        if not isinstance(i, int) or i < 0:
            return None
        v = arr[i]
        if isinstance(v, dict):
            return {k: build(x) for k, x in v.items()}
        if isinstance(v, list):
            return [build(x) for x in v]
        return v
    return build(0)


# ---------- export ----------

def _row(obj: Any) -> dict:
    out = {}
    for k, v in asdict(obj).items():
        if isinstance(v, (list, dict, tuple)):
            v = json.dumps(v, ensure_ascii=False)
        out[k] = v
    return out


def write_csv(path: str, items: list) -> None:
    if not items:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[x.name for x in fields(items[0])])
        w.writeheader()
        for it in items:
            w.writerow(_row(it))


def write_json(path: str, items: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(i) if i is not None else None for i in items], f, ensure_ascii=False, indent=1)


# ---------- CLI ----------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Public Rightmove pages through ScrapingBee")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="search results for sale or to rent")
    s.add_argument("area", help="outcode, postcode or town slug (SE15, SE15-6NJ, Manchester) or OUTCODE^2315")
    s.add_argument("--rent", action="store_true")
    s.add_argument("--pages", type=int, default=1)
    s.add_argument("--sort", choices=sorted(SORTS))
    s.add_argument("--sstc", action="store_true", help="include sold STC / let agreed")
    s.add_argument("--min-beds", type=int)
    s.add_argument("--min-price", type=int)
    s.add_argument("--max-price", type=int)

    li = sub.add_parser("listing", help="one or more listing pages by id")
    li.add_argument("ids", nargs="+", type=int)

    so = sub.add_parser("sold", help="sold prices for an area")
    so.add_argument("area")
    so.add_argument("--pages", type=int, default=1)

    for p in (s, li, so):
        p.add_argument("--csv")
        p.add_argument("--json")
    a = ap.parse_args(argv)

    rm = RightmoveClient()
    items: list = []
    if a.cmd == "search":
        first, items = rm.listings(a.area, a.pages, rent=a.rent, sort=a.sort, sstc=a.sstc,
                                   min_beds=a.min_beds, min_price=a.min_price, max_price=a.max_price)
        if first:
            print(f"{first.description}: {first.result_count} results, {first.pages} pages, {first.location_id}",
                  file=sys.stderr)
        for x in items:
            money = f"{x.rent_pcm:>7,} pcm" if x.rent_pcm else f"{(x.price or 0):>10,}"
            print(f"{x.id:<16}{money}  {x.bedrooms or 0}bd  {x.property_type[:14]:<14} "
                  f"{(x.days_listed if x.days_listed is not None else '-')!s:>4}d  "
                  f"{x.status or x.update_reason:<13} {x.address[:40]}")
    elif a.cmd == "listing":
        for pid in a.ids:
            d = rm.listing(pid)
            items.append(d)
            if d is None:
                print(json.dumps({"id": pid, "found": False}))
            else:
                short = {k: v for k, v in asdict(d).items() if k not in ("description",)}
                print(json.dumps(short, ensure_ascii=False))
        items = [i for i in items if i is not None] if a.csv else items
    else:
        for page in rm.sold(a.area, a.pages):
            if page.page == 1:
                for line in page.summary:
                    print(line, file=sys.stderr)
                print(f"{page.result_count} sold records, {page.pages} pages", file=sys.stderr)
            items.extend(page.homes)
        for h in items:
            print(f"{h.last_sold}  {(h.last_price or 0):>10,}  {h.property_type[:13]:<13} "
                  f"{h.bedrooms or '-'!s:>2}bd  {h.tenure:<9} {h.address[:48]}")

    if a.csv:
        write_csv(a.csv, items)
    if a.json:
        write_json(a.json, items)
    print(f"{len(items)} records, {rm.credits} credits", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
