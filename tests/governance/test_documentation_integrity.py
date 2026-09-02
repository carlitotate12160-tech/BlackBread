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


def _module_with_payload(character: str, doc_lines: int) -> str:
    doc = "\n".join(f"line {index}" for index in range(doc_lines))
    docstring = f'"""\n{doc}\n"""\n' if doc_lines else ""
    return f'{docstring}PAYLOAD = "{character * 256}"\n'


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


def test_loss_below_ratio_threshold_is_within_tolerance() -> None:
    path = "src/blackbread/graph/temporal_replay.py"
    base = {path: _module(code_lines=30, doc_lines=100)}
    head = {path: _module(code_lines=30, doc_lines=94)}

    assert evaluate_documentation_integrity(base, head) == []


def test_loss_at_absolute_threshold_is_within_tolerance() -> None:
    path = "src/blackbread/graph/temporal_replay.py"
    base = {path: _module(code_lines=30, doc_lines=6)}
    head = {path: _module(code_lines=30, doc_lines=1)}

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


def test_distinct_string_payloads_are_not_matched_as_a_rename() -> None:
    base_path = "src/blackbread/graph/old_adapter.py"
    head_path = "src/blackbread/graph/new_adapter.py"
    base = {base_path: _module_with_payload("A", doc_lines=20)}
    head = {head_path: _module_with_payload("Z", doc_lines=0)}

    assert evaluate_documentation_integrity(base, head) == []


def test_trivial_code_reduction_does_not_bypass_doc_strip() -> None:
    path = "src/blackbread/graph/temporal_replay.py"
    base = {path: _module(code_lines=20, doc_lines=20)}
    head = {path: _module(code_lines=19, doc_lines=0)}

    result = evaluate_documentation_integrity(base, head)

    assert len(result) == 1
    assert "density gaming is forbidden" in result[0]


def test_multiline_string_constant_counts_as_code() -> None:
    path = "src/blackbread/graph/temporal_replay.py"
    constant = "\n".join(
        [
            '    PAYLOAD = """',
            "    line 0",
            "    line 1",
            "    line 2",
            "    line 3",
            "    line 4",
            '    """',
            "",
        ]
    )
    base_doc = "\n".join(
        [
            "",
            '    """',
            "    doc line 0",
            "    doc line 1",
            "    doc line 2",
            "    doc line 3",
            "    doc line 4",
            '    """',
            "",
        ]
    )
    base_body = "def worker() -> None:\n" + base_doc + constant
    head_body = "def worker() -> None:\n    return None\n"
    base = {path: base_body}
    head = {path: head_body}

    result = evaluate_documentation_integrity(base, head)

    assert result == []
