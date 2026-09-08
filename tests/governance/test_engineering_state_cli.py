import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from blackbread.governance.engineering_state import (
    EngineeringStateManifest,
    render_projection,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "engineering_state.py"
SRC = REPO_ROOT / "src"
MANIFEST = ".github/engineering-state.json"
MARKDOWN = "ENGINEERING-STATE.md"
HISTORY = "ENGINEERING-HISTORY.md"
BASE = {
    "schema_version": 1,
    "state_revision": 1,
    "last_released_slice": "M1.4c1",
    "selected_next_slice": "M1.4c2a",
}


def _git(repo: Path, *a: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, check=True)


def _cli(repo: Path, *a: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, str(SCRIPT), *a],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _init(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@e.com")
    _git(repo, "config", "user.name", "T")
    return repo


def _commit(repo: Path, files: dict[str, str], msg: str = "i") -> str:
    for rel, content in files.items():
        full = repo / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        _git(repo, "add", "--", rel)
    _git(repo, "commit", "-m", msg)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _md() -> str:
    return render_projection(EngineeringStateManifest.model_validate(BASE))


def _base_commit(repo: Path) -> str:
    return _commit(repo, {MANIFEST: json.dumps(BASE) + "\n", MARKDOWN: _md()})


def _candidate_md(m: dict[str, object]) -> str:
    return render_projection(EngineeringStateManifest.model_validate(m))


# --- Test A: invalid release rollback ---
def test_invalid_release_rollback(tmp_path: Path):
    repo = _init(tmp_path)
    base = _base_commit(repo)
    bj, bm = (repo / MANIFEST).read_text(), (repo / MARKDOWN).read_text()
    r = _cli(
        repo,
        "transition",
        "--base-ref",
        base,
        "--kind",
        "release",
        "--released",
        "M1.4c2b",
        "--next",
        "M1.4c2c",
    )
    assert r.returncode != 0
    assert (repo / MANIFEST).read_text() == bj
    assert (repo / MARKDOWN).read_text() == bm


# --- Test B: invalid select rollback ---
def test_invalid_select_same_slice_rollback(tmp_path: Path):
    repo = _init(tmp_path)
    base = _base_commit(repo)
    bj, bm = (repo / MANIFEST).read_text(), (repo / MARKDOWN).read_text()
    r = _cli(repo, "transition", "--base-ref", base, "--kind", "select", "--next", "M1.4c2a")
    assert r.returncode != 0
    assert (repo / MANIFEST).read_text() == bj
    assert (repo / MARKDOWN).read_text() == bm


def test_invalid_select_with_released_rollback(tmp_path: Path):
    repo = _init(tmp_path)
    base = _base_commit(repo)
    bj, bm = (repo / MANIFEST).read_text(), (repo / MARKDOWN).read_text()
    r = _cli(
        repo,
        "transition",
        "--base-ref",
        base,
        "--kind",
        "select",
        "--released",
        "M1.4c2a",
        "--next",
        "M1.4c2b",
    )
    assert r.returncode == 2
    assert (repo / MANIFEST).read_text() == bj
    assert (repo / MARKDOWN).read_text() == bm


# --- Test C: bootstrap argument fidelity ---
def test_bootstrap_writes_explicit_arguments(tmp_path: Path):
    repo = _init(tmp_path)
    _git(repo, "commit", "--allow-empty", "-m", "e")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    r = _cli(
        repo,
        "transition",
        "--base-ref",
        base,
        "--kind",
        "bootstrap",
        "--released",
        "M1.4b2b-R",
        "--next",
        "M1.4c2a",
    )
    assert r.returncode == 0
    w = json.loads((repo / MANIFEST).read_text())
    assert w["last_released_slice"] == "M1.4b2b-R"
    assert w["selected_next_slice"] == "M1.4c2a"
    assert w["state_revision"] == 1


# --- Test D: missing and altered bootstrap history ---
def test_bootstrap_check_fails_when_history_absent(tmp_path: Path):
    repo = _init(tmp_path)
    base = _commit(repo, {MARKDOWN: _md()})
    cm = {
        "schema_version": 1,
        "state_revision": 1,
        "last_released_slice": "M1.4c1",
        "selected_next_slice": "M1.4c2a",
    }
    head = _commit(repo, {MANIFEST: json.dumps(cm) + "\n", MARKDOWN: _candidate_md(cm)})
    assert _cli(repo, "check", "--base-ref", base, "--head-ref", head).returncode == 1


def test_bootstrap_check_fails_when_history_altered(tmp_path: Path):
    repo = _init(tmp_path)
    base = _commit(repo, {MARKDOWN: _md()})
    cm = {
        "schema_version": 1,
        "state_revision": 1,
        "last_released_slice": "M1.4c1",
        "selected_next_slice": "M1.4c2a",
    }
    head = _commit(
        repo,
        {
            MANIFEST: json.dumps(cm) + "\n",
            MARKDOWN: _candidate_md(cm),
            HISTORY: "# Archive\n\nDifferent content.\n",
        },
    )
    assert _cli(repo, "check", "--base-ref", base, "--head-ref", head).returncode == 1


def test_bootstrap_check_passes_with_exact_history(tmp_path: Path):
    repo = _init(tmp_path)
    base = _commit(repo, {MARKDOWN: _md()})
    cm = {
        "schema_version": 1,
        "state_revision": 1,
        "last_released_slice": "M1.4c1",
        "selected_next_slice": "M1.4c2a",
    }
    head = _commit(
        repo,
        {
            MANIFEST: json.dumps(cm) + "\n",
            MARKDOWN: _candidate_md(cm),
            HISTORY: f"# Archive\n\n{_md()}\n",
        },
    )
    assert _cli(repo, "check", "--base-ref", base, "--head-ref", head).returncode == 0


# --- Test E: rename-safe changed-path classification ---
def test_rename_src_to_docs_is_release_bearing(tmp_path: Path):
    repo = _init(tmp_path)
    base = _commit(
        repo,
        {
            MANIFEST: json.dumps(BASE) + "\n",
            MARKDOWN: _md(),
            "src/blackbread/policy/core.py": "# p\n",
        },
    )
    (repo / "docs").mkdir()
    _git(repo, "mv", "src/blackbread/policy/core.py", "docs/core.py")
    _git(repo, "commit", "-m", "rn")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert _cli(repo, "check", "--base-ref", base, "--head-ref", head).returncode == 1


def test_rename_docs_to_src_is_release_bearing(tmp_path: Path):
    repo = _init(tmp_path)
    base = _commit(
        repo, {MANIFEST: json.dumps(BASE) + "\n", MARKDOWN: _md(), "docs/notes.md": "# n\n"}
    )
    (repo / "src" / "blackbread").mkdir(parents=True)
    _git(repo, "mv", "docs/notes.md", "src/blackbread/notes.py")
    _git(repo, "commit", "-m", "rn")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert _cli(repo, "check", "--base-ref", base, "--head-ref", head).returncode == 1


def test_deletion_under_release_bearing_path(tmp_path: Path):
    repo = _init(tmp_path)
    base = _commit(
        repo,
        {
            MANIFEST: json.dumps(BASE) + "\n",
            MARKDOWN: _md(),
            "src/blackbread/policy/core.py": "# p\n",
        },
    )
    _git(repo, "rm", "src/blackbread/policy/core.py")
    _git(repo, "commit", "-m", "rm")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert _cli(repo, "check", "--base-ref", base, "--head-ref", head).returncode == 1


def test_docs_only_rename_is_not_release_bearing(tmp_path: Path):
    repo = _init(tmp_path)
    base = _commit(repo, {MANIFEST: json.dumps(BASE) + "\n", MARKDOWN: _md(), "docs/a.md": "# a\n"})
    _git(repo, "mv", "docs/a.md", "docs/b.md")
    _git(repo, "commit", "-m", "rn")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert _cli(repo, "check", "--base-ref", base, "--head-ref", head).returncode == 0


# --- Test G: exit-code contract ---
def test_exit_code_valid_check(tmp_path: Path):
    repo = _init(tmp_path)
    base = _base_commit(repo)
    assert _cli(repo, "check", "--base-ref", base, "--head-ref", base).returncode == 0


def test_exit_code_policy_violation(tmp_path: Path):
    repo = _init(tmp_path)
    base = _base_commit(repo)
    r = _cli(
        repo,
        "transition",
        "--base-ref",
        base,
        "--kind",
        "release",
        "--released",
        "M1.4c2b",
        "--next",
        "M1.4c2c",
    )
    assert r.returncode == 1


def test_exit_code_unreadable_base_ref(tmp_path: Path):
    repo = _init(tmp_path)
    base = _base_commit(repo)
    assert _cli(repo, "check", "--base-ref", "nope", "--head-ref", base).returncode == 2


def test_exit_code_unreadable_head_ref(tmp_path: Path):
    repo = _init(tmp_path)
    base = _base_commit(repo)
    assert _cli(repo, "check", "--base-ref", base, "--head-ref", "nope").returncode == 2


def test_exit_code_malformed_manifest(tmp_path: Path):
    repo = _init(tmp_path)
    base = _base_commit(repo)
    head = _commit(repo, {MANIFEST: "{bad", MARKDOWN: _md()})
    assert _cli(repo, "check", "--base-ref", base, "--head-ref", head).returncode == 2


def test_exit_code_invalid_cli_combination(tmp_path: Path):
    repo = _init(tmp_path)
    _git(repo, "commit", "--allow-empty", "-m", "e")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    r = _cli(repo, "transition", "--base-ref", base, "--kind", "bootstrap", "--next", "M1.4c2a")
    assert r.returncode == 2


# --- Test J: no product runtime imports governance CLI ---
def test_no_product_runtime_imports_governance_cli():
    for py in (REPO_ROOT / "src" / "blackbread").rglob("*.py"):
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                names = (
                    [n.name for n in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                assert not any("scripts.engineering_state" in n for n in names)
