"""
LangGraphARBOrchestrator — drop-in replacement for EnhancedARBOrchestrator.

Public interface (identical signatures):
  async run_review(review_id, checklist_data, retry_domains=None) -> Dict[str, Any]
  async prepare_checklist_data(review_id)                         -> Dict[str, Any]

Graph topology:
  START
    → load_context_node
    → [Send("domain_agent", …) × N domains]         ← parallel fan-out
    → domain_agent_node (N parallel invocations, semaphore-capped)
    → aggregate_node                                ← fan-in join
    → synthesis_node
    → build_report_node
  END

Checkpointing:
  thread_id = review_id  →  a crashed run resumes from the last committed
  checkpoint when re-triggered with the same review_id.

  LANGGRAPH_CHECKPOINT_DB=true   → PostgresSaver (durable, same DATABASE_URL)
  LANGGRAPH_CHECKPOINT_DB=false  → MemorySaver   (in-process, dev/test)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from sqlalchemy.orm import Session

from app.agents.langgraph_orchestrator.nodes import (
    aggregate_node,
    build_report_node,
    domain_agent_node,
    load_context_node,
    route_to_domains,
    synthesis_node,
)
from app.agents.langgraph_orchestrator.rate_limiter import DomainRateLimiter
from app.agents.langgraph_orchestrator.state import ARBGraphState
from app.core.config import settings

logger = logging.getLogger(__name__)


class LangGraphARBOrchestrator:
    """Parallel ARB orchestrator built on LangGraph StateGraph."""

    def __init__(self, db: Session) -> None:
        self.db              = db
        self.rate_limiter    = DomainRateLimiter(settings.LANGGRAPH_MAX_PARALLEL)
        # Build once uncompiled — checkpointer is injected per-run in run_review()
        # so AsyncPostgresSaver's async context manager is honoured correctly.
        self._uncompiled     = self._build_uncompiled_graph()

    # ── Public interface (matches EnhancedARBOrchestrator) ────────────────────

    async def run_review(
        self,
        review_id: str,
        checklist_data: Dict[str, Any],
        retry_domains: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Run a full ARB review and return the merged report dict."""
        t0 = time.time()
        logger.info(
            f"[LG] run_review start review_id={review_id} "
            f"max_parallel={settings.LANGGRAPH_MAX_PARALLEL}"
            + (f" retry_domains={retry_domains}" if retry_domains else "")
        )

        # thread_id ties this run to a checkpoint stream keyed by review_id.
        # A re-trigger of the same review_id resumes from the last checkpoint.
        graph_config = {
            "configurable": {
                "thread_id":    review_id,
                "db":           self.db,
                "rate_limiter": self.rate_limiter,
            }
        }

        initial_state: ARBGraphState = {
            "review_id":         review_id,
            "solution_name":     "",
            "domains":           [],
            "checklist_data":    checklist_data,
            "domain_results":    {},
            "failed_domains":    [],
            "retry_counts":      {},
            "aggregate_score":   None,
            "domain_scores":     None,
            "all_findings":      None,
            "all_blockers":      None,
            "all_actions":       None,
            "all_adrs":          None,
            "all_recommendations": None,
            "all_nfr_scorecard": None,
            "kb_sources":        None,
            "total_tokens":      None,
            "domain_summaries":  None,
            "synthesis_result":  None,
            "final_report":      None,
        }

        if settings.LANGGRAPH_CHECKPOINT_DB:
            try:
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
                async with AsyncPostgresSaver.from_conn_string(settings.DATABASE_URL) as saver:
                    await saver.setup()
                    graph = self._uncompiled.compile(checkpointer=saver)
                    final_state = await graph.ainvoke(initial_state, config=graph_config)
            except Exception as exc:
                logger.warning(f"[LG] PostgresSaver failed ({exc}) — falling back to MemorySaver")
                from langgraph.checkpoint.memory import MemorySaver
                graph = self._uncompiled.compile(checkpointer=MemorySaver())
                final_state = await graph.ainvoke(initial_state, config=graph_config)
        else:
            from langgraph.checkpoint.memory import MemorySaver
            graph = self._uncompiled.compile(checkpointer=MemorySaver())
            final_state = await graph.ainvoke(initial_state, config=graph_config)

        elapsed = time.time() - t0
        report = final_state.get("final_report") or {}
        if not report:
            raise RuntimeError(
                f"[LG] Graph completed but final_report is empty for review={review_id}. "
                "Check that all domain Send targets match registered node names."
            )
        logger.info(
            f"[LG] run_review done review_id={review_id} "
            f"decision={report.get('decision')} elapsed={elapsed:.2f}s"
        )
        return report

    async def prepare_checklist_data(self, review_id: str) -> Dict[str, Any]:
        """Delegate to the existing orchestrator — identical logic, no duplication."""
        from app.agents.enhanced_orchestrator import EnhancedARBOrchestrator
        return await EnhancedARBOrchestrator(self.db).prepare_checklist_data(review_id)

    # ── Graph construction ────────────────────────────────────────────────────

    def _build_uncompiled_graph(self) -> StateGraph:
        """Build the StateGraph topology without compiling or attaching a checkpointer.

        The compiled graph (with checkpointer injected) is created per-run inside
        run_review() so that AsyncPostgresSaver's async context manager is used correctly.
        """
        g = StateGraph(ARBGraphState)

        g.add_node("load_context",  load_context_node)
        g.add_node("domain_agent",  domain_agent_node)
        g.add_node("aggregate",     aggregate_node)
        g.add_node("synthesis",     synthesis_node)
        g.add_node("build_report",  build_report_node)

        g.add_edge(START, "load_context")

        # Fan-out: load_context → N parallel domain_agent invocations via Send.
        g.add_conditional_edges("load_context", route_to_domains, ["domain_agent"])

        # Fan-in: all domain_agent branches converge on aggregate.
        g.add_edge("domain_agent", "aggregate")
        g.add_edge("aggregate",    "synthesis")
        g.add_edge("synthesis",    "build_report")
        g.add_edge("build_report", END)

        return g
