"""Generate the Power BI Project (TMDL model and PBIR report) for Korea's AI bet.

Run after the pipeline. Rewrites only the three KoreaAIBet paths under powerbi/.
Infrastructure (TMDL tables from parquet schemas, Page helpers, theme) follows the
sibling project malaysia-affordability-atlas/scripts/05_build_report.py.
"""
import json
import shutil
import uuid
from pathlib import Path

import pyarrow.parquet as pq

NAME = "KoreaAIBet"
MT = "BetMeasures"
ROOT = Path(__file__).resolve().parent.parent
PBI = ROOT / "powerbi"
PROCESSED_DIR = ROOT / "data" / "processed"
NS = uuid.UUID("7a5e3f1c-8b2d-4e9a-9f0e-3c5b7a1d9e2f")
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"

INK = "#1B2430"
PAPER = "#F7F5F0"
NAVY = "#1F3A5F"   # Korea
RED = "#C0392B"    # price, risk
SAND = "#D9A441"   # Malaysia
SLATE = "#6B7785"  # Japan, muted
LINE = "#E4DED3"
SOFT = "#C9D3DF"
SERIES = [NAVY, RED, SAND, SLATE, INK, SOFT]
COUNTRY_COLOURS = {"South Korea": NAVY, "Japan": SLATE, "Malaysia": SAND}

PCT = "0.0\\%"
PCT2 = "0.00\\%"
SIGNED = "+0.0\\%;-0.0\\%;0.0\\%"
TRN = "#,0.0"
IDX = "#,0"
R2 = "0.00"
TIMES = "0.0\\x"

TABLES = [
    "dim_country", "fact_indicators", "fact_kr_trade_month", "fact_kr_trade_year", "fact_trade_year",
    "fact_kr_chip_usd_month", "fact_kr_tax_year", "mart_chip_episodes", "mart_boom_decomposition",
    "mart_tax_vs_chips", "mart_tax_chip_correlation", "mart_peer_snapshot", "budget_2027",
]

FACT_KEY_COLS = {
    "fact_indicators": {"iso3"},
    "fact_trade_year": {"iso3"},
    "mart_peer_snapshot": {"iso3"},
}

COLUMN_FORMATS = {
    **{("mart_chip_episodes", c): SIGNED for c in
       ("drop_pct", "price_change_pct", "volume_change_pct", "all_goods_drop_pct")},
    **{("mart_chip_episodes", c): PCT for c in ("price_share_pct", "volume_share_pct")},
    **{("mart_boom_decomposition", c): SIGNED for c in
       ("value_change_pct", "price_change_pct", "volume_change_pct")},
    ("mart_boom_decomposition", "price_share_pct"): PCT,
    ("fact_kr_tax_year", "corporate_tax_trn_won"): TRN,
    ("fact_kr_tax_year", "total_tax_trn_won"): TRN,
    ("fact_kr_tax_year", "corp_share_pct"): PCT,
    ("fact_trade_year", "chip_share_pct"): PCT,
    ("budget_2027", "amount_trn_won"): TRN,
    ("budget_2027", "change_pct"): SIGNED,
}

SORT_BY = {
    ("mart_boom_decomposition", "boom_label"): "start_month",
}


def tag(*parts):
    return str(uuid.uuid5(NS, "/".join(str(p) for p in parts)))


def q(name):
    return name if name.isidentifier() else f"'{name}'"


def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def s(text):
    return lit("'" + str(text).replace("'", "''") + "'")


def color(hexv):
    return {"solid": {"color": lit(f"'{hexv}'")}}


def measure_ref(prop, entity=MT):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def col_ref(entity, prop):
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def proj(entity, prop, display=None, measure=False, active=None):
    p = {"field": measure_ref(prop, entity) if measure else col_ref(entity, prop),
         "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}
    if display:
        p["displayName"] = display
    if active:
        p["active"] = True
    return p


def M(prop, display=None):
    return proj(MT, prop, display, measure=True)


def C(entity, prop, display=None, active=None):
    return proj(entity, prop, display, active=active)


def padding(t, b, l, r):
    return [{"properties": {"top": lit(f"{t}D"), "bottom": lit(f"{b}D"), "left": lit(f"{l}D"), "right": lit(f"{r}D")}}]


def map_type(arrow_type):
    t = arrow_type.lower()
    if t.startswith("int"):
        return "int64", "Int64.Type", False
    if t in ("double", "float"):
        return "double", "type number", False
    if t == "bool":
        return "boolean", "type logical", False
    if t.startswith("date") or t.startswith("timestamp"):
        return "dateTime", "type date", True
    return "string", "type text", False


def read_schema(table):
    schema = pq.read_schema(PROCESSED_DIR / f"{table}.parquet")
    return [(f.name, *map_type(str(f.type))) for f in schema]


def tmdl_parquet_table(name):
    cols = read_schema(name)
    out = [f"table {name}", f"\tlineageTag: {tag(name)}", ""]
    hidden = FACT_KEY_COLS.get(name, set())
    for c, tmdl_type, _, is_date in cols:
        out += [f"\tcolumn {q(c)}", f"\t\tdataType: {tmdl_type}"]
        if c in hidden:
            out.append("\t\tisHidden")
        if is_date:
            out.append("\t\tformatString: mmm yyyy")
        elif (name, c) in COLUMN_FORMATS:
            out.append(f"\t\tformatString: {COLUMN_FORMATS[(name, c)]}")
        out += [f"\t\tlineageTag: {tag(name, c)}", "\t\tsummarizeBy: none", f"\t\tsourceColumn: {c}"]
        if (name, c) in SORT_BY:
            out.append(f"\t\tsortByColumn: {SORT_BY[(name, c)]}")
        if is_date:
            out += ["", "\t\tannotation UnderlyingDateTimeDataType = Date"]
        out.append("")
    selected = ", ".join(f'"{c[0]}"' for c in cols)
    typed = ",\n".join(f'\t\t\t\t        {{"{c[0]}", {c[2]}}}' for c in cols)
    out += [
        f"\tpartition {name} = m", "\t\tmode: import", "\t\tsource =", "\t\t\t\tlet",
        f'\t\t\t\t    Source = Parquet.Document(File.Contents(ProcessedFolder & "\\{name}.parquet")),',
        f'\t\t\t\t    #"Selected" = Table.SelectColumns(Source, {{{selected}}}),',
        '\t\t\t\t    #"Typed" = Table.TransformColumnTypes(#"Selected", {',
        typed, "\t\t\t\t    })", "\t\t\t\tin", '\t\t\t\t    #"Typed"', "",
    ]
    return "\n".join(out)


def measure_lines(name, expr, fmt=None, folder=None):
    lines = expr.strip().splitlines()
    if len(lines) == 1:
        out = [f"\tmeasure {q(name)} = {lines[0]}"]
    else:
        out = [f"\tmeasure {q(name)} ="] + [f"\t\t\t{ln}" for ln in lines]
    if fmt:
        out.append(f"\t\tformatString: {fmt}")
    if folder:
        out.append(f"\t\tdisplayFolder: {folder}")
    out += [f"\t\tlineageTag: {tag(MT, 'm', name)}", ""]
    return out


def indicator(code):
    return f'CALCULATE ( AVERAGE ( fact_indicators[value] ), fact_indicators[indicator_code] = "{code}" )'


def peer(col, iso3):
    return f'CALCULATE ( AVERAGE ( mart_peer_snapshot[{col}] ), mart_peer_snapshot[iso3] = "{iso3}" )'


def peer_year(col, iso3, suffix):
    return (f'VAR yr = CALCULATE ( MAX ( mart_peer_snapshot[{col}_year] ), mart_peer_snapshot[iso3] = "{iso3}" )\n'
            f'RETURN yr & "{suffix}"')


def chips(col):
    return f'CALCULATE ( AVERAGE ( fact_kr_trade_month[{col}] ), fact_kr_trade_month[series] = "semiconductors" )'


def current_boom(col):
    return f"CALCULATE ( AVERAGE ( mart_boom_decomposition[{col}] ), mart_boom_decomposition[is_current_boom] = TRUE () )"


def trade_share(iso3, year):
    return (f'CALCULATE ( AVERAGE ( fact_trade_year[chip_share_pct] ), '
            f'fact_trade_year[iso3] = "{iso3}", fact_trade_year[year] = {year} )')


LATEST_MONTH = "VAR latest_m = CALCULATE ( MAX ( fact_kr_chip_usd_month[month] ), REMOVEFILTERS ( fact_kr_chip_usd_month ) )"
PROJ27 = 'VAR proj27 = CALCULATE ( SUM ( budget_2027[amount_trn_won] ), budget_2027[item] = "Corporate tax 2027 (projected)" )'
ACT24 = "VAR act24 = CALCULATE ( SUM ( fact_kr_tax_year[corporate_tax_trn_won] ), fact_kr_tax_year[year] = 2024 )"

P1, P2, P3, P4 = "1 Pressure", "2 Boom", "3 Exposure", "4 Malaysia"
MEASURES = [
    ("Aged 65+ %", indicator("SP.POP.65UP.TO.ZS"), PCT, P1),
    ("Fertility rate", indicator("SP.DYN.TFRT.IN"), R2, P1),
    ("GDP growth %", indicator("NY.GDP.MKTP.KD.ZG"), PCT, P1),
    ("R&D % GDP (latest)", "AVERAGE ( mart_peer_snapshot[rd_pct_gdp_latest] )", PCT2, P1),
    ("KR Fertility", peer("fertility_rate_latest", "KOR"), R2, P1),
    ("KR Fertility Label", peer_year("fertility_rate_latest", "KOR", ", births per woman"), None, P1),
    ("KR Aged 65+", peer("pop_65plus_pct_latest", "KOR"), PCT, P1),
    ("KR Aged 65+ Label", peer_year("pop_65plus_pct_latest", "KOR", ", share of population"), None, P1),
    # Bank of Korea estimate, The Korea Times 2025-12-09 (data/seed/context_facts.csv)
    ("KR Potential Growth", "1.8", PCT, P1),
    ("KR Potential Growth Label", '"Bank of Korea estimate, Dec 2025"', None, P1),
    ("KR R&D", peer("rd_pct_gdp_latest", "KOR"), PCT2, P1),
    ("KR R&D Label", peer_year("rd_pct_gdp_latest", "KOR", ", share of GDP"), None, P1),

    ("Chip value index", chips("value_idx"), IDX, P2),
    ("Chip price index", chips("price_idx"), IDX, P2),
    ("Chip volume index", chips("volume_idx"), IDX, P2),
    ("Boom price share %", "AVERAGE ( mart_boom_decomposition[price_share_pct] )", PCT, P2),
    ("Current Boom Value Change", current_boom("value_change_pct"), SIGNED, P2),
    ("Current Boom Period Label",
     "VAR s = CALCULATE ( MIN ( mart_boom_decomposition[start_month] ), mart_boom_decomposition[is_current_boom] = TRUE () )\n"
     "VAR e = CALCULATE ( MAX ( mart_boom_decomposition[end_month] ), mart_boom_decomposition[is_current_boom] = TRUE () )\n"
     'RETURN FORMAT ( s, "mmm yyyy" ) & " to " & FORMAT ( e, "mmm yyyy" )', None, P2),
    ("Current Boom Price Share", current_boom("price_share_pct"), PCT, P2),
    ("Current Boom Price Share Label", '"of the rise came from higher prices"', None, P2),
    ("Downturn 2001 Drop",
     "CALCULATE ( AVERAGE ( mart_chip_episodes[drop_pct] ), YEAR ( mart_chip_episodes[start_month] ) = 2001 )",
     SIGNED, P2),
    ("Downturn 2001 Label",
     "VAR p = CALCULATE ( AVERAGE ( mart_chip_episodes[price_change_pct] ), YEAR ( mart_chip_episodes[start_month] ) = 2001 )\n"
     "VAR v = CALCULATE ( AVERAGE ( mart_chip_episodes[volume_change_pct] ), YEAR ( mart_chip_episodes[start_month] ) = 2001 )\n"
     'RETURN "prices " & FORMAT ( p, "0.0" ) & "%, volume " & FORMAT ( v, "0.0" ) & "%"', None, P2),

    ("Chip share of exports % (est)", "AVERAGE ( fact_kr_chip_usd_month[chip_share_pct_est] )", PCT, P3),
    ("Latest Chip Share",
     LATEST_MONTH + "\nRETURN CALCULATE ( AVERAGE ( fact_kr_chip_usd_month[chip_share_pct_est] ), "
                    "fact_kr_chip_usd_month[month] = latest_m )", PCT, P3),
    ("Latest Chip Share Label",
     LATEST_MONTH + '\nRETURN FORMAT ( latest_m, "mmm yyyy" ) & ", estimated, HS 8542 basis"', None, P3),
    ("Tax Chip r Lag1",
     "CALCULATE ( AVERAGE ( mart_tax_chip_correlation[pearson_r] ), mart_tax_chip_correlation[lag] = 1 )", R2, P3),
    ("Tax Chip r Lag1 Label",
     "VAR n1 = CALCULATE ( MAX ( mart_tax_chip_correlation[n] ), mart_tax_chip_correlation[lag] = 1 )\n"
     "VAR r0 = CALCULATE ( AVERAGE ( mart_tax_chip_correlation[pearson_r] ), mart_tax_chip_correlation[lag] = 0 )\n"
     'RETURN "n = " & n1 & " years; same-year r = " & FORMAT ( r0, "0.00" )', None, P3),
    ("Corp Tax 2027 vs 2024", PROJ27 + "\n" + ACT24 + "\nRETURN DIVIDE ( proj27, act24 )", TIMES, P3),
    ("Corp Tax 2027 vs 2024 Label",
     PROJ27 + "\n" + ACT24 + '\nRETURN FORMAT ( proj27, "#,0.0" ) & " trn won projected vs " & FORMAT ( act24, "#,0.0" ) & " in 2024"',
     None, P3),
    ("Corporate tax (trn won)", "SUM ( fact_kr_tax_year[corporate_tax_trn_won] )", TRN, P3),
    ("Budget amount (trn won)", "SUM ( budget_2027[amount_trn_won] )", TRN, P3),

    ("Chip share % (Comtrade)",
     "CALCULATE ( AVERAGE ( fact_trade_year[chip_share_pct] ), fact_trade_year[is_excluded] = FALSE () )", PCT, P4),
    ("MY Chip Share 2024", trade_share("MYS", 2024), PCT, P4),
    ("KR Chip Share 2024", trade_share("KOR", 2024), PCT, P4),
    ("Comtrade 2024 Label", '"2024, UN Comtrade HS 8542"', None, P4),
    ("MY R&D", peer("rd_pct_gdp_latest", "MYS"), PCT2, P4),
    ("MY R&D Label",
     'VAR yr = CALCULATE ( MAX ( mart_peer_snapshot[rd_pct_gdp_latest_year] ), mart_peer_snapshot[iso3] = "MYS" )\n'
     'VAR kr = CALCULATE ( AVERAGE ( mart_peer_snapshot[rd_pct_gdp_latest] ), mart_peer_snapshot[iso3] = "KOR" )\n'
     'RETURN yr & ", share of GDP (Korea " & FORMAT ( kr, "0.00" ) & "%)"', None, P4),
]


def tmdl_measures_table():
    out = [f"table {MT}", f"\tlineageTag: {tag(MT)}", ""]
    for m in MEASURES:
        out += measure_lines(*m)
    out += [
        "\tcolumn Value", "\t\tdataType: int64", "\t\tisHidden", "\t\tformatString: 0",
        f"\t\tlineageTag: {tag(MT, 'Value')}", "\t\tsummarizeBy: none", "\t\tisNameInferred",
        "\t\tsourceColumn: [Value]", "",
        f"\tpartition {MT} = calculated", "\t\tmode: import", "\t\tsource = {0}", "",
    ]
    return "\n".join(out)


def tmdl_relationships():
    out = []
    for table in ("fact_indicators", "fact_trade_year", "mart_peer_snapshot"):
        out += [f"relationship {tag('rel', table, 'iso3')}",
                f"\tfromColumn: {table}.iso3", "\ttoColumn: dim_country.iso3", ""]
    return "\n".join(out)


def platform_json(kind):
    return json.dumps({
        "$schema": f"{SCHEMA}/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": kind, "displayName": NAME},
        "config": {"version": "2.0", "logicalId": tag("platform", kind)}}, indent=2)


def model_files():
    all_tables = TABLES + [MT]
    escaped_dir = str(PROCESSED_DIR.resolve()).replace("\\", "\\\\")
    files = {
        ".platform": platform_json("SemanticModel"),
        "definition.pbism": json.dumps({
            "$schema": f"{SCHEMA}/item/semanticModel/definitionProperties/1.0.0/schema.json",
            "version": "4.2", "settings": {}}, indent=2),
        "definition/database.tmdl": "database\n\tcompatibilityLevel: 1567\n",
        "definition/cultures/en-US.tmdl": (
            'cultureInfo en-US\n\n\tlinguisticMetadata =\n\t\t\t{\n\t\t\t  "Version": "2.0.0",\n'
            '\t\t\t  "Language": "en-US"\n\t\t\t}\n\t\tcontentType: json\n'),
        "definition/model.tmdl": "\n".join([
            "model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
            "\tsourceQueryCulture: en-US", "\tdataAccessOptions", "\t\tlegacyRedirects",
            "\t\treturnErrorValuesAsNull", "",
            "annotation __PBI_TimeIntelligenceEnabled = 0", "",
            f"annotation PBI_QueryOrder = {json.dumps(['ProcessedFolder'] + TABLES)}", "",
            'annotation PBI_ProTooling = ["DevMode"]', "",
            *[f"ref table {t}" for t in all_tables], "", "ref cultureInfo en-US", ""]),
        "definition/expressions.tmdl": (
            f'expression ProcessedFolder = "{escaped_dir}" meta [IsParameterQuery=true, Type="Text", '
            f'IsParameterQueryRequired=true]\n\tlineageTag: {tag("ProcessedFolder")}\n\n'
            "\tannotation PBI_ResultType = Text\n"),
        "definition/relationships.tmdl": tmdl_relationships(),
        f"definition/tables/{MT}.tmdl": tmdl_measures_table(),
    }
    for name in TABLES:
        files[f"definition/tables/{name}.tmdl"] = tmdl_parquet_table(name)
    return files


def series_fill(entity, prop, value, hexv):
    return {"properties": {"fill": color(hexv)}, "selector": {"data": [{"scopeId": {"Comparison": {
        "ComparisonKind": 0,
        "Left": {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}},
        "Right": {"Literal": {"Value": f"'{value}'"}}}}}]}}


class Page:
    def __init__(self, name, display, height=900):
        self.name, self.display, self.height, self.visuals, self.z = name, display, height, {}, 1000

    def add(self, name, pos, visual, title=None, subtitle=None, alt=None, background=True, pad=None):
        x, y, w, h = pos
        self.z += 1000
        vco = {
            "title": [{"properties": {"show": lit("true" if title else "false")}}],
            "background": [{"properties": {"show": lit("true" if background else "false")}}],
        }
        if title:
            vco["title"][0]["properties"]["text"] = s(title)
        if subtitle:
            vco["subTitle"] = [{"properties": {"show": lit("true"), "text": s(subtitle)}}]
        if alt:
            vco["general"] = [{"properties": {"altText": s(alt)}}]
        if pad:
            vco["padding"] = padding(*pad)
        self.visuals[name] = {
            "$schema": f"{SCHEMA}/item/report/definition/visualContainer/2.3.0/schema.json",
            "name": name, "position": {"x": x, "y": y, "z": self.z, "height": h, "width": w, "tabOrder": self.z},
            "visual": {**visual, "visualContainerObjects": vco, "drillFilterOtherVisuals": True},
        }

    def text(self, name, pos, paragraphs, background=False, alt=None):
        runs = [{"textRuns": [{"value": v, "textStyle": {"fontFamily": f, "fontSize": sz, "color": c}}]}
                for v, f, sz, c in paragraphs]
        self.add(name, pos, {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": runs}}]}},
                 background=background, pad=(0, 0, 0, 0) if not background else (12, 12, 16, 16), alt=alt)

    def header(self, title, subtitle, number):
        self.text("header", (32, 20, 900, 116), [
            (f"KOREA'S AI BET  ·  {number} OF 4", "Segoe UI Semibold", "8.5pt", NAVY),
            (title, "Georgia", "22pt", INK),
            (subtitle, "Segoe UI", "10.5pt", INK),
        ], alt=f"{title} {subtitle}")

    def kpi(self, key, pos, value_measure, label_measure, title, alt, accent):
        x, y, w, h = pos
        blank = {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": []}}]}}
        self.add(f"kpi_{key}_tile", pos, blank, background=True, pad=(0, 0, 0, 0), alt=f"Background for {title}")
        self.add(f"kpi_{key}_accent", (x, y, 8, h), json.loads(json.dumps(blank)),
                 background=True, pad=(0, 0, 0, 0), alt=f"Accent for {title}")
        self.visuals[f"kpi_{key}_accent"]["visual"]["visualContainerObjects"]["background"][0]["properties"]["color"] = color(accent)
        self.add(f"kpi_{key}_value", (x + 8, y, w - 8, 64),
                 {"visualType": "card", "query": {"queryState": {"Values": {"projections": [M(value_measure)]}}},
                  "objects": {"labels": [{"properties": {"fontSize": lit("20D"), "fontFamily": s("Georgia")}}],
                              "categoryLabels": [{"properties": {"show": lit("false")}}]}},
                 title=title, alt=alt, background=False, pad=(8, 0, 16, 16))
        props = self.visuals[f"kpi_{key}_value"]["visual"]["visualContainerObjects"]["title"][0]["properties"]
        props.update({"fontSize": lit("10D"), "fontColor": color(SLATE), "alignment": s("left")})
        self.add(f"kpi_{key}_label", (x + 8, y + 64, w - 8, h - 64),
                 {"visualType": "card", "query": {"queryState": {"Values": {"projections": [M(label_measure)]}}},
                  "objects": {"labels": [{"properties": {"fontSize": lit("9D"), "color": color(SLATE)}}],
                              "categoryLabels": [{"properties": {"show": lit("false")}}]}},
                 background=False, pad=(0, 0, 16, 16), alt=f"Note for {title}")

    def _bars(self, kind, name, pos, category, measure, title, subtitle, alt, sort, fill):
        v = {"visualType": kind, "query": {"queryState": {
            "Category": {"projections": [C(category[0], category[1], active=True)]},
            "Y": {"projections": [M(measure)]}}},
            "objects": {
                "dataPoint": [{"properties": {"fill": color(fill)}}],
                "categoryAxis": [{"properties": {"maxMarginFactor": lit("40L")}}],
                "labels": [{"properties": {"show": lit("true"), "labelPosition": s("OutsideEnd")}}]}}
        if sort:
            v["query"]["sortDefinition"] = {"sort": [{"field": sort[0], "direction": sort[1]}]}
        self.add(name, pos, v, title=title, subtitle=subtitle, alt=alt, pad=(8, 8, 16, 16))

    def bar(self, name, pos, category, measure, title, subtitle=None, alt=None, sort=None, fill=NAVY):
        self._bars("clusteredBarChart", name, pos, category, measure, title, subtitle, alt, sort, fill)

    def column(self, name, pos, category, measure, title, subtitle=None, alt=None, sort=None, fill=NAVY):
        self._bars("clusteredColumnChart", name, pos, category, measure, title, subtitle, alt, sort, fill)

    def line(self, name, pos, category, measures, title, subtitle=None, alt=None, series=None, colours=None,
             x_end=None):
        """Line chart. Either one measure split by a `series` column (colours: {value: hex}),
        or several measures (colours: list of hex in the same order). x_end caps a numeric
        category axis. (A valueAxis axisScale 'log' setting was tried and ignored by Desktop.)"""
        state = {
            "Category": {"projections": [C(category[0], category[1], active=True)]},
            "Y": {"projections": [M(m) for m in measures]},
        }
        objects = {}
        if series:
            state["Series"] = {"projections": [C(series[0], series[1], "Country")]}
            objects["dataPoint"] = [series_fill(series[0], series[1], v, c) for v, c in (colours or {}).items()]
        else:
            # A fill without a selector is ignored on line charts, so every measure gets a
            # metadata selector, including a single one.
            cols = [colours] if isinstance(colours, str) else (colours or SERIES)
            objects["dataPoint"] = [{"properties": {"fill": color(c)}, "selector": {"metadata": f"{MT}.{m}"}}
                                    for m, c in zip(measures, cols)]
        if series or len(measures) > 1:
            objects["legend"] = [{"properties": {"show": lit("true"), "position": s("Top")}}]
        if x_end is not None:
            objects["categoryAxis"] = [{"properties": {"end": lit(f"{x_end}D")}}]
        v = {"visualType": "lineChart", "query": {"queryState": state}, "objects": objects}
        self.add(name, pos, v, title=title, subtitle=subtitle, alt=alt, pad=(8, 8, 16, 16))

    def table(self, name, pos, projections, title, subtitle=None, alt=None, sort=None, widths=None):
        objects = {
            "total": [{"properties": {"totals": lit("false")}}],
            "columnHeaders": [{"properties": {"wordWrap": lit("true")}}],
        }
        if widths:
            objects["columnWidth"] = [
                {"properties": {"value": lit(f"{w}D")}, "selector": {"metadata": pr["queryRef"]}}
                for pr, w in zip(projections, widths)
            ]
        v = {"visualType": "tableEx", "query": {"queryState": {"Values": {"projections": projections}}}, "objects": objects}
        if sort:
            v["query"]["sortDefinition"] = {"sort": [{"field": sort[0], "direction": sort[1]}]}
        self.add(name, pos, v, title=title, subtitle=subtitle, alt=alt, pad=(8, 8, 16, 16))

    def footnote(self, pos, text):
        self.text("footnote", pos, [(text, "Segoe UI", "8.5pt", SLATE)], alt=f"Footnote: {text}")

    def files(self):
        bg = {"color": color(PAPER), "transparency": lit("0D")}
        out = {f"definition/pages/{self.name}/page.json": {
            "$schema": f"{SCHEMA}/item/report/definition/page/2.0.0/schema.json",
            "name": self.name, "displayName": self.display, "displayOption": "FitToWidth",
            "height": self.height, "width": 1280,
            "objects": {"background": [{"properties": bg}], "outspace": [{"properties": bg}]}}}
        for name, visual in self.visuals.items():
            out[f"definition/pages/{self.name}/visuals/{name}/visual.json"] = visual
        return out


KPI_Y, KPI_H, BODY_Y, FOOT = 144, 92, 252, (16, 852, 1248, 32)


def kpi_row(p, items):
    """Lay out 3 or 4 KPI tiles evenly across the page."""
    n, gap = len(items), 16
    w = (1248 - gap * (n - 1)) // n
    for i, (key, value, label, title, alt, accent) in enumerate(items):
        p.kpi(key, (16 + i * (w + gap), KPI_Y, w, KPI_H), value, label, title, alt, accent)


def page_pressure():
    p = Page("pressure", "1 Why bet on AI?")
    p.header("Why would Korea bet on AI?",
             "A shrinking, ageing workforce and slow growth, compared with Japan and Malaysia.", 1)
    kpi_row(p, [
        ("fertility", "KR Fertility", "KR Fertility Label", "Fertility rate, Korea",
         "Korea's fertility rate: 0.75 births per woman in 2024.", NAVY),
        ("aged65", "KR Aged 65+", "KR Aged 65+ Label", "Aged 65 and over, Korea",
         "People aged 65 and over: 20.3% of Korea's population in 2025.", RED),
        ("potential", "KR Potential Growth", "KR Potential Growth Label", "Potential growth, Korea",
         "Korea's potential growth rate: about 1.8%, Bank of Korea estimate, December 2025.", SLATE),
        ("rd", "KR R&D", "KR R&D Label", "R&D spending, Korea",
         "Korea's R&D spending: 4.94% of GDP in 2023.", NAVY),
    ])
    p.line("aged65_line", (16, BODY_Y, 408, 584), ("fact_indicators", "year"), ["Aged 65+ %"],
           "Aged 65 and over, % of population", "Korea is ageing fastest; Japan is further along",
           "Line chart of the share of people aged 65 and over, 2000 to 2025, for South Korea, Japan and Malaysia.",
           series=("dim_country", "name"), colours=COUNTRY_COLOURS)
    p.line("fertility_line", (436, BODY_Y, 408, 584), ("fact_indicators", "year"), ["Fertility rate"],
           "Fertility rate, births per woman", "Korea fell below 1 in 2018 and was 0.75 in 2024",
           "Line chart of fertility rates, 2000 to 2024, for South Korea, Japan and Malaysia.",
           series=("dim_country", "name"), colours=COUNTRY_COLOURS)
    p.bar("rd_bar", (856, BODY_Y, 408, 584), ("dim_country", "name"), "R&D % GDP (latest)",
          "R&D spending, % of GDP", "Latest year: 2023 for Korea and Japan, 2022 for Malaysia",
          "Bar chart of R&D spending as a share of GDP: Korea 4.94%, Japan 3.44%, Malaysia 1.01%.",
          sort=(measure_ref("R&D % GDP (latest)"), "Descending"))
    p.footnote(FOOT, "World Bank, World Development Indicators. Potential growth: Bank of Korea estimate reported by "
                     "The Korea Times, 9 Dec 2025.")
    return p


def page_boom():
    p = Page("boom", "2 The boom")
    p.header("This chip boom runs on prices",
             "Korea's chip exports since 2000: value, and how much came from price versus volume.", 2)
    kpi_row(p, [
        ("boom", "Current Boom Value Change", "Current Boom Period Label", "Chip export value, current boom",
         "Korea's chip export value rose 917% from February 2023 to September 2026.", NAVY),
        ("price", "Current Boom Price Share", "Current Boom Price Share Label", "Share from price, current boom",
         "55% of the current boom's rise came from higher prices, in log terms.", RED),
        ("bust", "Downturn 2001 Drop", "Downturn 2001 Label", "Chip export value, 2001 downturn",
         "In the 2001 downturn chip export value fell 67.4%: prices fell 67.2% and volume 0.8%.", RED),
    ])
    # Price and quantity sit on separate charts: the 2000 price index (~2,700) would
    # otherwise flatten everything else on a shared linear axis.
    p.line("value_line", (16, BODY_Y, 616, 300), ("fact_kr_trade_month", "month"),
           ["Chip value index", "Chip volume index"],
           "Chip exports: value and volume", "Index, 2020 = 100, monthly, US dollar basis (Bank of Korea ECOS)",
           "Line chart of Korea's semiconductor export value and volume indices, monthly from 2000 to September 2026.",
           colours=[NAVY, SLATE])
    p.line("price_line", (648, BODY_Y, 616, 300), ("fact_kr_trade_month", "month"), ["Chip price index"],
           "Chip export prices", "Index, 2020 = 100: prices fell for two decades, then more than tripled from Feb 2023",
           "Line chart of Korea's semiconductor export price index, monthly from 2000 to September 2026.",
           colours=RED)
    p.bar("share_bar", (16, 568, 520, 268), ("mart_boom_decomposition", "boom_label"), "Boom price share %",
          "Share of each upswing that came from price", "Below zero: prices fell while volume rose",
          "Bar chart of the price share of each chip export upswing; only the current boom is above 50%.",
          sort=(col_ref("mart_boom_decomposition", "boom_label"), "Ascending"), fill=RED)
    p.table("episode_table", (552, 568, 712, 268), [
        C("mart_chip_episodes", "start_month", "Downturn began"),
        C("mart_chip_episodes", "months", "Months"),
        C("mart_chip_episodes", "drop_pct", "Chip value"),
        C("mart_chip_episodes", "price_change_pct", "Price"),
        C("mart_chip_episodes", "volume_change_pct", "Volume"),
        C("mart_chip_episodes", "all_goods_drop_pct", "All exports"),
    ], "Every chip downturn since 2000", "Change from peak to trough",
        "Table of six chip export downturns with the change in value, price, volume and all exports.",
        sort=(col_ref("mart_chip_episodes", "start_month"), "Ascending"), widths=[140, 80, 110, 110, 110, 110])
    p.footnote(FOOT, "Bank of Korea ECOS 403Y001, 403Y002, 402Y014 (반도체). Downturn: 3-month mean of year-on-year "
                     "change below zero for 6+ months. Shares are log changes.")
    return p


def page_exposure():
    p = Page("exposure", "3 The exposure")
    p.header("A bust would hit the budget twice",
             "Chips now carry Korea's exports, and corporate tax follows them a year later.", 3)
    kpi_row(p, [
        ("share", "Latest Chip Share", "Latest Chip Share Label", "Chips in Korea's exports",
         "Chips were an estimated 41.8% of Korea's exports in September 2026.", RED),
        ("r", "Tax Chip r Lag1", "Tax Chip r Lag1 Label", "Corporate tax vs last year's chips, r",
         "Corporate tax growth and the previous year's chip export growth: r = 0.50 over 23 years.", NAVY),
        ("tax", "Corp Tax 2027 vs 2024", "Corp Tax 2027 vs 2024 Label", "Corporate tax the 2027 plan needs",
         "The 2027 plan projects 216.7 trillion won of corporate tax, 3.0 times the 71.8 trillion won of 2024.", RED),
    ])
    p.line("share_line", (16, BODY_Y, 616, 284), ("fact_kr_chip_usd_month", "month"),
           ["Chip share of exports % (est)"], "Chips as a share of Korea's exports",
           "Monthly estimate, HS 8542 basis", "Line chart of chips' estimated share of Korea's exports, monthly.",
           colours=RED)
    p.column("tax_column", (16, 552, 616, 284), ("fact_kr_tax_year", "year"), "Corporate tax (trn won)",
             "Corporate tax, trillion won", "OECD, 2000 to 2024",
             "Column chart of Korea's corporate tax revenue by year.",
             sort=(col_ref("fact_kr_tax_year", "year"), "Ascending"))
    p.bar("budget_bar", (648, BODY_Y, 616, 584), ("budget_2027", "label"), "Budget amount (trn won)",
          "The 2027 proposal, trillion won", "Spending lines and projected revenue",
          "Bar chart of 2027 budget proposal items in trillion won.",
          sort=(measure_ref("Budget amount (trn won)"), "Descending"))
    p.footnote(FOOT, "OECD Revenue Statistics (1200). 2027: proposal reported by The Star and The Korea Times, "
                     "1 Sep 2026; Assembly vote due early Dec 2026. Chip share: ECOS index anchored to Comtrade "
                     "HS 8542 2020, within 5% of Comtrade 2011-2025.")
    return p


def page_malaysia():
    p = Page("malaysia", "4 Malaysia")
    p.header("What it means for Malaysia",
             "Malaysia is more concentrated in chips than Korea, with a fifth of the research spending.", 4)
    kpi_row(p, [
        ("my_share", "MY Chip Share 2024", "Comtrade 2024 Label", "Chips in Malaysia's exports",
         "Chips were 23.3% of Malaysia's exports in 2024.", SAND),
        ("kr_share", "KR Chip Share 2024", "Comtrade 2024 Label", "Chips in Korea's exports",
         "Chips were 17.6% of Korea's exports in 2024.", NAVY),
        ("my_rd", "MY R&D", "MY R&D Label", "R&D spending, Malaysia",
         "Malaysia spends 1.01% of GDP on R&D (2022), against 4.94% in Korea (2023).", SAND),
    ])
    p.line("country_line", (16, BODY_Y, 656, 584), ("fact_trade_year", "year"), ["Chip share % (Comtrade)"],
           "Chips as a share of exports", "UN Comtrade HS 8542, 2000 to 2025; Malaysia 2008 and 2025 left out",
           "Line chart of chips' share of exports for Malaysia, South Korea and Japan, 2000 to 2025.",
           series=("dim_country", "name"), colours=COUNTRY_COLOURS, x_end=2025)
    body = ("Segoe UI", "10pt", INK)
    p.text("takeaways", (688, BODY_Y, 576, 584), [
        ("Korea's bet holds only while chip prices hold", "Segoe UI Semibold", "11.5pt", RED),
        ("This boom is the first since 2000 to rest mainly on prices. From September 2000 to July 2001, chip "
         "prices fell by two-thirds, and Korean corporate tax follows chips a year later.", *body),
        (" ", *body),
        ("Malaysia is more exposed on trade, less on tax", "Segoe UI Semibold", "11.5pt", SAND),
        ("Chips are a bigger share of Malaysia's exports than of Korea's. Gross export value is not value "
         "added, though: much of it can be assembly, testing and re-exports, so a bust would reach Malaysia "
         "more through orders and jobs than through tax.", *body),
        (" ", *body),
        ("Copying the budget would not copy the base", "Segoe UI Semibold", "11.5pt", NAVY),
        ("Korea spends 4.94% of GDP on research and Malaysia 1.01%. A Korea-style megaproject budget would "
         "land on a much smaller research base.", *body),
    ], background=True, alt="Three takeaways for Malaysia from Korea's chip bet.")
    p.footnote(FOOT, "UN Comtrade HS 8542. Malaysia 2008 and 2025 excluded: a classification break and a total that "
                     "does not match DOSM (data/seed/exclusions.csv).")
    return p


def report_theme():
    axis = {"labelColor": {"solid": {"color": SLATE}}, "fontSize": 9, "fontFamily": "Segoe UI", "showAxisTitle": False}
    return {
        "name": NAME, "dataColors": SERIES, "background": "#FFFFFF", "foreground": INK, "tableAccent": NAVY,
        "good": "#16A34A", "neutral": SLATE, "bad": RED,
        "textClasses": {
            "callout": {"fontSize": 26, "fontFace": "Segoe UI Semibold", "color": INK},
            "title": {"fontSize": 12, "fontFace": "Segoe UI Semibold", "color": INK},
            "header": {"fontSize": 10, "fontFace": "Segoe UI Semibold", "color": INK},
            "label": {"fontSize": 9, "fontFace": "Segoe UI", "color": SLATE},
        },
        "visualStyles": {
            "page": {"*": {"background": [{"color": {"solid": {"color": PAPER}}, "transparency": 0}],
                           "outspace": [{"color": {"solid": {"color": PAPER}}, "transparency": 0}]}},
            "*": {"*": {"background": [{"show": True, "color": {"solid": {"color": "#FFFFFF"}}, "transparency": 0}],
                        "border": [{"show": False, "radius": 6}], "dropShadow": [{"show": False}],
                        "padding": [{"top": 8, "bottom": 8, "left": 12, "right": 12}],
                        "title": [{"show": True, "fontColor": {"solid": {"color": INK}}, "fontSize": 11,
                                   "fontFamily": "Segoe UI Semibold", "alignment": "left"}],
                        "subTitle": [{"fontColor": {"solid": {"color": SLATE}}, "fontSize": 8.5}]}},
            "card": {"*": {"labels": [{"color": {"solid": {"color": INK}}, "fontSize": 24, "fontFamily": "Segoe UI Semibold"}],
                           "categoryLabels": [{"show": False}]}},
            "clusteredBarChart": {"*": {"categoryAxis": [axis], "valueAxis": [{**axis, "show": False}],
                                        "labels": [{"show": True, "color": {"solid": {"color": INK}}, "fontSize": 8.5}]}},
            "clusteredColumnChart": {"*": {"categoryAxis": [axis], "valueAxis": [{**axis, "show": False}],
                                           "labels": [{"show": True, "color": {"solid": {"color": INK}}, "fontSize": 8}]}},
            "lineChart": {"*": {"categoryAxis": [axis], "valueAxis": [{**axis, "show": True}]}},
            "tableEx": {"*": {"grid": [{"gridHorizontal": True, "gridHorizontalColor": {"solid": {"color": LINE}},
                                        "gridVertical": False, "rowPadding": 2}],
                              "columnHeaders": [{"fontColor": {"solid": {"color": SLATE}}, "fontSize": 9,
                                                 "backColor": {"solid": {"color": "#FFFFFF"}}}],
                              "values": [{"fontSize": 9, "fontColorPrimary": {"solid": {"color": INK}},
                                          "backColorPrimary": {"solid": {"color": "#FFFFFF"}},
                                          "backColorSecondary": {"solid": {"color": "#FFFFFF"}}}]}},
        },
    }


def report_files():
    pages = [page_pressure(), page_boom(), page_exposure(), page_malaysia()]
    files = {
        ".platform": platform_json("Report"),
        "definition.pbir": {
            "$schema": f"{SCHEMA}/item/report/definitionProperties/2.0.0/schema.json",
            "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}},
        },
        "definition/version.json": {
            "$schema": f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0",
        },
        "definition/report.json": {
            "$schema": f"{SCHEMA}/item/report/definition/report/3.0.0/schema.json",
            "themeCollection": {"customTheme": {"name": f"{NAME}.json", "reportVersionAtImport": {
                "visual": "2.3.0", "report": "3.0.0", "page": "2.0.0"}, "type": "RegisteredResources"}},
            "objects": {"outspacePane": [{"properties": {"expanded": lit("false")}}]},
            "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources", "items": [
                {"name": f"{NAME}.json", "path": f"{NAME}.json", "type": "CustomTheme"}]}],
            "settings": {"useEnhancedTooltips": True},
        },
        "definition/pages/pages.json": {
            "$schema": f"{SCHEMA}/item/report/definition/pagesMetadata/1.0.0/schema.json",
            "pageOrder": [p.name for p in pages], "activePageName": pages[0].name,
        },
        f"StaticResources/RegisteredResources/{NAME}.json": report_theme(),
    }
    for p in pages:
        files.update(p.files())
    return files


def write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = content if isinstance(content, str) else json.dumps(content, indent=2, ensure_ascii=False)
    text = text.replace("\r\n", "\n")
    path.write_bytes((text if text.endswith("\n") else text + "\n").encode("utf-8"))


def main():
    report_dir = PBI / f"{NAME}.Report"
    model_dir = PBI / f"{NAME}.SemanticModel"
    pbip_file = PBI / f"{NAME}.pbip"
    for folder in (report_dir, model_dir):
        if folder.exists():
            shutil.rmtree(folder)
    pbip_file.unlink(missing_ok=True)
    for rel, content in model_files().items():
        write_file(model_dir / rel, content)
    for rel, content in report_files().items():
        write_file(report_dir / rel, content)
    write_file(pbip_file, {
        "$schema": f"{SCHEMA}/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0",
        "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True},
    })
    print(f"[OK] Generated {pbip_file}")


if __name__ == "__main__":
    main()
