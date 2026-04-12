# ADR-004: Traffic Light Scoring System

**Status:** Accepted  
**Date:** 2024-01-16

## Context
After Agent 5 generates a code fix, the platform needs a clear, human-readable signal for
whether to auto-apply (GREEN), escalate (YELLOW), or block (RED). A numeric score alone
is hard to act on quickly.

## Decision
Use a three-colour traffic light system:
- GREEN  >= 0.85 -- auto-apply the fix
- YELLOW  0.60-0.84 -- human review required before applying
- RED    < 0.60  -- block, notify team, human must act

Score formula: llm_confidence * 0.6 + blast_score * 0.4

Safety override: HIGH blast radius (6+ files) always forces RED regardless of score.

Quality modifiers (applied before threshold check):
- Bandit HIGH severity finding: -0.30
- Pylint score < 6.0:           -0.20
- Pylint score < 4.0:           -0.40

## Consequences
**Positive:**
- Operators understand GREEN/YELLOW/RED immediately
- Safety override prevents auto-applying risky large-scope fixes
- Modular score formula is easy to tune

**Negative:**
- Weights (0.6/0.4) are heuristic -- may need calibration over time
- YELLOW requires human action (pipeline blocks until review)
