# Task 21: Cost Tracking & Hard Budget Enforcement — Evaluation Evidence

**Engineer 2 — Planning & Execution Lead**  
**Repository:** TeslaLab-AI/website  
**Branch:** `agent-2-day2`  
**Base Commit:** `574795c` (Completed Task 19 & 20 state)  

---

## 1. Overview & Objectives Accomplished

Task 21 establishes financial visibility, cost tracking, and deterministic budget safety policies for Agent 2:
- **Centralized Model Pricing Configuration:**
  Full token pricing table covering all supported models across OpenAI, Anthropic, DeepSeek, and Google Gemini with support for prompt tokens, completion tokens, and cached tokens.
- **Deterministic Cost Calculator:**
  Exact USD cost calculator with micro-cent precision:
  $$\text{Cost} = [(\text{prompt\_tokens} - \text{cached\_tokens}) \times \text{prompt\_rate}] + [\text{cached\_tokens} \times \text{cached\_rate}] + [\text{completion\_tokens} \times \text{completion\_rate}]$$
- **Granular Per-Call & Session Cost Tracking:**
  Every LLM invocation records an immutable audit trail (`call_id`, `session_id`, `model`, `provider`, `prompt_tokens`, `completion_tokens`, `cached_tokens`, `total_tokens`, `cost_usd`, `latency_ms`, `timestamp`).
- **Seamless Gateway & ModelRouter Integration:**
  Directly integrated with `LLMGateway.complete(...)` and `ModelRouter.complete(...)`. Every successful response carries computed `cost_usd` without breaking normalized `LLMResponse`, retry policies, or telemetry.
- **Hard $0.50 Per-Task Budget Ceiling:**
  Pre-call interceptor inspects cumulative spend before any adapter invocation. If cumulative spend reaches or projected call exceeds $0.50, further execution immediately stops.
- **NEEDS_HUMAN State Transition & Structured Cutoff Events:**
  On budget breach, the session lifecycle is transitioned to `NEEDS_HUMAN`, an immutable `BUDGET_EXCEEDED_CUTOFF` event is logged, and a terminal `BudgetExceededError` is raised.
- **Zero Bypass Guarantees:**
  Enforced at the Gateway level before the retry/fallback loop. Prevents retry loops, failover models, or agent replanners from circumventing the budget ceiling.

---

## 2. Complete Model Pricing Matrix

| Provider | Model Name | Input Rate ($ / 1M) | Output Rate ($ / 1M) | Cached Input ($ / 1M) | Input Rate ($ / 1k) | Output Rate ($ / 1k) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **OpenAI** | `gpt-4o` | $2.50 | $10.00 | $1.25 | $0.002500 | $0.010000 |
| **OpenAI** | `gpt-4o-mini` | $0.15 | $0.60 | $0.075 | $0.000150 | $0.000600 |
| **OpenAI** | `o3-mini` | $1.10 | $4.40 | $0.55 | $0.001100 | $0.004400 |
| **Anthropic** | `claude-3-5-sonnet` | $3.00 | $15.00 | $0.30 | $0.003000 | $0.015000 |
| **Anthropic** | `claude-3-5-haiku` | $0.80 | $4.00 | $0.08 | $0.000800 | $0.004000 |
| **DeepSeek** | `deepseek-v3` (`deepseek-chat`) | $0.14 | $0.28 | $0.014 | $0.000140 | $0.000280 |
| **DeepSeek** | `deepseek-r1` (`deepseek-reasoner`) | $0.55 | $2.19 | $0.14 | $0.000550 | $0.002190 |
| **Gemini** | `gemini-1.5-pro` | $1.25 | $5.00 | $0.3125 | $0.001250 | $0.005000 |
| **Gemini** | `gemini-1.5-flash` | $0.075 | $0.30 | $0.01875 | $0.000075 | $0.000300 |

---

## 3. Cost Calculation Examples

### Example A: Standard GPT-4o Invocations with Prompt Caching
- **Model:** `gpt-4o`
- **Prompt Tokens:** `10,000` (including `2,000` cached tokens)
- **Completion Tokens:** `1,500`
- **Calculation:**
  - Uncached Prompt: $8,000 \times \frac{\$2.50}{1,000,000} = \$0.020000$
  - Cached Prompt: $2,000 \times \frac{\$1.25}{1,000,000} = \$0.002500$
  - Completion: $1,500 \times \frac{\$10.00}{1,000,000} = \$0.015000$
  - **Total Cost:** $\$0.037500$

### Example B: DeepSeek-V3 High-Throughput Triage
- **Model:** `deepseek-v3`
- **Prompt Tokens:** `15,000` (`12,000` cached tokens)
- **Completion Tokens:** `500`
- **Calculation:**
  - Uncached Prompt: $3,000 \times \frac{\$0.14}{1,000,000} = \$0.000420$
  - Cached Prompt: $12,000 \times \frac{\$0.014}{1,000,000} = \$0.000168$
  - Completion: $500 \times \frac{\$0.28}{1,000,000} = \$0.000140$
  - **Total Cost:** $\$0.000728$

---

## 4. Per-Call Audit Record & Session Summary Structure

### Granular Call Audit Record (`CostRecord`)
```json
{
  "call_id": "a983b3e2-882d-4581-b541-60a6311854bc",
  "session_id": "session-fix-cwe-89-auth",
  "model": "gpt-4o",
  "provider": "openai",
  "prompt_tokens": 10000,
  "completion_tokens": 1500,
  "cached_tokens": 2000,
  "total_tokens": 11500,
  "cost_usd": 0.0375,
  "prompt_cost_usd": 0.02,
  "completion_cost_usd": 0.015,
  "cached_cost_usd": 0.0025,
  "timestamp": "2026-09-20T00:06:00.123456Z",
  "latency_ms": 342.1
}
```

### Cumulative Session Summary (`SessionCostSummary`)
```json
{
  "session_id": "session-fix-cwe-89-auth",
  "total_prompt_tokens": 24500,
  "total_completion_tokens": 3800,
  "total_cached_tokens": 6000,
  "total_tokens": 28300,
  "total_cost_usd": 0.09245,
  "call_count": 3,
  "budget_limit_usd": 0.50,
  "status": "active",
  "is_budget_exceeded": false,
  "remaining_budget_usd": 0.40755
}
```

---

## 5. Five Normal Sessions Demonstration (Spend Well Under $0.50)

Demonstrates typical automated repair flows operating within normal operational envelopes:

| Session ID | Task Workflow | Model Invocations | Total Tokens | Cumulative Cost | Budget Remaining | Final Status |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| `session_norm_1` | Finding Triage & Tagging | 2x `gpt-4o-mini` | 3,200 | **$0.00096** | $0.49904 | `active` |
| `session_norm_2` | Root Cause & Execution Plan | 1x `gpt-4o-mini`, 1x `gpt-4o` | 5,800 | **$0.02150** | $0.47850 | `active` |
| `session_norm_3` | SQL Injection Diagnosis | 2x `claude-3-5-sonnet` | 7,200 | **$0.04500** | $0.45500 | `active` |
| `session_norm_4` | Race Condition Reasoning | 1x `deepseek-r1` | 8,500 | **$0.00980** | $0.49020 | `active` |
| `session_norm_5` | Verification & Test Impact | 1x `gemini-1.5-pro` | 6,400 | **$0.01525** | $0.48475 | `active` |

*Result:* All 5 normal sessions complete successfully without budget warnings, retaining > $0.45 remaining headroom per task.

---

## 6. Runaway Session Simulation & Hard Cutoff Trace

### Runaway Scenario Details
A failing test triggers automated replanning loops. Each attempt invokes `gpt-4o` ($0.050 / call). The budget ceiling is enforced at exactly **$0.5000**.

```text
[Call 01] gpt-4o -> prompt=10,000, comp=2,500 | Call Cost: $0.0500 | Session Spend: $0.0500 / $0.5000 | Status: active
[Call 02] gpt-4o -> prompt=10,000, comp=2,500 | Call Cost: $0.0500 | Session Spend: $0.1000 / $0.5000 | Status: active
[Call 03] gpt-4o -> prompt=10,000, comp=2,500 | Call Cost: $0.0500 | Session Spend: $0.1500 / $0.5000 | Status: active
[Call 04] gpt-4o -> prompt=10,000, comp=2,500 | Call Cost: $0.0500 | Session Spend: $0.2000 / $0.5000 | Status: active
[Call 05] gpt-4o -> prompt=10,000, comp=2,500 | Call Cost: $0.0500 | Session Spend: $0.2500 / $0.5000 | Status: active
[Call 06] gpt-4o -> prompt=10,000, comp=2,500 | Call Cost: $0.0500 | Session Spend: $0.3000 / $0.5000 | Status: active
[Call 07] gpt-4o -> prompt=10,000, comp=2,500 | Call Cost: $0.0500 | Session Spend: $0.3500 / $0.5000 | Status: active
[Call 08] gpt-4o -> prompt=10,000, comp=2,500 | Call Cost: $0.0500 | Session Spend: $0.4000 / $0.5000 | Status: active
[Call 09] gpt-4o -> prompt=10,000, comp=2,500 | Call Cost: $0.0500 | Session Spend: $0.4500 / $0.5000 | Status: active
[Call 10] gpt-4o -> prompt=10,000, comp=2,500 | Call Cost: $0.0500 | Session Spend: $0.5000 / $0.5000 | Status: NEEDS_HUMAN
-------------------------------------------------------------------------------------------------------------------------
[Call 11] PRE-CALL INTERCEPTOR ACTIVATED:
          Current Spend: $0.5000 >= Budget Ceiling $0.5000
          --> CUTOFF TRIGGERED!
          --> Logged BudgetCutoffEvent(session_id='runaway_loop_incident_842', to_state='NEEDS_HUMAN')
          --> Raised BudgetExceededError: "[BUDGET EXCEEDED] Task session 'runaway_loop_incident_842' reached hard budget limit of $0.50. Call blocked; session transitioned to NEEDS_HUMAN."
          --> Adapter Calls: 0 (Execution halted before network request)
          --> Fallback Bypassed: True (Fallback prevented from consuming additional funds)
```

---

## 7. NEEDS_HUMAN Transition & Persistence Payloads

### 1. `agent_events` Transition Payload (Migration 009 Compliant)
```json
{
  "session_id": "runaway_loop_incident_842",
  "from_state": "active",
  "to_state": "NEEDS_HUMAN",
  "event_type": "BUDGET_EXCEEDED_CUTOFF",
  "payload": {
    "current_cost_usd": 0.5000,
    "budget_limit_usd": 0.50,
    "attempted_model": "gpt-4o",
    "reason": "Cumulative spend already reached or exceeded budget limit",
    "transition": "NEEDS_HUMAN"
  },
  "timestamp": "2026-09-20T00:08:12.842109Z"
}
```

### 2. Final Session Summary Record
```json
{
  "session_id": "runaway_loop_incident_842",
  "total_prompt_tokens": 100000,
  "total_completion_tokens": 25000,
  "total_cached_tokens": 0,
  "total_tokens": 125000,
  "total_cost_usd": 0.5000,
  "call_count": 10,
  "budget_limit_usd": 0.50,
  "status": "NEEDS_HUMAN",
  "is_budget_exceeded": true,
  "remaining_budget_usd": 0.0
}
```

---

## 8. Full Automated Test Suite Verification (85/85 Passing)

```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\kanis\Downloads\website-main\website-main\backend
collected 85 items

tests/test_agent_2_integration.py ....                                   [  4%]
tests/test_cost_tracker.py ................                              [ 23%]
tests/test_github_install.py ...                                         [ 27%]
tests/test_github_repo_delete.py ....                                    [ 31%]
tests/test_llm_gateway.py ............                                   [ 45%]
tests/test_model_router.py .............                                 [ 61%]
tests/test_plan_schema.py .........                                      [ 71%]
tests/test_plan_validator.py .............                               [ 87%]
tests/test_planner_agent.py .....                                        [ 92%]
tests/test_tool_resolver.py ......                                       [100%]

============================= 85 passed in 0.62s ==============================
```

- **Baseline & Auth Suite:** 7 passed
- **Day 1 Plan Schema & Validator:** 37 passed
- **Task 19 LLM Gateway:** 12 passed
- **Task 20 Model Router v1:** 13 passed
- **Task 21 Cost Tracking & Budget:** 16 passed
- **Total:** **85 passed, 0 failed (100% pass rate)**
