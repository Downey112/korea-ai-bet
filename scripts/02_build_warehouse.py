"""scripts/02_build_warehouse.py

Builds data/warehouse.duckdb from data/raw/ and exports sorted CSV + parquet
tables to data/processed/.

Tables:
- dim_country
- fact_kr_trade_month / fact_kr_trade_year: ECOS export value, volume and price
  indices (all goods, semiconductors), total exports in USD, yoy %, and the
  implied value index (price x volume / 100) as a consistency check.
- fact_trade_year: Comtrade HS 8542 chip exports vs total exports, by country.
- fact_indicators: World Bank indicators, long format.
- fact_kr_tax_year: OECD corporate and total tax, trillion won.
- mart_chip_episodes: chip export downturns with a price/volume split.
- mart_boom_decomposition: upswings, including the current boom, split the same way.
- mart_tax_vs_chips + mart_tax_chip_correlation: corporate tax vs chip exports.
- mart_peer_snapshot: Korea, Japan, Malaysia, 2000 vs latest.
- budget_2027: the hand-sourced seed table.
"""

import json
import math
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
SEED_DIR = ROOT / "data" / "seed"
PROCESSED_DIR = ROOT / "data" / "processed"
WAREHOUSE_PATH = ROOT / "data" / "warehouse.duckdb"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


# -----------------------------------------------------------------------------
# Staging
# -----------------------------------------------------------------------------
def load_ecos_raw(con: duckdb.DuckDBPyConnection) -> None:
    """Stage ECOS rows.

    The export price index (402Y014) comes in three bases in ITEM_CODE2:
    D (달러기준, US dollar), W (원화기준, won) and C (계약통화기준, contract
    currency). Only D is kept, because the value index and total exports are
    in US dollars, so price x volume must be on the same basis.
    """
    rows = []
    for f in sorted((RAW_DIR / "ecos").glob("*.json")):
        payload = json.loads(f.read_text(encoding="utf-8"))
        for r in payload.get("StatisticSearch", {}).get("row", []):
            if r.get("STAT_CODE") == "402Y014" and r.get("ITEM_CODE2") != "D":
                continue
            t = str(r.get("TIME", ""))
            rows.append({
                "stat_code": r.get("STAT_CODE"),
                "cycle": "M" if len(t) == 6 else "A",
                "time": t,
                "item_code": r.get("ITEM_CODE1"),
                "unit_name": r.get("UNIT_NAME"),
                "data_value": float(r["DATA_VALUE"]) if r.get("DATA_VALUE") not in (None, "") else None,
            })
    df = pd.DataFrame(rows).drop_duplicates(subset=["stat_code", "cycle", "item_code", "time"])
    con.register("stg_ecos_df", df)
    con.execute("create or replace table stg_ecos as select * from stg_ecos_df")


def load_comtrade_raw(con: duckdb.DuckDBPyConnection) -> None:
    rep_map = {"410": "KOR", "458": "MYS", "392": "JPN"}
    rows = []
    for f in sorted((RAW_DIR / "comtrade").glob("*.json")):
        payload = json.loads(f.read_text(encoding="utf-8"))
        for r in payload.get("data") or []:
            if r.get("primaryValue") is None:
                continue
            rep = str(r.get("reporterCode"))
            rows.append({
                "iso3": rep_map.get(rep, rep),
                "year": int(r.get("period")),
                "cmd_code": str(r.get("cmdCode")),
                "primary_value": float(r["primaryValue"]),
            })
    df = pd.DataFrame(rows).drop_duplicates(subset=["iso3", "year", "cmd_code"])
    con.register("stg_comtrade_df", df)
    con.execute("create or replace table stg_comtrade as select * from stg_comtrade_df")


def load_worldbank_raw(con: duckdb.DuckDBPyConnection) -> None:
    rows = []
    for f in sorted((RAW_DIR / "worldbank").glob("*.json")):
        payload = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(payload, list) and len(payload) >= 2 and payload[1]:
            for r in payload[1]:
                if r.get("value") is not None:
                    rows.append({
                        "iso3": r.get("countryiso3code"),
                        "year": int(r.get("date")),
                        "indicator_code": r["indicator"]["id"],
                        "indicator_name": r["indicator"]["value"],
                        "value": float(r["value"]),
                    })
    df = pd.DataFrame(rows).drop_duplicates(subset=["iso3", "year", "indicator_code"])
    con.register("stg_worldbank_df", df)
    con.execute("create or replace table stg_worldbank as select * from stg_worldbank_df")


def load_oecd_raw(con: duckdb.DuckDBPyConnection) -> None:
    f = RAW_DIR / "oecd" / "oecd_revenue_kor.csv"
    if not f.exists():
        raise FileNotFoundError(f"Missing OECD revenue file at {f}")
    # pandas, because DuckDB's CSV sniffer cannot read the OECD labelled export
    df = pd.read_csv(f, low_memory=False)
    df = df[(df.SECTOR == "S13") & (df.CTRY_SPECIFIC_REVENUE == "_T")
            & df.STANDARD_REVENUE.isin(["T_1200", "_T"]) & (df.UNIT_MEASURE == "KRW")]
    if not (df.UNIT_MULT == 9).all():
        raise ValueError("OECD UNIT_MULT is not 9 (billion won) for every row")
    df = pd.DataFrame({
        "year": df.TIME_PERIOD.astype(int),
        "standard_revenue": df.STANDARD_REVENUE,
        "obs_value": df.OBS_VALUE.astype(float),
    })
    con.register("stg_oecd_df", df)
    con.execute("create or replace table stg_oecd as select * from stg_oecd_df")


def stage_seed_budget(con: duckdb.DuckDBPyConnection) -> None:
    f = SEED_DIR / "budget_2027.csv"
    con.execute(f"""
        create or replace table budget_2027 as
        select item,
               cast(amount_trn_won as double) as amount_trn_won,
               try_cast(change_pct as double) as change_pct,
               status, source_url, source_quote, note
        from read_csv('{f.as_posix()}', header=true, all_varchar=true)
    """)


# -----------------------------------------------------------------------------
# Dimensions and facts
# -----------------------------------------------------------------------------
def build_dimensions(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        create or replace table dim_country as
        select * from (values
            ('KOR', 'South Korea', true),
            ('JPN', 'Japan', false),
            ('MYS', 'Malaysia', false)
        ) t(iso3, name, is_focus)
    """)


def _trade_sql(cycle: str) -> str:
    """Shared SQL for the monthly (M) and annual (A) trade facts.

    yoy uses lag 12 for months and lag 1 for years. implied_value_idx is
    price_idx * volume_idx / 100; its ratio to value_idx is a check that the
    three indices are consistent, not a replacement for the published value.
    """
    if cycle == "M":
        key, key_expr, lag = "month", "strptime(time, '%Y%m')::date", 12
    else:
        key, key_expr, lag = "year", "cast(time as integer)", 1

    def yoy(col: str) -> str:
        prev = f"lag({col}, {lag}) over (partition by series order by {key})"
        return f"round(({col} - {prev}) / {prev} * 100.0, 4) as {col}_yoy_pct"

    return f"""
        with staged as (
            select {key_expr} as {key},
                   case when item_code = '*AA' then 'all_goods' else 'semiconductors' end as series,
                   max(case when stat_code = '403Y001' then data_value end) as value_idx,
                   max(case when stat_code = '403Y002' then data_value end) as volume_idx,
                   max(case when stat_code = '402Y014' then data_value end) as price_idx
            from stg_ecos
            where cycle = '{cycle}' and stat_code in ('403Y001', '403Y002', '402Y014')
              and item_code in ('*AA', '3091AA')
            group by all
        ),
        customs as (
            select {key_expr} as {key}, data_value / 1000000.0 as total_exports_usd_bn
            from stg_ecos
            where cycle = '{cycle}' and stat_code = '901Y118' and item_code = 'T002'
        ),
        joined as (
            select s.*,
                   case when s.series = 'all_goods' then c.total_exports_usd_bn end as total_exports_usd_bn
            from staged s left join customs c using ({key})
        )
        select {key}, series, value_idx, volume_idx, price_idx,
               round(total_exports_usd_bn, 4) as total_exports_usd_bn,
               {yoy('value_idx')}, {yoy('volume_idx')}, {yoy('price_idx')},
               round(price_idx * volume_idx / 100.0, 4) as implied_value_idx,
               round(price_idx * volume_idx / 100.0 / value_idx, 4) as implied_actual_ratio
        from joined
        order by {key}, series
    """


def build_fact_kr_trade(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("create or replace table fact_kr_trade_month as " + _trade_sql("M"))
    con.execute("create or replace table fact_kr_trade_year as " + _trade_sql("A"))


def build_fact_trade_year(con: duckdb.DuckDBPyConnection) -> None:
    """Comtrade chips vs total exports. Rows listed in data/seed/exclusions.csv
    are kept but flagged is_excluded, with the reason, so visuals can drop them."""
    excl = (SEED_DIR / "exclusions.csv").as_posix()
    con.execute(f"""
        create or replace table fact_trade_year as
        with p as (
            select iso3, year,
                   max(case when cmd_code = '8542' then primary_value end) / 1e9 as chip_exports_usd_bn,
                   max(case when cmd_code = 'TOTAL' then primary_value end) / 1e9 as total_exports_usd_bn
            from stg_comtrade group by iso3, year
        ),
        x as (select iso3, cast(year as integer) as year, reason
              from read_csv('{excl}', header=true, all_varchar=true))
        select p.iso3, p.year,
               round(chip_exports_usd_bn, 6) as chip_exports_usd_bn,
               round(total_exports_usd_bn, 6) as total_exports_usd_bn,
               round(chip_exports_usd_bn / total_exports_usd_bn * 100.0, 4) as chip_share_pct,
               x.reason is not null as is_excluded,
               x.reason as exclusion_reason
        from p left join x using (iso3, year)
        where total_exports_usd_bn > 0 and chip_exports_usd_bn is not null
        order by iso3, year
    """)


def build_fact_kr_chip_usd_month(con: duckdb.DuckDBPyConnection) -> None:
    """Monthly Korean chip exports in USD, estimated.

    ECOS gives the semiconductor export value index (2020=100) but no dollar
    level, so the index is anchored to Comtrade HS 8542 for 2020:
        chip_usd_bn(m) = value_idx(m) / 100 * comtrade_2020 / 12
    The ECOS 반도체 class and HS 8542 are not identical, so this is an estimate;
    validate checks that its annual sums stay within 5% of Comtrade from 2011.
    chip_share_pct divides by ECOS customs total exports for the same month.
    """
    con.execute("""
        create or replace table fact_kr_chip_usd_month as
        with base as (
            select chip_exports_usd_bn / 12.0 as m2020
            from fact_trade_year where iso3 = 'KOR' and year = 2020
        )
        select s.month,
               round(s.value_idx / 100.0 * b.m2020, 4) as chip_exports_usd_bn_est,
               a.total_exports_usd_bn,
               round(s.value_idx / 100.0 * b.m2020 / a.total_exports_usd_bn * 100.0, 2) as chip_share_pct_est
        from fact_kr_trade_month s
        join fact_kr_trade_month a on a.month = s.month and a.series = 'all_goods'
        cross join base b
        where s.series = 'semiconductors'
        order by s.month
    """)
    con.execute("""
        create or replace table check_chip_usd_annual as
        select year(e.month) as year, round(sum(e.chip_exports_usd_bn_est), 3) as est_usd_bn,
               any_value(t.chip_exports_usd_bn) as comtrade_usd_bn,
               round(sum(e.chip_exports_usd_bn_est) / any_value(t.chip_exports_usd_bn), 4) as ratio
        from fact_kr_chip_usd_month e
        join fact_trade_year t on t.iso3 = 'KOR' and t.year = year(e.month)
        group by all order by year
    """)


def build_fact_indicators(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        create or replace table fact_indicators as
        select iso3, year, indicator_code, indicator_name, round(value, 4) as value
        from stg_worldbank order by iso3, year, indicator_code
    """)


def build_fact_kr_tax_year(con: duckdb.DuckDBPyConnection) -> None:
    """OECD OBS_VALUE has UNIT_MULT=9 (billion won); /1000 gives trillion won."""
    con.execute("""
        create or replace table fact_kr_tax_year as
        with p as (
            select year,
                   max(case when standard_revenue = 'T_1200' then obs_value end) / 1000.0 as corporate_tax_trn_won,
                   max(case when standard_revenue = '_T' then obs_value end) / 1000.0 as total_tax_trn_won
            from stg_oecd group by year
        )
        select year,
               round(corporate_tax_trn_won, 4) as corporate_tax_trn_won,
               round(total_tax_trn_won, 4) as total_tax_trn_won,
               round(corporate_tax_trn_won / total_tax_trn_won * 100.0, 4) as corp_share_pct
        from p
        where corporate_tax_trn_won is not null and total_tax_trn_won is not null
        order by year
    """)


# -----------------------------------------------------------------------------
# Marts
# -----------------------------------------------------------------------------
def _log_split(p0, p1, v0, v1) -> tuple[float, float, float]:
    """Log-change of price and volume, and price's share of their sum (in %)."""
    dp, dv = math.log(p1 / p0), math.log(v1 / v0)
    share = dp / (dp + dv) * 100.0 if (dp + dv) != 0 else float("nan")
    return dp, dv, share


def build_mart_chip_episodes(con: duckdb.DuckDBPyConnection) -> None:
    """Chip export downturns from the MONTHLY semiconductor value index.

    1. ma3 = 3-month trailing mean of value_idx yoy %, only once 3 yoy values
       exist (no look-ahead; uses current and past months only).
    2. A downturn starts in the first month ma3 < 0 and ends in the last month
       before ma3 turns >= 0. Episodes shorter than 6 months are dropped.
    3. Peak = max value_idx in the 12 months before the start month.
       Trough = min value_idx within the episode.
    4. Price/volume split: log-change of price_idx and volume_idx from peak
       month to trough month, each as a share of their sum. Shares add to 100;
       a share above 100 means the other component moved the opposite way.
    5. all_goods_drop_pct: the all-goods value index over the same two months.
    An episode still open at the last month is kept and flagged is_open.
    """
    df = con.execute("""
        select month, value_idx, volume_idx, price_idx,
               case when count(value_idx_yoy_pct) over w = 3
                    then avg(value_idx_yoy_pct) over w end as ma3_yoy_pct
        from fact_kr_trade_month
        where series = 'semiconductors'
        window w as (order by month rows between 2 preceding and current row)
        order by month
    """).fetchdf().reset_index(drop=True)
    all_goods = con.execute(
        "select month, value_idx from fact_kr_trade_month where series = 'all_goods'"
    ).fetchdf().set_index("month")["value_idx"]

    episodes, start = [], None
    for i, ma3 in df["ma3_yoy_pct"].items():
        if pd.isna(ma3):
            continue
        if ma3 < 0 and start is None:
            start = i
        elif ma3 >= 0 and start is not None:
            if i - start >= 6:
                episodes.append((start, i - 1, False))
            start = None
    if start is not None and len(df) - start >= 6:
        episodes.append((start, len(df) - 1, True))

    out = []
    for n, (s, e, is_open) in enumerate(episodes, start=1):
        pre = df.loc[max(0, s - 12): s - 1]
        pk = pre["value_idx"].idxmax()
        tr = df.loc[s:e, "value_idx"].idxmin()
        P, T = df.loc[pk], df.loc[tr]
        dp, dv, share = _log_split(P.price_idx, T.price_idx, P.volume_idx, T.volume_idx)
        ag0, ag1 = all_goods.loc[P.month], all_goods.loc[T.month]
        out.append({
            "episode_id": n,
            "start_month": df.loc[s, "month"],
            "end_month": df.loc[e, "month"],
            "months": e - s + 1,
            "is_open": is_open,
            "peak_month": P.month,
            "peak_value_idx": round(P.value_idx, 2),
            "trough_month": T.month,
            "trough_value_idx": round(T.value_idx, 2),
            "drop_pct": round((T.value_idx / P.value_idx - 1) * 100, 2),
            "price_change_pct": round((T.price_idx / P.price_idx - 1) * 100, 2),
            "volume_change_pct": round((T.volume_idx / P.volume_idx - 1) * 100, 2),
            "price_share_pct": round(share, 2),
            "volume_share_pct": round(100 - share, 2),
            "all_goods_drop_pct": round((ag1 / ag0 - 1) * 100, 2),
        })
    con.register("ep_df", pd.DataFrame(out))
    con.execute("""
        create or replace table mart_chip_episodes as
        select * replace (start_month::date as start_month, end_month::date as end_month,
                          peak_month::date as peak_month, trough_month::date as trough_month)
        from ep_df order by start_month
    """)


def build_mart_boom_decomposition(con: duckdb.DuckDBPyConnection) -> None:
    """Upswings split into price and volume, the same way as downturns.

    Completed upswing: trough of episode i to peak of episode i+1.
    Current boom: trough of the last closed episode to the latest month
    (only when no downturn is open).
    """
    ep = con.execute("select * from mart_chip_episodes order by start_month").fetchdf()
    semi = con.execute("""
        select month, value_idx, volume_idx, price_idx
        from fact_kr_trade_month where series = 'semiconductors' order by month
    """).fetchdf()
    semi["month"] = pd.to_datetime(semi["month"])
    semi = semi.set_index("month")
    ep["trough_month"] = pd.to_datetime(ep["trough_month"])
    ep["peak_month"] = pd.to_datetime(ep["peak_month"])

    spans = [(ep.loc[i, "trough_month"], ep.loc[i + 1, "peak_month"], False) for i in range(len(ep) - 1)]
    if len(ep) and not bool(ep.iloc[-1]["is_open"]):
        spans.append((ep.iloc[-1]["trough_month"], semi.index[-1], True))

    rows = []
    for a, b, current in spans:
        A, B = semi.loc[a], semi.loc[b]
        dp, dv, share = _log_split(A.price_idx, B.price_idx, A.volume_idx, B.volume_idx)
        rows.append({
            "boom_label": f"{'Current boom' if current else 'Upswing'} {a:%Y-%m} to {b:%Y-%m}",
            "start_month": a.date(),
            "end_month": b.date(),
            "months": (b.year - a.year) * 12 + b.month - a.month,
            "is_current_boom": current,
            "value_change_pct": round((B.value_idx / A.value_idx - 1) * 100, 2),
            "price_change_pct": round((B.price_idx / A.price_idx - 1) * 100, 2),
            "volume_change_pct": round((B.volume_idx / A.volume_idx - 1) * 100, 2),
            "dlog_value": round(math.log(B.value_idx / A.value_idx), 4),
            "dlog_price": round(dp, 4),
            "dlog_volume": round(dv, 4),
            "price_share_pct": round(share, 2),
        })
    con.register("boom_df", pd.DataFrame(rows))
    con.execute("""
        create or replace table mart_boom_decomposition as
        select * replace (start_month::date as start_month, end_month::date as end_month)
        from boom_df order by start_month
    """)


def build_mart_tax_vs_chips(con: duckdb.DuckDBPyConnection) -> None:
    """Corporate tax vs the annual semiconductor export value index.

    Korean corporate tax is mostly paid in the year after profits are earned,
    so the chip yoy is also tested at lag 1. Correlations are descriptive only
    (small n, both series trend with the business cycle).
    """
    con.execute("""
        create or replace table mart_tax_vs_chips as
        with tax as (
            select year, corporate_tax_trn_won,
                   round((corporate_tax_trn_won / lag(corporate_tax_trn_won) over (order by year) - 1) * 100, 4)
                       as corporate_tax_yoy_pct
            from fact_kr_tax_year
        ),
        chips as (
            select year, value_idx as chip_value_idx, value_idx_yoy_pct as chip_value_yoy_pct,
                   lag(value_idx_yoy_pct) over (order by year) as chip_value_yoy_lag1_pct
            from fact_kr_trade_year where series = 'semiconductors'
        )
        select t.year, t.corporate_tax_trn_won, t.corporate_tax_yoy_pct,
               c.chip_value_idx, c.chip_value_yoy_pct, c.chip_value_yoy_lag1_pct
        from tax t join chips c using (year)
        order by year
    """)
    d = con.execute("select * from mart_tax_vs_chips").fetchdf()
    rows = []
    for lag, col in [(0, "chip_value_yoy_pct"), (1, "chip_value_yoy_lag1_pct")]:
        s = d.dropna(subset=["corporate_tax_yoy_pct", col])
        r = float(np.corrcoef(s["corporate_tax_yoy_pct"], s[col])[0, 1]) if len(s) > 2 else None
        rows.append({
            "relationship": f"corp_tax_yoy_vs_chip_yoy_lag{lag}",
            "lag": lag,
            "pearson_r": round(r, 4) if r is not None else None,
            "n": len(s),
            "first_year": int(s["year"].min()),
            "last_year": int(s["year"].max()),
        })
    con.register("corr_df", pd.DataFrame(rows))
    con.execute("create or replace table mart_tax_chip_correlation as select * from corr_df")


def build_mart_peer_snapshot(con: duckdb.DuckDBPyConnection) -> None:
    """One row per country: each indicator in 2000 and at its latest year."""
    wb = con.execute("select * from fact_indicators").fetchdf()
    cols = {
        "SP.DYN.TFRT.IN": "fertility_rate",
        "SP.POP.65UP.TO.ZS": "pop_65plus_pct",
        "SP.POP.1564.TO.ZS": "pop_working_pct",
        "SP.POP.1564.TO": "pop_working_count",
        "NY.GDP.MKTP.KD.ZG": "gdp_growth_pct",
        "GB.XPD.RSDV.GD.ZS": "rd_pct_gdp",
        "NE.EXP.GNFS.ZS": "export_pct_gdp",
    }
    names = {"KOR": "South Korea", "JPN": "Japan", "MYS": "Malaysia"}
    rows = []
    for iso3, name in names.items():
        row = {"iso3": iso3, "country_name": name}
        for code, c in cols.items():
            sub = wb[(wb.iso3 == iso3) & (wb.indicator_code == code)].sort_values("year")
            v2000 = sub.loc[sub.year == 2000, "value"]
            row[f"{c}_2000"] = float(v2000.iloc[0]) if len(v2000) else None
            row[f"{c}_latest"] = float(sub["value"].iloc[-1]) if len(sub) else None
            row[f"{c}_latest_year"] = int(sub["year"].iloc[-1]) if len(sub) else None
        rows.append(row)
    con.register("peer_df", pd.DataFrame(rows))
    con.execute("create or replace table mart_peer_snapshot as select * from peer_df order by iso3")


# -----------------------------------------------------------------------------
# Export
# -----------------------------------------------------------------------------
EXPORT_TABLES = [
    "dim_country", "fact_kr_trade_month", "fact_kr_trade_year", "fact_trade_year",
    "fact_kr_chip_usd_month", "check_chip_usd_annual",
    "fact_indicators", "fact_kr_tax_year", "mart_chip_episodes", "mart_boom_decomposition",
    "mart_tax_vs_chips", "mart_tax_chip_correlation", "mart_peer_snapshot", "budget_2027",
]


def export_warehouse(con: duckdb.DuckDBPyConnection) -> None:
    for tbl in EXPORT_TABLES:
        n = con.execute(f"select count(*) from {tbl}").fetchone()[0]
        for ext, opts in [("parquet", "(format parquet)"), ("csv", "(header, delimiter ',')")]:
            out = (PROCESSED_DIR / f"{tbl}.{ext}").as_posix()
            con.execute(f"copy (select * from {tbl} order by all) to '{out}' {opts}")
        print(f"[OK]   {tbl:<28} {n:>5} rows")


def build() -> None:
    t0 = time.perf_counter()
    print("=== Build warehouse ===")
    con = duckdb.connect(str(WAREHOUSE_PATH))
    load_ecos_raw(con)
    load_comtrade_raw(con)
    load_worldbank_raw(con)
    load_oecd_raw(con)
    stage_seed_budget(con)
    build_dimensions(con)
    build_fact_kr_trade(con)
    build_fact_trade_year(con)
    build_fact_kr_chip_usd_month(con)
    build_fact_indicators(con)
    build_fact_kr_tax_year(con)
    build_mart_chip_episodes(con)
    build_mart_boom_decomposition(con)
    build_mart_tax_vs_chips(con)
    build_mart_peer_snapshot(con)
    export_warehouse(con)
    con.close()
    print(f"[SUCCESS] built in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    build()
