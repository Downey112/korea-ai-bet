# Korea's AI Bet: Smart Move or Bigger Risk?

**Can a chip price boom pay for South Korea's answer to a shrinking workforce, or does it leave the budget exposed?**

South Korea has a fertility rate of 0.748, an elderly share above 20% and an estimated potential
growth rate of about 1.8%. For 2027 the government has proposed an 821.0 trillion won budget, with
21.3 trillion won for three AI and semiconductor megaprojects, up 97.2%. The plan leans on a projected
corporate tax take of 216.7 trillion won, about three times the 2024 actual. This project joins Bank
of Korea (ECOS) monthly export price and volume indices from 2000 to 2026 with OECD tax revenue, UN
Comtrade trade flows and World Bank indicators to test how solid that funding is.

Built with **Python**, **DuckDB** and **Power BI** (report in progress).

## What the data said

| The question | What the data said | Where |
|---|---|---|
| What pressure is Korea under? | Fertility fell to **0.748** in 2024. People aged 65 and over rose from **7.1%** of the population in 2000 to **20.3%** in 2025. GDP grew **1.0%** in 2025, against an estimated potential growth rate of about **1.8%**. Korea already spends **4.94%** of GDP on R&D (2023), against **3.44%** in Japan and **1.01%** in Malaysia. | [`mart_peer_snapshot.csv`](data/processed/mart_peer_snapshot.csv), [`context_facts.csv`](data/seed/context_facts.csv) |
| How big is the 2027 plan? | Spending of **821.0 trillion won** (+12.8%), including **21.3 trillion won** (+97.2%) for the three megaprojects: semiconductors, physical AI and AI data centres. A separate **2.6 trillion won** line is described as chip funding by one outlet and as physical AI demonstrations by another, so it is shown as unresolved. | [`budget_2027.csv`](data/seed/budget_2027.csv) |
| How is it paid for? | Tax revenue is projected to rise 40.7% to **584.4 trillion won**, with corporate tax at **216.7 trillion won**. Actual corporate tax in 2024 was **71.8 trillion won**. The budget is a proposal, with a National Assembly vote due in early December 2026. | [`budget_2027.csv`](data/seed/budget_2027.csv), [`fact_kr_tax_year.csv`](data/processed/fact_kr_tax_year.csv) |
| Is this chip boom like earlier ones? | No. From the February 2023 trough to September 2026, chip export value rose about tenfold (**+917%**), and higher prices account for **55%** of that rise in log terms. In every earlier upswing since 2001, volume did most of the work: price's share ranged from **-52% to +36%**. | [`mart_boom_decomposition.csv`](data/processed/mart_boom_decomposition.csv) |
| Why does that matter? | Prices can fall fast. In the 2001 downturn, chip export value fell **67.4%** from peak to trough, and prices fell **67.2%** while volume barely moved (**-0.8%**). | [`mart_chip_episodes.csv`](data/processed/mart_chip_episodes.csv) |
| How exposed are exports and tax? | Chips were an estimated **41.8%** of Korean exports in September 2026, up from **21.9%** in October 2025 (press reports give 48% on a wider definition). Corporate tax growth tracks the previous year's chip export growth (**r = 0.50**, n = 23) far more than the same year's (**r = 0.12**, n = 24). After the 2023 chip slump, corporate tax fell from **116.3 trillion won** in 2022 to **71.8 trillion won** in 2024. | [`fact_kr_chip_usd_month.csv`](data/processed/fact_kr_chip_usd_month.csv), [`mart_tax_chip_correlation.csv`](data/processed/mart_tax_chip_correlation.csv), [`mart_tax_vs_chips.csv`](data/processed/mart_tax_vs_chips.csv) |
| What does it mean for Malaysia? | By the same HS 8542 definition, chips were **23.3%** of Malaysia's exports in 2024, against **17.6%** for Korea. Malaysia is more concentrated in chips but spends **1.01%** of GDP on R&D, against Korea's **4.94%**. Malaysia's 2025 Comtrade row is excluded because it does not match DOSM. | [`fact_trade_year.csv`](data/processed/fact_trade_year.csv), [`mart_peer_snapshot.csv`](data/processed/mart_peer_snapshot.csv), [`exclusions.csv`](data/seed/exclusions.csv) |

The tax line is the one I would take to a budget meeting. A chip downturn reaches the government
twice: first through exports, then a year later through corporate tax. Corporate tax was 116.3
trillion won in 2022 and 71.8 trillion won in 2024, one year after the 2023 slump. The 2027 plan
needs 216.7 trillion won, and this boom is the first in the data that rests mainly on prices. That
does not make the plan wrong, but it does mean it depends on chip prices holding.

## How the comparison is made

1. **Price and volume are on the same basis.** ECOS publishes the export price index in won, US
   dollars and contract currency. Only the US dollar series (달러기준) is used, so that price times
   volume tracks the dollar value index. It does: the ratio stays between 0.93 and 1.05 every month.
2. **Booms and downturns are split into price and volume** with log changes, where
   `dlog(value) ≈ dlog(price) + dlog(volume)`. A downturn starts when the 3-month average of
   year-on-year growth in chip export value turns negative and must last at least 6 months. Six
   downturns qualify, starting in 2001, 2008, 2011, 2015, 2019 and 2022.
3. **Monthly chip dollars are estimated.** ECOS gives an index for semiconductors (반도체) but no dollar
   level, so the index is anchored to Korea's 2020 Comtrade HS 8542 exports (US$82.9 billion). The
   annual sums stay within 5% of Comtrade in every year from 2011 to 2025.
4. **Tax is compared with the year before.** Korean corporate tax is mostly paid the year after the
   profit is earned, so OECD corporate tax is compared with chip exports in the same year and in the
   previous year.
5. **Countries are compared on one definition.** Korea, Japan and Malaysia all use Comtrade HS 8542.
   Rows that fail a cross-check are kept, flagged and explained in
   [`exclusions.csv`](data/seed/exclusions.csv) instead of being silently dropped.

## What this can and cannot tell you

- **Data cannot prove motives.** It shows the pressures and the money, not why the government chose
  this plan or whether something else would work better. The government's own stated aim is to raise
  potential growth.
- **The budget is a proposal.** The 821.0 trillion won plan and the 216.7 trillion won tax projection
  were submitted on 3 September 2026 and can change before the National Assembly vote.
- **Monthly chip dollars are estimates.** ECOS 반도체 and HS 8542 are not the same basket. The annual
  totals agree within 5%, but a single month can be off by more.
- **The tax correlations are descriptive.** Twenty-three years is a small sample, and both series move
  with the wider economy. Tax law changes are not controlled for.
- **The downturn rule is a choice.** A different smoothing window would move start and end dates by a
  few months.
- **Export share is not value added.** Malaysia's chip exports can include assembly, testing and
  re-exports, so a 23.3% share does not mean the same domestic income as Korea's.
- **No account is needed.** The public ECOS `sample` key works but returns 10 rows per call, so a clean
  run takes a few minutes. A free ECOS key makes it faster.

## The report

The Power BI report is in progress. It will have four pages:

| Page | Question |
|---|---|
| The pressure | How Korea's ageing and growth compare with Japan and Malaysia |
| The boom | How this boom splits into price and volume, against every cycle since 2000 |
| The exposure | How corporate tax follows chips, and the gap the 2027 plan has to close |
| Malaysia | How concentrated Malaysia is in chips, and what Korea's playbook would need here |

## Run it

Needs Python 3.13.

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
run_pipeline.bat
```

For faster ECOS downloads, set a free key first: `set ECOS_API_KEY=your_key`.

The pipeline downloads ECOS, Comtrade, World Bank and OECD data, builds `data/warehouse.duckdb`,
writes the tables in `data/processed/` as CSV and parquet, and runs 16 validation checks.

## Repository

```text
data/raw/        cached downloads (not committed; rebuilt by the pipeline)
data/seed/       hand-sourced budget figures, context facts and exclusions, each with its source
data/processed/  fact tables and marts, CSV and parquet
scripts/         01_ingest.py, 02_build_warehouse.py, 03_validate.py
powerbi/         Power BI project (in progress)
```

## Sources

- Bank of Korea, ECOS: export value, volume and price indices (all goods, 반도체), customs exports.
- UN Comtrade: HS 8542 and total exports for Korea, Japan and Malaysia.
- OECD Revenue Statistics: Korea corporate income tax (1200) and total tax revenue.
- World Bank, World Development Indicators: fertility, age structure, GDP growth, R&D, exports.
- DOSM, via the sibling project `dosm_trade_engine`: Malaysian exports used to check Comtrade.
- Budget figures: [The Korea Times](https://www.koreatimes.co.kr/economy/policy/20260901/govt-bets-big-on-ai-chips-for-2027-budget-to-compete-in-global-tech-race) and [The Star](https://www.thestar.com.my/tech/tech-news/2026/09/01/south-korea-proposes-record-597-billion-2027-budget-to-supercharge-ai-investment), 1 September 2026.
- Potential growth: [The Korea Times](https://www.koreatimes.co.kr/economy/20251209/koreas-potential-growth-rate-could-fall-to-0-range-by-2040s-bok-chief), 9 December 2025.
