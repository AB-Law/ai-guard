# Procurement policy (synthetic demo content)

## Auto-approval

Purchase orders at or below **USD 10,000** may be auto-approved when:

- The vendor is **active** on the vendor master list.
- Required budget and duplicate-PO checks pass.
- Evidence references include procurement policy and vendor master data.

## Required checks

1. Vendor status must be `active`.
2. Amount must not exceed the band without human approval.
3. Banking or payment details must not be modified via agent tools.

## Escalation

- Amounts above **USD 10,000** require human approval (`request_approval` or escalate).
- Risk score at or above **60** requires human sign-off before tool execution.
