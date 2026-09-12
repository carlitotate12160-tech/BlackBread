# ADR-FINAL-009 — Vulnerability Currency: No Zero-Day Weaponization and Rapid N-Day Response

**Status:** ACCEPTED — 2026-09-12; becomes repository authority only when merged

**Implementation status:** DECIDED only

**Decision class:** Vulnerability-intelligence and capability-qualification amendment

**Amends:** `ADR-FINAL-002.md` §§13, 20, 23, 33–40; `PRD.md` §§3, 6.4–6.5, 10–13

**Primary principle:** BlackBread wins by rapidly proving applicable public risk and composing paths,
not by becoming a zero-day exploit-development laboratory.

## 0. Decision

Dedicated zero-day hunting and weaponization are product non-goals. BlackBread SHALL NOT search client
targets for unknown vulnerabilities in order to develop exploits, turn novel crashes into payloads,
or run unpublished exploit research against production.

BlackBread SHALL implement a **Rapid N-Day** response lane. This includes the period sometimes called
`1-day`: authoritative vulnerability information has become public, while exposure may remain high
because defenders have not yet patched or mitigated affected systems.

The product term is `Rapid N-Day`, not `+1 day`, because response remains useful after the first
24 hours and capability readiness cannot truthfully be inferred from elapsed time.

## 1. Internal vulnerability classes

BlackBread SHALL use these operational classes:

- `NOVEL_VULNERABILITY_CANDIDATE`: observed behavior lacks a matching authoritative public advisory
  at the decision time; it is not proof of a zero-day.
- `PUBLIC_N_DAY`: an authoritative vendor or CVE record describes the vulnerability or affected
  condition.
- `RAPID_N_DAY`: a `PUBLIC_N_DAY` inside the configured rapid-response window after authoritative
  disclosure or an urgent material update.
- `KNOWN_EXPLOITED`: authoritative evidence such as CISA KEV indicates exploitation in the wild.

These classes describe intelligence state. None proves that a client asset is affected, exploitable,
in scope, or authorized for testing.

## 2. Rapid N-Day pipeline

The implementation SHALL separate intelligence from execution:

```text
authoritative feed/advisory
-> normalized versioned advisory record
-> observed-product and target-identity correlation
-> probabilistic exposure candidate
-> safe applicability recipe
-> evidence-backed applicability result
-> reviewed ProofRecipe candidate
-> capability qualification lifecycle
-> exact target proposal, Policy, lease, WorkOrder
```

Primary intake sources are vendor advisories and CVE records, enriched with NVD, CISA KEV, and EPSS.
Secondary write-ups and public proof-of-concept repositories may inform review but never override an
authoritative affected-version or mitigation record.

For this policy, public exploit code is untrusted research input. Ingestion SHALL NOT import it into
the live registry, render it into an action, or expose it directly to an agent. Static analysis,
licensing, provenance, fixture behavior, negative controls, target effects, cleanup, supply-chain
identity, platform support, and range results remain mandatory before capability promotion.

No advisory, CVE, KEV entry, EPSS score, model assessment, observed version, public PoC, graph path,
or elapsed disclosure time can activate a capability.

Unqualified intelligence cannot activate a capability.

## 3. The 24-hour objective

The default 24-hour objective applies to ingestion and triage after a supported authoritative
disclosure:

- acquire and provenance-bind the advisory;
- normalize affected and fixed product ranges without silently resolving conflicts;
- correlate it to known external terrain;
- rank candidate exposure using reachability, KEV, EPSS, objective relevance, and evidence quality;
- identify the least-invasive applicability oracle and whether a qualified capability already exists;
- notify the operator when authorized terrain may be materially exposed.

It does not promise a client-executable exploit within 24 hours. If only a version match is available,
BlackBread reports a candidate and patch/mitigation urgency, not proven exploitability.

## 4. Accidental novel findings

If ordinary authorized testing produces a `NOVEL_VULNERABILITY_CANDIDATE`, the agent SHALL stop
increasing invasiveness, preserve the minimum reproducible evidence, mark affected path claims
unproven, and notify the operator/White Cell under the engagement disclosure procedure.

Further root-cause research, vendor coordination, disclosure timing, CVE assignment, or exploit
development requires a separate human-owned research and responsible-disclosure authority outside
the client campaign. The candidate SHALL NOT be reused across clients, added to the capability
registry, or sent into adaptive payload generation automatically.

## 5. Evidence, prioritization, and sources

NVD/CVE and vendor records describe public vulnerability information; they do not prove client
applicability. CISA KEV is a prioritization signal for known exploitation. EPSS estimates future
exploitation probability and does not determine technical exploitability. BlackBread retains these
signals separately from observed client evidence and the capability lifecycle.

Non-normative authoritative sources:

- [NIST National Vulnerability Database](https://www.nist.gov/itl/nvd)
- [CISA Known Exploited Vulnerabilities Catalog](https://www.cisa.gov/known-exploited-vulnerabilities-catalog)
- [FIRST Exploit Prediction Scoring System](https://www.first.org/epss/)

## 6. Release placement and non-claims

Rapid N-Day implementation begins with passive/control-plane feed ingestion and offline correlation.
T1/T2 applicability and T3 proof remain separate capability slices under their existing identity,
approval, range, OPSEC, cleanup, and release gates.

This ADR does not implement a feed, define a client-executable exploit, admit or promote a capability,
or authorize zero-day research. This ADR does not authorize target-facing execution.
