# Analytics Portfolio

Product & game analytics case studies: A/B testing, payment funnels, monetization and retention.
Each case is a full analysis with a clear recommendation. Public or synthetic data only.

**Live reports:** https://pavloshylov.github.io/analytics-portfolio/

| Case | What it shows | Report | Code |
|---|---|---|---|
| Mobile Game A/B Test | Sample-ratio mismatch, placebo check, bootstrap CIs, Bayesian probability, power / MDE | [open](https://pavloshylov.github.io/analytics-portfolio/ab-test/) | [ab-test-cookie-cats](ab-test-cookie-cats/) |
| Payment Funnel Audit | Funnel in SQL, bug vs. user behaviour vs. UX, revenue impact, priorities | [open](https://pavloshylov.github.io/analytics-portfolio/funnel-audit/) | [funnel-audit](funnel-audit/) |
| E-commerce Dashboard | Data cleaning, YoY revenue, new vs returning, cohort retention, markets | [open](https://pavloshylov.github.io/analytics-portfolio/retail-dashboard/) | [retail-dashboard](retail-dashboard/) |

## Reproduce

```
pip install -r requirements.txt
```

Each folder runs in order (`01_…`, `02_…`, `03_…`); the last step writes the HTML report to `output/`.

- **ab-test-cookie-cats** — download `cookie_cats.csv` from
  [Kaggle: Mobile Games A/B Testing](https://www.kaggle.com/datasets/yufengsui/mobile-games-ab-testing) into `ab-test-cookie-cats/data/`.
  Public educational dataset (originally a DataCamp project); not redistributed here.
- **retail-dashboard** — download `online_retail_II.xlsx` from
  [UCI Machine Learning Repository](https://archive.ics.uci.edu/dataset/502/online+retail+ii) into `retail-dashboard/data/`.
  Chen, D. (2012). Online Retail II. https://doi.org/10.24432/C5CG6D — CC BY 4.0.
- **funnel-audit** — no download needed: `01_generate.py` creates the synthetic event log (fixed seed).
  The issues in it were planted on purpose to demonstrate the audit method.

## Tools

SQL (DuckDB), Python (pandas, NumPy, SciPy), ECharts.
