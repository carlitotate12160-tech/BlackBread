"""Canonical list of safety-critical source paths.

This list is the single source consumed by governance tests to prove that every
safety-critical coverage module named in ``pyproject.toml`` is recognized as a
safety-critical path. It carries no review-policy semantics.
"""

SAFETY_CRITICAL_PATH_PARTS = (
    "src/blackbread/ledger/",
    "src/blackbread/conductor/",
    "src/blackbread/policy/",
    "src/blackbread/opsec/",
    "src/blackbread/identity/",
    "src/blackbread/authorization/",
    "src/blackbread/scope/",
    "src/blackbread/security/",
    "src/blackbread/leases/",
    "src/blackbread/kill_switch",
    "src/blackbread/capability/",
    "src/blackbread/capabilities/",
    "src/blackbread/gateway/",
    "src/blackbread/tenant",
    "src/blackbread/models/core.py",
    "config/capability-registry.json",
)
