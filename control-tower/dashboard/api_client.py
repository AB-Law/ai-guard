"""HTTP client for the Aegis FastAPI control tower."""

from __future__ import annotations

from typing import Any

import httpx


class AegisApiClient:
    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def health(self) -> dict[str, Any]:
        resp = httpx.get(self._url("/health"), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def list_cases(self) -> list[dict[str, Any]]:
        resp = httpx.get(self._url("/cases"), timeout=self.timeout)
        resp.raise_for_status()
        return list(resp.json().get("cases") or [])

    def get_case(self, case_id: str) -> dict[str, Any]:
        resp = httpx.get(self._url(f"/cases/{case_id}"), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_audit(self, case_id: str) -> dict[str, Any]:
        resp = httpx.get(self._url(f"/cases/{case_id}/audit"), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def verify_audit(self) -> dict[str, Any]:
        resp = httpx.get(self._url("/audit/verify"), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def submit_case(
        self,
        *,
        process: str,
        request: dict[str, Any],
        mock_agent_plan: dict[str, Any] | None = None,
        force_chunk_ids: list[str] | None = None,
        case_id: str | None = None,
        source_app: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"process": process, "request": request}
        if mock_agent_plan is not None:
            payload["mock_agent_plan"] = mock_agent_plan
        if force_chunk_ids is not None:
            payload["force_chunk_ids"] = force_chunk_ids
        if case_id is not None:
            payload["case_id"] = case_id
        if source_app is not None:
            payload["source_app"] = source_app
        resp = httpx.post(self._url("/cases"), json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def seed_demo(self) -> dict[str, Any]:
        """POST /demo/seed — reset + load rehearsal pack (escalate left pending)."""
        resp = httpx.post(self._url("/demo/seed"), timeout=max(self.timeout, 60.0))
        resp.raise_for_status()
        return resp.json()

    def reset_demo(self) -> dict[str, Any]:
        resp = httpx.post(self._url("/demo/reset"), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def investigate(
        self,
        question: str,
        *,
        case_id: str | None = None,
        mock_answer: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"question": question}
        if case_id:
            payload["case_id"] = case_id
        if mock_answer is not None:
            payload["mock_answer"] = mock_answer
        resp = httpx.post(
            self._url("/investigate"),
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def traffic_recent(
        self,
        *,
        limit: int = 100,
        since_minutes: int | None = None,
        source_app: str | None = None,
        decision: str | None = None,
    ) -> dict[str, Any]:
        """GET /traffic/recent — pipeline rows + matched/total metadata."""
        params: dict[str, Any] = {"limit": limit}
        if since_minutes is not None:
            params["since_minutes"] = since_minutes
        if source_app:
            params["source_app"] = source_app
        if decision:
            params["decision"] = decision
        resp = httpx.get(
            self._url("/traffic/recent"), params=params, timeout=self.timeout
        )
        resp.raise_for_status()
        body = resp.json()
        cases = list(body.get("cases") or [])
        # Older APIs omit ``matched``; never report 0 when rows are present.
        matched_raw = body.get("matched")
        matched = len(cases) if matched_raw is None else int(matched_raw)
        matched = max(matched, len(cases))
        return {
            "cases": cases,
            "total_cases": int(body.get("total_cases") or 0),
            "matched": matched,
            "since_minutes": body.get("since_minutes"),
            "limit": int(body.get("limit") or limit),
        }

    def upload_document(
        self, filename: str, content: bytes, *, process: str
    ) -> dict[str, Any]:
        resp = httpx.post(
            self._url("/knowledge/documents"),
            files={"file": (filename, content)},
            data={"process": process},
            timeout=max(self.timeout, 30.0),
        )
        resp.raise_for_status()
        return resp.json()

    def approve(self, call_id: str, *, action: str, actor: str) -> dict[str, Any]:
        resp = httpx.post(
            self._url(f"/approvals/{call_id}"),
            json={"action": action, "actor": actor},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()
