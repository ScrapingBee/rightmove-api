// Median rent per calendar month by bedroom count for one Rightmove area.
// Node 18+ (global fetch), no dependencies. 1 credit per result page.
//
//   SCRAPINGBEE_API_KEY=... node examples/rent_by_bedroom.js SE15 8
//
// Reads /property-to-rent/<AREA>.html?index=0,24,48... through ScrapingBee with
// render_js=false and an extract_rules call that returns only the
// __NEXT_DATA__ script. Rents arrive monthly or weekly; the "pcm" display
// string Rightmove puts next to every rent is used so both line up.

const API = "https://app.scrapingbee.com/api/v1/";
const RULES = { next: { selector: "script#__NEXT_DATA__", output: "html" } };

async function page(area, index, key) {
  const target = `https://www.rightmove.co.uk/property-to-rent/${area}.html` + (index ? `?index=${index}` : "");
  const qs = new URLSearchParams({
    url: target,
    render_js: "false",
    country_code: "gb",
    extract_rules: JSON.stringify(RULES),
  });
  for (let attempt = 1; attempt <= 3; attempt++) {
    const res = await fetch(`${API}?${qs}`, { headers: { Authorization: `Bearer ${key}` } });
    const cost = Number(res.headers.get("spb-cost") || 0);
    if (res.status >= 500 && attempt < 3) {          // not billed, safe to retry
      await new Promise((r) => setTimeout(r, 2000 * attempt));
      continue;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
    const body = await res.json();
    const raw = (body.next || "").replace(/^<script[^>]*>/, "").replace(/<\/script>$/, "");
    if (!raw) throw new Error(`no __NEXT_DATA__ in ${target}`);
    return { sr: JSON.parse(raw).props.pageProps.searchResults, cost };
  }
  throw new Error(`gave up on ${target}`);
}

function pcm(price) {
  const shown = (price.displayPrices || []).find((p) => p.displayPrice.endsWith("pcm"));
  if (shown) return Number(shown.displayPrice.replace(/[^\d]/g, ""));
  if (price.frequency === "monthly") return price.amount;
  if (price.frequency === "weekly") return Math.round((price.amount * 52) / 12);
  return null;
}

function median(xs) {
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

async function main() {
  const key = process.env.SCRAPINGBEE_API_KEY;
  if (!key) throw new Error("set SCRAPINGBEE_API_KEY");
  const area = process.argv[2] || "SE15";
  const maxPages = Number(process.argv[3] || 2);

  const seen = new Map();
  let credits = 0;
  let header = "";
  for (let n = 0; n < maxPages; n++) {
    const { sr, cost } = await page(area, n * 24, key);
    credits += cost;
    header = header || `${sr.searchParametersDescription}: ${sr.resultCount} results`;
    for (const p of sr.properties) seen.set(p.id, p);       // featured slot repeats, keep one
    if (Number(sr.pagination.page) >= Number(sr.pagination.total)) break;
  }

  const byBeds = new Map();
  for (const p of seen.values()) {
    const rent = pcm(p.price || {});
    if (!rent || p.bedrooms == null) continue;
    const k = p.bedrooms === 0 ? "studio" : p.bedrooms >= 4 ? "4+" : String(p.bedrooms);
    if (!byBeds.has(k)) byBeds.set(k, []);
    byBeds.get(k).push(rent);
  }

  console.log(header);
  for (const k of ["studio", "1", "2", "3", "4+"]) {
    const xs = byBeds.get(k);
    if (!xs) continue;
    const lo = Math.min(...xs);
    const hi = Math.max(...xs);
    console.log(`${k.padStart(6)} bed  median £${Math.round(median(xs)).toLocaleString("en-GB")} pcm  range £${lo.toLocaleString("en-GB")} to £${hi.toLocaleString("en-GB")}  n=${xs.length}`);
  }
  console.log(`${seen.size} listings, ${credits} credits`);
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
