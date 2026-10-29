"""Render data/results.json into output/funnel_audit_report.html. All numbers in the text come from results.json."""
import json
from pathlib import Path

ROOT = Path(__file__).parent
r = json.loads((ROOT / "data" / "results.json").read_text())
truth = json.loads((ROOT / "data" / "truth.json").read_text())
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

F = {x["platform"]: x for x in r["funnel"]}
A = {x["app_version"]: x for x in r["android_v"]}
CK = {x["platform"]: x for x in r["clicks"]}
T = {x["platform"]: x for x in r["threeds"]}
pc = lambda v, d=0: f"{v * 100:.{d}f}%"
usd = lambda v: f"${v / 1000:,.1f}k"
rev_m = r["revenue_monthly"]
days = r["period"]["days"]

# naive reading of the iOS gap: treat every missing checkout (vs other platforms) as a technical loss
others_ck = sum(CK[p]["checkout"] for p in CK if p != "ios") / sum(CK[p]["clicks"] for p in CK if p != "ios")
ios = F["ios"]
naive_ios = (CK["ios"]["clicks"] / days * 30 * (others_ck - CK["ios"]["checkout_rate"])
             * ios["payment_success"] / ios["checkout_open"] * ios["revenue"] / ios["payment_success"])
unexp_other = [CK[p]["unexplained_rate"] for p in CK if p != "ios"]
release = r["release_day"][:10]

text = {
    "verdict": (
        "<b>Three drops in the funnel, three different kinds of problem — and only one of them is urgent.</b><ol>"
        f"<li><b>Android 5.2 bug</b> — the payment-method list fails to load for about a third of checkouts. "
        f"≈ {usd(r['android_lost_monthly'])} revenue lost per month ({pc(r['android_lost_monthly'] / rev_m)} of revenue). <b>Fix first.</b></li>"
        f"<li><b>3-D Secure on mobile web</b> — users complete only {pc(T['web_mobile']['completion_rate'])} of card challenges vs "
        f"{pc(r['threeds_bench'])} elsewhere. ≈ {usd(r['threeds_lost_monthly'])} per month. UX fix.</li>"
        f"<li><b>iOS \"Buy\" clicks without checkout</b> — the biggest-looking gap is <b>not a loss</b>: users close the price "
        f"confirmation dialog by choice. Treating it as a broken button would book ≈ {usd(naive_ios)}/month of losses that don't exist.</li></ol>"
    ),
    "android_info": (
        f"Since the 5.2 release ({release}) only {pc(A['5.2']['method_rate'])} of Android 5.2 checkouts reach payment-method selection, "
        f"vs {pc(A['5.1']['method_rate'])} on 5.1 over the same days and the same level on other platforms. "
        f"{pc(A['5.2']['error_share_of_drops'])} of 5.2 drop-offs log a <code>payment_methods_error</code> event (vs {pc(A['5.1']['error_share_of_drops'])} on 5.1) — "
        f"the payment-method list fails to load. At the current adoption this costs ≈ {usd(r['android_lost_monthly'])} per month. "
        f"<b>Next step:</b> hotfix or roll back 5.2, and add an alert on step conversion by app version so the next regression is caught in a day, not weeks."
    ),
    "clicks_info": (
        f"On iOS only {pc(CK['ios']['checkout_rate'])} of \"Buy\" clicks reach checkout vs {pc(others_ck)} on other platforms — it looks like a broken button. "
        f"But {pc(CK['ios']['dialog_closed_rate'])} of iOS clicks end with <code>price_dialog_closed</code>: the app shows a price confirmation and users decide not to continue. "
        f"The unexplained remainder on iOS ({pc(CK['ios']['unexplained_rate'], 1)}) is no worse than elsewhere "
        f"({pc(min(unexp_other), 1)}–{pc(max(unexp_other), 1)}). <b>Not a bug — no engineering fix needed.</b> "
        f"If the dialog itself is worth questioning, that is a product decision to A/B test, not a defect."
    ),
    "threeds_info": (
        f"Mobile-web users complete {pc(T['web_mobile']['completion_rate'])} of 3-D Secure challenges vs {pc(r['threeds_bench'])} on other platforms. "
        f"Card payments without a challenge succeed at the same rate as elsewhere ({pc(T['web_mobile']['success_not_challenged'])}), so the problem is the "
        f"challenge step itself, not card declines. ≈ {usd(r['threeds_lost_monthly'])} per month. "
        f"<b>Next step:</b> check how the challenge renders in mobile browsers (embedded frame vs redirect, switching to the bank app and back), "
        f"and whether low-value payments can use a 3-D Secure exemption."
    ),
}
prio = [
    ("1", "Android 5.2: payment-method list fails to load", "Bug", f"Android 5.2 users ({pc(A['5.2']['checkout'] / (A['5.2']['checkout'] + A['5.1']['checkout']))} of Android checkouts since release)",
     usd(r["android_lost_monthly"]), "Hotfix / roll back; alert on step conversion by app version"),
    ("2", "3-D Secure challenge abandoned on mobile web", "UX / payments", "Mobile-web card payments with a challenge",
     usd(r["threeds_lost_monthly"]), "Fix challenge rendering; review exemptions for low-value payments"),
    ("3", "iOS Buy clicks without checkout", "User behaviour", "iOS buyers who close the price dialog",
     "Not a loss", "No fix needed; optional A/B test of the dialog"),
]
prio_html = ("<tr><th>#</th><th>Issue</th><th>Type</th><th>Affected</th><th class='num'>Revenue impact / month</th><th>Next step</th></tr>"
             + "".join(f"<tr><td>{a}</td><td>{b}</td><td>{c}</td><td>{d}</td><td class='num'><b>{e}</b></td><td>{f}</td></tr>" for a, b, c, d, e, f in prio))

html = (ROOT / "report_template.html").read_text(encoding="utf-8")
for k, v in text.items():
    html = html.replace(f"<!--{k}-->", v)
html = html.replace("/*__PRIO__*/''", json.dumps(prio_html)).replace("/*__DATA__*/null", json.dumps(r))
html = (html.replace("<!--t_bug-->", f"{pc(1 - A['5.2']['method_rate'] / A['5.1']['method_rate'], 1)} vs {pc(truth['bug_fail'], 1)}")
            .replace("<!--t_dialog-->", f"{pc(CK['ios']['dialog_closed_rate'], 1)} vs {pc(truth['ios_dialog_close'], 1)}")
            .replace("<!--t_3ds-->", f"{pc(T['web_mobile']['completion_rate'], 1)} vs {pc(truth['threeds_complete']['web_mobile'], 1)}"))
(OUT / "funnel_audit_report.html").write_text(html, encoding="utf-8")
print("written", OUT / "funnel_audit_report.html")
for k, v in text.items():
    print(f"[{k}]", v, "\n")
