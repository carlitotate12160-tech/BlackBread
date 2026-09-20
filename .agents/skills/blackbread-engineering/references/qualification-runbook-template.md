# Qualification Runbook Template

Use when the implementation owner cannot run an authoritative environment proof. Bind every command
and result to one commit. This packet grants execution of listed verification commands only; it does
not authorize code changes or product/target activity.

```text
STATE: QUALIFICATION_REQUIRED
SLICE:
COMMIT_SHA:
SOURCE_PR:
RUNNER_OWNER:
ENVIRONMENT_CLASS: PostgreSQL | Oracle ARM64 | other
EXPECTED_PLATFORM_IDENTITY:
```

## Preconditions and commands

```text
Read-only environment checks:
Required services and versions:
Secret handling: references only; never print or upload values
Setup commands:
Focused proof commands:
Affected-suite commands:
Full-gate commands:
Cleanup commands:
```

Commands must come from live repository authority or the sealed packet. The runner must stop on a
commit mismatch, platform mismatch, missing dependency, destructive/target-facing step, or any need
to edit the repository.

## Result

```text
STATE: QUALIFIED | QUALIFICATION_FAILED
ACTUAL_COMMIT_SHA:
PLATFORM_EVIDENCE:
COMMAND_RESULTS:
FAILURE_EVIDENCE:
ARTIFACT_OR_LOG_REFERENCES:
CLAIMS_PROVED:
CLAIMS_NOT_PROVED:
EXACT_NEXT_ACTION:
```

Return the record to the implementation owner or review/seal owner. Do not repair failures in the
qualification environment; a valid code finding requires a correction packet.
