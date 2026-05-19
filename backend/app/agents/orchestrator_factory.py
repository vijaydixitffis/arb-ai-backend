"""
Orchestrator factory — returns the correct orchestrator based on AGENT_FRAMEWORK.

  AGENT_FRAMEWORK=custom     → EnhancedARBOrchestrator  (existing, sequential)
  AGENT_FRAMEWORK=langgraph  → LangGraphARBOrchestrator (parallel fan-out)

The two orchestrators share the same public interface:
  async run_review(review_id, checklist_data, retry_domains) -> Dict[str, Any]
  async prepare_checklist_data(review_id)                    -> Dict[str, Any]
"""

from sqlalchemy.orm import Session

from app.core.config import settings


def get_orchestrator(db: Session):
    framework = settings.AGENT_FRAMEWORK.strip().lower()
    if framework == "langgraph":
        from app.agents.langgraph_orchestrator.graph import LangGraphARBOrchestrator
        return LangGraphARBOrchestrator(db)
    from app.agents.enhanced_orchestrator import EnhancedARBOrchestrator
    return EnhancedARBOrchestrator(db)
