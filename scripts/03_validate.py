"""scripts/03_validate.py

Data checks for "Korea's AI bet". Prints a pass/fail table and exits 1 on any failure.
"""

import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
results = []


def check(name: str, passed: bool, observed: str) -> None:
    results.append((name, bool(passed), observed))


def read(name: str) -> pd.DataFrame:
    return pd.read_parquet(PROCESSED_DIR / f"{name}.parquet")


def main() -> None:
    month = read("fact_kr_trade_month")
    year = read("fact_kr_trade_year")
    trade = read("fact_trade_year")
    ind = read("fact_indicators")
    tax = read("fact_kr_tax_year")
    ep = read("mart_chip_episodes")
    boom = read("mart_boom_decomposition")
    txc = read("mart_tax_vs_chips")
    peer = read("mart_peer_snapshot")
    budget = read("budget_2027")

    # 1. Unique keys
    keys = [
        ("dim_country", read("dim_country"), ["iso3"]),
        ("fact_kr_trade_month", month, ["month", "series"]),
        ("fact_kr_trade_year", year, ["year", "series"]),
        ("fact_trade_year", trade, ["iso3", "year"]),
        ("fact_indicators", ind, ["iso3", "year", "indicator_code"]),
        ("fact_kr_tax_year", tax, ["year"]),
        ("mart_chip_episodes", ep, ["start_month"]),
        ("mart_tax_vs_chips", txc, ["year"]),
        ("mart_peer_snapshot", peer, ["iso3"]),
    ]
    dups = [f"{n}:{d.duplicated(subset=k).sum()}" for n, d, k in keys if d.duplicated(subset=k).any()]
    check("No duplicate keys", not dups, "; ".join(dups) or "0 duplicates")

    # 2. Monthly coverage, no gaps from 2000-01
    obs = []
    ok = True
    for s in ["all_goods", "semiconductors"]:
        m = pd.to_datetime(month.loc[month.series == s, "month"])
        exp = pd.date_range("2000-01-01", m.max(), freq="MS")
        missing = len(set(exp) - set(m))
        ok &= m.min() == pd.Timestamp("2000-01-01") and missing == 0
        obs.append(f"{s} 2000-01..{m.max():%Y-%m}, {missing} missing")
    check("Monthly coverage", ok, "; ".join(obs))

    # 3. All three indices present and positive
    idx = month[["value_idx", "volume_idx", "price_idx"]]
    check("Indices present and > 0", idx.notna().all().all() and (idx > 0).all().all(),
          f"min {idx.min().min():.2f}, nulls {int(idx.isna().sum().sum())}")

    # 4. 2020 mean of each monthly index ~ 100
    m20 = month[pd.to_datetime(month.month).dt.year == 2020].groupby("series")[
        ["value_idx", "volume_idx", "price_idx"]].mean()
    dev = (m20 - 100).abs().max().max()
    check("2020 base year mean ~100 (±1.0)", dev <= 1.0, f"max deviation {dev:.3f}")

    # 5. Implied (price x volume) vs published value index
    r = pd.concat([month.implied_actual_ratio, year.implied_actual_ratio])
    check("Implied/actual value ratio in [0.85, 1.15]", r.between(0.85, 1.15).all(),
          f"range [{r.min():.3f}, {r.max():.3f}]")

    # 6. Comtrade benchmark (verified by hand 2026-11-03)
    k24 = trade[(trade.iso3 == "KOR") & (trade.year == 2024)]
    v = float(k24.chip_exports_usd_bn.iloc[0]) if len(k24) else float("nan")
    check("Comtrade KOR 2024 HS8542 = 120.189bn ±0.5%", abs(v / 120.189285 - 1) <= 0.005, f"{v:.3f} bn")

    # 7. OECD benchmark (verified by hand 2026-11-03)
    t22 = tax.loc[tax.year == 2022, "corporate_tax_trn_won"]
    v = float(t22.iloc[0]) if len(t22) else float("nan")
    check("OECD KOR 2022 corporate tax = 116.267 trn", abs(v - 116.267) < 0.01, f"{v:.3f} trn won")

    # 7b. Index-anchored monthly chip dollars agree with Comtrade
    cu = read("check_chip_usd_annual")
    recent = cu[cu.year >= 2011]
    check("Chip USD estimate within 5% of Comtrade (2011+)", recent.ratio.between(0.95, 1.05).all(),
          f"ratio [{recent.ratio.min():.3f}, {recent.ratio.max():.3f}], n={len(recent)}")
    mys25 = trade[(trade.iso3 == "MYS") & (trade.year == 2025)]
    check("MYS 2025 Comtrade row flagged", len(mys25) == 1 and bool(mys25.is_excluded.iloc[0]),
          "excluded via data/seed/exclusions.csv")

    # 7c. No unflagged one-year spike: chip value moves >50% into a year and >50% out of it
    t = trade.sort_values(["iso3", "year"]).copy()
    prev = t.groupby("iso3").chip_exports_usd_bn.shift(1)
    nxt = t.groupby("iso3").chip_exports_usd_bn.shift(-1)
    spike = ((t.chip_exports_usd_bn / prev - 1).abs() > 0.5) & ((nxt / t.chip_exports_usd_bn - 1).abs() > 0.5)
    bad = t[spike & ~t.is_excluded]
    check("No unflagged one-year chip spikes", bad.empty,
          ", ".join(f"{r.iso3} {r.year}" for r in bad.itertuples()) or
          f"{int((spike & t.is_excluded).sum())} spike(s), all flagged")

    # 8. Chip share bounded
    s = trade.chip_share_pct
    check("Chip share in (0, 100)", ((s > 0) & (s < 100)).all(), f"[{s.min():.2f}, {s.max():.2f}]")

    # 9. Each country has Comtrade years
    yrs = trade.groupby("iso3").year.agg(["min", "max", "count"])
    check("Comtrade has KOR, JPN, MYS", set(yrs.index) == {"KOR", "JPN", "MYS"},
          "; ".join(f"{i} {r['min']}-{r['max']} n={r['count']}" for i, r in yrs.iterrows()))

    # 10. Episodes: >= 6 months, shares add to 100, a drop is a drop
    check("Episodes >= 6 months", len(ep) > 0 and (ep.months >= 6).all(),
          f"{len(ep)} episodes, min {ep.months.min() if len(ep) else 0}")
    check("Episode shares add to 100",
          ((ep.price_share_pct + ep.volume_share_pct - 100).abs() < 0.05).all(), "price + volume = 100")
    check("Episode drops are negative", (ep.drop_pct < 0).all(), f"max {ep.drop_pct.max():.2f}%")

    # 11. Boom decomposition: price + volume log-changes close to the value log-change
    gap = (boom.dlog_price + boom.dlog_volume - boom.dlog_value).abs()
    check("Boom dlog(p)+dlog(v) ~ dlog(value) (±0.15)", (gap <= 0.15).all(), f"max gap {gap.max():.3f}")

    # 12. Seed table loaded with sources
    check("Budget seed has sources", len(budget) > 0 and budget.source_url.notna().all(), f"{len(budget)} rows")

    print(f"\n{'STATUS':<6} | {'CHECK':<46} | OBSERVED")
    print("-" * 110)
    for name, passed, observed in results:
        print(f"{'PASS' if passed else 'FAIL':<6} | {name:<46} | {observed}")
    fails = sum(not p for _, p, _ in results)
    print("-" * 110)
    if fails:
        print(f"[FATAL] {fails} check(s) failed")
        sys.exit(1)
    print(f"[SUCCESS] all {len(results)} checks passed")


if __name__ == "__main__":
    main()
