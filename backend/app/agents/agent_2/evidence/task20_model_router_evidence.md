# Task 20: Model Router v1 — Evaluation Evidence

**Engineer 2 — Planning & Execution Lead**  
**Repository:** TeslaLab-AI/website  
**Branch:** `agent-2-day2`  
**Base Commit:** `d9b89a8` (Completed Task 19 state)  

---

## 1. Overview & Objectives Accomplished

Task 20 establishes **Model Router v1** for Agent 2:
- **3 Model Tiers Configured:**
  1. **Fast / Cheap:** `gpt-4o-mini`, `claude-3-5-haiku`, `deepseek-v3`
  2. **Strong:** `gpt-4o`, `claude-3-5-sonnet`
  3. **Reasoning:** `deepseek-r1`, `o3-mini`
- **Configuration-Driven Routing Table:**
  Externalized in `router_config.json`, mapping task types (`triage`, `classification`, `planning`, `diagnosis`, `complex_logic_bug`, etc.) to tiers and models.
- **Runtime Override & Escalation:**
  Supports dynamic tier escalation via `override_tier="reasoning"` and `complexity_hint="high"`.
- **Zero-Restart Hot Reload:**
  Automatically detects configuration modifications on disk via timestamp inspection (`mtime`) and supports explicit `reload_config()` programmatic updates.
- **Clean Gateway Integration:**
  Delegates execution to Task 19's `LLMGateway.complete(...)` using the selected model, tier, and fallback routes.
- **Cost Reduction Verification:**
  Deterministic 10-task workload simulation achieves **65.20% cost reduction** compared to using the Strong tier for every task (exceeding the >60% SLA target).

---

## 2. Active Routing Configuration (`router_config.json`)

```json
{
  "default_tier": "strong",
  "tiers": {
    "fast": {
      "primary_model": "gpt-4o-mini",
      "provider": "openai",
      "fallback_model": "claude-3-5-haiku",
      "allowed_models": [
        "gpt-4o-mini",
        "claude-3-5-haiku",
        "deepseek-v3"
      ]
    },
    "strong": {
      "primary_model": "gpt-4o",
      "provider": "openai",
      "fallback_model": "claude-3-5-sonnet",
      "allowed_models": [
        "gpt-4o",
        "claude-3-5-sonnet"
      ]
    },
    "reasoning": {
      "primary_model": "deepseek-r1",
      "provider": "deepseek",
      "fallback_model": "o3-mini",
      "allowed_models": [
        "deepseek-r1",
        "o3-mini"
      ]
    }
  },
  "task_rules": {
    "triage": { "tier": "fast" },
    "classification": { "tier": "fast" },
    "tagging": { "tier": "fast" },
    "summary": { "tier": "fast" },
    "file_filter": { "tier": "fast" },
    "diff_inspection": { "tier": "fast" },
    "planning": { "tier": "strong" },
    "diagnosis": { "tier": "strong" },
    "code_generation": { "tier": "strong" },
    "review": { "tier": "strong" },
    "complex_logic_bug": { "tier": "reasoning" },
    "race_condition": { "tier": "reasoning" },
    "security_exploit_analysis": { "tier": "reasoning" }
  },
  "complexity_escalations": {
    "high": "reasoning",
    "complex": "reasoning",
    "critical": "reasoning"
  }
}
```

---

## 3. Ten Varied Tasks Routing Evaluation Matrix

Feed 10 varied task types across typical automated maintenance workloads:

| # | Task Type | Assigned Tier | Primary Model | Provider | Fallback Model | Resolution Reason |
| :---: | :--- | :---: | :--- | :--- | :--- | :--- |
| **1** | `triage` | **FAST** | `gpt-4o-mini` | `openai` | `claude-3-5-haiku` | Configured task rule mapped 'triage' to tier 'fast' |
| **2** | `classification` | **FAST** | `gpt-4o-mini` | `openai` | `claude-3-5-haiku` | Configured task rule mapped 'classification' to tier 'fast' |
| **3** | `tagging` | **FAST** | `gpt-4o-mini` | `openai` | `claude-3-5-haiku` | Configured task rule mapped 'tagging' to tier 'fast' |
| **4** | `summary` | **FAST** | `gpt-4o-mini` | `openai` | `claude-3-5-haiku` | Configured task rule mapped 'summary' to tier 'fast' |
| **5** | `file_filter` | **FAST** | `gpt-4o-mini` | `openai` | `claude-3-5-haiku` | Configured task rule mapped 'file_filter' to tier 'fast' |
| **6** | `diff_inspection`| **FAST** | `gpt-4o-mini` | `openai` | `claude-3-5-haiku` | Configured task rule mapped 'diff_inspection' to tier 'fast' |
| **7** | `planning` | **STRONG** | `gpt-4o` | `openai` | `claude-3-5-sonnet` | Configured task rule mapped 'planning' to tier 'strong' |
| **8** | `diagnosis` | **STRONG** | `gpt-4o` | `openai` | `claude-3-5-sonnet` | Configured task rule mapped 'diagnosis' to tier 'strong' |
| **9** | `complex_logic_bug` | **REASONING** | `deepseek-r1` | `deepseek` | `o3-mini` | Configured task rule mapped 'complex_logic_bug' to tier 'reasoning' |
| **10** | `race_condition` | **REASONING** | `deepseek-r1` | `deepseek` | `o3-mini` | Configured task rule mapped 'race_condition' to tier 'reasoning' |

---

## 4. Runtime Override & Complexity Escalation Traces

### Example 1: Runtime Override to Reasoning Tier
```python
route = router.get_model_for_task(task_type="triage", override_tier="reasoning")
```
- **Output:** `tier="reasoning"`, `model="deepseek-r1"`, `provider="deepseek"`, `is_override=True`
- **Reason:** `"Runtime override explicitly requested tier 'reasoning'"`

### Example 2: Complexity Hint Escalation
```python
route = router.get_model_for_task(task_type="diagnosis", complexity_hint="high")
```
- **Output:** `tier="reasoning"`, `model="deepseek-r1"`, `provider="deepseek"`
- **Reason:** `"Configured task rule mapped 'diagnosis' to tier 'strong' (escalated from 'strong' to 'reasoning' due to complexity_hint='high')"`

### Example 3: Unknown / Invalid Task Type Graceful Fallback
```python
route = router.get_model_for_task(task_type="unregistered_custom_pipeline_step")
```
- **Output:** `tier="strong"`, `model="gpt-4o"`, `provider="openai"`
- **Reason:** `"Unknown task type 'unregistered_custom_pipeline_step' defaulted to 'strong' tier"`

---

## 5. Cost Comparison & Savings Analysis (>60% Reduction)

### Blended Token Pricing Reference (per 1,000 Tokens)
- **Fast Tier (`gpt-4o-mini`):** $0.000375 / 1k tokens ($0.375 / 1M)
- **Strong Tier (`gpt-4o`):** $0.006250 / 1k tokens ($6.250 / 1M) — ~16.6x more expensive
- **Reasoning Tier (`deepseek-r1`):** $0.001370 / 1k tokens ($1.370 / 1M) — ~4.5x cheaper than Strong

### Workload Simulation (10 Varied Tasks)

| Task | Tokens | Assigned Tier | Model | Option A: Strong Tier Cost | Option B: Routed Cost | Cost Savings |
| :--- | :---: | :---: | :--- | :---: | :---: | :---: |
| `triage` | 1,200 | **FAST** | `gpt-4o-mini` | $0.00750 | $0.00045 | 94.0% |
| `classification` | 1,000 | **FAST** | `gpt-4o-mini` | $0.00625 | $0.00038 | 94.0% |
| `tagging` | 800 | **FAST** | `gpt-4o-mini` | $0.00500 | $0.00030 | 94.0% |
| `summary` | 1,500 | **FAST** | `gpt-4o-mini` | $0.00938 | $0.00056 | 94.0% |
| `file_filter` | 900 | **FAST** | `gpt-4o-mini` | $0.00563 | $0.00034 | 94.0% |
| `diff_inspection`| 1,100 | **FAST** | `gpt-4o-mini` | $0.00688 | $0.00041 | 94.0% |
| `planning` | 2,000 | **STRONG** | `gpt-4o` | $0.01250 | $0.01250 | 0.0% |
| `diagnosis` | 1,800 | **STRONG** | `gpt-4o` | $0.01125 | $0.01125 | 0.0% |
| `complex_logic_bug` | 2,200 | **REASONING**| `deepseek-r1` | $0.01375 | $0.00301 | 78.1% |
| `race_condition` | 2,500 | **REASONING**| `deepseek-r1` | $0.01563 | $0.00343 | 78.1% |
| **Total Workload** | **15,000** | — | — | **$0.09375** | **$0.03263** | **65.20% Savings** |

### Key Takeaway
- **Option A Baseline (All Strong):** `$0.09375`
- **Option B Routed (ModelRouter):** `$0.03263`
- **Net Cost Reduction:** **65.20% savings**, exceeding the >60% requirement while ensuring critical planning and complex logic debugging receive top-tier models.

---

## 6. Full Test Suite Verification

```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\kanis\Downloads\website-main\website-main\backend
collected 69 items

tests/test_agent_2_integration.py ....                                   [  5%]
tests/test_github_install.py ...                                         [ 10%]
tests/test_github_repo_delete.py ....                                    [ 15%]
tests/test_llm_gateway.py ............                                   [ 33%]
tests/test_model_router.py .............                                 [ 52%]
tests/test_plan_schema.py .........                                      [ 65%]
tests/test_plan_validator.py .............                               [ 84%]
tests/test_planner_agent.py .....                                        [ 91%]
tests/test_tool_resolver.py ......                                       [100%]

============================= 69 passed in 0.64s ==============================
```
- **Day 1 Tests:** 44/44 passing (0 regressions)
- **Task 19 Tests:** 12/12 passing (0 regressions)
- **Task 20 Tests:** 13/13 passing
- **Total:** 69/69 passing (100%)
