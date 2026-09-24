"""RAG / Chroma knowledge base with offline-safe deterministic embeddings."""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DIM = 64
_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)


class DeterministicHashEmbedding(EmbeddingFunction[Documents]):
    """Hash-bag embedding — no model download, stable offline retrieval."""

    def __init__(self, dim: int = _DIM) -> None:
        self._dim = dim

    @staticmethod
    def name() -> str:
        return "deterministic_hash"

    def get_config(self) -> dict:
        return {"dim": self._dim}

    @staticmethod
    def build_from_config(config: dict) -> DeterministicHashEmbedding:
        return DeterministicHashEmbedding(dim=int(config.get("dim", _DIM)))

    def __call__(self, input: Documents) -> Embeddings:
        return [self._embed_one(text) for text in input]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        tokens = _TOKEN_RE.findall(text.lower())
        if not tokens:
            tokens = ["empty"]
        for tok in tokens:
            digest = hashlib.sha256(tok.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self._dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]


@dataclass(frozen=True)
class RetrievedChunk:
    id: str
    text: str
    source: str


class KnowledgeBase:
    """In-memory Chroma index over procurement seed documents."""

    def __init__(self, collection_name: str = "aegis_kb") -> None:
        self._embedder = DeterministicHashEmbedding()
        self._client = chromadb.EphemeralClient()
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=self._embedder,
            metadata={"hnsw:space": "cosine"},
        )
        self._docs: dict[str, RetrievedChunk] = {}

    @property
    def size(self) -> int:
        return len(self._docs)

    def index_seed(self, paths: list[str | Path], *, project_root: Path | None = None) -> int:
        """Load and index documents from paths (relative to project_root)."""
        root = project_root or _PROJECT_ROOT
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict] = []

        for raw in paths:
            path = Path(raw)
            if not path.is_absolute():
                path = (root / path).resolve()
            if not path.is_file():
                continue
            for chunk_id, text, source in self._load_file(path):
                if chunk_id in self._docs:
                    continue
                self._docs[chunk_id] = RetrievedChunk(id=chunk_id, text=text, source=source)
                ids.append(chunk_id)
                documents.append(text)
                metadatas.append({"source": source})

        if ids:
            self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        return len(self._docs)

    def upsert_chunks(self, chunks: list[RetrievedChunk]) -> int:
        """Index arbitrary chunks (e.g. audit log entries) into the collection."""
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict] = []
        for chunk in chunks:
            self._docs[chunk.id] = chunk
            ids.append(chunk.id)
            documents.append(chunk.text)
            metadatas.append({"source": chunk.source})
        if ids:
            self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        return len(self._docs)

    def retrieve(self, query: str, k: int = 4) -> list[RetrievedChunk]:
        if not self._docs:
            return []
        n = min(k, len(self._docs))
        result = self._collection.query(query_texts=[query], n_results=n)
        ids = (result.get("ids") or [[]])[0]
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        chunks: list[RetrievedChunk] = []
        for i, chunk_id in enumerate(ids):
            text = docs[i] if i < len(docs) else self._docs[chunk_id].text
            source = ""
            if i < len(metas) and metas[i]:
                source = str(metas[i].get("source", ""))
            elif chunk_id in self._docs:
                source = self._docs[chunk_id].source
            chunks.append(RetrievedChunk(id=chunk_id, text=text, source=source))
        return chunks

    def get_by_id(self, chunk_id: str) -> RetrievedChunk | None:
        return self._docs.get(chunk_id)

    def all_chunks(self) -> list[RetrievedChunk]:
        """Every indexed chunk, in insertion order — lets a caller pull the
        full, small, bounded policy text deterministically instead of
        trusting semantic retrieval to surface every governing section."""
        return list(self._docs.values())

    def _load_file(self, path: Path) -> list[tuple[str, str, str]]:
        name = path.name.lower()
        source = str(path.relative_to(_PROJECT_ROOT)) if _PROJECT_ROOT in path.parents else path.name

        if name.endswith(".csv"):
            return self._load_vendor_csv(path, source)
        if "injected" in name or "malicious" in name:
            text = path.read_text(encoding="utf-8").strip()
            return [("chunk:injected:quote", text, source)]
        if name.endswith(".md") or "policy" in name:
            return self._load_policy_md(path, source)

        text = path.read_text(encoding="utf-8").strip()
        stem = path.stem.lower().replace(" ", "_")
        return [(f"chunk:doc:{stem}", text, source)]

    def _load_policy_md(self, path: Path, source: str) -> list[tuple[str, str, str]]:
        text = path.read_text(encoding="utf-8").strip()
        sections = re.split(r"\n(?=##\s)", text)
        stem = path.stem.lower()
        is_kyc = "kyc" in stem
        ns = "kyc" if is_kyc else "policy"
        out: list[tuple[str, str, str]] = []
        for i, section in enumerate(sections):
            section = section.strip()
            if not section:
                continue
            heading = section.split("\n", 1)[0].lower()
            if is_kyc and ("identity" in heading or "verif" in heading):
                chunk_id = f"chunk:{ns}:identity_verification"
            elif "auto-approv" in heading or "auto approv" in heading:
                chunk_id = f"chunk:{ns}:auto_approve"
            elif "escalat" in heading:
                chunk_id = f"chunk:{ns}:escalation"
            elif "required" in heading:
                chunk_id = f"chunk:{ns}:required_checks"
            else:
                # Unqualified fallback — must include the file stem or a second
                # uploaded doc whose section lands at the same index silently
                # collides with (and is dropped in favor of) an earlier one.
                chunk_id = f"chunk:{ns}:{stem}:section_{i}"
            out.append((chunk_id, section, source))
        if not out:
            out.append((f"chunk:{ns}:{stem}:full", text, source))
        return out

    def _load_vendor_csv(self, path: Path, source: str) -> list[tuple[str, str, str]]:
        out: list[tuple[str, str, str]] = []
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                vendor_id = (row.get("vendor_id") or "").strip()
                if not vendor_id:
                    continue
                text = (
                    f"Vendor {vendor_id}: name={row.get('name', '')}; "
                    f"status={row.get('status', '')}; country={row.get('country', '')}"
                )
                out.append((f"chunk:vendor:{vendor_id}", text, source))
        return out


UPLOADS_DIRNAME = "uploads"


def uploads_dir(project_root: Path | None = None, process: str | None = None) -> Path:
    """Directory for live uploads; process-scoped under data/uploads/<process>/."""
    root = project_root or _PROJECT_ROOT
    base = root / "data" / UPLOADS_DIRNAME
    if process is None:
        raise TypeError("uploads_dir() requires process= (per-process upload isolation)")
    return base / process


def _seed_pack_includes_injected_quote(knowledge_base_paths: list[str]) -> bool:
    """Demo injection fixture ships with the procurement seed pack (vendor master)."""
    return any("vendor_master" in Path(raw).name for raw in knowledge_base_paths)


def seed_paths_for_process(
    process: str, project_root: Path | None = None
) -> list[Path]:
    """KB seed paths for a single process: config paths, its uploads, and demo injection."""
    root = project_root or _PROJECT_ROOT
    from configs.loader import load_process

    config = load_process(process)
    paths: list[Path] = []
    seen: set[Path] = set()
    for raw in config.knowledge_base_paths:
        path = root / raw if not Path(raw).is_absolute() else Path(raw)
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            paths.append(path)
    if _seed_pack_includes_injected_quote(config.knowledge_base_paths):
        injected = root / "data" / "injected_quote_malicious.txt"
        if injected.is_file() and injected.resolve() not in seen:
            seen.add(injected.resolve())
            paths.append(injected)
    uploads = uploads_dir(root, process)
    if uploads.is_dir():
        for path in sorted(uploads.iterdir()):
            if path.is_file() and path.resolve() not in seen:
                seen.add(path.resolve())
                paths.append(path)
    return paths

def default_seed_paths(project_root: Path | None = None) -> list[Path]:
    """Union of all known process KB paths, injected quote, and process-scoped uploads."""
    root = project_root or _PROJECT_ROOT
    from configs.loader import KNOWN_PROCESSES

    paths: list[Path] = []
    seen: set[Path] = set()
    for name in KNOWN_PROCESSES:
        for path in seed_paths_for_process(name, root):
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                paths.append(path)
    return paths


def build_kb_for_process(
    process: str, project_root: Path | None = None
) -> KnowledgeBase:
    """Build an in-memory KB indexed only with that process's seed docs + uploads."""
    root = project_root or _PROJECT_ROOT
    kb = KnowledgeBase(collection_name=f"aegis_kb_{process}")
    kb.index_seed(seed_paths_for_process(process, root), project_root=root)
    return kb


def build_default_kb(project_root: Path | None = None) -> KnowledgeBase:
    """Full-corpus KB (all processes) — for investigation / legacy callers."""
    root = project_root or _PROJECT_ROOT
    kb = KnowledgeBase()
    kb.index_seed(default_seed_paths(root), project_root=root)
    return kb
