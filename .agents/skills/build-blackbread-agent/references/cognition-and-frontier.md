# Cognition and Frontier

Authority: ADR-FINAL-003.md §§10–13, ADR-FINAL-004.md, and ADR-FINAL-006.md.
Knowledge, specialist, and learning integration from draft ADR 010/011 remains prospective until merged.

## Cognition loop (implement per agent — graph-driven OODA)
```
1 Observe  → read a coherent graph slice, current AccessContexts, opportunity frontier,
             and a separately versioned learning snapshot (not raw LLM memory)
2 Orient   → LLM planner challenges/extends typed opportunities and emits candidates:
             {proves, precondition, info_gain, risk, cost, opsec_noise}
3 Critic   → challenge evidence / uncertainty / duplication / scope / oracle / alternative path
4 Rank     → role applies a versioned multi-objective ranking policy; deterministic code
             validates feature ranges, freshness, deduplication, and budgets—not offensive utility
5 Reserve  → emit one canonical InvestigationIntent; the Conductor admits readiness,
             dependencies, fairness, resources, locks, and one active reservation per dedup key
6 Decide   → only for an active reservation, emit one atomic proposal bound to campaign
             authority + source context → Conductor + Policy Kernel + OPSEC gate it
7 Act      → executor runs ONE typed capability via the OPSEC egress gateway
8 Interpret→ LLM proposes; deterministic oracle + evidence rules confirm/reject
9 Update   → write typed events to the hash-chained ledger; re-read a new snapshot; loop
```
**Anti-loop (mandatory):**
- Use the canonical ADR-003 intent deduplication key and semantic action identity. Bind objective,
  hypothesis, capability family, oracle, target set, and snapshot; a three-field hash is insufficient.
- Count stall only after attempted work under otherwise-ready conditions. Apply the accepted
  trajectory budget; waiting for evidence, resources, or OPSEC clearance does not consume progress.
- Keep ready, waiting, and terminal candidates separate. An empty ready queue is not frontier exhaustion.
- Wait only for an explicit dependency or event with a deadline and remaining campaign budget.
  When evidence/resources change, re-read the snapshot and reassess readiness.
- Declare FRONTIER_EXHAUSTED only after current candidates are reconciled and no pending outcome,
  viable deferred candidate, or admitted in-flight work can reopen the frontier. A timeout or missing
  evidence produces the applicable budget/authority/inconclusive outcome, not false exhaustion.
- BURNED freezes target-active work; passive reasoning may continue. Recovery follows the OPSEC
  contract in capability-integration.md, never a timer-based autonomous resume.

Every admitted graph/context/capability/control/expiry/outcome delta invalidates and recomputes only
the affected opportunities. Do not restart the campaign from zero and do not globally blacklist a
technique from one contextual failure.

An owning role may instantiate an `EphemeralCognitionWorker` for one bounded specialist question.
The worker receives immutable references and a typed output schema, then expires. It has no permanent
agent identity, reservation, target egress, secret access, capability ownership, proposal right,
Policy standing, evidence-promotion right, or durable private memory. The owning role remains
accountable; multiple specialists do not vote a claim into truth.

## LLM integration
- One `LLMProvider` abstraction; OpenAI-compatible adapter covers OpenRouter/DeepSeek/Qwen/local; deterministic router by role/sensitivity/cost/health. MVP: OpenRouter.
- Structured/schema-constrained output (Pydantic validate + repair). Log model + version + prompt hash + inputs + output as decision provenance.
- Handle refusal as typed `MODEL_REFUSAL`: provide transparent authorization context, retry once with
  a narrower analytical or candidate-synthesis task, route to an approved provider/local model, use
  a reviewed deterministic/OSS or human/IDE fallback, or choose another path. No prompt injection,
  jailbreak, identity deception, or hidden-policy circumvention.

## Prompt-injection defense (build into every LLM call)
Target content is untrusted DATA, never instructions. A low-privilege reader extracts it into structured facts; planners reason only over structured facts. The typed-output backstop means an injected agent can at most emit a proposal that deterministic gates still deny. Tag provenance; run the injection test suite.
