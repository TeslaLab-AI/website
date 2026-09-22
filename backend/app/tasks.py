import time
from typing import Any
from app.celery_app import celery_app
from app.contracts.schemas import SessionState, AgentEventType
from agents.agent_1 import event_bus

@celery_app.task(bind=True, max_retries=3, default_retry_delay=2)
def run_investigation_task(self, session_id: str, finding_id: str, workspace_id: str) -> dict[str, Any]:
    """
    Background worker task to run the investigation pipeline.
    """
    try:
        from agents.agent_1.diagnosis_agent import DiagnosisAgent
        
        agent = DiagnosisAgent(workspace_id=workspace_id)
        final_state = agent.execute_investigation(finding_id=finding_id, session_id=session_id)
        
        return {"status": "success", "session_id": session_id, "final_state_node": final_state.get("current_state")}
        
    except Exception as exc:
        try:
            self.retry(exc=exc, countdown=2 ** self.request.retries)
            return {"status": "retrying", "session_id": session_id}
        except self.MaxRetriesExceededError:
            # On absolute failure, transition to NEEDS_HUMAN
            event_bus.emit_sync(
                session_id=session_id,
                event_type=AgentEventType.STATE_TRANSITION,
                payload={"error": str(exc), "message": "Worker crashed or timed out."},
                from_state=SessionState.INVESTIGATING,
                to_state=SessionState.NEEDS_HUMAN
            )
            raise
