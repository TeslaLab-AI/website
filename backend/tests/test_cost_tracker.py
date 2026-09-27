"""
Unit and integration tests for Task 21: Cost Tracking & Budget Enforcement.
Verifies pricing calculations, session accumulations, gateway integration,
hard $0.50 budget enforcement, runaway session cutoffs, and NEEDS_HUMAN transitions.
"""

from unittest.mock import MagicMock
import pytest

from app.agents.agent_2.gateway.models import LLMMessage, LLMResponse, TokenUsage
from app.agents.agent_2.gateway.gateway import LLMGateway
from app.agents.agent_2.cost.pricing import (
    ModelPricing,
    PricingRegistry,
    default_pricing_registry,
)
from app.agents.agent_2.cost.calculator import CostCalculator
from app.agents.agent_2.cost.tracker import CostTracker, CostRecord
from app.agents.agent_2.cost.session_cost import SessionCostManager
from app.agents.agent_2.cost.budget import (
    BudgetEnforcer,
    BudgetExceededError,
    BudgetCutoffEvent,
    DEFAULT_TASK_BUDGET_USD,
)
from app.agents.agent_2.cost.persistence import CostPersistenceService


class MockAdapter:
    """Deterministic mock provider adapter for offline tests."""

    def __init__(self, provider_name: str, supported_models: list[str]) -> None:
        self.provider_name = provider_name
        self.supported_models = supported_models
        self.calls: list[dict] = []
        self.preset_response: LLMResponse | None = None

    def supports_model(self, model: str) -> bool:
        return any(m in model.lower() for m in self.supported_models)

    def complete(self, messages, model, **kwargs) -> LLMResponse:
        self.calls.append({"model": model, "messages": messages, "kwargs": kwargs})
        if self.preset_response:
            return self.preset_response
        return LLMResponse(
            content=f"Mock response from {self.provider_name} for {model}",
            model=model,
            provider=self.provider_name,
            usage=TokenUsage(prompt_tokens=1000, completion_tokens=500),
            latency_ms=12.5,
        )


class TestCostTrackerSuite:
    """Test suite covering all Task 21 requirements."""

    def setup_method(self) -> None:
        self.registry = PricingRegistry()
        self.calculator = CostCalculator(registry=self.registry)
        self.tracker = CostTracker(calculator=self.calculator, default_budget_limit_usd=0.50)
        self.enforcer = BudgetEnforcer(budget_limit_usd=0.50, calculator=self.calculator)

    # 1. Pricing input cost
    def test_01_pricing_input_cost(self) -> None:
        # gpt-4o: $2.50 per 1M prompt tokens -> 10,000 tokens = $0.025
        breakdown = self.calculator.calculate_cost("gpt-4o", prompt_tokens=10_000, completion_tokens=0)
        assert breakdown.prompt_cost_usd == pytest.approx(0.025, abs=1e-6)
        assert breakdown.completion_cost_usd == 0.0
        assert breakdown.cached_cost_usd == 0.0
        assert breakdown.total_cost_usd == pytest.approx(0.025, abs=1e-6)

    # 2. Pricing output cost
    def test_02_pricing_output_cost(self) -> None:
        # claude-3-5-sonnet: $15.00 per 1M completion tokens -> 2,000 tokens = $0.030
        breakdown = self.calculator.calculate_cost("claude-3-5-sonnet", prompt_tokens=0, completion_tokens=2_000)
        assert breakdown.prompt_cost_usd == 0.0
        assert breakdown.completion_cost_usd == pytest.approx(0.030, abs=1e-6)
        assert breakdown.total_cost_usd == pytest.approx(0.030, abs=1e-6)

    # 3. Cached token cost
    def test_03_cached_token_cost(self) -> None:
        # deepseek-v3: $0.14 per 1M prompt, $0.014 per 1M cached prompt
        # 10,000 prompt tokens with 8,000 cached:
        # Uncached prompt: 2,000 * 0.14/1M = $0.00028
        # Cached prompt: 8,000 * 0.014/1M = $0.000112
        # Total prompt cost = $0.000392
        breakdown = self.calculator.calculate_cost(
            "deepseek-v3", prompt_tokens=10_000, completion_tokens=0, cached_tokens=8_000
        )
        assert breakdown.cached_tokens == 8_000
        assert breakdown.cached_cost_usd == pytest.approx(0.000112, abs=1e-7)
        assert breakdown.prompt_cost_usd == pytest.approx(0.00028, abs=1e-7)
        assert breakdown.total_cost_usd == pytest.approx(0.000392, abs=1e-7)

    # 4. Combined call cost
    def test_04_combined_call_cost(self) -> None:
        # gemini-1.5-pro: $1.25/1M prompt, $5.00/1M completion, $0.3125/1M cached
        # 4,000 prompt (1,000 cached), 1,000 completion
        # Uncached prompt: 3,000 * 1.25/1M = $0.00375
        # Cached prompt: 1,000 * 0.3125/1M = $0.0003125
        # Completion: 1,000 * 5.00/1M = $0.005
        # Total = 0.00375 + 0.0003125 + 0.005 = 0.0090625
        breakdown = self.calculator.calculate_cost(
            "gemini-1.5-pro", prompt_tokens=4_000, completion_tokens=1_000, cached_tokens=1_000
        )
        assert breakdown.total_tokens == 5_000
        assert breakdown.total_cost_usd == pytest.approx(0.0090625, abs=1e-7)

    # 5. Unknown model error handling
    def test_05_unknown_model_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="No pricing configured"):
            self.calculator.calculate_cost("non_existent_super_llm_99", prompt_tokens=100)

    # 6. Session accumulation: single call
    def test_06_session_accumulation_single_call(self) -> None:
        rec = self.tracker.record_call(
            model="gpt-4o-mini",
            prompt_tokens=2_000,
            completion_tokens=1_000,
            session_id="session_alpha",
        )
        assert rec.session_id == "session_alpha"
        assert rec.cost_usd > 0.0

        summary = self.tracker.get_session_summary("session_alpha")
        assert summary.call_count == 1
        assert summary.total_prompt_tokens == 2_000
        assert summary.total_completion_tokens == 1_000
        assert summary.total_tokens == 3_000
        assert summary.total_cost_usd == pytest.approx(rec.cost_usd, abs=1e-7)
        assert summary.status == "active"

    # 7. Session accumulation: multiple calls
    def test_07_session_accumulation_multiple_calls(self) -> None:
        r1 = self.tracker.record_call("gpt-4o", prompt_tokens=1_000, completion_tokens=200, session_id="multi_sess")
        r2 = self.tracker.record_call("claude-3-5-sonnet", prompt_tokens=2_000, completion_tokens=500, session_id="multi_sess")
        r3 = self.tracker.record_call("deepseek-r1", prompt_tokens=4_000, completion_tokens=1_000, session_id="multi_sess")

        summary = self.tracker.get_session_summary("multi_sess")
        assert summary.call_count == 3
        assert summary.total_tokens == (1200 + 2500 + 5000)
        expected_cost = round(r1.cost_usd + r2.cost_usd + r3.cost_usd, 8)
        assert summary.total_cost_usd == pytest.approx(expected_cost, abs=1e-7)
        assert summary.remaining_budget_usd == pytest.approx(0.50 - expected_cost, abs=1e-6)

    # 8. Multiple concurrent sessions isolated
    def test_08_multiple_concurrent_sessions_isolated(self) -> None:
        mgr = SessionCostManager(default_budget_limit_usd=0.50)
        r_a = CostRecord(model="gpt-4o", provider="openai", prompt_tokens=100, completion_tokens=50, total_tokens=150, cost_usd=0.01, session_id="sess_A")
        r_b = CostRecord(model="claude-3-5-sonnet", provider="anthropic", prompt_tokens=500, completion_tokens=200, total_tokens=700, cost_usd=0.05, session_id="sess_B")

        mgr.record_call("sess_A", r_a)
        mgr.record_call("sess_B", r_b)

        sum_a = mgr.get_summary("sess_A")
        sum_b = mgr.get_summary("sess_B")

        assert sum_a.total_cost_usd == 0.01
        assert sum_b.total_cost_usd == 0.05
        assert sum_a.call_count == 1
        assert sum_b.call_count == 1

    # 9. Below-budget call allowed
    def test_09_below_budget_call_allowed(self) -> None:
        # Pre-seed session with $0.20 expenditure
        self.tracker.record_call("gpt-4o", prompt_tokens=40_000, completion_tokens=10_000, session_id="budget_pass")
        # Next call estimated at ~$0.01 -> well within $0.50 budget
        self.enforcer.check_budget(
            session_id="budget_pass",
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "analyze this test function"}],
            tracker=self.tracker,
        )
        # Should complete without error
        assert self.tracker.get_session_status("budget_pass") == "active"

    # 10. Exact budget condition triggers cutoff
    def test_10_exact_budget_condition_stops(self) -> None:
        # Create cost record that lands exactly at $0.50
        rec = CostRecord(
            model="gpt-4o",
            provider="openai",
            prompt_tokens=100_000,
            completion_tokens=25_000,
            total_tokens=125_000,
            cost_usd=0.50,
            session_id="exact_budget",
        )
        self.tracker._records.append(rec)
        self.tracker._session_records["exact_budget"] = [rec]

        summary = self.tracker.get_session_summary("exact_budget")
        assert summary.total_cost_usd == 0.50
        assert summary.is_budget_exceeded is True

        with pytest.raises(BudgetExceededError) as exc_info:
            self.enforcer.check_budget(
                session_id="exact_budget",
                model="gpt-4o-mini",
                tracker=self.tracker,
            )

        assert "reached hard budget limit of $0.50" in str(exc_info.value)
        assert self.tracker.get_session_status("exact_budget") == "NEEDS_HUMAN"

    # 11. Exceeding budget call blocked at gateway level
    def test_11_exceeding_budget_call_blocked_at_gateway(self) -> None:
        mock_adp = MockAdapter(provider_name="openai", supported_models=["gpt-4o", "gpt-4o-mini"])
        gw = LLMGateway(adapters=[mock_adp], cost_tracker=self.tracker, budget_enforcer=self.enforcer)

        # Pre-seed session with $0.49 spend
        rec = CostRecord(
            model="gpt-4o",
            provider="openai",
            prompt_tokens=98_000,
            completion_tokens=24_500,
            total_tokens=122_500,
            cost_usd=0.49,
            session_id="gateway_block_sess",
        )
        self.tracker._records.append(rec)
        self.tracker._session_records["gateway_block_sess"] = [rec]

        # Call with heavy projected tokens that will exceed remaining $0.01 balance
        with pytest.raises(BudgetExceededError) as exc_info:
            gw.complete(
                messages=[{"role": "user", "content": "X" * 20_000}],
                model="gpt-4o",
                session_id="gateway_block_sess",
                max_tokens=2048,
            )

        # Confirm adapter was NOT invoked (0 calls through adapter)
        assert len(mock_adp.calls) == 0
        assert self.tracker.get_session_status("gateway_block_sess") == "NEEDS_HUMAN"

    # 12. Gateway refuses any further calls after budget reached
    def test_12_gateway_refuses_after_budget_reached(self) -> None:
        mock_adp = MockAdapter(provider_name="openai", supported_models=["gpt-4o", "gpt-4o-mini"])
        gw = LLMGateway(adapters=[mock_adp], cost_tracker=self.tracker, budget_enforcer=self.enforcer)

        # Pre-seed session at $0.52 (exceeded)
        rec = CostRecord(
            model="gpt-4o",
            provider="openai",
            prompt_tokens=104_000,
            completion_tokens=26_000,
            total_tokens=130_000,
            cost_usd=0.52,
            session_id="spent_sess",
        )
        self.tracker._records.append(rec)
        self.tracker._session_records["spent_sess"] = [rec]
        self.tracker.set_session_status("spent_sess", "NEEDS_HUMAN")

        # Attempt 1: blocked
        with pytest.raises(BudgetExceededError):
            gw.complete([{"role": "user", "content": "hi"}], model="gpt-4o-mini", session_id="spent_sess")

        # Attempt 2: still blocked
        with pytest.raises(BudgetExceededError):
            gw.complete([{"role": "user", "content": "hello again"}], model="gpt-4o-mini", session_id="spent_sess")

        assert len(mock_adp.calls) == 0
        assert self.tracker.get_session_status("spent_sess") == "NEEDS_HUMAN"

    # 13. Cost records audit fields
    def test_13_cost_records_audit_fields(self) -> None:
        rec = self.tracker.record_call(
            model="claude-3-5-sonnet",
            prompt_tokens=5_000,
            completion_tokens=1_000,
            cached_tokens=2_000,
            provider="anthropic",
            session_id="audit_sess",
            latency_ms=145.2,
        )
        assert rec.call_id is not None
        assert rec.session_id == "audit_sess"
        assert rec.model == "claude-3-5-sonnet"
        assert rec.provider == "anthropic"
        assert rec.prompt_tokens == 5_000
        assert rec.completion_tokens == 1_000
        assert rec.cached_tokens == 2_000
        assert rec.total_tokens == 6_000
        assert rec.cost_usd > 0.0
        assert rec.latency_ms == 145.2
        assert "T" in rec.timestamp  # Valid ISO timestamp

    # 14. Persistence payload and NEEDS_HUMAN transition event
    def test_14_persistence_payload_and_needs_human_event(self) -> None:
        svc = CostPersistenceService(dry_run=True)
        cutoff = BudgetCutoffEvent(
            session_id="sess_persist",
            current_cost_usd=0.501,
            budget_limit_usd=0.50,
            attempted_model="gpt-4o",
            reason="Hard budget reached",
        )
        payload = svc.persist_cutoff_event(cutoff)

        assert payload["session_id"] == "sess_persist"
        assert payload["to_state"] == "NEEDS_HUMAN"
        assert payload["event_type"] == "BUDGET_EXCEEDED_CUTOFF"
        assert payload["payload"]["current_cost_usd"] == 0.501
        assert len(svc.persisted_events) == 1

    # 15. Five normal sessions demonstration (all below $0.50, active/completed)
    def test_15_five_normal_sessions_demonstration(self) -> None:
        normal_scenarios = [
            ("session_norm_1_triage", "gpt-4o-mini", 1200, 300),
            ("session_norm_2_planning", "gpt-4o", 2500, 800),
            ("session_norm_3_diag", "claude-3-5-sonnet", 3000, 1200),
            ("session_norm_4_deepseek", "deepseek-r1", 4000, 1500),
            ("session_norm_5_gemini", "gemini-1.5-pro", 3500, 1000),
        ]

        for sid, model, prompt_tok, comp_tok in normal_scenarios:
            rec = self.tracker.record_call(model=model, prompt_tokens=prompt_tok, completion_tokens=comp_tok, session_id=sid)
            summary = self.tracker.get_session_summary(sid)
            assert summary.call_count == 1
            assert summary.total_cost_usd < 0.50
            assert summary.is_budget_exceeded is False
            assert summary.status == "active"
            assert summary.remaining_budget_usd > 0.40

    # 16. Runaway session cutoff demonstration
    def test_16_runaway_session_cutoff_demonstration(self) -> None:
        """
        Simulate an automated repair loop where repeated replanning/calls
        accumulate cost until the $0.50 ceiling is breached.
        Verifies exact ceiling behavior, execution halt, and transition to NEEDS_HUMAN.
        """
        mock_adp = MockAdapter(provider_name="openai", supported_models=["gpt-4o"])
        gw = LLMGateway(adapters=[mock_adp], cost_tracker=self.tracker, budget_enforcer=self.enforcer)

        session_id = "runaway_loop_incident_842"
        # gpt-4o cost: 10,000 prompt ($0.025) + 2,500 comp ($0.025) = $0.050 per call
        mock_adp.preset_response = LLMResponse(
            content="Runaway replanning attempt",
            model="gpt-4o",
            provider="openai",
            usage=TokenUsage(prompt_tokens=10_000, completion_tokens=2_500),
            latency_ms=250.0,
        )

        successful_calls = 0
        # Loop up to 15 iterations: calls 1 to 10 accumulate $0.050 each -> exactly $0.500 total
        # Call 11 must be rejected by pre-call budget check!
        for i in range(15):
            try:
                gw.complete(
                    messages=[{"role": "user", "content": f"Replanning attempt {i+1}"}],
                    model="gpt-4o",
                    session_id=session_id,
                )
                successful_calls += 1
            except BudgetExceededError:
                break

        # Verification: Exactly 10 calls allowed (10 * $0.050 = $0.500)
        assert successful_calls == 10
        summary = self.tracker.get_session_summary(session_id)
        assert summary.total_cost_usd == pytest.approx(0.500, abs=1e-6)
        assert summary.call_count == 10
        assert summary.is_budget_exceeded is True
        assert summary.status == "NEEDS_HUMAN"

        # Further call is strictly rejected without reaching adapter
        with pytest.raises(BudgetExceededError) as exc_info:
            gw.complete(
                messages=[{"role": "user", "content": "Replanning attempt 12"}],
                model="gpt-4o",
                session_id=session_id,
            )
        assert "reached hard budget limit of $0.50" in str(exc_info.value)
        assert len(mock_adp.calls) == 10  # 11th call never reached adapter!

    # 17. Gateway call creates expected persistence payload
    def test_17_gateway_call_creates_expected_persistence_payload(self) -> None:
        mock_adp = MockAdapter(provider_name="openai", supported_models=["gpt-4o"])
        mock_adp.preset_response = LLMResponse(
            content="persistence payload test response",
            model="gpt-4o",
            provider="openai",
            usage=TokenUsage(prompt_tokens=1500, completion_tokens=350),
            latency_ms=45.0,
        )
        persistence = CostPersistenceService(dry_run=True)
        gw = LLMGateway(
            adapters=[mock_adp],
            cost_tracker=self.tracker,
            budget_enforcer=self.enforcer,
            persistence_service=persistence,
        )

        gw.complete(
            messages=[{"role": "user", "content": "test message"}],
            model="gpt-4o",
            session_id="persist_payload_session",
            cached_tokens=250,
        )

        assert len(persistence.persisted_events) == 1
        event = persistence.persisted_events[0]
        assert event["session_id"] == "persist_payload_session"
        assert event["event_type"] == "LLM_CALL_COST"
        assert event["from_state"] == "active"
        assert event["to_state"] == "active"

        payload = event["payload"]
        assert payload["session_id"] == "persist_payload_session"
        assert payload["model"] == "gpt-4o"
        assert payload["prompt_tokens"] == 1500
        assert payload["completion_tokens"] == 350
        assert payload["cached_tokens"] == 250
        assert payload["cost_usd"] > 0.0

    # 18. Gateway invokes persistence service after cost calculation
    def test_18_gateway_invokes_persistence_service_after_cost_calculation(self) -> None:
        mock_adp = MockAdapter(provider_name="openai", supported_models=["gpt-4o"])
        mock_adp.preset_response = LLMResponse(
            content="cost calculated response",
            model="gpt-4o",
            provider="openai",
            usage=TokenUsage(prompt_tokens=2000, completion_tokens=500),
            latency_ms=60.0,
        )
        persistence = CostPersistenceService(dry_run=True)
        persistence.persist_call_event = MagicMock(wraps=persistence.persist_call_event)
        persistence.persist_session_summary = MagicMock(wraps=persistence.persist_session_summary)

        gw = LLMGateway(
            adapters=[mock_adp],
            cost_tracker=self.tracker,
            budget_enforcer=self.enforcer,
            persistence_service=persistence,
        )

        resp = gw.complete(
            messages=[{"role": "user", "content": "analyze code"}],
            model="gpt-4o",
            session_id="calc_invoke_session",
        )

        # Confirm cost calculation was attached to response before persistence
        assert resp.cost_usd > 0.0

        # Confirm persistence service was invoked with the exact computed cost
        assert persistence.persist_call_event.call_count == 1
        call_arg = persistence.persist_call_event.call_args[0][0]
        assert isinstance(call_arg, CostRecord)
        assert call_arg.cost_usd == resp.cost_usd
        assert call_arg.session_id == "calc_invoke_session"

        # Confirm session summary was persisted
        assert persistence.persist_session_summary.call_count == 1
        summary_arg = persistence.persist_session_summary.call_args[0][0]
        assert summary_arg.session_id == "calc_invoke_session"
        assert summary_arg.total_cost_usd == resp.cost_usd

    # 19. Session summary receives accumulated cost and token information
    def test_19_session_summary_receives_accumulated_cost_and_token_info(self) -> None:
        from app.agents.agent_1 import pipeline_event_bus as event_bus
        event_bus.init_run("accum_sess_100", "finding_100", "repo_100")

        mock_adp = MockAdapter(provider_name="openai", supported_models=["gpt-4o"])
        persistence = CostPersistenceService(dry_run=True)
        gw = LLMGateway(
            adapters=[mock_adp],
            cost_tracker=self.tracker,
            budget_enforcer=self.enforcer,
            persistence_service=persistence,
        )

        mock_adp.preset_response = LLMResponse(
            content="call 1",
            model="gpt-4o",
            provider="openai",
            usage=TokenUsage(prompt_tokens=1000, completion_tokens=200),
            latency_ms=30.0,
        )
        gw.complete([{"role": "user", "content": "1"}], model="gpt-4o", session_id="accum_sess_100", cached_tokens=100)

        mock_adp.preset_response = LLMResponse(
            content="call 2",
            model="gpt-4o",
            provider="openai",
            usage=TokenUsage(prompt_tokens=2000, completion_tokens=300),
            latency_ms=40.0,
        )
        gw.complete([{"role": "user", "content": "2"}], model="gpt-4o", session_id="accum_sess_100", cached_tokens=200)

        assert len(persistence.persisted_summaries) == 2
        latest_summary = persistence.persisted_summaries[-1]
        assert latest_summary["session_id"] == "accum_sess_100"
        assert latest_summary["call_count"] == 2
        assert latest_summary["total_prompt_tokens"] == 3000
        assert latest_summary["total_completion_tokens"] == 500
        assert latest_summary["total_cached_tokens"] == 300
        assert latest_summary["total_tokens"] == 3500
        assert latest_summary["total_cost_usd"] > 0.0

        # Verify event_bus run received cost summary
        bus_run = event_bus.get_run("accum_sess_100")
        assert bus_run is not None
        assert "cost_summary" in bus_run
        assert bus_run["cost_summary"]["call_count"] == 2
        assert bus_run["cost_summary"]["total_tokens"] == 3500

    # 20. Existing $0.50 hard cutoff still blocks provider before execution with persistence
    def test_20_existing_hard_cutoff_blocks_provider_before_execution_with_persistence(self) -> None:
        persistence = CostPersistenceService(dry_run=True)
        enforcer = BudgetEnforcer(budget_limit_usd=0.50, calculator=self.calculator, persistence_service=persistence)
        mock_adp = MockAdapter(provider_name="openai", supported_models=["gpt-4o"])
        gw = LLMGateway(
            adapters=[mock_adp],
            cost_tracker=self.tracker,
            budget_enforcer=enforcer,
            persistence_service=persistence,
        )

        # Pre-seed session with $0.50 spend
        rec = CostRecord(
            model="gpt-4o",
            provider="openai",
            prompt_tokens=100_000,
            completion_tokens=25_000,
            total_tokens=125_000,
            cost_usd=0.50,
            session_id="blocked_before_exec_sess",
        )
        self.tracker._records.append(rec)
        self.tracker._session_records["blocked_before_exec_sess"] = [rec]

        with pytest.raises(BudgetExceededError):
            gw.complete(
                messages=[{"role": "user", "content": "should never reach adapter"}],
                model="gpt-4o",
                session_id="blocked_before_exec_sess",
            )

        # Provider must NOT have been called
        assert len(mock_adp.calls) == 0

        # Cutoff event must be persisted to agent_events with NEEDS_HUMAN
        cutoff_events = [e for e in persistence.persisted_events if e["event_type"] == "BUDGET_EXCEEDED_CUTOFF"]
        assert len(cutoff_events) == 1
        assert cutoff_events[0]["session_id"] == "blocked_before_exec_sess"
        assert cutoff_events[0]["to_state"] == "NEEDS_HUMAN"
        assert cutoff_events[0]["payload"]["current_cost_usd"] == 0.50

    # 21. Existing NEEDS_HUMAN transition remains unchanged
    def test_21_existing_needs_human_transition_remains_unchanged(self) -> None:
        from app.agents.agent_1 import pipeline_event_bus as event_bus
        event_bus.init_run("needs_human_run_77", "finding_77", "repo_77")

        persistence = CostPersistenceService(dry_run=True)
        enforcer = BudgetEnforcer(budget_limit_usd=0.50, calculator=self.calculator, persistence_service=persistence)

        # Trigger cutoff via enforcer
        with pytest.raises(BudgetExceededError) as exc_info:
            enforcer._trigger_cutoff(
                session_id="needs_human_run_77",
                current_cost=0.505,
                budget_limit=0.50,
                model="gpt-4o",
                tracker=self.tracker,
                reason="Ceiling breached",
            )

        # Check terminal exception fields
        err = exc_info.value
        assert err.retryable is False
        assert err.status_code == 402
        assert err.model == "gpt-4o"

        # Check tracker session status
        assert self.tracker.get_session_status("needs_human_run_77") == "NEEDS_HUMAN"

        # Check event_bus status and phase
        run = event_bus.get_run("needs_human_run_77")
        assert run is not None
        assert run["status"] == "NEEDS_HUMAN"
        assert run["phase"] == "NEEDS_HUMAN"
        assert any("[NEEDS_HUMAN]" in log["message"] for log in run["logs"])
