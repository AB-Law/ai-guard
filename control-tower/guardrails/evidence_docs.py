"""Deterministic required-evidence presence check against retrieved chunk ids."""

from __future__ import annotations

from configs.loader import ProcessConfig

# Doc labels from process YAML → chunk-id prefixes produced by knowledge/rag.py.
_EVIDENCE_DOC_PREFIXES: dict[str, tuple[str, ...]] = {
    "procurement_policy": ("chunk:policy:",),
    "vendor_master_list": ("chunk:vendor:",),
    "kyc_policy": ("chunk:kyc:",),
    "finance_policy": ("chunk:policy:",),
    "risk_rating_policy": ("chunk:policy:",),
    "rag_bot_policy": ("chunk:policy:",),
}


def _doc_present(doc_id: str, chunk_ids: list[str]) -> bool:
    prefixes = _EVIDENCE_DOC_PREFIXES.get(doc_id)
    if prefixes is None:
        # Unknown label: treat as present only if any chunk id contains the label.
        needle = doc_id.lower()
        return any(needle in cid.lower() for cid in chunk_ids)
    return any(cid.startswith(prefix) for cid in chunk_ids for prefix in prefixes)


def missing_required_evidence_docs(
    config: ProcessConfig,
    chunk_ids: list[str],
) -> list[str]:
    """Return required_evidence_docs labels with no matching retrieved chunk id."""
    return [doc for doc in config.required_evidence_docs if not _doc_present(doc, chunk_ids)]
