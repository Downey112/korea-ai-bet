"""scripts/01_ingest.py

Raw data ingestion for "Korea's AI bet: smart move or bigger risk?".
Downloads Bank of Korea ECOS, UN Comtrade (public preview), World Bank and OECD
Revenue Statistics into data/raw/, one cached file per request.

- Reruns skip cached files unless --refresh is passed.
- Requests are paced and retried with exponential backoff on 429 and network errors.
- Exits non-zero if any required series comes back empty.
- ECOS uses env var ECOS_API_KEY, falling back to the public "sample" key
  (10 rows per call, so a cold run takes a few minutes).
"""

import io
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

import pandas as pd
import requests

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
SEED_DIR = ROOT / "data" / "seed"
ECOS_DIR = RAW_DIR / "ecos"
COMTRADE_DIR = RAW_DIR / "comtrade"
WORLDBANK_DIR = RAW_DIR / "worldbank"
OECD_DIR = RAW_DIR / "oecd"

for directory in [ECOS_DIR, COMTRADE_DIR, WORLDBANK_DIR, OECD_DIR, SEED_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

ECOS_LAST_MONTH = "202609"
ECOS_LAST_YEAR = "2025"


def fetch_with_retry(url: str, max_attempts: int = 5, initial_wait: float = 3.0) -> requests.Response:
    """Fetch a URL with exponential backoff on 429 and network errors."""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=60)
            if resp.status_code == 429:
                wait = initial_wait * (2 ** (attempt - 1))
                print(f"[RETRY 429] waiting {wait:.1f}s (attempt {attempt}/{max_attempts})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as error:
            last_error = error
            wait = initial_wait * (2 ** (attempt - 1))
            print(f"[RETRY NET] {error}; waiting {wait:.1f}s (attempt {attempt}/{max_attempts})")
            time.sleep(wait)
    raise RuntimeError(f"Failed to fetch {url} after {max_attempts} attempts.") from last_error


def safe_code(code: str) -> str:
    """Make an ECOS item code safe for Windows filenames ('*AA' -> 'STAR_AA')."""
    return code.replace("*", "STAR_").replace("?", "_").replace("/", "_")


# -----------------------------------------------------------------------------
# 1. Bank of Korea ECOS
# -----------------------------------------------------------------------------
def ingest_ecos(refresh: bool = False) -> list[dict]:
    """Monthly and annual export value, volume and price indices plus total exports.

    Paginates with list_total_count: 10 rows per call on the sample key,
    1000 on a real key.
    """
    key = os.environ.get("ECOS_API_KEY", "sample")
    page_size = 10 if key == "sample" else 1000
    m_from, m_to = "200001", ECOS_LAST_MONTH
    a_from, a_to = "2000", ECOS_LAST_YEAR

    series = []
    for cycle, f, t in [("M", m_from, m_to), ("A", a_from, a_to)]:
        for stat in ["403Y001", "403Y002", "402Y014"]:
            for item in ["*AA", "3091AA"]:
                series.append((stat, cycle, item, f, t))
        series.append(("901Y118", cycle, "T002", f, t))

    meta = []
    for stat, cycle, item, f, t in series:
        rows, start, total = [], 1, None
        while True:
            end = start + page_size - 1
            cache = ECOS_DIR / f"ecos_{stat}_{cycle}_{safe_code(item)}_{f}_{t}_{start}_{end}.json"
            if cache.exists() and not refresh:
                payload = json.loads(cache.read_text(encoding="utf-8"))
            else:
                url = (
                    f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/"
                    f"{start}/{end}/{stat}/{cycle}/{f}/{t}/{urllib.parse.quote(item, safe='')}"
                )
                payload = fetch_with_retry(url, initial_wait=1.0).json()
                if "RESULT" in payload:
                    r = payload["RESULT"]
                    raise RuntimeError(f"ECOS error [{r.get('CODE')}] for {stat}/{item}: {r.get('MESSAGE')}")
                cache.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
                time.sleep(0.35)
            block = payload.get("StatisticSearch", {})
            page = block.get("row", [])
            rows.extend(page)
            if total is None:
                total = int(block.get("list_total_count", 0))
            if end >= total or not page:
                break
            start = end + 1

        name = f"ECOS {stat} {cycle} {item}"
        if rows:
            print(f"[OK]   {name:<26} {len(rows):>4} rows, {rows[0]['TIME']} to {rows[-1]['TIME']}")
            meta.append({"name": name, "rows": len(rows), "status": "OK"})
        else:
            print(f"[FAIL] {name}: 0 rows")
            meta.append({"name": name, "rows": 0, "status": "FAIL"})
    return meta


# -----------------------------------------------------------------------------
# 2. UN Comtrade public preview (annual, one period per call)
# -----------------------------------------------------------------------------
def ingest_comtrade(refresh: bool = False) -> list[dict]:
    """HS 8542 and TOTAL exports for Korea, Malaysia and Japan, 2000 to 2025.

    An empty data list for the newest year is normal (not yet reported).
    """
    meta = []
    for rep, iso3 in [("410", "KOR"), ("458", "MYS"), ("392", "JPN")]:
        years_with_data, n = [], 0
        for yr in range(2000, 2026):
            cache = COMTRADE_DIR / f"comtrade_{rep}_{yr}.json"
            if cache.exists() and not refresh:
                payload = json.loads(cache.read_text(encoding="utf-8"))
            else:
                url = (
                    "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
                    f"?reporterCode={rep}&period={yr}&partnerCode=0&partner2Code=0"
                    "&cmdCode=8542,TOTAL&flowCode=X&customsCode=C00&motCode=0"
                )
                payload = fetch_with_retry(url, initial_wait=3.0).json()
                cache.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
                time.sleep(3.0)
            data = payload.get("data") or []
            if data:
                n += len(data)
                years_with_data.append(yr)
        name = f"Comtrade {iso3}"
        if years_with_data:
            print(f"[OK]   {name:<26} {n:>4} rows, {min(years_with_data)} to {max(years_with_data)} ({len(years_with_data)} years)")
            meta.append({"name": name, "rows": n, "status": "OK"})
        else:
            print(f"[FAIL] {name}: no rows in any year")
            meta.append({"name": name, "rows": 0, "status": "FAIL"})
    return meta


# -----------------------------------------------------------------------------
# 3. World Bank indicators
# -----------------------------------------------------------------------------
WB_INDICATORS = [
    "SP.DYN.TFRT.IN",
    "SP.POP.65UP.TO.ZS",
    "SP.POP.1564.TO.ZS",
    "SP.POP.1564.TO",
    "NY.GDP.MKTP.KD.ZG",
    "GB.XPD.RSDV.GD.ZS",
    "NE.EXP.GNFS.ZS",
]


def ingest_worldbank(refresh: bool = False) -> list[dict]:
    meta = []
    for ind in WB_INDICATORS:
        cache = WORLDBANK_DIR / f"worldbank_{ind}.json"
        if cache.exists() and not refresh:
            payload = json.loads(cache.read_text(encoding="utf-8"))
        else:
            url = (
                f"https://api.worldbank.org/v2/country/KOR;JPN;MYS/indicator/{ind}"
                "?format=json&per_page=2000&date=2000:2025"
            )
            payload = fetch_with_retry(url, initial_wait=2.0).json()
            cache.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            time.sleep(0.5)
        name = f"World Bank {ind}"
        if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
            print(f"[FAIL] {name}: empty payload")
            meta.append({"name": name, "rows": 0, "status": "FAIL"})
            continue
        yrs = [int(r["date"]) for r in payload[1] if r.get("value") is not None]
        print(f"[OK]   {name:<26} {len(yrs):>4} values, {min(yrs)} to {max(yrs)}")
        meta.append({"name": name, "rows": len(yrs), "status": "OK" if yrs else "FAIL"})
    return meta


# -----------------------------------------------------------------------------
# 4. OECD Revenue Statistics, Korea
# -----------------------------------------------------------------------------
def ingest_oecd(refresh: bool = False) -> list[dict]:
    cache = OECD_DIR / "oecd_revenue_kor.csv"
    if cache.exists() and not refresh:
        df = pd.read_csv(cache)
    else:
        url = (
            "https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS,DSD_REV_OECD@DF_REVKOR,2.0/all"
            "?startPeriod=2000&format=csvfilewithlabels"
        )
        text = fetch_with_retry(url, initial_wait=3.0).text
        cache.write_text(text, encoding="utf-8")
        df = pd.read_csv(io.StringIO(text))
    if df.empty:
        print("[FAIL] OECD DF_REVKOR: empty")
        return [{"name": "OECD DF_REVKOR", "rows": 0, "status": "FAIL"}]
    yrs = sorted(df["TIME_PERIOD"].dropna().astype(int).unique())
    print(f"[OK]   {'OECD DF_REVKOR':<26} {len(df):>5} rows, {yrs[0]} to {yrs[-1]}")
    return [{"name": "OECD DF_REVKOR", "rows": len(df), "status": "OK"}]


def main() -> None:
    refresh = "--refresh" in sys.argv
    print(f"=== Ingest (refresh={refresh}) ===")
    meta = []
    meta += ingest_ecos(refresh)
    meta += ingest_comtrade(refresh)
    meta += ingest_worldbank(refresh)
    meta += ingest_oecd(refresh)
    seed = SEED_DIR / "budget_2027.csv"
    print(f"[{'OK' if seed.exists() else 'INFO'}]   seed budget_2027.csv {'present' if seed.exists() else 'missing'}")

    failures = [m for m in meta if m["status"] == "FAIL" or m["rows"] == 0]
    if failures:
        print(f"\n[FATAL] {len(failures)} empty or failed series:")
        for m in failures:
            print(f"  - {m['name']}")
        sys.exit(1)
    print("\n[SUCCESS] All required series downloaded.")


if __name__ == "__main__":
    main()
