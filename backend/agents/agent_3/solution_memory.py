"""
Purpose:
Task 42: Solution Memory & ContextPack (AC-E3-D4-03 & AC-E3-D4-04).
Implements an in-memory mock vector store, solution indexer, semantic retriever,
and few-shot context builder with strict multi-tenant repository isolation.

Key Capabilities:
1. In-Memory Mock Vector Store: Fast, deterministic cosine similarity over normalized
   feature embeddings.
2. Solution Indexer: Ingests resolved sessions (root cause, solution pattern, diff, feedback).
3. Memory Retriever: Semantic retrieval of top-k past solutions.
4. Strict Multi-Tenant Isolation (AC-E3-D4-04): Strictly partitioned by repo_id;
   cross-tenant memory bleed is architecturally impossible.
5. ContextPack Builder (AC-E3-D4-03): Formats retrieved past solutions into structured
   few-shot prompt context.

Acceptance Criteria:
- AC-E3-D4-03: Resolves Bug A, indexes solution; query for similar Bug B injects past
  solution pattern into ContextPack few-shot context.
- AC-E3-D4-04: Cross-repo isolation test queries repo_beta and confirms 0 memory records
  from repo_alpha are returned.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import time
from typing import Dict, List, Optional, Tuple, Any

from agents.agent_3.day2_models import ValidationVerdict, RepairPlan
from agents.agent_3.day4_models import (
    UnifiedFinding,
    FindingCategory,
    MemoryRecord,
    ContextPack,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Deterministic In-Memory Vectorizer & Math Utilities
# ─────────────────────────────────────────────────────────────────────────────

def compute_text_embedding(text: str, dim: int = 64) -> List[float]:
    """
    Computes a deterministic, L2-normalized vector embedding using token hashing.
    Provides fast, deterministic cosine similarity without external dependencies.
    """
    if not text or not text.strip():
        return [0.0] * dim

    tokens = re.findall(r"\b\w{2,}\b", text.lower())
    if not tokens:
        return [0.0] * dim

    vector = [0.0] * dim
    for token in tokens:
        # Deterministic MD5 hash bucket
        bucket = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % dim
        vector[bucket] += 1.0

    # L2 Normalization
    magnitude = math.sqrt(sum(x * x for x in vector))
    if magnitude > 0.0:
        vector = [round(x / magnitude, 6) for x in vector]

    return vector


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Computes cosine similarity between two normalized vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    return max(0.0, min(1.0, dot_product))


# ─────────────────────────────────────────────────────────────────────────────
# 2. In-Memory Mock Vector Store with Strict Multi-Tenant Partitioning
# ─────────────────────────────────────────────────────────────────────────────

class SolutionMemoryStore:
    """
    In-memory vector store partitioned strictly by repository ID (tenant).
    """

    def __init__(self):
        # Partitioned store: repo_id -> List[MemoryRecord]
        self._partitions: Dict[str, List[MemoryRecord]] = {}

    def insert(self, record: MemoryRecord) -> None:
        """Inserts a memory record into the designated repo_id partition."""
        if not record.embedding:
            combined_text = f"{record.finding_type} {record.root_cause_pattern} {record.solution_pattern}"
            record.embedding = compute_text_embedding(combined_text)

        if record.repo_id not in self._partitions:
            self._partitions[record.repo_id] = []

        self._partitions[record.repo_id].append(record)

    def count_for_repo(self, repo_id: str) -> int:
        """Returns the number of stored records for a specific repository."""
        return len(self._partitions.get(repo_id, []))

    def clear(self) -> None:
        """Clears all records in the store."""
        self._partitions.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Solution Indexer
# ─────────────────────────────────────────────────────────────────────────────

class SolutionIndexer:
    """
    Indexes verified defect resolutions into the solution memory store.
    """

    def __init__(self, store: SolutionMemoryStore):
        self.store = store

    def index_resolution(
        self,
        finding: UnifiedFinding,
        plan: RepairPlan,
        verdict: ValidationVerdict,
        human_feedback: Optional[str] = None,
    ) -> MemoryRecord:
        """
        Creates and stores a MemoryRecord from a completed finding resolution session.
        """
        root_cause = plan.diagnosis or finding.description
        solution = plan.adjusted_patch or plan.remediation_strategy or "Corrective patch applied"

        combined_text = f"{finding.category.value} {finding.title} {root_cause} {solution}"
        embedding = compute_text_embedding(combined_text)

        record = MemoryRecord(
            task_id=f"MEM-{finding.finding_id}",
            repo_id=finding.repo_id,
            finding_type=finding.category.value,
            root_cause_pattern=root_cause,
            solution_pattern=solution,
            affected_files=finding.target_files,
            outcome=verdict.verdict,
            human_feedback=human_feedback or f"Auto-verified with composite score {verdict.score * 100:.0f}%",
            embedding=embedding,
        )

        self.store.insert(record)
        return record


# ─────────────────────────────────────────────────────────────────────────────
# 4. Memory Retriever with Strict Tenant Isolation (AC-E3-D4-04)
# ─────────────────────────────────────────────────────────────────────────────

class MemoryRetriever:
    """
    Semantic retriever querying the vector store with strict repository boundary isolation.
    """

    def __init__(self, store: SolutionMemoryStore):
        self.store = store

    def query(
        self,
        finding: UnifiedFinding,
        top_k: int = 2,
        min_similarity: float = 0.10,
    ) -> List[Tuple[MemoryRecord, float]]:
        """
        Queries top-k similar memories strictly within finding.repo_id.
        Invariant: Records from other repositories can NEVER be returned.
        """
        query_text = f"{finding.category.value} {finding.title} {finding.description}"
        query_embedding = compute_text_embedding(query_text)

        # STRICT PARTITION ISOLATION: Only fetch partition matching finding.repo_id
        partition = self.store._partitions.get(finding.repo_id, [])
        scored_records: List[Tuple[MemoryRecord, float]] = []

        for record in partition:
            # Defensive check: absolute isolation enforcement
            if record.repo_id != finding.repo_id:
                continue

            sim = cosine_similarity(query_embedding, record.embedding or [])
            if sim >= min_similarity:
                scored_records.append((record, sim))

        # Sort by similarity descending
        scored_records.sort(key=lambda x: x[1], reverse=True)
        return scored_records[:top_k]


# ─────────────────────────────────────────────────────────────────────────────
# 5. ContextBuilder & ContextPack Assembly (AC-E3-D4-03)
# ─────────────────────────────────────────────────────────────────────────────

class ContextBuilder:
    """
    Constructs ContextPack payloads injecting retrieved past solutions
    as few-shot context alongside repository files.
    """

    @classmethod
    def build_context_pack(
        cls,
        finding: UnifiedFinding,
        retrieved_memories: List[MemoryRecord],
        worktree_dir: Optional[str] = None,
    ) -> ContextPack:
        """
        Assembles ContextPack with structured few-shot prompt markdown.
        """
        few_shot_sections = []
        for idx, mem in enumerate(retrieved_memories, start=1):
            few_shot_sections.append(
                f"### Past Solution #{idx} (Task: {mem.task_id} | Category: {mem.finding_type})\n"
                f"- **Root Cause Pattern**: {mem.root_cause_pattern}\n"
                f"- **Verified Solution**: \n```\n{mem.solution_pattern}\n```\n"
                f"- **Outcome**: {mem.outcome} | **Reviewer Feedback**: {mem.human_feedback or 'None'}\n"
            )

        few_shot_markdown = (
            "## 💡 Retrieved Solution Memory (Few-Shot Context)\n"
            + ("\n".join(few_shot_sections) if few_shot_sections else "No relevant past solutions found in memory.")
        )

        return ContextPack(
            finding_id=finding.finding_id,
            repo_id=finding.repo_id,
            retrieved_memories=retrieved_memories,
            relevant_files=finding.target_files,
            few_shot_context=few_shot_markdown,
        )
