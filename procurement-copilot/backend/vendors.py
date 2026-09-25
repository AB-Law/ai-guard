"""Local vendor master data for this app — deliberately NOT imported from the
control-tower repo. This app knows nothing about Aegis's policy; it only
knows the vendors it buys from. Mirrors the shape (not the file) of the
tower's own demo vendor_master.csv so results line up across both UIs during
a demo, but that's a coincidence of picking realistic test data, not a
dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

DEPARTMENTS = ["engineering", "marketing", "facilities", "sales", "it"]


@dataclass(frozen=True)
class Vendor:
    vendor_id: str
    name: str
    status: str  # active | blocked
    country: str
    category: str  # loose hint used by the demo data generator, not by tools


VENDORS: dict[str, Vendor] = {
    v.vendor_id: v
    for v in [
        Vendor("V-1001", "Acme Supplies Ltd", "active", "US", "office"),
        Vendor("V-1002", "Global Parts Inc", "active", "UK", "hardware"),
        Vendor("V-1003", "Blocked Vendor Co", "blocked", "US", "office"),
        Vendor("V-1004", "Northwind Traders", "active", "CA", "hardware"),
        Vendor("V-1005", "Contoso Hardware", "active", "US", "hardware"),
        Vendor("V-1006", "Fabrikam IT", "active", "DE", "software"),
        Vendor("V-1007", "Yalu Trading Co", "active", "KP", "hardware"),
        Vendor("V-1008", "Nimbus Cloud Systems", "active", "US", "software"),
        Vendor("V-1009", "Brightline Consulting", "active", "US", "services"),
        Vendor("V-1010", "Parcel & Post Supply", "active", "US", "office"),
    ]
}


def lookup(vendor_id: str) -> Vendor | None:
    return VENDORS.get(vendor_id)
