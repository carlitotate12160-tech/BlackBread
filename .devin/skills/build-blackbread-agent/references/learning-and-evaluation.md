# Learning and Evaluation

Authority for current campaign state: ADR-FINAL-003.md and ADR-FINAL-006.md.
The additional memory/learning model in ADR-FINAL-011.md remains prospective until merged;
it does not establish implemented learning or permission for cross-tenant reuse.

## Learning and memory

Keep four planes separate: ephemeral task scratch, ledger-backed campaign memory, tenant-scoped
longitudinal priors, and privacy-qualified global experience. A new campaign has no current target
facts until it observes them, even when tenant history suggests useful hypotheses.

Emit a provenance-bound `TechniqueOutcome` for proof, valid disproof, control block, Policy denial,
authority/artifact expiry, tool or adapter error, target-health stop, model refusal, cancellation, and
inconclusive evidence. Do not train or rank these as one success/failure bit. Cleanup state remains an
independent result.

Learning may update versioned contextual priors, propose declarative knowledge, or create a
privacy-safe range scenario after qualification. It never self-modifies or deploys a production
model, prompt, registry, oracle, ranking function, or capability. Use held-out replay/range evaluation,
reviewed promotion, and rollback for each new version.

## Selection versus execution

Record a candidate's selection, deferral, rejection, or pre-dispatch expiry as a typed
`TechniqueOutcome` carrying an explicit attempted-effect discriminator, separately from an attempted
effect.
Do not put an unexecuted opportunity in the denominator of execution success rates. Retain Policy
and model outcomes as their own reason classes. A tool error cannot prove the target is safe; a
control block cannot erase the underlying applicability evidence. Cleanup status is independent.

## Behavioral evaluation

Evaluate the role with held-out synthetic/replay/range scenarios appropriate to its released tier:

- empty ready queue with pending evidence, resource wait, and material-delta reopening;
- genuine exhausted frontier, deadline expiry, operator stop, and BURNED;
- path-value reversal, contradictory evidence, duplicate intent, and stale context;
- report downgrade and independent evidence lineage;
- historical prior that cannot satisfy a present precondition;
- cross-tenant isolation, privacy, version rollback, and provenance when learning is implemented.

Measure objective progress, information gain per request, calibrated uncertainty, client
reproducibility, and cleanup. Stored outcome count alone does not demonstrate improvement.
