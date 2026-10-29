"""Render data/metrics.json into a self-contained ECharts dashboard -> output/retail_dashboard.html.
Fixed light palette (no dark-mode switching by design)."""
import json
from pathlib import Path

ROOT = Path(__file__).parent
m = json.loads((ROOT / "data" / "metrics.json").read_text())
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

a = m["segments"]["all"]["kpi"]
l, p = a["l12"], a["p12"]
ct = m["segments"]["all"]["ctype"]
ret_share = sum(ct["returning"]) / l["revenue"]
new_share = sum(ct["new"]) / l["revenue"]
m1 = sorted(c[2] for c in m["segments"]["all"]["cohorts"]["cells"] if c[1] == 1)
m1_median = (m1[len(m1) // 2] + m1[(len(m1) - 1) // 2]) / 2


def med_age(age):
    v = sorted(c[2] for c in m["segments"]["all"]["cohorts"]["cells"] if c[1] == age)
    return (v[len(v) // 2] + v[(len(v) - 1) // 2]) / 2
yoy = m["segments"]["all"]["yoy"]
peak_i = max(range(12), key=lambda i: yoy["last"][i])
top3 = m["countries"]["names"][:3]
top3 = ["Ireland" if c == "EIRE" else c for c in top3]

insights = [
    f"Revenue grew {l['revenue'] / p['revenue'] - 1:+.1%} year over year while orders fell {1 - l['orders'] / p['orders']:.1%}: "
    f"growth came from bigger baskets (average order value {l['aov'] / p['aov'] - 1:+.1%}), not from more orders.",
    f"Returning customers bring {ret_share:.0%} of revenue; first-time customers only {new_share:.0%}. "
    f"Keeping existing customers matters far more to revenue here than acquiring new ones.",
    f"About {m1_median:.0%} of new customers buy again in each of the following four months (cohort median); "
    f"by months 9–12 it drops to {med_age(9):.0%}–{med_age(12):.0%}.",
    f"Guest checkouts (no customer ID) grew from {p['guest_share']:.0%} to {l['guest_share']:.0%} of revenue — "
    f"a growing share of sales that cannot be retargeted or tracked for retention.",
    f"Seasonality is strong: revenue peaks in {yoy['labels'][peak_i]} ahead of the holidays. "
    f"The UK is {m['uk_share_l12']:.0%} of revenue; {', '.join(top3)} lead international sales.",
]
insights_html = "\n".join(f"<li>{s}</li>" for s in insights)

html = (ROOT / "report_template.html").read_text(encoding="utf-8")
html = html.replace("/*__DATA__*/null", json.dumps(m)).replace("<!--__INSIGHTS__-->", insights_html)
(OUT / "retail_dashboard.html").write_text(html, encoding="utf-8")
print("written", OUT / "retail_dashboard.html")
for s in insights:
    print("-", s)
