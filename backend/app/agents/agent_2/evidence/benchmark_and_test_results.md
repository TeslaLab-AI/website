# Agent 2 Evidence: Benchmark & Test Results

## Test Suite Execution Summary
Ran complete test suite containing all 44 tests (7 original backend tests + 37 Agent 2 tests).

### Command
```powershell
$env:SUPABASE_URL="https://example.supabase.co"
$env:SUPABASE_SERVICE_ROLE_KEY="dummy"
python -m pytest tests -v -s
```

### Result
- **Passed**: 44 / 44 (100%)
- **Failed**: 0
- **Execution Time**: 0.43s

---

## Benchmark: PlanValidator Latency
Task 18 specifies a target validator runtime of `< 50ms`.
The benchmark runs `default_validator.validate()` across 500 iterations on a multi-step ExecutionPlan.

### Benchmark Output
```text
[BENCHMARK] PlanValidator average runtime: 0.059 ms across 500 runs
```
- **Average Execution Time**: **0.059 ms** (59 microseconds)
- **Target SLA**: < 50.0 ms
- **Margin**: > 800x faster than the 50ms SLA requirement.

---

## Test Inventory

| Test File | Tests | Coverage | Status |
| :--- | :--- | :--- | :--- |
| `test_github_install.py` | 3 | Existing auth & token signing | PASS |
| `test_github_repo_delete.py` | 4 | Existing repository removal endpoints | PASS |
| `test_plan_schema.py` | 9 | 20 valid payloads, 10 malformed payloads, roundtrip serialization, StepOutcome, JSON schema export, arbitrary fake field rejection, mismatched tool argument rejection, mismatched model rejection, ExecutionPlan step validation | PASS |
| `test_tool_resolver.py` | 6 | Registry of 6 tools, unknown tool rejection, validation helper, JSON schema extraction | PASS |
| `test_plan_validator.py` | 13 | 5 valid plans, 5 invalid plans (destructive command, protected paths, backwards ordering, invalid numbering, missing file), <50ms benchmark, force push variants (`-f`, `--force-with-lease`, `+main`), ordering edge cases | PASS |
| `test_planner_agent.py` | 5 | 5 seeded bug diagnoses (SQLi, NullPointer, Hardcoded Creds, CSRF, Vulnerable Dependency), >=3 steps, ordering, rollback | PASS |
| `test_agent_2_integration.py` | 4 | Adapter to FixPlan/FixStep, validator gatekeeper, workspace execution, execute_plan gatekeeper mock | PASS |
| **Total** | **44** | **100% test pass rate** | **ALL PASS** |
