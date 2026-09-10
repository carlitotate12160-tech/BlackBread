"""Canonical list of safety-critical source paths.

This list is the single source consumed by governance tests and the PR-Agent
workflow classifier. Every safety-critical coverage module named in
``pyproject.toml`` must be recognized here. It also lists safety-critical
delivery paths that are not coverage modules, such as Alembic migrations under
``migrations/versions/`` (schema, tenant-isolation, privilege, and role DDL),
so those changes require the binding current-head review and the
``safety-critical`` label.
"""

SAFETY_CRITICAL_PATH_PARTS = (
    "migrations/versions/",
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
        elif (part.endswith("/") and path.startswith(part)) or (
            path in (part, f"{part}.py") or path.startswith(f"{part}/")
        ):
            return True
    return False
