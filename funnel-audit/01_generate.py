"""Generate a SYNTHETIC event log for an in-app store payment funnel -> data/events.parquet.

Fictional app, 8 weeks, 4 platforms (web desktop, mobile web, iOS app, Android app).
Three issues are planted on purpose so the audit (02_funnel_sql.py) can be checked against a known truth:
  1. BUG       - Android app 5.2 (released on day 28, ramps over a week): payment-method list fails to load for 35%
                 of checkouts; most failures log a `payment_methods_error` event.
  2. BEHAVIOUR - iOS shows a price-confirmation dialog after "Buy"; 25% of users close it on purpose
                 (`price_dialog_closed`) -> looks like a broken "Buy" button but is a user choice.
  3. UX / PAYMENTS - 3-D Secure challenge on mobile web is completed far less often (62%) than elsewhere (~88-90%).
TRUTH below is written to data/truth.json for the verification step.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
(ROOT / "data").mkdir(exist_ok=True)
rng = np.random.default_rng(2026)

N = 250_000
DAYS = 56
START = pd.Timestamp("2026-08-03")
RELEASE_DAY = 28

PLATFORMS = np.array(["web_desktop", "web_mobile", "ios", "android"])
P_BUY = {"web_desktop": 0.30, "web_mobile": 0.22, "ios": 0.28, "android": 0.27}
P_METHOD = 0.80
BUG_FAIL = 0.35
IOS_DIALOG_CLOSE = 0.25
P_CHECKOUT = 0.965          # click -> checkout for platforms without the dialog (rest = unexplained loss)
THREEDS_COMPLETE = {"web_desktop": 0.90, "web_mobile": 0.62, "ios": 0.88, "android": 0.88}
METHOD_MIX = {
    "web_desktop": (["card", "paypal", "apple_pay", "google_pay"], [0.55, 0.30, 0.10, 0.05]),
    "web_mobile": (["card", "paypal", "apple_pay", "google_pay"], [0.55, 0.20, 0.15, 0.10]),
    "ios": (["card", "apple_pay"], [0.45, 0.55]),
    "android": (["card", "google_pay"], [0.50, 0.50]),
}
PRICES, PRICE_P = [4.99, 9.99, 19.99, 49.99], [0.40, 0.30, 0.20, 0.10]

s = pd.DataFrame({
    "session_id": np.arange(1, N + 1),
    "day": rng.integers(0, DAYS, N),
    "platform": rng.choice(PLATFORMS, N, p=[0.25, 0.20, 0.25, 0.30]),
    "is_returning": rng.random(N) < 0.30,
})
s["user_id"] = rng.integers(1, 140_000, N)
s["has_saved_card"] = s.is_returning & (rng.random(N) < 0.6)
s["app_version"] = None
s.loc[s.platform == "ios", "app_version"] = "7.4"
andr = s.platform == "android"
adopt = np.clip((s.day - RELEASE_DAY + 1) / 7, 0, 1) * 0.85
s.loc[andr, "app_version"] = np.where(rng.random(N)[andr] < adopt[andr], "5.2", "5.1")

u = lambda: rng.random(N)
s["buy"] = u() < s.platform.map(P_BUY)
ios = s.platform == "ios"
s["dialog_closed"] = s.buy & ios & (u() < IOS_DIALOG_CLOSE)
s["checkout"] = s.buy & ~s.dialog_closed & (u() < P_CHECKOUT)
bug = s.checkout & (s.app_version == "5.2") & (u() < BUG_FAIL)
s["pm_error_logged"] = bug & (u() < 0.9)
s["method"] = s.checkout & ~bug & (u() < P_METHOD)

pm = np.full(N, None, dtype=object)
for p, (names, probs) in METHOD_MIX.items():
    idx = np.where(s.method & (s.platform == p))[0]
    pm[idx] = rng.choice(names, len(idx), p=probs)
saved = s.method & s.has_saved_card & (u() < 0.7)
pm[saved.values] = "saved_card"
s["payment_method"] = pm

p_submit = np.select([s.payment_method == "saved_card", s.payment_method.isin(["apple_pay", "google_pay"])], [0.95, 0.90], 0.84)
s["submit"] = s.method & (u() < p_submit)
s["threeds"] = s.submit & (s.payment_method == "card") & (u() < 0.35)
completed_3ds = s.threeds & (u() < s.platform.map(THREEDS_COMPLETE))
p_ok = np.select([s.payment_method.isin(["apple_pay", "google_pay", "paypal"]), s.payment_method == "saved_card"], [0.97, 0.95], 0.92)
s["success"] = s.submit & (~s.threeds | completed_3ds) & (u() < np.where(s.threeds, 0.95, p_ok))
s["fail_reason"] = None
s.loc[s.submit & ~s.success, "fail_reason"] = "declined"
s.loc[s.threeds & ~completed_3ds, "fail_reason"] = "threeds_not_completed"
s["amount"] = np.where(s.success, rng.choice(PRICES, N, p=PRICE_P), np.nan)

# ---- explode sessions into an event log ----
base_ts = START + pd.to_timedelta(s.day, unit="D") + pd.to_timedelta(rng.integers(0, 86_000, N), unit="s")
cols = ["session_id", "user_id", "platform", "app_version", "is_returning"]
events = []


def add(mask, name, offset, extra=None):
    e = s.loc[mask, cols].copy()
    e["event_name"] = name
    e["ts"] = base_ts[mask] + pd.Timedelta(seconds=offset)
    for k, v in (extra or {}).items():
        e[k] = s.loc[mask, v].values
    events.append(e)


add(s.index == s.index, "store_open", 0)
add(s.buy, "buy_click", 20)
add(s.dialog_closed, "price_dialog_closed", 25)
add(s.checkout, "checkout_open", 30)
add(s.pm_error_logged, "payment_methods_error", 33)
add(s.method, "payment_method_selected", 45, {"payment_method": "payment_method"})
add(s.submit, "payment_submit", 60, {"payment_method": "payment_method"})
add(s.threeds, "threeds_challenge_shown", 62, {"payment_method": "payment_method"})
add(s.success, "payment_success", 90, {"payment_method": "payment_method", "amount": "amount"})
add(s.submit & ~s.success, "payment_failed", 90, {"payment_method": "payment_method", "fail_reason": "fail_reason"})
ev = pd.concat(events, ignore_index=True).sort_values(["session_id", "ts"]).reset_index(drop=True)
ev.to_parquet(ROOT / "data" / "events.parquet", index=False)

truth = {"release_day": RELEASE_DAY, "bug_fail": BUG_FAIL, "ios_dialog_close": IOS_DIALOG_CLOSE,
         "p_checkout_other": P_CHECKOUT, "threeds_complete": THREEDS_COMPLETE, "start": str(START.date()), "days": DAYS}
(ROOT / "data" / "truth.json").write_text(json.dumps(truth, indent=1))
print(f"sessions {N:,}  events {len(ev):,}")
print(ev.event_name.value_counts())
