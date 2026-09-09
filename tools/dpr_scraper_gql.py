"""
DPR GQL Full Scraper - menggunakan cookies dari Playwright session.
1. Playwright load homepage → dapat cookies
2. Intercept getDaftarRiwayatAnggota response dari anggota page
3. Fallback: getDaftarQuoteAnggota
4. Paginate all members, save ke JSON + CSV
"""
from playwright.sync_api import sync_playwright
import httpx, json, time, csv, re
from pathlib import Path

OUT = Path("D:/Hermes/tools")
GQL = "https://www.dpr.go.id/gql"

# ── Playwright browser helpers ──────────────────────────────
HEADERS_BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json, */*",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://www.dpr.go.id",
    "Referer": "https://www.dpr.go.id/tentang-dpr/informasi-anggota-dewan",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

all_riwayat = []        # from getDaftarRiwayatAnggota
all_quote_members = []  # from getDaftarQuoteAnggota
cookies_dict = {}
periode_id = None

def on_response(response):
    """Capture GQL responses from browser."""
    try:
        if GQL not in response.url:
            return
        if response.status != 200:
            return
        req = response.request
        body_str = req.post_data or ""
        if not body_str:
            return
        data = json.loads(body_str)
        query_text = data.get("query", "")
        m = re.search(r'query\s+(\w+)', query_text)
        qname = m.group(1) if m else "unknown"

        resp_bytes = response.body()
        resp = json.loads(resp_bytes.decode("utf-8", errors="replace"))
        
        if "errors" in resp:
            return

        resp_data = resp.get("data", {})
        
        if qname == "getDaftarRiwayatAnggota":
            key = "getDaftarRiwayatAnggota"
            if key in resp_data:
                info = resp_data[key].get("paginatorInfo", {})
                members = resp_data[key].get("data", [])
                print(f"  [GQL] {qname}: {len(members)} members | total={info.get('total')} | page={info.get('currentPage')} | lastPage={info.get('lastPage')}")
                all_riwayat.extend(members)
                # Store periode info from variables
                global periode_id
                if not periode_id and "wherePeriode" in str(data.get("variables", {})):
                    periode_id = data.get("variables", {})
            
        elif qname == "getDaftarQuoteAnggota":
            key = "getDaftarQuoteAnggota"
            if key in resp_data:
                info = resp_data[key].get("paginatorInfo", {})
                members = resp_data[key].get("data", [])
                print(f"  [GQL] {qname}: {len(members)} members | total={info.get('total')}")
                all_quote_members.extend(members)

    except Exception as ex:
        pass  # silent


def get_cookies_and_capture():
    """Use Playwright to load DPR pages and capture cookies + GQL data."""
    global cookies_dict
    
    print("Starting Playwright browser...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="id-ID",
            timezone_id="Asia/Jakarta",
            viewport={"width": 1440, "height": 900},
            extra_http_headers={
                "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
            }
        )
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            window.chrome = {runtime: {}};
        """)
        page = ctx.new_page()
        page.on("response", on_response)

        # Step 1: Load homepage
        print("Loading homepage...")
        try:
            page.goto("https://www.dpr.go.id", wait_until="networkidle", timeout=35000)
            time.sleep(5)
            cookies_browser = ctx.cookies()
            cookies_dict = {c["name"]: c["value"] for c in cookies_browser}
            print(f"Cookies after homepage: {list(cookies_dict.keys())}")
            print(f"QuoteAnggota so far: {len(all_quote_members)}")
        except Exception as ex:
            print(f"Homepage error: {ex}")

        # Step 2: Navigate to anggota page
        print("\nNavigating to anggota page...")
        try:
            page.goto("https://www.dpr.go.id/tentang-dpr/informasi-anggota-dewan",
                      wait_until="networkidle", timeout=45000)
            print("Page loaded, waiting for GQL calls...")
            time.sleep(15)  # Wait for all async GQL calls to complete
            
            cookies_browser = ctx.cookies()
            cookies_dict = {c["name"]: c["value"] for c in cookies_browser}
            print(f"Cookies after anggota page: {list(cookies_dict.keys())}")
            
            # Save cookies
            (OUT / "_dpr_cookies.json").write_text(
                json.dumps(cookies_dict, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as ex:
            print(f"Anggota page error: {ex}")

        browser.close()
    
    print(f"\nCaptured: {len(all_riwayat)} riwayat, {len(all_quote_members)} quote members")
    print(f"Cookies: {list(cookies_dict.keys())[:5]}...")


def call_gql(client, query, variables):
    """Direct GQL call via httpx."""
    body = json.dumps({"query": query, "variables": variables})
    r = client.post(GQL, content=body, timeout=30)
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    try:
        data = r.json()
        if "errors" in data:
            return None, str(data["errors"][0]["message"])
        return data.get("data", {}), None
    except:
        return None, "JSON parse error"


# QUERY TEMPLATES
Q_RIWAYAT = """query getDaftarRiwayatAnggota($page: Int, $first: Int!, $wherePeriode: QueryGetDaftarRiwayatAnggotaWherePeriodeWhereHasConditions) {
    getDaftarRiwayatAnggota(page: $page, first: $first, wherePeriode: $wherePeriode) {
        paginatorInfo { count currentPage hasMorePages lastPage total }
        data {
            id
            idDapil
            dapil { id dapil }
            anggota {
                id
                nama
                namaLengkap
                fraksi
                jabatan
                noAnggota
                jenisKelamin
                tempatLahir
                tanggalLahir
                photofileLink
            }
        }
    }
}"""

Q_QUOTE = """query getDaftarQuoteAnggota($page: Int, $first: Int!) {
    getDaftarQuoteAnggota(page: $page, first: $first) {
        paginatorInfo { count currentPage hasMorePages lastPage total }
        data { id nama quote fraksi jabatan linkFotoLink }
    }
}"""

Q_FRAKSI = """query getAllFraksi {
    getAllFraksi {
        id fraksi fraksiEn singkatan
    }
}"""

Q_PROPINSI = """query getDaftarPropinsi($first: Int!) {
    getDaftarPropinsi(first: $first) {
        data { id propinsi }
    }
}"""


def scrape_all_with_cookies():
    """Use cookies to paginate through all members."""
    if not cookies_dict:
        print("No cookies available!")
        return []
    
    client = httpx.Client(headers=HEADERS_BROWSER, cookies=cookies_dict, 
                          timeout=30, follow_redirects=True)
    
    # Test: get fraksi list (should work without much auth)
    print("\n=== Testing getAllFraksi ===")
    data, err = call_gql(client, Q_FRAKSI, {})
    if err:
        print(f"getAllFraksi error: {err}")
    else:
        fraksies = data.get("getAllFraksi", [])
        print(f"Fraksi: {fraksies}")
        (OUT / "_dpr_fraksi.json").write_text(json.dumps(fraksies, ensure_ascii=False, indent=2))
    
    # Try getDaftarRiwayatAnggota with pagination
    members = []
    print("\n=== Paginating getDaftarRiwayatAnggota ===")
    for page in range(1, 30):
        data, err = call_gql(client, Q_RIWAYAT, {"page": page, "first": 25})
        if err:
            print(f"  Page {page}: ERROR - {err}")
            if "Unauthenticated" in str(err):
                break  # No point continuing
            time.sleep(2)
            continue
        
        key = "getDaftarRiwayatAnggota"
        if key not in data:
            break
        
        info = data[key].get("paginatorInfo", {})
        page_data = data[key].get("data", [])
        print(f"  Page {page}: {len(page_data)} members | total={info.get('total')} | hasMore={info.get('hasMorePages')}")
        members.extend(page_data)
        
        if not info.get("hasMorePages"):
            break
        time.sleep(1)  # Rate limit protection
    
    print(f"\nTotal from riwayat: {len(members)}")
    
    # Fallback: getDaftarQuoteAnggota
    if not members:
        print("\n=== Fallback: getDaftarQuoteAnggota ===")
        for page in range(1, 30):
            data, err = call_gql(client, Q_QUOTE, {"page": page, "first": 25})
            if err:
                print(f"  Page {page}: ERROR - {err}")
                if "Unauthenticated" in str(err):
                    break
                time.sleep(2)
                continue
            
            key = "getDaftarQuoteAnggota"
            if key not in data:
                break
            info = data[key].get("paginatorInfo", {})
            page_data = data[key].get("data", [])
            print(f"  Page {page}: {len(page_data)} | total={info.get('total')}")
            members.extend(page_data)
            
            if not info.get("hasMorePages"):
                break
            time.sleep(1)
    
    client.close()
    return members


def normalize_member(m, source="riwayat"):
    """Normalize member data to common format."""
    if source == "riwayat":
        anggota = m.get("anggota") or {}
        return {
            "id": anggota.get("id") or m.get("id"),
            "nama": anggota.get("nama", ""),
            "nama_lengkap": anggota.get("namaLengkap", ""),
            "fraksi": anggota.get("fraksi", ""),
            "jabatan": anggota.get("jabatan", "Anggota DPR RI"),
            "dapil": (m.get("dapil") or {}).get("dapil", ""),
            "no_anggota": anggota.get("noAnggota", ""),
            "jenis_kelamin": anggota.get("jenisKelamin", ""),
            "tempat_lahir": anggota.get("tempatLahir", ""),
            "tanggal_lahir": str(anggota.get("tanggalLahir", "")),
            "foto": anggota.get("photofileLink", ""),
        }
    else:  # quote
        return {
            "id": m.get("id"),
            "nama": m.get("nama", ""),
            "nama_lengkap": "",
            "fraksi": m.get("fraksi", ""),
            "jabatan": m.get("jabatan", "Anggota DPR RI"),
            "dapil": "",
            "no_anggota": "",
            "jenis_kelamin": "",
            "tempat_lahir": "",
            "tanggal_lahir": "",
            "foto": m.get("linkFotoLink", ""),
        }


def main():
    # Phase 1: Use Playwright to get cookies + capture some data
    get_cookies_and_capture()
    
    # Phase 2: If we captured members via browser interception, use those
    if all_riwayat:
        print(f"\nUsing {len(all_riwayat)} members captured via browser interception")
        members_raw = all_riwayat
        source = "riwayat"
    elif all_quote_members:
        print(f"\nUsing {len(all_quote_members)} members from quote interception")
        members_raw = all_quote_members
        source = "quote"
    else:
        members_raw = []
        source = "riwayat"
    
    # Phase 3: Paginate for remaining members using cookies
    if cookies_dict and len(members_raw) < 500:
        print(f"\nNeed more members, using direct API with cookies...")
        api_members = scrape_all_with_cookies()
        if api_members:
            members_raw = api_members
            source = "api"
    
    if not members_raw:
        print("\nFailed to get any members!")
        return
    
    # Normalize
    is_riwayat = source in ("riwayat", "api") and "anggota" in str(members_raw[0])
    normalized = [normalize_member(m, "riwayat" if is_riwayat else "quote") for m in members_raw]
    
    # Deduplicate by ID
    seen = set()
    deduped = []
    for m in normalized:
        key = m["id"]
        if key not in seen:
            seen.add(key)
            deduped.append(m)
    
    print(f"\nTotal unique members: {len(deduped)}")
    
    # Save JSON
    json_path = OUT / "_dpr_members_full.json"
    json_path.write_text(json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved JSON: {json_path}")
    
    # Save CSV
    csv_path = OUT / "_dpr_members_full.csv"
    if deduped:
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=deduped[0].keys())
            w.writeheader()
            w.writerows(deduped)
        print(f"Saved CSV: {csv_path}")
    
    # Summary by fraksi
    from collections import Counter
    fraksi_count = Counter(m["fraksi"] for m in deduped)
    print("\nFraksi breakdown:")
    for fraksi, count in sorted(fraksi_count.items(), key=lambda x: -x[1]):
        print(f"  {fraksi}: {count}")
    
    # Sample members
    print("\nSample members:")
    for m in deduped[:5]:
        print(f"  {m['nama']} | {m['fraksi']} | {m['dapil']}")


if __name__ == "__main__":
    main()
