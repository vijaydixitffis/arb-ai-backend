"""
ARBGraphState — the single shared state object that flows through the LangGraph
StateGraph for one ARB review run.

LangGraph fans out one domain_agent_node invocation per domain slug via Send().
Each domain node writes its result into domain_results under its own slug key.
The merge_domain_results reducer merges these dicts as they arrive in parallel,
so the fan-in aggregate_node sees a fully populated dict regardless of arrival order.

failed_domains uses operator.add as its reducer so parallel nodes can append
independently without overwriting each other.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Optional

from typing_extensions import TypedDict


# ── Reducers ──────────────────────────────────────────────────────────────────

def _merge_dicts(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """Merge two dicts — used to accumulate parallel domain results."""
    return {**left, **right}


# ── State ─────────────────────────────────────────────────────────────────────

class ARBGraphState(TypedDict):
    # Set once by load_context_node; read-only for all subsequent nodes.
    review_id:      str
    solution_name:  str
    domains:        List[str]           # ordered domain slugs to evaluate
    checklist_data: Dict[str, Any]      # per-domain checklist items
    retry_domains:  Optional[List[str]] # when set, only these domains are run

    # Populated by parallel domain_agent_node invocations.
    # Reducer merges {slug: payload_dict} dicts from each parallel branch.
    domain_results: Annotated[Dict[str, Any], _merge_dicts]

    # Each domain node appends its slug here on failure.
    # operator.add concatenates lists from parallel branches safely.
    failed_domains: Annotated[List[str], operator.add]

    # Retry counts per domain slug — written by parallel domain nodes, merged by reducer.
    retry_counts:   Annotated[Dict[str, int], _merge_dicts]

    # Set by aggregate_node; read by synthesis_node and build_report_node.
    aggregate_score:    Optional[int]
    domain_scores:      Optional[Dict[str, int]]
    all_findings:       Optional[List[Dict[str, Any]]]
    all_blockers:       Optional[List[Dict[str, Any]]]
    all_actions:        Optional[List[Dict[str, Any]]]
    all_adrs:           Optional[List[Dict[str, Any]]]
    all_recommendations: Optional[List[Dict[str, Any]]]
    all_nfr_scorecard:  Optional[List[Dict[str, Any]]]
    kb_sources:         Optional[List[str]]
    total_tokens:       Optional[int]
    domain_summaries:   Optional[Dict[str, Any]]

    # Set by synthesis_node; read by build_report_node.
    synthesis_result: Optional[Dict[str, Any]]

    # Set by build_report_node; returned as run_review() output.
    final_report: Optional[Dict[str, Any]]
