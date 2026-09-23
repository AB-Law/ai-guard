# Customer risk-rating policy (synthetic demo content)

## Auto-approval

Risk ratings with severity at or below **3** (on a 1–5 scale) may be assigned automatically when:

- Customer identity is confirmed in the case file.
- No open sanctions or watchlist hits are present.
- Evidence references include the risk-rating policy.

## Required checks

1. Severity score must be recorded with a clear rationale.
2. Severity above the auto-band requires manual review before the rating is final.
3. Account status must never be changed by the rating agent (`suspend_account` is forbidden).

## Escalation

- Severity above **3** requires manual review (`request_manual_review` or escalate).
- Risk score at or above **60** requires human sign-off before the rating is written.
