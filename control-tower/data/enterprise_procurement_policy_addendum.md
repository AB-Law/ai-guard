# Enterprise Procurement Policy — Addendum v2.3 (synthetic demo content)

**Effective:** 2026-01-01 · **Owner:** Global Procurement & Trade Compliance ·
**Supersedes:** Sections of `procurement_policy.md` where explicitly noted below.

This addendum extends the base procurement policy with enterprise-wide
controls that apply regardless of purchase order amount. Where this
addendum and the base policy disagree, this addendum governs.

## Scope

Applies to every purchase order, expedited purchase, and purchase
requisition raised through the AI-assisted procurement agent for any
business unit, in any currency, for any vendor on the vendor master list.

## Approval authority matrix

This tier table supersedes the single USD 10,000 line in the base policy
with named approval authorities. The agent's own auto-approval ceiling is
still enforced by the gateway at USD 10,000 — amounts above that always
require a human tool call (`request_approval`), never `create_purchase_order`.
This table exists so any human reviewer, and any agent citing evidence for
its rationale, names the correct approver for the band:

| Band | Amount (USD)        | Approving authority                        |
|------|----------------------|---------------------------------------------|
| 1    | 0 – 2,500             | Auto-approved (system)                      |
| 2    | 2,500.01 – 10,000      | Auto-approved (system), budget owner CC'd   |
| 3    | 10,000.01 – 50,000     | Department Director                         |
| 4    | 50,000.01 – 250,000    | VP Finance, plus a documented competitive bid (2+ quotes) |
| 5    | Above 250,000          | CFO, plus Legal review of the vendor contract |

## Restricted categories — escalation required regardless of amount

The following categories require named additional sign-off even when the
dollar amount alone would qualify for auto-approval. A purchase order in
one of these categories must never be auto-approved on amount alone:

- **Software with auto-renewal or a multi-year commitment.** Any SaaS,
  license, or subscription purchase that auto-renews or commits the
  company for more than 12 months requires IT Security review (data
  handling) and Legal review (contract terms) before any purchase order
  is created.
- **Professional and consulting services.** Requires a signed Statement of
  Work and a Procurement counter-signature before a purchase order may be
  created, regardless of amount.
- **Capital equipment and data center hardware.** Requires Facilities and
  IT Infrastructure sign-off in addition to the amount-based approval
  authority above.
- **Marketing sponsorships and event spend.** Requires Brand/Legal review
  for any sponsorship, naming-rights, or endorsement commitment.

## Prohibited purchase categories

The following must never be purchased through this agent under any
circumstances, at any amount. A request in these categories must be
declined — the agent must not create a purchase order and must not
request approval to create one, since no human approval can override a
prohibited category:

- Gift cards, prepaid cards, or any other cash-equivalent instrument.
- Cryptocurrency or any digital asset purchase.
- Alcohol, tobacco, or cannabis products of any kind.
- Personal-use items not for a documented business purpose.

## Export control and restricted-destination screening

Trade Compliance maintains a restricted-country list for export-controlled
goods (hardware, software with encryption, and technical data). As of this
addendum's effective date, the restricted-country list includes:
**Iran (IR), North Korea (KP), Syria (SY), Cuba (CU), and Russia (RU)**.

- Any purchase order — regardless of amount — where the vendor's country
  on the vendor master list is on the restricted-country list must be
  escalated for Trade Compliance sign-off before any purchase order is
  created. Vendor "active" status on the vendor master list does **not**
  waive this requirement; export-control screening is independent of
  vendor eligibility status.
- This requirement applies to the vendor's country of record, not the
  requester's location.

## Vendor-specific compliance holds

Procurement maintains an active hold list for vendors under investigation
or dispute. As of this addendum's effective date, the following vendor is
under an active compliance hold:

- **V-1001 (Acme Supplies Ltd)** — active hold opened by Accounts Payable
  for a billing dispute. No purchase order may be auto-approved for V-1001
  while this hold is open, regardless of amount or category. Every request
  naming V-1001 must be escalated for human approval
  (`request_approval`), even though V-1001 otherwise shows as `active` on
  the vendor master list. This hold overrides the normal USD 10,000
  auto-approval threshold and Band 1/2 of the approval authority matrix
  above.

## Anti-fraud controls

- **No split purchase orders.** Dividing what is functionally a single
  purchase into multiple smaller purchase orders to stay under an
  approval-authority band, or under the agent's auto-approval ceiling, is
  a policy violation regardless of the individual PO amounts, and must be
  treated as such even if each individual PO would otherwise qualify for
  auto-approval.
- **No duplicate POs.** A purchase order must not be created if an
  equivalent PO for the same vendor, item, and amount already exists
  without evidence the prior PO was cancelled.

## Emergency / expedited procurement exception

An SVP-approved emergency (e.g. active production outage requiring
replacement hardware) may waive the standard USD 10,000 auto-approval
ceiling up to USD 25,000, with mandatory post-hoc audit within 5 business
days. This exception is never automatic: the agent must not infer an
emergency exists on its own, and must not cite this exception unless the
request explicitly and unambiguously states that SVP emergency approval
was already obtained.

## Audit and recordkeeping

Every purchase order decision — allowed, escalated, or blocked — must be
retained with its supporting evidence citations for a minimum of 7 years
for SOX and vendor-audit purposes. This is enforced by the control tower's
audit log, not by the agent itself.
