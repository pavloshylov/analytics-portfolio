"""Load UCI Online Retail II (CC BY 4.0) from xlsx, save to parquet, print a data profile."""
from pathlib import Path

import pandas as pd

RAW = Path(__file__).parent / "data" / "online_retail_II.xlsx"  # download from UCI, see README
OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True)

sheets = pd.read_excel(RAW, sheet_name=None, dtype={"Invoice": str, "StockCode": str})
print({k: len(v) for k, v in sheets.items()})
df = pd.concat(sheets.values(), ignore_index=True)
df["Description"] = df["Description"].astype("string")  # a few descriptions are parsed as numbers
df.to_parquet(OUT / "raw.parquet", index=False)

print(df.dtypes)
print("rows", len(df))
print("date range", df.InvoiceDate.min(), df.InvoiceDate.max())
print("exact duplicate rows", df.duplicated().sum())
print("cancelled invoices (C*)", df.Invoice.str.startswith("C").sum())
print("other non-numeric invoices", (~df.Invoice.str.match(r"^C?\d+$")).sum(), df.loc[~df.Invoice.str.match(r"^C?\d+$"), "Invoice"].unique()[:10])
print("qty<=0", (df.Quantity <= 0).sum(), "price<=0", (df.Price <= 0).sum())
print("missing Customer ID", df["Customer ID"].isna().sum())
non_product = df.loc[~df.StockCode.str.match(r"^\d{5}"), "StockCode"].value_counts().head(25)
print("non-product stock codes:\n", non_product)
print("countries", df.Country.nunique())
print(df.Country.value_counts().head(10))
