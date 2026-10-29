"""Clean UCI Online Retail II and compute dashboard aggregates -> data/metrics.json.

Cleaning rules (each printed with its row impact):
  1. drop exact duplicate rows (the two Excel sheets overlap on 2010-12-01..09)
  2. keep sales only: numeric invoice (no 'C' cancellations / 'A' bad-debt adjustments), Quantity > 0, Price > 0
  3. keep products only: StockCode starting with 5 digits (drops postage, fees, manual adjustments, gift cards)
  4. drop the partial month 2011-12 (data ends 2011-12-09)
Customer metrics use rows with a Customer ID; rows without one are "guest" revenue.
"""
import json
from pathlib import Path

import pandas as pd

DATA = Path(__file__).parent / "data"
df = pd.read_parquet(DATA / "raw.parquet")
n0 = len(df)
print(f"raw rows {n0:,}")

df = df.drop_duplicates()
print(f"1. after dropping exact duplicates {len(df):,} (-{n0 - len(df):,})")

n = len(df)
df = df[df.Invoice.str.fullmatch(r"\d+") & (df.Quantity > 0) & (df.Price > 0)]
print(f"2. after sales-only filter {len(df):,} (-{n - len(df):,})")

n = len(df)
df = df[df.StockCode.str.match(r"^\d{5}")]
print(f"3. after products-only filter {len(df):,} (-{n - len(df):,})")

df["month"] = df.InvoiceDate.dt.to_period("M")
n = len(df)
df = df[df.month <= pd.Period("2011-11", "M")]
print(f"4. after dropping partial 2011-12 {len(df):,} (-{n - len(df):,})")

df["revenue"] = df.Quantity * df.Price
df["cust"] = df["Customer ID"].astype("Int64")
df["segment"] = df.Country.eq("United Kingdom").map({True: "uk", False: "intl"})

# first purchase month per customer (over the whole history in the data)
first = df.dropna(subset=["cust"]).groupby("cust").month.min().rename("first_month")
df = df.join(first, on="cust")
df["ctype"] = "guest"
df.loc[df.cust.notna() & (df.month == df.first_month), "ctype"] = "new"
df.loc[df.cust.notna() & (df.month > df.first_month), "ctype"] = "returning"

L12 = (pd.Period("2010-12", "M"), pd.Period("2011-11", "M"))
P12 = (pd.Period("2009-12", "M"), pd.Period("2010-11", "M"))
MONTHS_L12 = [str(p) for p in pd.period_range(*L12, freq="M")]


def kpis(d):
    def period(lo, hi):
        x = d[(d.month >= lo) & (d.month <= hi)]
        known = x.dropna(subset=["cust"])
        orders_per_cust = known.groupby("cust").Invoice.nunique()
        return {
            "revenue": float(x.revenue.sum()),
            "orders": int(x.Invoice.nunique()),
            "customers": int(known.cust.nunique()),
            "aov": float(x.revenue.sum() / x.Invoice.nunique()),
            "repeat_rate": float((orders_per_cust >= 2).mean()),
            "guest_share": float(x.loc[x.cust.isna(), "revenue"].sum() / x.revenue.sum()),
        }
    return {"l12": period(*L12), "p12": period(*P12)}


def yoy_lines(d):
    m = d.groupby("month").revenue.sum()
    return {
        "labels": [p.strftime("%b") for p in pd.period_range(*L12, freq="M")],
        "prev": [float(m.get(p, 0)) for p in pd.period_range(*P12, freq="M")],
        "last": [float(m.get(p, 0)) for p in pd.period_range(*L12, freq="M")],
    }


def by_ctype(d):
    x = d[(d.month >= L12[0]) & (d.month <= L12[1])]
    t = x.pivot_table(index="month", columns="ctype", values="revenue", aggfunc="sum").reindex(
        pd.period_range(*L12, freq="M")).fillna(0)
    return {"labels": MONTHS_L12, **{c: [float(v) for v in t.get(c, pd.Series(0, index=t.index))] for c in ["returning", "new", "guest"]}}


def cohorts(d, max_age=12):
    # cohorts from 2010-01: the 2009-12 "cohort" mixes in customers who bought before the data starts
    k = d.dropna(subset=["cust"])[["cust", "month", "first_month"]].drop_duplicates()
    k = k[k.first_month >= pd.Period("2010-01", "M")]
    k["age"] = (k.month - k.first_month).apply(lambda x: x.n)
    size = k[k.age == 0].groupby("first_month").cust.nunique()
    active = k.groupby(["first_month", "age"]).cust.nunique()
    rows = []
    for c, s in size.items():
        for a in range(0, max_age + 1):
            if c + a > L12[1]:
                break
            rows.append([str(c), a, round(active.get((c, a), 0) / s, 4), int(s)])
    return {"cells": rows, "cohorts": [str(c) for c in size.index], "max_age": max_age}


def countries(d):
    x = d[(d.month >= L12[0]) & (d.month <= L12[1]) & (d.Country != "United Kingdom")]
    s = x.groupby("Country").revenue.sum().sort_values(ascending=False)
    top = s.head(10)
    return {"names": list(top.index), "values": [float(v) for v in top.values], "other": float(s.iloc[10:].sum()),
            "intl_total": float(s.sum())}


out = {"segments": {}}
for seg, d in {"all": df, "uk": df[df.segment == "uk"], "intl": df[df.segment == "intl"]}.items():
    out["segments"][seg] = {"kpi": kpis(d), "yoy": yoy_lines(d), "ctype": by_ctype(d), "cohorts": cohorts(d)}
out["countries"] = countries(df)
out["uk_share_l12"] = out["segments"]["uk"]["kpi"]["l12"]["revenue"] / out["segments"]["all"]["kpi"]["l12"]["revenue"]

(DATA / "metrics.json").write_text(json.dumps(out))

# ---- sanity checks ----
a, u, i = (out["segments"][s]["kpi"]["l12"] for s in ("all", "uk", "intl"))
print("\nL12 KPIs all:", {k: round(v, 3) for k, v in a.items()})
print("P12 KPIs all:", {k: round(v, 3) for k, v in out["segments"]["all"]["kpi"]["p12"].items()})
print("UK + intl revenue == all:", round(u["revenue"] + i["revenue"], 2) == round(a["revenue"], 2))
ct = out["segments"]["all"]["ctype"]
print("ctype sum == L12 revenue:", round(sum(ct["returning"]) + sum(ct["new"]) + sum(ct["guest"]), 2) == round(a["revenue"], 2))
print("yoy last sum == L12 revenue:", round(sum(out["segments"]["all"]["yoy"]["last"]), 2) == round(a["revenue"], 2))
cells = out["segments"]["all"]["cohorts"]["cells"]
print("cohort age-0 all == 1.0:", all(r[2] == 1.0 for r in cells if r[1] == 0), "| max retention age>0:", max(r[2] for r in cells if r[1] > 0))
print("customers counted in 2 segments (multi-country):", int(df.dropna(subset=["cust"]).groupby("cust").segment.nunique().gt(1).sum()))
print("UK share of L12 revenue:", round(out["uk_share_l12"], 3))
print("top intl countries:", list(zip(out["countries"]["names"], [round(v) for v in out["countries"]["values"]])))
print("returning share of L12 revenue:", round(sum(ct["returning"]) / a["revenue"], 3), "new:", round(sum(ct["new"]) / a["revenue"], 3))
m1 = [r[2] for r in cells if r[1] == 1]
print("month-1 retention median:", round(pd.Series(m1).median(), 3), "range", min(m1), max(m1))
