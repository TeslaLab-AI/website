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
        # Simulate investigation process for Task 5 Worker Resilience test
        
        # INVESTIGATING -> REPRODUCING
        time.sleep(1)
        event_bus.emit_sync(
            session_id=session_id,
            event_type=AgentEventType.SEARCHING_REPOSITORY,
            payload={"query": "find bug", "finding_id": finding_id},
            from_state=SessionState.INVESTIGATING,
            to_state=SessionState.REPRODUCING
        )
        
        # REPRODUCING -> ROOT_CAUSE
        time.sleep(1)
        event_bus.emit_sync(
            session_id=session_id,
            event_type=AgentEventType.READING_FILE,
            payload={"file": "simulated_file.ts"},
            from_state=SessionState.REPRODUCING,
            to_state=SessionState.ROOT_CAUSE
        )

        # ROOT_CAUSE -> PLANNING
        time.sleep(1)
        event_bus.emit_sync(
            session_id=session_id,
            event_type=AgentEventType.HYPOTHESIS_GENERATED,
            payload={"hypothesis": "Simulated root cause found by Celery background worker."},
            from_state=SessionState.ROOT_CAUSE,
            to_state=SessionState.PLANNING
        )
        
        return {"status": "success", "session_id": session_id}
        
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
