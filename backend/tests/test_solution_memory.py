"""
Purpose:
Task 42 Test Suite: Solution Memory & ContextPack (AC-E3-D4-03 & AC-E3-D4-04).
Verifies:
1. In-Memory Mock Vector Store: Fast, deterministic cosine similarity and indexing.
2. Acceptance Criteria AC-E3-D4-03:
   Resolves Bug A, indexes solution in memory; querying for similar Bug B injects
   the past solution pattern into ContextPack as structured few-shot context.
3. Acceptance Criteria AC-E3-D4-04:
   Strict cross-repository tenant isolation: querying repo_beta confirms 0 memory
   records from repo_alpha are returned.
"""

from __future__ import annotations

import pytest

from agents.agent_3.day2_models import ValidationVerdict, RepairPlan, CheckResult
from agents.agent_3.day4_models import (
    UnifiedFinding,
    FindingCategory,
    MemoryRecord,
    ContextPack,
)
from agents.agent_3.solution_memory import (
    SolutionMemoryStore,
    SolutionIndexer,
    MemoryRetriever,
    ContextBuilder,
    compute_text_embedding,
    cosine_similarity,
)
from tests.fixtures.day4_fixtures import (
    SEEDED_MEMORIES_TENANT_A,
    SEEDED_MEMORIES_TENANT_B,
    SEEDED_FINDINGS_6,
)


def test_vector_math_and_normalization():
    """
    Verifies embedding computation, L2 normalization, and cosine similarity.
    """
    v1 = compute_text_embedding("pagination slice boundary error")
    v2 = compute_text_embedding("pagination slice boundary error")
    v3 = compute_text_embedding("unrelated database transaction deadlock")

    assert len(v1) == 64
    # Identical text must produce similarity of 1.0
    sim_identical = cosine_similarity(v1, v2)
    assert pytest.approx(sim_identical, rel=1e-3) == 1.0

    # Similar text should have higher similarity than unrelated text
    v_similar = compute_text_embedding("pagination slice off by one")
    sim_similar = cosine_similarity(v1, v_similar)
    sim_unrelated = cosine_similarity(v1, v3)

    assert sim_similar > sim_unrelated, f"Expected {sim_similar} > {sim_unrelated}"


def test_solution_indexer_and_storage():
    """
    Verifies that SolutionIndexer processes resolved sessions into MemoryRecords
    and inserts them into the partitioned vector store.
    """
    store = SolutionMemoryStore()
    indexer = SolutionIndexer(store)

    finding = SEEDED_FINDINGS_6[0]  # BUG-PAGINATE-01
    plan = RepairPlan(
        attempt=1,
        target_components=["src/catalog/paginate.py"],
        diagnosis="Off-by-one boundary in catalog pagination",
        adjusted_patch="end = start + page_size",
        status="PROPOSED",
    )
    verdict = ValidationVerdict(
        verdict="PASS",
        score=1.0,
        checks={},
        failure_reasons=[],
    )

    record = indexer.index_resolution(finding, plan, verdict, human_feedback="Clean boundary fix")

    assert record.task_id == "MEM-BUG-PAGINATE-01"
    assert record.repo_id == finding.repo_id
    assert record.outcome == "PASS"
    assert record.embedding is not None
    assert len(record.embedding) == 64
    assert store.count_for_repo(finding.repo_id) == 1


def test_few_shot_injection_into_context_pack_ac_e3_d4_03():
    """
    Acceptance Criteria AC-E3-D4-03:
    1. Seed memory store with resolved Bug A (Pagination boundary error).
    2. Query memory store with new similar Bug B (Slice off-by-one).
    3. Assert MemoryRetriever returns Bug A's pattern.
    4. Assert ContextBuilder injects Bug A's solution pattern into ContextPack few_shot_context.
    """
    store = SolutionMemoryStore()
    retriever = MemoryRetriever(store)

    # 1. Populate store with seeded memories for repo_stage0_main
    for mem in SEEDED_MEMORIES_TENANT_A:
        # Re-tag to target repo
        mem_copy = mem.model_copy()
        mem_copy.repo_id = "repo_stage0_main"
        store.insert(mem_copy)

    # 2. Query with similar Bug: BUG-PAGINATE-01
    query_finding = SEEDED_FINDINGS_6[0]
    matches = retriever.query(query_finding, top_k=2)

    assert len(matches) >= 1, "Expected at least 1 memory match for similar pagination bug"
    top_record, score = matches[0]

    # Verify semantic match
    assert "Pagination slice" in top_record.root_cause_pattern
    assert score > 0.40, f"Expected high similarity score, got {score}"

    # 3. Build ContextPack
    context_pack = ContextBuilder.build_context_pack(
        finding=query_finding,
        retrieved_memories=[r for r, _ in matches],
    )

    assert isinstance(context_pack, ContextPack)
    assert context_pack.finding_id == query_finding.finding_id
    assert len(context_pack.retrieved_memories) >= 1
    assert "## 💡 Retrieved Solution Memory (Few-Shot Context)" in context_pack.few_shot_context
    assert "Pagination slice" in context_pack.few_shot_context
    assert "page_size" in context_pack.few_shot_context


def test_strict_cross_repo_tenant_isolation_ac_e3_d4_04():
    """
    Acceptance Criteria AC-E3-D4-04:
    Multi-tenant isolation test:
    - Index Tenant A memories under 'repo_alpha'.
    - Index Tenant B memories under 'repo_beta'.
    - Querying under 'repo_beta' must return ZERO records from 'repo_alpha',
      even if the query text explicitly matches Tenant A's memories.
    """
    store = SolutionMemoryStore()
    retriever = MemoryRetriever(store)

    # Populate Tenant A (repo_alpha)
    for mem in SEEDED_MEMORIES_TENANT_A:
        store.insert(mem)

    # Populate Tenant B (repo_beta)
    for mem in SEEDED_MEMORIES_TENANT_B:
        store.insert(mem)

    assert store.count_for_repo("repo_alpha") == 2
    assert store.count_for_repo("repo_beta") == 1

    # Query using repo_beta with query text that strongly resembles Tenant A's pagination bug!
    probe_finding = UnifiedFinding(
        finding_id="PROBE-CROSS-TENANT-01",
        category=FindingCategory.BUG,
        title="Pagination slice off-by-one boundary omitting final item",
        description="Database connection pool timeout",
        target_files=["src/catalog/paginate.py"],
        repo_id="repo_beta",  # Target tenant is repo_beta!
    )

    results = retriever.query(probe_finding, top_k=5, min_similarity=0.0)

    # Strict Isolation Invariants
    for record, score in results:
        assert record.repo_id == "repo_beta", (
            f"CRITICAL ISOLATION BREACH: Record from {record.repo_id} leaked into query for repo_beta!"
        )
        assert record.repo_id != "repo_alpha", "Leaked repo_alpha record into repo_beta query!"

    # Also verify that a tenant with no memories returns empty list
    empty_tenant_finding = UnifiedFinding(
        finding_id="PROBE-EMPTY-02",
        category=FindingCategory.BUG,
        title="Some bug",
        repo_id="repo_gamma_empty",
    )
    empty_results = retriever.query(empty_tenant_finding)
    assert len(empty_results) == 0, f"Expected 0 results for non-existent tenant, got {len(empty_results)}"
