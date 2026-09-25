"""Generate a CSV of procurement requests for the demo app to process.

Mixes realistic bulk filler (mostly clean, varied vendors/items/amounts)
with a fixed set of seeded edge cases — one row per addendum clause the
tower's policy actually enforces — inserted at random positions so they
read as "this happened to come up" rather than a rehearsed section.
--seed makes the output reproducible: your dress rehearsal and the live
run get the same file.

Usage:
    python generate_requests.py --count 300 --seed 42 --out ../data/requests.csv
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

# Vendors available to the *bulk random* generator only — deliberately
# excludes V-1003 (blocked) and V-1007 (export-restricted country), which
# only ever appear via the fixed seeded rows below, so each generated file
# has exactly one of each instead of a random, inconsistent count.
_BULK_VENDORS = [
    ("V-1001", "office"),
    ("V-1002", "hardware"),
    ("V-1004", "hardware"),
    ("V-1005", "hardware"),
    ("V-1006", "software"),
    ("V-1008", "software"),
    ("V-1009", "services"),
    ("V-1010", "office"),
]

_DEPARTMENTS = ["engineering", "marketing", "facilities", "sales", "it"]

_ITEMS_BY_CATEGORY = {
    "office": ["Office chairs x4", "Desk supplies restock", "Printer paper, 20 boxes", "Standing desks x2"],
    "hardware": ["Laptop docks x10", "Monitor stands x6", "Replacement keyboards x12", "Network switches x2"],
    "software": ["Team chat app seats renewal", "Design tool license, monthly", "Analytics dashboard seats"],
    "services": ["Vendor onboarding workshop", "Quarterly security audit", "Contractor staffing, 1 month"],
}


def _bulk_row(rng: random.Random) -> dict:
    vendor_id, category = rng.choice(_BULK_VENDORS)
    item = rng.choice(_ITEMS_BY_CATEGORY[category])
    amount = round(rng.uniform(150, 9500), 2)
    return {
        "vendor_id": vendor_id,
        "amount": amount,
        "item": item,
        "department": rng.choice(_DEPARTMENTS),
        "notes": "",
    }


def _seeded_rows(rng: random.Random) -> list[dict]:
    split_amount = round(rng.uniform(9200, 9600), 2)
    return [
        {
            "vendor_id": "V-1003",
            "amount": round(rng.uniform(200, 800), 2),
            "item": "Printer paper, 20 boxes",
            "department": "facilities",
            "notes": "seed:blocked_vendor",
        },
        {
            "vendor_id": "V-1007",
            "amount": round(rng.uniform(2000, 6000), 2),
            "item": "Server rack hardware components",
            "department": "it",
            "notes": "seed:export_restricted_country",
        },
        {
            "vendor_id": "V-1001",
            "amount": round(rng.uniform(1500, 3000), 2),
            "item": "Laptop docks x10",
            "department": "engineering",
            "notes": "seed:vendor_compliance_hold",
        },
        {
            "vendor_id": "V-1010",
            "amount": round(rng.uniform(30, 100), 2),
            "item": "Visa gift cards for employee rewards program",
            "department": "marketing",
            "notes": "seed:prohibited_gift_cards",
        },
        {
            "vendor_id": "V-1006",
            "amount": round(rng.uniform(3000, 4500), 2),
            "item": "Annual SaaS subscription for CRM platform, auto-renews annually, 3-year initial term",
            "department": "it",
            "notes": "seed:software_auto_renew",
        },
        {
            "vendor_id": "V-1005",
            "amount": round(rng.uniform(70000, 80000), 2),
            "item": "Enterprise data center hardware refresh",
            "department": "it",
            "notes": "seed:large_capital_equipment",
        },
        {
            "vendor_id": "V-1009",
            "amount": round(rng.uniform(8000, 15000), 2),
            "item": "Independent contractor consulting services, 6-week engagement",
            "department": "engineering",
            "notes": "seed:professional_services_needs_sow",
        },
        # Split-PO pair — same vendor/item, both just under the $10,000
        # auto-approve band. Order matters: the first creates a PO the
        # second's lookup_vendor(recent_orders) can actually see.
        {
            "vendor_id": "V-1004",
            "amount": split_amount,
            "item": "Warehouse shelving units, phase 1",
            "department": "facilities",
            "notes": "seed:split_po_part_1",
        },
        {
            "vendor_id": "V-1004",
            "amount": round(split_amount - rng.uniform(10, 100), 2),
            "item": "Warehouse shelving units, phase 1",
            "department": "facilities",
            "notes": "seed:split_po_part_2",
        },
    ]


def generate(count: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    seeded = _seeded_rows(rng)
    n_bulk = max(0, count - len(seeded))
    bulk = [_bulk_row(rng) for _ in range(n_bulk)]

    # Scatter the seeded rows at random positions in the bulk list, except
    # keep the split-PO pair adjacent and in order (part_2 must come after
    # part_1, and inserting them independently could reverse or separate
    # them far enough that the demo narrative — "these look related" — is
    # lost).
    split_pair = seeded[-2:]
    singles = seeded[:-2]

    rows = list(bulk)
    for row in singles:
        idx = rng.randint(0, len(rows))
        rows.insert(idx, row)
    pair_idx = rng.randint(0, len(rows))
    rows[pair_idx:pair_idx] = split_pair

    for i, row in enumerate(rows):
        row["row_index"] = i
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "data" / "requests.csv")
    args = parser.parse_args()

    rows = generate(args.count, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["row_index", "vendor_id", "amount", "item", "department", "notes"]
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {args.out} (seed={args.seed})")


if __name__ == "__main__":
    main()
