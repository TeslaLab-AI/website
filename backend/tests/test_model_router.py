"""
Tests for Task 20: Model Router v1.

Comprehensive test suite verifying:
1. Triage -> Fast tier.
2. Classification -> Fast tier.
3. Planning -> Strong tier.
4. Diagnosis -> Strong tier.
5. Complex logic bug -> Reasoning tier.
6. Runtime override can request Reasoning tier.
7. Configuration is actually used for routing (custom config dynamically changes behavior).
8. Invalid / unknown task type is handled cleanly (graceful fallback to default tier).
9. Configuration can be reloaded without restarting (hot reload).
10. Feed at least 10 varied task requests and verify expected tiers.
11. Deterministic workload cost simulation showing > 60% savings compared to all-Strong baseline.
12. Complexity hint escalation.
13. Full completion integration with Task 19 LLMGateway.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import httpx
import pytest

from app.agents.agent_2.router.models import ModelRoute, ModelTier, RouterConfig, TierConfig
from app.agents.agent_2.router.router import ModelRouter, default_router, get_model_for_task
from app.agents.agent_2.gateway.models import LLMResponse
from app.agents.agent_2.gateway.adapters.openai_adapter import OpenAIAdapter
from app.agents.agent_2.gateway.adapters.anthropic_adapter import AnthropicAdapter
from app.agents.agent_2.gateway.adapters.deepseek_adapter import DeepSeekAdapter
from app.agents.agent_2.gateway.adapters.gemini_adapter import GeminiAdapter
from app.agents.agent_2.gateway.gateway import LLMGateway
from tests.test_llm_gateway import (
    make_openai_transport,
    make_anthropic_transport,
    make_deepseek_transport,
    make_gemini_transport,
)


class TestModelRouter:

    def test_01_triage_routes_to_fast_tier(self):
        """1. Triage -> Fast tier."""
        route = default_router.get_model_for_task("triage")
        assert route.tier == "fast"
        assert route.model == "gpt-4o-mini"
        assert route.provider == "openai"
        assert route.is_override is False

    def test_02_classification_routes_to_fast_tier(self):
        """2. Classification -> Fast tier."""
        route = default_router.get_model_for_task("classification")
        assert route.tier == "fast"
        assert route.model == "gpt-4o-mini"
        assert route.provider == "openai"

    def test_03_planning_routes_to_strong_tier(self):
        """3. Planning -> Strong tier."""
        route = default_router.get_model_for_task("planning")
        assert route.tier == "strong"
        assert route.model == "gpt-4o"
        assert route.provider == "openai"

    def test_04_diagnosis_routes_to_strong_tier(self):
        """4. Diagnosis -> Strong tier."""
        route = default_router.get_model_for_task("diagnosis")
        assert route.tier == "strong"
        assert route.model == "gpt-4o"
        assert route.provider == "openai"

    def test_05_complex_logic_bug_routes_to_reasoning_tier(self):
        """5. Complex logic bug -> Reasoning tier."""
        route = default_router.get_model_for_task("complex_logic_bug")
        assert route.tier == "reasoning"
        assert route.model == "deepseek-r1"
        assert route.provider == "deepseek"

    def test_06_runtime_override_can_request_reasoning_tier(self):
        """6. Runtime override can request Reasoning tier."""
        # Even for a triage task, runtime override must force the reasoning tier
        route = default_router.get_model_for_task(
            task_type="triage",
            override_tier="reasoning",
        )
        assert route.tier == "reasoning"
        assert route.model == "deepseek-r1"
        assert route.provider == "deepseek"
        assert route.is_override is True
        assert "override" in route.reason.lower()

        # Invalid override tier raises ValueError
        with pytest.raises(ValueError) as exc:
            default_router.get_model_for_task("triage", override_tier="super_quantum")
        assert "unknown override_tier" in str(exc.value).lower()

    def test_07_configuration_is_actually_used_for_routing(self):
        """7. Configuration is actually used for routing (not hardcoded)."""
        custom_config = {
            "default_tier": "fast",
            "tiers": {
                "fast": {
                    "primary_model": "claude-3-5-haiku",
                    "provider": "anthropic",
                    "fallback_model": "gpt-4o-mini",
                    "allowed_models": ["claude-3-5-haiku", "gpt-4o-mini"]
                },
                "strong": {
                    "primary_model": "claude-3-5-sonnet",
                    "provider": "anthropic",
                    "fallback_model": "gpt-4o",
                    "allowed_models": ["claude-3-5-sonnet", "gpt-4o"]
                },
                "reasoning": {
                    "primary_model": "o3-mini",
                    "provider": "openai",
                    "fallback_model": "deepseek-r1",
                    "allowed_models": ["o3-mini", "deepseek-r1"]
                }
            },
            "task_rules": {
                "triage": {"tier": "fast"},
                "planning": {"tier": "strong"},
                "complex_logic_bug": {"tier": "reasoning"}
            },
            "complexity_escalations": {}
        }

        router = ModelRouter(config=custom_config)

        # Fast maps to custom primary model claude-3-5-haiku
        route_fast = router.get_model_for_task("triage")
        assert route_fast.model == "claude-3-5-haiku"
        assert route_fast.provider == "anthropic"

        # Strong maps to claude-3-5-sonnet
        route_strong = router.get_model_for_task("planning")
        assert route_strong.model == "claude-3-5-sonnet"
        assert route_strong.provider == "anthropic"

        # Reasoning maps to o3-mini
        route_reasoning = router.get_model_for_task("complex_logic_bug")
        assert route_reasoning.model == "o3-mini"
        assert route_reasoning.provider == "openai"

    def test_08_invalid_unknown_task_type_is_handled_cleanly(self):
        """8. Invalid/unknown task type is handled cleanly (graceful fallback)."""
        route = default_router.get_model_for_task("nonexistent_exotic_task_xyz")
        assert route.tier == "strong"  # default_tier
        assert route.model == "gpt-4o"
        assert "defaulted" in route.reason.lower()
        assert route.is_override is False

    def test_09_configuration_can_be_reloaded_without_restarting(self):
        """9. Configuration can be reloaded without restarting (hot reload)."""
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False, encoding="utf-8") as tf:
            initial_cfg = {
                "default_tier": "strong",
                "tiers": {
                    "fast": {"primary_model": "gpt-4o-mini", "allowed_models": ["gpt-4o-mini"]},
                    "strong": {"primary_model": "gpt-4o", "allowed_models": ["gpt-4o"]},
                    "reasoning": {"primary_model": "deepseek-r1", "allowed_models": ["deepseek-r1"]},
                },
                "task_rules": {
                    "triage": {"tier": "fast"}
                }
            }
            json.dump(initial_cfg, tf)
            tf.flush()
            temp_path = Path(tf.name)

        try:
            router = ModelRouter(config_path=temp_path)
            assert router.get_model_for_task("triage").model == "gpt-4o-mini"

            # Modify config file on disk
            updated_cfg = {
                "default_tier": "strong",
                "tiers": {
                    "fast": {"primary_model": "deepseek-v3", "allowed_models": ["deepseek-v3"]},
                    "strong": {"primary_model": "claude-3-5-sonnet", "allowed_models": ["claude-3-5-sonnet"]},
                    "reasoning": {"primary_model": "o3-mini", "allowed_models": ["o3-mini"]},
                },
                "task_rules": {
                    "triage": {"tier": "fast"}
                }
            }
            temp_path.write_text(json.dumps(updated_cfg), encoding="utf-8")

            # Reload explicitly
            router.reload_config()
            new_route = router.get_model_for_task("triage")
            assert new_route.model == "deepseek-v3"
            assert new_route.provider == "deepseek"
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_10_feed_ten_varied_task_requests_and_verify_tiers(self):
        """10. Feed at least 10 varied task requests through the router and verify expected tiers."""
        ten_tasks = [
            ("triage", "fast", "gpt-4o-mini"),
            ("classification", "fast", "gpt-4o-mini"),
            ("tagging", "fast", "gpt-4o-mini"),
            ("summary", "fast", "gpt-4o-mini"),
            ("file_filter", "fast", "gpt-4o-mini"),
            ("planning", "strong", "gpt-4o"),
            ("diagnosis", "strong", "gpt-4o"),
            ("code_generation", "strong", "gpt-4o"),
            ("complex_logic_bug", "reasoning", "deepseek-r1"),
            ("race_condition", "reasoning", "deepseek-r1"),
        ]

        assert len(ten_tasks) >= 10

        results = []
        for task_name, expected_tier, expected_model in ten_tasks:
            route = default_router.get_model_for_task(task_name)
            assert route.tier == expected_tier, f"Task '{task_name}' expected tier {expected_tier}, got {route.tier}"
            assert route.model == expected_model, f"Task '{task_name}' expected model {expected_model}, got {route.model}"
            results.append((task_name, route.tier, route.model))

        assert len(results) == 10

    def test_11_cost_comparison_simulation_exceeds_60_percent_savings(self):
        """
        11. Cost comparison: Target > 60% cost reduction compared with using Strong tier for every task.
        Deterministic workload simulation across 10 varied tasks.
        """
        # Benchmark token pricing per 1M tokens (industry standard averages)
        # Fast (gpt-4o-mini): $0.15 input / $0.60 output -> ~$0.375 / 1M blended
        # Strong (gpt-4o): $2.50 input / $10.00 output -> ~$6.25 / 1M blended (~16.6x more expensive)
        # Reasoning (deepseek-r1): $0.55 input / $2.19 output -> ~$1.37 / 1M blended
        BLENDED_COST_PER_1K_TOKENS = {
            "fast": 0.000375,       # ~$0.375 / 1M tokens
            "strong": 0.006250,     # ~$6.250 / 1M tokens
            "reasoning": 0.001370,  # ~$1.370 / 1M tokens
        }

        # Workload simulation: 10 varied tasks in an automated maintenance pipeline
        # Fast tasks (triage, classification, tagging, summary, file_filter, diff_inspection)
        # Strong tasks (planning, diagnosis)
        # Reasoning tasks (complex_logic_bug, race_condition)
        workload = [
            {"task": "triage", "tokens": 1200},
            {"task": "classification", "tokens": 1000},
            {"task": "tagging", "tokens": 800},
            {"task": "summary", "tokens": 1500},
            {"task": "file_filter", "tokens": 900},
            {"task": "diff_inspection", "tokens": 1100},
            {"task": "planning", "tokens": 2000},
            {"task": "diagnosis", "tokens": 1800},
            {"task": "complex_logic_bug", "tokens": 2200},
            {"task": "race_condition", "tokens": 2500},
        ]

        total_baseline_cost = 0.0  # Option A: All tasks on Strong tier
        total_routed_cost = 0.0    # Option B: Tasks routed dynamically

        for item in workload:
            token_count = item["tokens"]
            thousands = token_count / 1000.0

            # Option A: Always Strong tier
            total_baseline_cost += thousands * BLENDED_COST_PER_1K_TOKENS["strong"]

            # Option B: Router decision
            route = default_router.get_model_for_task(item["task"])
            tier_rate = BLENDED_COST_PER_1K_TOKENS[route.tier]
            total_routed_cost += thousands * tier_rate

        savings = total_baseline_cost - total_routed_cost
        percentage_reduction = (savings / total_baseline_cost) * 100.0

        # Assert savings exceed the 60% requirement
        assert percentage_reduction > 60.0, f"Expected > 60% reduction, got {percentage_reduction:.2f}%"
        assert total_routed_cost < total_baseline_cost

    def test_12_complexity_hint_escalates_to_reasoning(self):
        """12. Complexity hint escalates diagnosis to reasoning tier."""
        # Diagnosis without complexity is Strong
        route_standard = default_router.get_model_for_task("diagnosis")
        assert route_standard.tier == "strong"

        # Diagnosis with complexity_hint="high" escalates to Reasoning
        route_high = default_router.get_model_for_task("diagnosis", complexity_hint="high")
        assert route_high.tier == "reasoning"
        assert route_high.model == "deepseek-r1"
        assert "escalated" in route_high.reason.lower()

    def test_13_router_complete_integrates_with_llm_gateway(self):
        """13. Router complete(...) routes and executes seamlessly via Task 19 LLMGateway."""
        mock_gateway = LLMGateway(
            adapters=[
                OpenAIAdapter(api_key="mock", http_client=httpx.Client(transport=make_openai_transport("Triage result"))),
                DeepSeekAdapter(api_key="mock", http_client=httpx.Client(transport=make_deepseek_transport("Reasoning result"))),
            ]
        )

        router = ModelRouter(gateway=mock_gateway)

        # Complete triage (routes to gpt-4o-mini)
        res_triage = router.complete(
            task_type="triage",
            messages=[{"role": "user", "content": "Triage this issue"}],
        )
        assert isinstance(res_triage, LLMResponse)
        assert res_triage.content == "Triage result"
        assert res_triage.model == "gpt-4o-mini"
        assert res_triage.provider == "openai"

        # Complete complex bug (routes to deepseek-r1 / deepseek-reasoner)
        res_complex = router.complete(
            task_type="complex_logic_bug",
            messages=[{"role": "user", "content": "Fix deadlock"}],
        )
        assert isinstance(res_complex, LLMResponse)
        assert res_complex.content == "Reasoning result"
        assert res_complex.model in ("deepseek-r1", "deepseek-reasoner")
        assert res_complex.provider == "deepseek"
