"""Canonical list of safety-critical source paths.

This list is the single source consumed by governance tests and the PR-Agent
workflow classifier. Every safety-critical coverage module named in
``pyproject.toml`` must be recognized here.
"""

SAFETY_CRITICAL_PATH_PARTS = (
    "src/blackbread/ledger/",
    "src/blackbread/conductor/",
    "src/blackbread/graph/",
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
    "src/blackbread/tenancy/",
    "src/blackbread/models/core.py",
    "config/capability-registry.json",
)


def paths_require_binding_review(paths: list[str]) -> bool:
    return any(_is_safety_critical_path(path) for path in paths)


def _is_safety_critical_path(path: str) -> bool:
    for part in SAFETY_CRITICAL_PATH_PARTS:
        if part.endswith((".json", ".py")):
            if path == part:
                return True
        elif path.startswith(part):
            return True
    return False
