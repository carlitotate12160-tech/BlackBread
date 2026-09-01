from blackbread.governance.documentation_integrity import evaluate_documentation_integrity


def _module(code_lines: int, doc_lines: int) -> str:
    body = [f"    value_{index} = {index}" for index in range(code_lines)]
    doc = "\n".join(f"    line {index}" for index in range(doc_lines))
    docstring = f'    """\n{doc}\n    """' if doc_lines else ""
    parts = ["def worker() -> None:"]
    if docstring:
        parts.append(docstring)
    parts.extend(body or ["    return None"])
    return "\n".join(parts) + "\n"


def test_docstring_stripping_while_code_flat_is_rejected() -> None:
    path = "src/blackbread/graph/temporal_replay.py"
    base = {path: _module(code_lines=20, doc_lines=20)}
    head = {path: _module(code_lines=20, doc_lines=2)}

    result = evaluate_documentation_integrity(base, head)

    assert len(result) == 1
    assert "density gaming is forbidden" in result[0]


def test_documentation_removed_with_shrinking_code_is_allowed() -> None:
    path = "src/blackbread/graph/temporal_replay.py"
    base = {path: _module(code_lines=40, doc_lines=20)}
    head = {path: _module(code_lines=15, doc_lines=2)}

    assert evaluate_documentation_integrity(base, head) == []


def test_new_module_has_no_base_to_strip() -> None:
    path = "src/blackbread/graph/temporal_persistence.py"
    head = {path: _module(code_lines=30, doc_lines=0)}

    assert evaluate_documentation_integrity({}, head) == []


def test_small_documentation_change_is_within_tolerance() -> None:
    path = "src/blackbread/graph/temporal_replay.py"
    base = {path: _module(code_lines=30, doc_lines=8)}
    head = {path: _module(code_lines=30, doc_lines=5)}

    assert evaluate_documentation_integrity(base, head) == []


def test_renamed_module_with_stripped_documentation_is_rejected() -> None:
    base_path = "src/blackbread/graph/temporal_replay.py"
    head_path = "src/blackbread/graph/temporal_replay_new.py"
    base = {base_path: _module(code_lines=30, doc_lines=8)}
    head = {head_path: _module(code_lines=30, doc_lines=0)}

    result = evaluate_documentation_integrity(base, head)

    assert len(result) == 1
    assert head_path in result[0]
    assert "density gaming is forbidden" in result[0]
