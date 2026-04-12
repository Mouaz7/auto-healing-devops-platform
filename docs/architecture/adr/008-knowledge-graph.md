# ADR-008: In-Memory Knowledge Graph for Error Analysis (Agent 4)

**Status:** Accepted  
**Date:** 2024-01-18

## Context
Agent 4 (Error Analyst) needs to understand which files are affected by a build failure
and estimate blast radius. A full graph database (Neo4j, etc.) is heavyweight for this use case.

## Decision
Use an in-memory dependency graph (dict-based adjacency list) within Agent 4:
- DependencyTracker builds the graph from import analysis + file structure
- max_depth = 5 (prevents runaway recursion)
- visited set prevents cycles
- Blast radius computed as: LOW (1 file), MEDIUM (2-5), HIGH (6+)

The graph is rebuilt per analysis request (stateless between calls).

## Consequences
**Positive:**
- Zero external dependencies (no graph DB to manage)
- Fast for typical Python project sizes (< 200 files)
- Blast radius is deterministic and testable

**Negative:**
- Graph is not persisted -- no historical pattern learning
- May be slow for very large repos (>1000 files), mitigated by max_depth=5
- Import analysis is static (misses runtime dynamic imports)
