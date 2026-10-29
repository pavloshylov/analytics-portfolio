"""Cookie Cats A/B test (gate at level 30 vs 40) -> data/results.json + printed checks.

Group A = gate_30 (control), Group B = gate_40 (treatment).
Metrics: D1 / D7 retention (binary), game rounds in first 14 days (heavy-tailed -> winsorized mean + median).
Exposure split: a player with < 30 rounds in total never reached level 30 (every level takes >= 1 round), so the game
was identical for them in both groups -> difference there should be ~0 (placebo). Membership in that bucket cannot
be changed by the treatment (rounds before level 30 are identical in both arms), so the split is not post-treatment biased.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "cookie_cats.csv"  # download from Kaggle, see README
(ROOT / "data").mkdir(exist_ok=True)
rng = np.random.default_rng(42)
B_ITER = 10_000

df = pd.read_csv(RAW)
assert df.userid.is_unique, "duplicate users"
df["group"] = df.version.map({"gate_30": "A", "gate_40": "B"})
assert df.group.notna().all()
for c in ("retention_1", "retention_7"):
    df[c] = df[c].astype(bool).astype(int)

out = {"n_total": len(df)}
n = df.group.value_counts().to_dict()
out["n"] = n
print("rows", len(df), "groups", n)

# --- SRM: expected 50/50 ---
chi2, p_srm = stats.chisquare([n["A"], n["B"]])
out["srm"] = {"chi2": chi2, "p": p_srm, "share_A": n["A"] / len(df)}
print(f"SRM chi2={chi2:.2f} p={p_srm:.4f} share A={n['A'] / len(df):.4f}")

# --- winsorization threshold for rounds: pooled 99th percentile ---
cap = float(np.percentile(df.sum_gamerounds, 99))
df["rounds_w"] = df.sum_gamerounds.clip(upper=cap)
out["rounds_cap_p99"] = cap
out["rounds_max"] = int(df.sum_gamerounds.max())
print(f"rounds p99 cap={cap}, max={df.sum_gamerounds.max()}")


def bootstrap_diff(a, b, stat=np.mean, iters=B_ITER):
    """Bootstrap distribution of stat(b) - stat(a)."""
    a, b = np.asarray(a), np.asarray(b)
    ia = rng.integers(0, len(a), (iters, len(a)))
    ib = rng.integers(0, len(b), (iters, len(b)))
    if stat is np.mean:
        da = a[ia].mean(1)
        db = b[ib].mean(1)
    else:
        da = np.median(a[ia], 1)
        db = np.median(b[ib], 1)
    return db - da


def binary_metric(d, col):
    a, b = d.loc[d.group == "A", col], d.loc[d.group == "B", col]
    diff = bootstrap_diff(a.values, b.values)
    # Bayesian: Beta(1,1) prior, P(B > A)
    sa = rng.beta(1 + a.sum(), 1 + len(a) - a.sum(), 200_000)
    sb = rng.beta(1 + b.sum(), 1 + len(b) - b.sum(), 200_000)
    z, p = two_prop_z(a.sum(), len(a), b.sum(), len(b))
    return {"A": a.mean(), "B": b.mean(), "nA": len(a), "nB": len(b), "diff": b.mean() - a.mean(),
            "ci": [float(np.percentile(diff, 2.5)), float(np.percentile(diff, 97.5))],
            "p_b_better": float((sb > sa).mean()), "p_value": p,
            "boot_hist": hist(diff)}


def two_prop_z(xa, na, xb, nb):
    p = (xa + xb) / (na + nb)
    se = np.sqrt(p * (1 - p) * (1 / na + 1 / nb))
    z = (xb / nb - xa / na) / se
    return float(z), float(2 * stats.norm.sf(abs(z)))


def hist(x, bins=40):
    h, e = np.histogram(x, bins=bins)
    return {"counts": h.tolist(), "edges": [float(v) for v in e]}


def rounds_metric(d):
    a, b = d.loc[d.group == "A"], d.loc[d.group == "B"]
    dm = bootstrap_diff(a.rounds_w.values, b.rounds_w.values)
    _, p_mw = stats.mannwhitneyu(a.sum_gamerounds, b.sum_gamerounds)
    return {"A_mean_w": a.rounds_w.mean(), "B_mean_w": b.rounds_w.mean(),
            "A_mean_raw": a.sum_gamerounds.mean(), "B_mean_raw": b.sum_gamerounds.mean(),
            "A_median": float(a.sum_gamerounds.median()), "B_median": float(b.sum_gamerounds.median()),
            "diff_w": b.rounds_w.mean() - a.rounds_w.mean(),
            "ci_w": [float(np.percentile(dm, 2.5)), float(np.percentile(dm, 97.5))],
            "p_mannwhitney": float(p_mw)}


def mde(p_base, n_per_group, alpha=0.05, power=0.8):
    """Minimum detectable absolute difference for two proportions (normal approx)."""
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    return float(z * np.sqrt(2 * p_base * (1 - p_base) / n_per_group))


segments = {
    "all": df,
    "reached_30": df[df.sum_gamerounds >= 30],   # could have reached the gate
    "below_30": df[df.sum_gamerounds < 30],      # never reached level 30 -> placebo
}
out["segments"] = {}
for name, d in segments.items():
    out["segments"][name] = {
        "n": d.group.value_counts().to_dict(),
        "share_of_players": len(d) / len(df),
        "d1": binary_metric(d, "retention_1"),
        "d7": binary_metric(d, "retention_7"),
        "rounds": rounds_metric(d),
    }

# SRM inside each segment: where does the extra traffic in one group sit?
for name, s in out["segments"].items():
    c, p = stats.chisquare([s["n"]["A"], s["n"]["B"]])
    s["srm_p"] = float(p)
    s["reach_share"] = None
for g in ("A", "B"):
    out[f"reach_share_{g}"] = out["segments"]["reached_30"]["n"][g] / n[g]

# composition-adjusted (post-stratified) difference: within-segment diffs weighted by pooled segment share
def stratified(col):
    w = {k: out["segments"][k]["share_of_players"] for k in ("reached_30", "below_30")}
    point = sum(w[k] * out["segments"][k][col]["diff"] for k in w)
    boots = []
    for _ in range(2000):
        tot = 0.0
        for k, d in (("reached_30", segments["reached_30"]), ("below_30", segments["below_30"])):
            a = d.loc[d.group == "A", "retention_1" if col == "d1" else "retention_7"].values
            b = d.loc[d.group == "B", "retention_1" if col == "d1" else "retention_7"].values
            tot += w[k] * (rng.choice(b, len(b)).mean() - rng.choice(a, len(a)).mean())
        boots.append(tot)
    return {"diff": point, "ci": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]}


out["stratified"] = {"d1": stratified("d1"), "d7": stratified("d7")}

# power / MDE on the full population and on players who reached the gate
for name in ("all", "reached_30"):
    s = out["segments"][name]
    nn = min(s["n"].values())
    s["mde_d1"] = mde(s["d1"]["A"], nn)
    s["mde_d7"] = mde(s["d7"]["A"], nn)

# rounds distribution (for the chart): share of players by rounds bucket, per group
buckets = [0, 1, 5, 10, 20, 30, 40, 50, 100, 200, 500, 10**9]
labels = ["0", "1–4", "5–9", "10–19", "20–29", "30–39", "40–49", "50–99", "100–199", "200–499", "500+"]
df["bucket"] = pd.cut(df.sum_gamerounds, buckets, right=False, labels=labels)
dist = df.groupby(["bucket", "group"], observed=False).size().unstack().fillna(0)
out["rounds_dist"] = {"labels": labels, "A": (dist.A / n["A"]).tolist(), "B": (dist.B / n["B"]).tolist()}

(ROOT / "data" / "results.json").write_text(json.dumps(out, default=float))

# ---- printed checks ----
for name, s in out["segments"].items():
    print(f"\n[{name}] n={s['n']} share={s['share_of_players']:.3f}")
    for m in ("d1", "d7"):
        r = s[m]
        print(f"  {m}: A={r['A']:.4f} B={r['B']:.4f} diff={r['diff'] * 100:+.2f}pp CI=[{r['ci'][0] * 100:+.2f},{r['ci'][1] * 100:+.2f}] "
              f"P(B>A)={r['p_b_better']:.3f} p={r['p_value']:.4f}")
    r = s["rounds"]
    print(f"  rounds: mean_w A={r['A_mean_w']:.2f} B={r['B_mean_w']:.2f} diff={r['diff_w']:+.2f} CI={[round(x, 2) for x in r['ci_w']]} "
          f"median A={r['A_median']} B={r['B_median']} MW p={r['p_mannwhitney']:.4f}")
    if "mde_d1" in s:
        print(f"  MDE (80% power): D1 {s['mde_d1'] * 100:.2f}pp, D7 {s['mde_d7'] * 100:.2f}pp")
print("\nSRM by segment:", {k: round(v["srm_p"], 4) for k, v in out["segments"].items()})
print("share reaching 30 rounds: A", round(out["reach_share_A"], 4), "B", round(out["reach_share_B"], 4))
for m in ("d1", "d7"):
    s = out["stratified"][m]
    print(f"composition-adjusted {m}: {s['diff'] * 100:+.2f}pp CI=[{s['ci'][0] * 100:+.2f},{s['ci'][1] * 100:+.2f}]")
# consistency: segment counts add up
a, b = out["segments"]["reached_30"]["n"], out["segments"]["below_30"]["n"]
print("\nsegments add up:", a["A"] + b["A"] == n["A"] and a["B"] + b["B"] == n["B"])
