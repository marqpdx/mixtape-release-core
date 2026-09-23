from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from sourcework.models import OpportunityProfile

from .contracts import OpportunitySearchProfile, OpportunitySourceObservation
from .text import html_to_readable_text


DICE_MCP_URL = "https://mcp.dice.com/mcp"
DICE_AI_DISCLOSURE = (
    "These job listings were found using AI-powered search. Please review all job details "
    "carefully and verify information directly with employers before applying."
)


class DiceMCPError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiceSearchBatch:
    observations: tuple[OpportunitySourceObservation, ...]
    query_results: tuple[dict[str, Any], ...]


class DiceMCPClient:
    """Small Streamable HTTP client for Dice's official public MCP server."""

    def __init__(self, *, endpoint: str = DICE_MCP_URL, timeout_seconds: float = 30.0):
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def search_jobs(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._call_tool("search_jobs", arguments)

    def get_job_details(self, job_id: str) -> dict[str, Any]:
        return self._call_tool("get_job_details", {"job_id": job_id})

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(
                self.endpoint,
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DiceMCPError(f"Dice MCP request failed: {exc}") from exc
        envelope = _parse_mcp_response(response.text)
        if envelope.get("error"):
            raise DiceMCPError(str(envelope["error"]))
        result = envelope.get("result") or {}
        if result.get("isError"):
            message = next(
                (item.get("text") for item in result.get("content", []) if item.get("type") == "text"),
                "Dice MCP tool returned an error.",
            )
            raise DiceMCPError(str(message))
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        for item in result.get("content", []):
            if item.get("type") == "text":
                try:
                    return json.loads(item.get("text") or "{}")
                except json.JSONDecodeError as exc:
                    raise DiceMCPError("Dice MCP returned malformed JSON content.") from exc
        raise DiceMCPError("Dice MCP returned no structured content.")


def plan_dice_queries(profile: OpportunityProfile) -> list[dict[str, Any]]:
    posted_date = "ONE" if profile.freshness_hours <= 24 else "THREE" if profile.freshness_hours <= 72 else "SEVEN"
    shared: dict[str, Any] = {
        "posted_date": posted_date,
        "sort": "datePosted",
        "jobs_per_page": min(max(int(profile.preferences.get("results_per_lane", 10)), 1), 25),
    }
    if profile.workplace_types:
        shared["workplace_types"] = profile.workplace_types
    if profile.employment_types:
        shared["employment_types"] = profile.employment_types
    if profile.preferences.get("search_location"):
        shared["location"] = profile.preferences["search_location"]
    if profile.preferences.get("radius") and shared.get("location"):
        shared["radius"] = int(profile.preferences["radius"])
        shared["radius_unit"] = profile.preferences.get("radius_unit", "mi")

    lanes = [lane for lane in profile.query_lanes if lane.get("enabled", True) and lane.get("keyword")]
    if not lanes:
        lanes = [
            {"id": f"role-{index + 1}", "label": role, "keyword": role, "enabled": True}
            for index, role in enumerate(profile.target_roles)
            if role
        ]
    return [
        {
            "lane_id": str(lane.get("id") or f"lane-{index + 1}"),
            "lane_label": str(lane.get("label") or lane["keyword"]),
            "arguments": {**shared, "keyword": str(lane["keyword"]).strip()},
        }
        for index, lane in enumerate(lanes)
    ]


def acquire_dice_search(profile: OpportunityProfile, *, client: DiceMCPClient | None = None) -> DiceSearchBatch:
    client = client or DiceMCPClient()
    retrieved_at = datetime.now(timezone.utc)
    observations_by_id: dict[str, OpportunitySourceObservation] = {}
    query_results: list[dict[str, Any]] = []

    for query in plan_dice_queries(profile):
        payload = client.search_jobs(query["arguments"])
        jobs = payload.get("data") or []
        metadata = payload.get("metadata") or {}
        query_results.append(
            {
                "lane_id": query["lane_id"],
                "lane_label": query["lane_label"],
                "arguments": query["arguments"],
                "returned": len(jobs),
                "available": metadata.get("total"),
                "search_id": metadata.get("searchId"),
            }
        )
        for job in jobs:
            external_id = str(job.get("guid") or job.get("id") or "").strip()
            if not external_id:
                continue
            raw = _normalize_search_result(job, query)
            observations_by_id[external_id] = OpportunitySourceObservation(
                provider="dice",
                external_id=external_id,
                canonical_url=str(job.get("detailsPageUrl") or ""),
                retrieved_at=retrieved_at,
                observed_at=_parse_datetime(job.get("postedDate")),
                relevant_text=str(job.get("summary") or ""),
                raw_payload=raw,
            )

    return DiceSearchBatch(tuple(observations_by_id.values()), tuple(query_results))


def profile_contract(profile: OpportunityProfile) -> OpportunitySearchProfile:
    return OpportunitySearchProfile(
        profile_id=str(profile.id),
        version=str(profile.version),
        geography=tuple(profile.geography),
        engagement_types=tuple(profile.employment_types),
        seniority=tuple(profile.seniority),
        strong_domains=tuple(profile.strong_domains),
        strong_technologies=tuple(profile.strong_technologies),
        exclusions=tuple(profile.exclusions),
        freshness_hours=profile.freshness_hours,
        overrides={
            "query_lanes": profile.query_lanes,
            "workplace_types": profile.workplace_types,
            "resume_label": profile.resume_label,
            "resume_version": profile.resume_version,
            "preferences": profile.preferences,
        },
    )


def _parse_mcp_response(body: str) -> dict[str, Any]:
    body = body.strip()
    if body.startswith("{"):
        return json.loads(body)
    data_lines = [line.removeprefix("data:").strip() for line in body.splitlines() if line.startswith("data:")]
    if not data_lines:
        raise DiceMCPError("Dice MCP returned an unsupported response envelope.")
    return json.loads(data_lines[-1])


def _normalize_search_result(job: dict[str, Any], query: dict[str, Any]) -> dict[str, Any]:
    workplace_types = list(job.get("workplaceTypes") or [])
    summary = str(job.get("summary") or "")
    return {
        **job,
        "title": job.get("title") or "",
        "organization": job.get("companyName") or "",
        "description": html_to_readable_text(summary),
        "arrangement": workplace_types[0] if len(workplace_types) == 1 else ", ".join(workplace_types),
        "required_location": (job.get("jobLocation") or {}).get("displayName", ""),
        "engagement_type": job.get("employmentType") or "",
        "compensation_min": None,
        "compensation_max": None,
        "compensation_unit": "",
        "posted_at": job.get("postedDate"),
        "updated_at": job.get("modifiedDate"),
        "listing_status": "live",
        "query_lane_id": query["lane_id"],
        "query_lane_label": query["lane_label"],
        "query_arguments": query["arguments"],
    }


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
