"""Render data/results.json into output/cookie_cats_ab_report.html (fixed light palette, ECharts).
All numbers in the text are formatted from results.json — nothing typed by hand."""
import json
from pathlib import Path

from scipy import stats

ROOT = Path(__file__).parent
r = json.loads((ROOT / "data" / "results.json").read_text())
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

S = r["segments"]
al, ex, pl = S["all"], S["reached_30"], S["below_30"]
st = r["stratified"]
pp = lambda x: f"{x * 100:+.2f} pp".replace("-", "−")
ci = lambda c: f"{c[0] * 100:+.2f} to {c[1] * 100:+.2f} pp".replace("-", "−")
pc = lambda x: f"{x * 100:.1f}%"

# sample needed to detect the observed exposed-player D7 difference with 80% power
z = stats.norm.ppf(0.975) + stats.norm.ppf(0.8)
p0, d = ex["d7"]["A"], abs(ex["d7"]["diff"])
need_exposed = z ** 2 * 2 * p0 * (1 - p0) / d ** 2
reach = ex["share_of_players"]
need_total = 2 * need_exposed / reach
extra_B = pl["n"]["B"] - pl["n"]["A"]

text = {
    "verdict": (
        f"<b>Keep the first gate at level 30.</b> Moving it to level 40 did not improve retention: 7-day retention is "
        f"{pp(al['d7']['diff'])} for Group B (95% CI {ci(al['d7']['ci'])}). But the test has a sample-ratio mismatch "
        f"(p = {r['srm']['p']:.3f}) and, once it is accounted for, the real effect is smaller and less certain than the headline suggests."
    ),
    "srm_info": (
        f"Groups should be 50/50, but Group B received {r['n']['B'] - r['n']['A']:,} more players (p = {r['srm']['p']:.3f}). "
        f"The imbalance comes <b>entirely from players who never reached level 30</b> (+{extra_B:,} in Group B, p = {pl['srm_p']:.4f}), "
        f"while players with 30+ rounds are balanced ({abs(ex['n']['A'] - ex['n']['B']):,} players apart, p = {ex['srm_p']:.2f}). For players who never reach level 30 the game is "
        f"identical in both groups, so the gate cannot explain this — it points to an assignment or logging issue that adds low-engagement "
        f"players to Group B and mechanically lowers its average retention."
    ),
    "exposure_info": (
        f"{pc(pl['share_of_players'])} of players played fewer than 30 rounds in their first 14 days, so they never reached level 30 "
        f"and never saw either gate. Including them dilutes the effect (intent-to-treat). For them the two groups should be identical — "
        f"a built-in placebo check. Every level takes at least one round, and the game is the same in both groups until level 30, "
        f"so this split is not biased by the treatment itself."
    ),
    "placebo_info": (
        f"Placebo: among players who never reached the gate, Group B still shows 7-day retention {pp(pl['d7']['diff'])} "
        f"(95% CI {ci(pl['d7']['ci'])}). It should be zero — another sign the groups are not fully comparable."
    ),
    "power_info": (
        f"Among players who could reach the gate, the test could reliably detect (80% power) only D7 differences of "
        f"{ex['mde_d7'] * 100:.1f} pp or more; the observed difference is {abs(ex['d7']['diff']) * 100:.2f} pp. "
        f"To confirm an effect of that size you would need about {need_total / 1000:,.0f}k players in total — "
        f"{need_total / r['n_total']:.1f}× this test."
    ),
}

conclusions = [
    ("neg", "✗", f"Moving the gate to level 40 did not improve retention. Day-1 retention: {pc(al['d1']['A'])} vs {pc(al['d1']['B'])} "
                 f"(not significant); day-7: {pc(al['d7']['A'])} vs {pc(al['d7']['B'])}."),
    ("warn", "⚠", f"Sample-ratio mismatch (p = {r['srm']['p']:.3f}): Group B got {extra_B:,} extra players who never reached level 30. "
                  f"The headline D7 gap of {pp(al['d7']['diff'])} shrinks to {pp(st['d7']['diff'])} after adjusting for group composition."),
    ("warn", "⚠", f"Placebo check fails at the margin: players who never saw a gate differ by {pp(pl['d7']['diff'])} on D7. "
                  f"Part of the remaining gap is likely not caused by the gate."),
    ("info", "–", f"Among players who could reach the gate ({pc(reach)} of players), the D7 difference is {pp(ex['d7']['diff'])} "
                  f"(95% CI {ci(ex['d7']['ci'])}), probability that Group B is better {ex['d7']['p_b_better'] * 100:.0f}%. Day-1 retention is unchanged "
                  f"({pp(ex['d1']['diff'])})."),
    ("info", "–", f"Group B players with 30+ rounds played slightly more rounds (median {ex['rounds']['B_median']:.0f} vs "
                  f"{ex['rounds']['A_median']:.0f}) — expected, since they get 10 more levels before the gate."),
]
concl_html = "\n".join(f'<li class="c-{k}"><span class="ic">{ic}</span><span>{t}</span></li>' for k, ic, t in conclusions)
reco_html = (
    "<ul><li><b>Keep the gate at level 30</b> — there is no evidence that level 40 helps, and the data leans towards it hurting 7-day retention.</li>"
    "<li><b>Audit the assignment before trusting the size of the effect:</b> check how players were bucketed, bot/duplicate installs "
    "and event logging for low-activity players in Group B.</li>"
    f"<li>If the decision is worth it, <b>re-run with fixed assignment</b> and plan the sample for the effect size that matters "
    f"(about {need_total / 1000:,.0f}k players to detect a {abs(ex['d7']['diff']) * 100:.1f} pp D7 change among exposed players).</li></ul>"
)

html = (ROOT / "report_template.html").read_text(encoding="utf-8")
for k, v in text.items():
    html = html.replace(f"<!--{k}-->", v)
html = html.replace("<!--conclusions-->", concl_html).replace("<!--reco-->", reco_html)
html = html.replace("/*__DATA__*/null", json.dumps(r))
(OUT / "cookie_cats_ab_report.html").write_text(html, encoding="utf-8")
print("written", OUT / "cookie_cats_ab_report.html")
print(f"need_total={need_total:,.0f} ({need_total / r['n_total']:.2f}x), extra_B={extra_B}")
for k, v in text.items():
    print(f"[{k}]", v)
