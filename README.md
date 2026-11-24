# Rightmove API

<p align="center">
  <a href="https://www.scrapingbee.com/">
    <img src="REPLACE_WITH_SCREENSHOT_URL" alt="rightmove-api" />
  </a>
</p>

[![checks](https://github.com/ScrapingBee/rightmove-api/workflows/checks/badge.svg)](https://github.com/ScrapingBee/rightmove-api/actions)
[![license](https://img.shields.io/github/license/ScrapingBee/rightmove-api.svg)](LICENSE)

How much does a two bed flat in Peckham cost? What would it rent for? How long do homes there sit on the market, and who is selling them? This repo answers questions like those for a UK postcode district or town, using a [Rightmove API](https://www.scrapingbee.com/scrapers/rightmove-api/) client that runs on [ScrapingBee](https://www.scrapingbee.com/) and reads Rightmove's public pages as a signed out visitor sees them.

Rightmove turned out to be a cheap target. Search results, listing pages and sold price pages are all rendered on the server, so a plain request with JavaScript off (1 credit) already holds the full data. The whole SE15 picture below, 659 homes for sale, 176 to rent and 100 sold records, cost 41 credits and took under a minute.

```bash
pip install requests
export SCRAPINGBEE_API_KEY=your_key
python examples/postcode_report.py SE15 --csv se15_listings.csv
```

```
# SE15: Properties For Sale in SE15, including sold STC
read 659 sale, 176 rent, 100 sold records for 41 credits

1. What does it cost to buy? (33 land, plot, commercial or shared ownership listings left out)
   studio bed     £215,000 median asking  (n=4)
        1 bed     £325,000 median asking  (n=154)
        2 bed     £467,500 median asking  (n=256)
        3 bed     £750,000 median asking  (n=134)
       4+ bed   £1,175,000 median asking  (n=78)
   price per sq ft £679 (n=275, only listings that state a size)
2. What does it cost to rent?
        1 bed    £1,750 pcm median  (n=58)
        2 bed    £2,300 pcm median  (n=61)
        3 bed    £3,400 pcm median  (n=26)
       4+ bed    £4,500 pcm median  (n=28)
3. Gross yield, median rent x 12 / median asking
        1 bed  6.5%
        2 bed  5.9%
        3 bed  5.4%
       4+ bed  4.6%
4. How fast do listings move?
   433 available, 659 incl. sold STC; 35.8% of the homes read are sold STC or under offer
   status of the homes read: {'available': 402, 'Sold STC': 172, 'Under offer': 52}
   median days on Rightmove: 67.0 (available), 145.0 (sold STC or under offer)
   45.3% of available listings were last updated by a price reduction
5. Who holds the stock? (sale + rent listings)
     99  Acorn, Peckham Rye
     57  Foxtons, Peckham
     54  Kinleigh Folkard & Hayward - Sales, Peckham Rye
     50  Dexters, Peckham
6. What did homes sell for? (2026-04-21 to 2026-08-18)
   Flat                £415,000 median  (n=59)
   Terraced            £860,000 median  (n=38)
   Semi-Detached       £950,000 median  (n=3)
```

That run is from 24 November 2026, trimmed for space: the studio rent and yield rows (3 lets), the price qualifier line, Rightmove's own summary lines and agents after the fourth are cut. The rest of this README goes question by question and shows where on Rightmove each answer comes from.

## Pages this repo reads, and the ones it leaves alone

Before any page was requested, robots.txt was fetched through ScrapingBee (1 credit). The `User-agent: *` group is long; these are the lines that shaped the code:

```
Allow: /api/property-search/*
Disallow: /api/*
Disallow: /property-for-sale/map.html?*
Disallow: /property-for-sale/draw-a-search.html?*
Disallow: /property-for-sale/market-information/*
Disallow: /property-to-rent/map.html?*
Disallow: /house-prices/details/*
Disallow: /house-prices/detailMatching.html*
Disallow: /property/view.html*
Disallow: /property-details/print.html*
Disallow: /*/fullscreen/image-gallery.html*
Disallow: /rss/*
```

So the client touches four URL shapes and nothing else:

| Question | Page | robots.txt | Where the data sits |
|---|---|---|---|
| asking prices, rents, agents, listing age | `/property-for-sale/SE15.html`, `/property-to-rent/SE15.html` | not disallowed | `__NEXT_DATA__` JSON |
| one home in full | `/properties/90625020` | not disallowed | `window.__PAGE_MODEL` JSON |
| sold prices | `/house-prices/se15.html` | not disallowed | server rendered HTML |
| the same search by id | `/property-for-sale/find.html?locationIdentifier=OUTCODE%5E2315` | not disallowed | `__NEXT_DATA__` JSON |

Two things are deliberately missing. The JSON endpoint under `/api/property-search/` is allowed by robots.txt, but it is Rightmove's internal search backend, and this repo does not call private endpoints. The search JSON itself carries a `termsOfUse` string saying that API is "for the use of Rightmove Group Limited only". Every number here comes from the HTML pages a browser loads. And the sold price cards link to `/house-prices/details/<uuid>`, which is disallowed, so those links are kept as an id and never followed.

The file also blocks a few named crawlers outright (GPTBot, CCbot, TrovitBot and others). Requests in this repo do not identify as any of them.

## Question 1 and 2: what does it cost to buy or rent here?

A search page for an outcode lives at `/property-for-sale/<OUTCODE>.html` or `/property-to-rent/<OUTCODE>.html`. Town slugs work the same way (`/property-for-sale/Manchester.html`), and so does a full postcode with a dash (`SE15-6NJ.html`, the form Rightmove uses in its own "similar properties" link). `SE15-6NJ.html?minPrice=500000` returned one home and reported its location as `POSTCODE^756927`.

The visible cards use CSS module class names with build hashes, for example:

```html
<div class="PropertyCard_propertyCardContainerWrapper__mcK1Z propertyCard-details" data-testid="propertyCard-vrt-3">
  <a id="prop90625020" class="PropertyCard_propertyCardAnchor__s2ZaP"></a>
  ...
  <address class="PropertyAddress_address__LYRPq" aria-label="Property address: Glengall Road, Peckham, SE15">Glengall Road, Peckham, SE15</address>
  <div class="PropertyInformation_container__2wY0G" data-testid="property-information">
    <span class="PropertyInformation_propertyType__u8e76" aria-label="Semi-Detached">Semi-Detached</span>
    <span class="PropertyInformation_bedroomsCount___2b5R" aria-label="4 in property">4</span>
  ...
  <span class="MarketedBy_addedOrReduced__Vtc9o" tabindex="0">Added on 08/07/2026</span>
```

Those `__mcK1Z` suffixes change whenever Rightmove ships a new build, so the cards are the wrong thing to parse. The same page is a Next.js app, and the server puts the whole result set in `<script id="__NEXT_DATA__" type="application/json">` under `props.pageProps.searchResults`. One entry from `properties[]`, trimmed to the fields the client keeps:

```json
{"id": 90625020, "bedrooms": 4, "bathrooms": 3,
 "displayAddress": "Glengall Road, Peckham, SE15",
 "location": {"latitude": 51.485836, "longitude": -0.0721},
 "propertySubType": "Semi-Detached", "tenure": {"tenureType": "FREEHOLD"},
 "listingUpdate": {"listingUpdateReason": "new", "listingUpdateDate": "2026-07-08T11:39:35Z"},
 "price": {"amount": 1750000, "frequency": "not specified", "currencyCode": "GBP",
           "displayPrices": [{"displayPrice": "£1,750,000", "displayPriceQualifier": "Guide Price",
                              "abbreviatedPrice": "£1.75m"}]},
 "customer": {"branchId": 40674, "branchDisplayName": "Wooster & Stock, London",
              "brandTradingName": "Wooster & Stock"},
 "displaySize": "2,455 sq. ft.", "firstVisibleDate": "2026-07-08T11:33:49Z",
 "addedOrReduced": "Added on 08/07/2026", "displayStatus": "", "featuredProperty": false,
 "channel": "BUY", "propertyUrl": "/properties/90625020#/?channel=RES_BUY"}
```

Next to `properties[]` sit `resultCount` (a string, `"433"`, or `"56,321"` with a comma for London), `pagination` and a `location` object with the id Rightmove uses internally (`{"id": 2315, "locationType": "OUTCODE"}` for SE15).

The full page is 1.3 MB. `extract_rules` can return just that one script tag, which brings a response down to about 420 KB. The tag has to be asked for with `"output": "html"`, then the `<script>` wrapper is stripped before `json.loads`:

```python
SEARCH_RULES = {"next": {"selector": "script#__NEXT_DATA__", "output": "html"}}

r = self._get(url, SEARCH_RULES)
blob = re.sub(r"^<script[^>]*>|</script>$", "", (r.json().get("next") or "").strip())
sr = json.loads(blob)["props"]["pageProps"].get("searchResults")
if not sr or "properties" not in sr:
    raise EmptyPage(url)      # billed, so the caller retries it
```

```bash
python examples/rightmove_client.py search SE15 --pages 2 --sort newest --sstc --csv se15_sale.csv
```

```
Properties For Sale in SE15, including sold STC: 659 results, 28 pages, OUTCODE^2315
95284719            88,125  2bd  Apartment        14d  new           840 Old Kent Road, London, SE15 1NQ
95145756           380,000  2bd  Apartment        19d  price_reduced Brayards Road, London
94950300           325,000  1bd  Flat             24d  price_reduced Woods Road, Peckham
95770398           400,000  2bd  Apartment         0d  new           Peckham Rye, London
95768934           375,000  1bd  Flat              0d  new           Shield Street, LONDON
...
50 records, 2 credits
```

Things that would quietly skew the answers if you took the JSON at face value:

**Shared ownership prices are the price of a share.** The first row above, £88,125 for a two bed flat, carries `displayPriceQualifier: "Shared ownership"`. 28 of the 659 SE15 sale listings did. `postcode_report.py` leaves them out of the medians along with land, plots and commercial units, and prints how many it dropped. The qualifier mix for SE15 was 303 with none, 204 `Guide Price`, 84 `Offers in Excess of`, 18 `Offers in Region of`, 16 `Offers Over`, 5 `Fixed Price` and 1 `From`.

**Rents come in two units.** Most rents arrive as `"frequency": "monthly"`, but some are weekly: listing 95791491 had `"amount": 392, "frequency": "weekly"`. Every rent also carries a display string ending in `pcm` (`"£1,699 pcm"` for that one), so the client reads the monthly figure from there and only falls back to `amount * 52 / 12`.

**Each page holds 24 results plus one featured slot.** A page has 25 entries; one has `featuredProperty: true` and can repeat on a later page. `listings()` keys everything by id. Over all 28 SE15 pages that gave 659 unique homes, matching `resultCount` exactly, so nothing was lost or doubled.

**A search stops at 42 pages.** `index` steps by 24. For London (56,321 results) `index=984` was page 42 of 42, and `index=1008` came back as a 307 to `/page-not-found`, billed at 1 credit. To cover a large city, split it into outcodes or price bands. `minPrice`, `maxPrice` and `minBedrooms` all worked on the slug URL in our runs.

**The default sort differs by channel.** A bare sale URL comes back with `sortType=2` (highest price first), a rent URL with `sortType=6` (newest first). We checked three values on live pages, and the client only exposes those: `1` lowest price, `2` highest price, `6` newest.

The Node example answers question 2 for another city:

```bash
SCRAPINGBEE_API_KEY=... node examples/rent_by_bedroom.js Manchester 3
```

```
Properties To Rent in Manchester, Greater Manchester: 5,987 results
studio bed  median £800 pcm  range £700 to £899  n=2
     1 bed  median £1,240 pcm  range £700 to £1,723  n=25
     2 bed  median £1,350 pcm  range £715 to £1,895  n=30
     3 bed  median £1,625 pcm  range £1,300 to £2,095  n=13
    4+ bed  median £3,630 pcm  range £2,000 to £4,680  n=4
74 listings, 3 credits
```

Rent searches come back newest first by default, so three pages are the 74 most recent of 5,987 lets: a snapshot of what was just listed, not a city average.

## Question 3: how fast do listings move?

Rightmove hides homes that have found a buyer unless you ask for them. Adding `includeSSTC=true` to a sale search (or `includeLetAgreed=true` to a rental one) brings them back, and the page title changes to say so. For SE15 the counts were 433 without and 659 with, so a third of what is listed has already found a buyer. Those cards carry a non empty `displayStatus`: `"Sold STC"` (172) or `"Under offer"` (52) for sales, `"Let agreed"` (37 of 176) for rentals.

Days on the market come from `firstVisibleDate`, not from the "Added on" label. The two disagree when a home is relisted: listing 88140273 was first visible on 2026-05-06 but its card read "Added on 13/11/2026". 25 SE15 sale listings looked new by their label and were older by `firstVisibleDate`. The client stores both (`first_visible`, `days_listed`, `added_or_reduced`) and the report uses the first.

`listingUpdate.listingUpdateReason` held one of two values in everything we read, `new` or `price_reduced`. In SE15, 45.3% of the homes still available had a price cut as their most recent update.

To see movement over time instead of a single reading, [`examples/price_watch.py`](examples/price_watch.py) re-reads a search and logs every change to a CSV:

```bash
python examples/price_watch.py SE15 --rent --pages 8 --state rent_state.json --log rent_changes.csv
```

Two rounds on 24 November 2026, the second one 24 minutes after the first:

```
2026-11-24T13:37:16Z: 176 listings of 176, 176 changes, 8 credits
  93893457 | _new |  | 4600 | Copleston Road, Southwark, London
  95792067 | _new |  | 1650 | Cheltenham Road, London, SE15
  95791491 | _new |  | 1699 | Nunhead Lane, London, London, London, SE
  95757132 | _new |  | 1750 | Peckham Grove London SE15
  ...
2026-11-24T14:01:11Z: 176 listings of 176, 0 changes, 8 credits
```

The first round logs every listing as `_new`, because there is no earlier state. The second found nothing: in 24 minutes no SE15 rental changed price or status, and a parallel run over all 659 sale listings (28 credits) found none either. With that little movement per half hour, a run every few hours, or daily from cron, catches the same changes for far fewer credits. Listing 95791491 shows the weekly rent fix at work: its `amount` is 1699, the pcm figure, not the 392 a week the JSON stores.

It reads the search sorted newest first with sold STC and let agreed included, so a listing that goes under offer stays in view and shows up as a `status` change instead of vanishing. The changes it logs:

```python
WATCHED = ("amount", "status", "update_reason")

for f in WATCHED:
    if before.get(f) != rec.get(f):
        rows.append((pid, "price" if f == "amount" else f, before.get(f), rec.get(f)))
for pid in old.keys() - new.keys():
    rows.append((pid, "_gone", old[pid].get("status") or "listed", ""))
```

`amount` is the monthly rent for lettings and the asking price for sales. A `_gone` row means the id left the pages read: withdrawn, completed, or pushed beyond the last page you read. Read every page of the area (8 for SE15 rentals, 28 for SE15 sales) if you want `_gone` to mean "no longer listed".

## Question 4: who holds the stock?

Every listing names its branch in `customer.branchDisplayName` with a stable `customer.branchId`. Counting them over the sale and rent pages of SE15 put Acorn, Peckham Rye first with 99 listings, then Foxtons (57), Kinleigh Folkard & Hayward (54) and Dexters (50). That is the agency share view, built from listing counts only; this repo does not collect agent contact details, even though the cards show a branch phone number.

## Question 5: what does one listing page add?

`/properties/<id>` is not a Next.js page. Its data sits in an inline script:

```html
<script>
    window.__PAGE_MODEL = {"data":"[{\"propertyData\":1,\"metadata\":584,\"isAuthenticated\":7,\"analyticsInfo\":1881},{\"id\":2,\"encId\":3,\"buildingId\":4,\"status\":5,\"text\":8,\"prices\":18,\"address\":22,\"keyFeatures\":28, ...
```

`data` is a JSON string holding a flattened graph: a list of 1,900 entries for listing 90625020, where every value inside an object or list is an index into that same list. `"bedrooms": 437` means "look at entry 437", which holds `4`. Index 0 is the root. Rebuilding it takes a few lines:

```python
def unflatten(arr: list) -> Any:
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
```

The object is followed by more statements inside the same script tag, so the client uses `json.JSONDecoder().raw_decode()` from the start of the object rather than a regex up to `</script>`.

```bash
python examples/rightmove_client.py listing 90625020 95792067 1 --json listings.json
```

Output trimmed to the main fields:

```
{"id": 90625020, "url": "https://www.rightmove.co.uk/properties/90625020", "published": true, "archived": false,
 "tags": [], "channel": "RES_BUY", "title": "4 bedroom semi-detached house", "price": "£1,750,000",
 "price_qualifier": "Guide Price", "price_per_sqft": "£712.83 per sq ft", "address": "Glengall Road, Peckham, SE15",
 "outcode": "SE15", "incode": "6NJ", "bedrooms": 4, "bathrooms": 3, "property_type": "Semi-Detached",
 "tenure": "FREEHOLD", "council_tax_band": "E", "size_sqft": 2455, "size_sqm": 228,
 "agent": "Wooster & Stock, London", "listing_history": "Added on 08/07/2026", "images": 45, "floorplans": 1,
 "virtual_tours": 1, "stations": ["South Bermondsey Station (0.8 miles)", "Bermondsey Station (0.9 miles)",
 "Queens Road Peckham Station (1.1 miles)"], "parking": "Yes", "garden": "Yes", "lettings": null,
 "nearby_sold_url": "/house-prices/se15-6nj.html", ...}
{"id": 95792067, ..., "channel": "RES_LET", "title": "1 bedroom apartment", "price": "£1,650 pcm",
 "council_tax_band": "TBC", "agent": "Truepenny's, Dulwich",
 "lettings": {"letAvailableDate": "20/01/2027", "deposit": 0, "minimumTermInMonths": null,
              "letType": "Long term", "furnishType": "Unfurnished"}, ...}
{"id": 1, "found": false}
```

What the listing page has that the search card does not: the incode (the second half of the postcode, `6NJ`), council tax band, price per sq ft, square metres, lease years and service charge where the agent filled them in, nearest stations with distances, the full description, the lettings block for rentals, and a `tags` list. Listing 95639466 had `"tags": ["SOLD_STC"]`, which is how a sold STC home reads on its own page. The `nearbySoldPropertiesUrl` (`/house-prices/se15-6nj.html`) points to the sold prices for that exact postcode, which feeds the next question.

A listing id that does not exist came back as HTTP 410 and, unlike ScrapingBee's own failures, was billed at 1 credit. `listing()` returns `None` for it.

## Question 6: what did homes sell for? Rightmove data from the sold prices page

`/house-prices/<area>.html` is a React Router page whose cards are plain server HTML, 25 per page. Its opening paragraphs are Rightmove's own summary of the area, for SE15:

```html
<p class="_explainer_1webw_98">House prices in SE15 have an overall average of £654,280 over the last year.</p>
```

Each card is an `<a data-testid="propertyCard">` with the address in an `h2`, type, bedrooms and tenure in elements labelled by `aria-label`, and a table of past sales:

```html
<a class="_propertyCardVariant_1h056_34" data-testid="propertyCard" href=".../house-prices/details/812b502f-849f-4575-ae82-27118dbfd6dd">
  <h2 class="_title_1h056_50">106, Cossall Walk, London SE15 2TN</h2>
  <div class="_propertyCategory_1h056_193" aria-label="Property Type: Flat.">Flat</div>
  <div class="_propertyCategory_1h056_193" aria-label="Bedrooms: 1.">1</div>
  <div class="_propertyCategory_1h056_193" aria-label="Tenure: Leasehold.">Leasehold</div>
  <table class="_transactionTable_1m1we_32"><tbody>
    <tr><td><span>Today</span></td><td><a aria-label="See today's value" href="...">See today's value</a></td></tr>
    <tr><td class="_transactionTableCell_1m1we_42 _transactionTableDateBody_1m1we_39">18 Aug 2026</td>
        <td><div aria-label="£305,000.">£305,000</div></td></tr>
    <tr><td class="_transactionTableCell_1m1we_42 _transactionTableDateBody_1m1we_39">29 Nov 2019</td>
        <td><div aria-label="£305,000.">£305,000</div></td></tr>
```

The class names are hashed here too, so the rules use `data-testid`, `aria-label` prefixes and tag positions, and match on `[class*=...]` only where nothing else exists. With them the response drops from 543 KB to 9 KB:

```python
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
            "rows": {"selector": "tr", "type": "list",
                     "output": {"date": "td:nth-child(1)", "price": "td:nth-child(2) div[aria-label]"}},
        },
    },
}
```

A bare string like `"href": "@href"` was rejected by the API with `Expected selector, got <EOF at 0>` (not billed); an attribute needs the `{"selector": ..., "output": "@href"}` form. The "Today / See today's value" row has no price and is skipped by the parser.

```bash
python examples/rightmove_client.py sold SE15 --pages 2 --csv se15_sold.csv
```

```
House prices in SE15 have an overall average of £654,280 over the last year.
...
10092 sold records, 40 pages
2026-08-18     305,000  Flat           1bd  Leasehold 106, Cossall Walk, London SE15 2TN
2026-08-18   1,300,000  Terraced       5bd  Freehold  262, Ivydale Road, London SE15 3DF
2026-08-10     420,000  Flat           2bd  Leasehold Flat 24, 47 Sarawak Court, Consort Road, London
2026-08-07     700,000  Terraced       2bd  Freehold  94, Bellenden Road, London SE15 4RF
50 records, 2 credits
```

```
address,postcode,property_type,bedrooms,tenure,last_sold,last_price,previous,record_id
"262, Ivydale Road, London SE15 3DF",SE15 3DF,Terraced,5,Freehold,2026-08-18,1300000,"[[""2020-08-18"", 875000]]",d49d2141-36ba-478d-9d75-c894c2fce45c
```

The pager is a set of buttons, but `?pageNumber=2` on the URL returns the second page, and the pager text reads "of 40". For SE15 that reaches 1,000 of the 10,092 records, newest sale first. The newest sale on the list was dated 18 August 2026, three months before our run, which is how far the sold records trailed the live listings in November 2026. One card read as a six bed flat (39a Kings Grove); the parser keeps such values exactly as the page prints them.

## Which proxy tier is enough

Measured on `/property-for-sale/SE15.html` on 24 November 2026:

| Request | Credits | Response | `__NEXT_DATA__` | Property cards | Time |
|---|---|---|---|---|---|
| `render_js=false` | 1 | 1,336,592 bytes | yes | 25 | 2 s |
| `render_js=true` | 5 | 1,830,092 bytes | yes | 25 | 5 s |
| `premium_proxy=true`, no JS | 10 | 1,329,335 bytes | yes | 25 | 2 s |

Rendering added about 500 KB and no listings. Listing pages and sold price pages also returned their full data at 1 credit, so every call in this repo sends `render_js=false` with `country_code=gb`. Over the roughly 280 requests made while writing this, none came back as an empty shell and none hit a ScrapingBee 500; the retry code for both is there because it costs nothing when unused.

```python
def _get(self, url: str, rules: dict | None = None) -> requests.Response:
    params = {"url": url, "render_js": "false", "country_code": "gb"}
    if rules:
        params["extract_rules"] = json.dumps(rules)
    for attempt in range(1, self.attempts + 1):
        r = self.session.get(API, params=params, timeout=self.timeout)
        self.credits += int(r.headers.get("spb-cost") or 0)
        if r.status_code >= 500 and attempt < self.attempts:    # ScrapingBee does not bill these
            time.sleep(2 * attempt)
            continue
        ...
```

## The Rightmove scraper files

| File | What it does | Credits |
|---|---|---|
| [`examples/rightmove_client.py`](examples/rightmove_client.py) | `RightmoveClient`; `Listing`, `PropertyDetail` and `SoldHome` dataclasses; `search`, `listing` and `sold` subcommands with `--csv` and `--json` | 1 per page |
| [`examples/postcode_report.py`](examples/postcode_report.py) | the six answers for one area, plus every listing read to CSV | 41 for SE15 |
| [`examples/price_watch.py`](examples/price_watch.py) | change log for one search: new, price, status, gone | 1 per page per round |
| [`examples/rent_by_bedroom.js`](examples/rent_by_bedroom.js) | Node 18+, no dependencies, median rent by bedrooms | 1 per page |

The Python files need only `requests` and run on Python 3.10 or newer. The two tools import the client, so keep them in the same folder.

## What each job costs

| Job | Requests | Credits |
|---|---|---|
| one search page, 24 listings plus a featured slot | 1 | 1 |
| every SE15 sale listing incl. sold STC (659) | 28 | 28 |
| the full SE15 report above | 41 | 41 |
| one listing page | 1 | 1 |
| a listing id that no longer exists (HTTP 410) | 1 | 1 |
| a search page past page 42 (307 to page-not-found) | 1 | 1 |
| one sold prices page, 25 addresses | 1 | 1 |
| watch all SE15 rentals hourly for a day | 192 | 192 |

The [pricing page](https://www.scrapingbee.com/pricing/) lists the plans; a new account starts with 1,000 free credits, enough for the SE15 report about twenty times over. The parameters used here are covered in the [API documentation](https://www.scrapingbee.com/documentation/), `extract_rules` on the [data extraction page](https://www.scrapingbee.com/documentation/data-extraction/) and [feature overview](https://www.scrapingbee.com/features/data-extraction/), and the `gb` exit on the [country codes list](https://www.scrapingbee.com/documentation/country_codes/).

## What Rightmove data is public, and what is not

Everything above is what rightmove.co.uk shows a visitor who is not signed in, and the search JSON says as much with `"isAuthenticated": false`. Each listing also carries `saved` and `hidden` flags, which only mean something for a signed in user and are always false here. Anything tied to an account is out of scope, and this repo does not sign in. ScrapingBee's terms do not allow scraping with login credentials, so there is no session or cookie handling anywhere in the code.

Some things are public but sit on paths robots.txt disallows (map search, draw a search, market information, the per sale detail pages, print views, RSS), and those are skipped even where they would be convenient. Commercial listings appear in normal searches (3 in SE15) and pass through the client as `COMMERCIAL_BUY`. Only England postcodes were tested; Scottish and Welsh areas use the same page types, but nothing here was run against them.

Related endpoints for other property sites: [Zoopla API](https://www.scrapingbee.com/scrapers/zoopla-api/), [OnTheMarket scraper API](https://www.scrapingbee.com/scrapers/onthemarket-scraper-api/), [OpenRent API](https://www.scrapingbee.com/scrapers/openrent-api/), [real estate data API](https://www.scrapingbee.com/scrapers/real-estate-data-api/), [Zillow API](https://www.scrapingbee.com/scrapers/zillow-api/), [Idealista API](https://www.scrapingbee.com/scrapers/idealista-api/), [Redfin API](https://www.scrapingbee.com/scrapers/redfin-api/).

## FAQ

**Does Rightmove have a public API?**
Not one this repo could build on. The data embedded in its own pages states that its API is reserved for Rightmove Group, so the client reads the public HTML pages instead and never calls an `/api/` path.

**How do I get Rightmove data into a CSV?**
`python examples/rightmove_client.py search SE15 --pages 28 --sstc --csv se15.csv` writes one row per listing, with price, qualifier, rent pcm, bedrooms, size, tenure, coordinates, agent, first seen date and status. The `sold` subcommand does the same for sold prices, and `postcode_report.py --csv` saves everything a report read.

**Is a Rightmove scraper allowed to read sold house prices?**
The area pages (`/house-prices/se15.html`) are not disallowed in robots.txt and are what this repo reads. The per address detail pages under `/house-prices/details/` are disallowed, and the client never requests them.

**Why do some rents look far too low?**
They are weekly. Use `rent_pcm`, which comes from Rightmove's own pcm figure, not `price`. And a sale price that looks too low is often a shared ownership share; check `price_qualifier`.

**How many listings can one Rightmove search return?**
42 pages of 24, so 1,008. Split a city into outcodes or price bands to get past that. The SE15 sold price list showed 40 pages of 25 out of 10,092 records.

**Do I need JavaScript rendering or premium proxies for Rightmove?**
Not in our tests. The 1 credit request returned the same listings as the 5 and 10 credit ones.

## License

MIT. See [LICENSE](LICENSE).
