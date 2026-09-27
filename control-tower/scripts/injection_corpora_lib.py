"""Live loaders for third-party prompt-injection corpora.

Fetched over the network — nothing here is vendored. Used by
``scripts/eval_injection_corpora.py``; see ``reports/injection_corpora_eval.md``
for the generated report and rationale.

Each HTTP response can be cached to disk (``cache_dir``) so re-running the
eval — locally, or across CI runs when that directory is restored via
``actions/cache`` — doesn't re-hit HuggingFace/GitHub for data that rarely
changes. Pass ``cache_dir=None`` (the default) to always fetch fresh.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_TIMEOUT = 20.0
_HF_ROWS_URL = "https://datasets-server.huggingface.co/rows"
_INJECAGENT_BASE = "https://raw.githubusercontent.com/uiuc-kang-lab/InjecAgent/main/data"

# AgentDojo's injection tasks carry only the attacker's goal text (its own
# harness delivers that goal via a full simulated tool-call environment we
# don't run here). Dropping it into a generic tool-response envelope lets it
# be scanned the same way as the other two corpora's real tool-response text.
_AGENTDOJO_TEMPLATE = '{{"result": "ok", "content": "Note: {injection}"}}'


@dataclass
class CorpusCase:
    id: str
    text: str
    label: bool  # True = known injection/attack
    source: str
    meta: dict[str, Any] = field(default_factory=dict)


def _cache_path(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"


def _get_json(url: str, cache_dir: Path | None = None) -> Any:
    if cache_dir is not None:
        path = _cache_path(cache_dir, url)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))

    with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
        data = json.load(resp)

    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        _cache_path(cache_dir, url).write_text(
            json.dumps(data), encoding="utf-8"
        )
    return data


def fetch_deepset_prompt_injections(
    split: str = "test", *, cache_dir: Path | None = None
) -> list[CorpusCase]:
    """``deepset/prompt-injections`` via the HF datasets-server rows API.

    Avoids the ``datasets`` package dependency for a two-column CSV-shaped
    corpus. Has real negatives (label 0), so precision and recall both apply.
    """
    cases: list[CorpusCase] = []
    offset = 0
    while True:
        url = (
            f"{_HF_ROWS_URL}?dataset=deepset%2Fprompt-injections&config=default"
            f"&split={split}&offset={offset}&length=100"
        )
        page = _get_json(url, cache_dir=cache_dir)
        for row in page["rows"]:
            r = row["row"]
            cases.append(
                CorpusCase(
                    id=f"deepset-{split}-{row['row_idx']}",
                    text=str(r["text"]),
                    label=bool(r["label"]),
                    source="deepset/prompt-injections",
                    meta={"split": split},
                )
            )
        offset += 100
        if offset >= page["num_rows_total"]:
            break
    return cases


def fetch_injecagent_cases(
    file: str = "test_cases_dh_base",
    limit: int | None = None,
    *,
    cache_dir: Path | None = None,
) -> list[CorpusCase]:
    """InjecAgent tool-response attacks — indirect injection via contaminated
    tool output. Every row is a known attack; there are no negatives, so
    only recall / detection-rate is meaningful here.
    """
    url = f"{_INJECAGENT_BASE}/{file}.json"
    rows = _get_json(url, cache_dir=cache_dir)
    if limit is not None:
        rows = rows[:limit]
    return [
        CorpusCase(
            id=f"injecagent-{file}-{i}",
            text=str(row.get("Tool Response", "")),
            label=True,
            source="InjecAgent",
            meta={
                "attack_type": row.get("Attack Type"),
                "user_tool": row.get("User Tool"),
                "modified": row.get("Modifed"),
            },
        )
        for i, row in enumerate(rows)
    ]


def fetch_agentdojo_injection_cases(version: str = "v1.2.1") -> list[CorpusCase]:
    """AgentDojo injection-task goals across its banking/travel/workspace/slack
    suites, synthesized into tool-response-shaped text. Requires the optional
    ``agentdojo`` package (``pip install -e ".[corpora]"``); raises
    ``ImportError`` if it isn't installed so callers can skip gracefully.

    Every case is a known attack — recall / detection-rate only, same as
    InjecAgent above.
    """
    from agentdojo.task_suite.load_suites import get_suites

    cases: list[CorpusCase] = []
    for suite_name, suite in get_suites(version).items():
        tool_name = next(iter(suite.tools)).name if suite.tools else "unknown_tool"
        for task_id, task in suite.injection_tasks.items():
            goal = (getattr(task, "GOAL", "") or "").strip()
            if not goal:
                continue
            cases.append(
                CorpusCase(
                    id=f"agentdojo-{suite_name}-{task_id}",
                    text=_AGENTDOJO_TEMPLATE.format(injection=goal),
                    label=True,
                    source="AgentDojo",
                    meta={"suite": suite_name, "tool_name": tool_name},
                )
            )
    return cases
