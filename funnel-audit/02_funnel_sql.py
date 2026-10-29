"""Funnel audit on the synthetic event log, in SQL (DuckDB) -> data/results.json.
The audit only sees events; data/truth.json is read at the very end to check that the planted issues were recovered."""
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).parent
EV = (ROOT / "data" / "events.parquet").as_posix()
con = duckdb.connect()
con.execute(f"CREATE VIEW events AS SELECT * FROM read_parquet('{EV}')")
q = lambda sql: con.execute(sql).df()

# one row per session with step flags — the base of every funnel query
FUNNEL_SQL = """
WITH sessions AS (
    SELECT
        session_id,
        any_value(platform)                                         AS platform,
        any_value(app_version)                                      AS app_version,
        CAST(min(ts) AS DATE)                                       AS day,
        max(event_name = 'buy_click')::INT                          AS buy_click,
        max(event_name = 'price_dialog_closed')::INT                AS dialog_closed,
        max(event_name = 'checkout_open')::INT                      AS checkout_open,
        max(event_name = 'payment_methods_error')::INT              AS pm_error,
        max(event_name = 'payment_method_selected')::INT            AS method_selected,
        max(event_name = 'payment_submit')::INT                     AS payment_submit,
        max(event_name = 'threeds_challenge_shown')::INT            AS threeds_shown,
        max(event_name = 'payment_success')::INT                    AS payment_success,
        max(CASE WHEN event_name = 'payment_failed' THEN fail_reason END) AS fail_reason,
        max(CASE WHEN event_name = 'payment_submit' THEN payment_method END) AS payment_method,
        sum(CASE WHEN event_name = 'payment_success' THEN amount ELSE 0 END) AS revenue
    FROM events
    GROUP BY session_id
)
SELECT
    platform,
    count(*)                  AS store_open,
    sum(buy_click)            AS buy_click,
    sum(checkout_open)        AS checkout_open,
    sum(method_selected)      AS method_selected,
    sum(payment_submit)       AS payment_submit,
    sum(payment_success)      AS payment_success,
    round(sum(revenue), 2)    AS revenue
FROM sessions
GROUP BY ROLLUP (platform)
ORDER BY platform NULLS FIRST
"""
SESSIONS_SQL = FUNNEL_SQL.split("SELECT\n    platform,")[0].replace("WITH sessions AS (", "CREATE TABLE sessions AS (", 1).rstrip().rstrip(")") + ")"
con.execute(SESSIONS_SQL.replace("CREATE TABLE sessions AS (", "CREATE TABLE sessions AS ", 1).rstrip(")"))

funnel = q(FUNNEL_SQL)
funnel["platform"] = funnel.platform.fillna("all")
days = q("SELECT min(day) AS d0, max(day) AS d1, count(DISTINCT day) AS n FROM sessions").iloc[0]
n_days = int(days.n)

# ---- Issue 1: checkout -> payment method, daily, Android by app version vs other platforms ----
daily = q("""
    SELECT day,
           CASE WHEN platform = 'android' THEN 'Android ' || app_version ELSE 'Other platforms' END AS series,
           sum(checkout_open) AS checkout, sum(method_selected) AS method
    FROM sessions WHERE checkout_open = 1
    GROUP BY ALL ORDER BY day
""")
release_day = q("SELECT min(day) AS d FROM sessions WHERE app_version = '5.2'").iloc[0].d
android_v = q(f"""
    SELECT app_version,
           sum(checkout_open)                                   AS checkout,
           avg(method_selected)                                 AS method_rate,
           sum(pm_error)                                        AS error_events,
           sum(1 - method_selected)                             AS dropped,
           sum(pm_error) / sum(1 - method_selected)             AS error_share_of_drops,
           avg(payment_success) FILTER (WHERE method_selected = 1) AS success_after_method,
           avg(revenue) FILTER (WHERE payment_success = 1)      AS aov
    FROM sessions
    WHERE platform = 'android' AND checkout_open = 1 AND day >= DATE '{release_day}'
    GROUP BY app_version ORDER BY app_version
""").set_index("app_version")
last7 = q(f"""
    SELECT count(*) AS checkout_52
    FROM sessions
    WHERE platform = 'android' AND app_version = '5.2' AND checkout_open = 1
      AND day > (SELECT max(day) FROM sessions) - INTERVAL 7 DAY
""").iloc[0].checkout_52
r51, r52 = android_v.loc["5.1", "method_rate"], android_v.loc["5.2", "method_rate"]
lost_monthly_android = last7 / 7 * 30 * (r51 - r52) * android_v.loc["5.1", "success_after_method"] * android_v.loc["5.1", "aov"]

# ---- Issue 2: "Buy" clicks that never reach checkout ----
clicks = q("""
    SELECT platform,
           sum(buy_click)                                                    AS clicks,
           sum(checkout_open)                                                AS checkout,
           sum(dialog_closed)                                                AS dialog_closed,
           sum(buy_click * (1 - checkout_open) * (1 - dialog_closed))        AS unexplained
    FROM sessions WHERE buy_click = 1
    GROUP BY platform ORDER BY platform
""")
for c in ("checkout", "dialog_closed", "unexplained"):
    clicks[c + "_rate"] = clicks[c] / clicks.clicks

# ---- Issue 3: 3-D Secure challenge completion by platform (card payments) ----
tds = q("""
    SELECT platform,
           sum(payment_submit)                                                   AS card_submits,
           sum(threeds_shown)                                                    AS challenged,
           sum(threeds_shown * (coalesce(fail_reason, '') <> 'threeds_not_completed')::INT) AS completed,
           avg(payment_success) FILTER (WHERE threeds_shown = 1)                AS success_challenged,
           avg(payment_success) FILTER (WHERE threeds_shown = 0)                AS success_not_challenged,
           avg(revenue) FILTER (WHERE payment_success = 1)                       AS aov
    FROM sessions WHERE payment_submit = 1 AND payment_method = 'card'
    GROUP BY platform ORDER BY platform
""").set_index("platform")
tds["completion_rate"] = tds.completed / tds.challenged
other = tds.drop("web_mobile")
bench = (other.completed.sum() / other.challenged.sum())
mw = tds.loc["web_mobile"]
success_if_completed = q("""
    SELECT avg(payment_success) AS r FROM sessions
    WHERE threeds_shown = 1 AND coalesce(fail_reason, '') <> 'threeds_not_completed'
""").iloc[0].r
lost_monthly_3ds = mw.challenged / n_days * 30 * (bench - mw.completion_rate) * success_if_completed * mw.aov

# ---- payment method mix (context) ----
methods = q("""
    SELECT payment_method, count(*) AS submits, avg(payment_success) AS success_rate
    FROM sessions WHERE payment_submit = 1 GROUP BY ALL ORDER BY submits DESC
""")

rev_monthly = float(funnel.loc[funnel.platform == "all", "revenue"].iloc[0]) / n_days * 30
out = {
    "period": {"start": str(days.d0), "end": str(days.d1), "days": n_days},
    "funnel": funnel.to_dict("records"),
    "revenue_monthly": rev_monthly,
    "daily": daily.assign(day=daily.day.astype(str)).to_dict("records"),
    "release_day": str(release_day),
    "android_v": android_v.reset_index().to_dict("records"),
    "android_lost_monthly": float(lost_monthly_android),
    "clicks": clicks.to_dict("records"),
    "threeds": tds.reset_index().to_dict("records"),
    "threeds_bench": float(bench),
    "threeds_lost_monthly": float(lost_monthly_3ds),
    "methods": methods.to_dict("records"),
    "funnel_sql": FUNNEL_SQL.strip(),
}
(ROOT / "data" / "results.json").write_text(json.dumps(out, default=float, indent=1))

# ---- checks ----
f = funnel.set_index("platform")
steps = ["store_open", "buy_click", "checkout_open", "method_selected", "payment_submit", "payment_success"]
print(f[steps + ["revenue"]])
print("funnel never grows:", all((f[steps].diff(axis=1).iloc[:, 1:] <= 0).all()))
print("platforms sum to total:", (f.drop("all")[steps].sum() == f.loc["all", steps]).all())
print(f"days={n_days} release={release_day} monthly revenue≈{rev_monthly:,.0f}")
print("\nAndroid since release:\n", android_v[["checkout", "method_rate", "error_share_of_drops", "success_after_method", "aov"]])
print(f"lost/month Android bug ≈ ${lost_monthly_android:,.0f}")
print("\nclicks:\n", clicks[["platform", "clicks", "checkout_rate", "dialog_closed_rate", "unexplained_rate"]])
print("\n3DS:\n", tds[["card_submits", "challenged", "completion_rate", "success_challenged", "success_not_challenged"]])
print(f"bench completion {bench:.3f}; lost/month 3DS mobile web ≈ ${lost_monthly_3ds:,.0f}")

truth = json.loads((ROOT / "data" / "truth.json").read_text())
print("\nTRUTH CHECK")
print(f"  bug fail rate: estimated {1 - r52 / r51:.3f} vs planted {truth['bug_fail']}")
ios_c = clicks.set_index("platform").loc["ios"]
print(f"  iOS dialog close: estimated {ios_c.dialog_closed_rate:.3f} vs planted {truth['ios_dialog_close']}")
print(f"  3DS completion mobile web: estimated {mw.completion_rate:.3f} vs planted {truth['threeds_complete']['web_mobile']}")
