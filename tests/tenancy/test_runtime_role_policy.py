import pytest

from blackbread.tenancy.roles import RuntimeRoleFacts, check_runtime_role_isolatable


def test_isolatable_facts_pass() -> None:
    check_runtime_role_isolatable(
        RuntimeRoleFacts(
            role_name="blackbread_runtime",
            exists=True,
            can_bypass_rls=False,
            has_parent_role=False,
        )
    )


def test_missing_role_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="does not exist"):
        check_runtime_role_isolatable(
            RuntimeRoleFacts("r", exists=False, can_bypass_rls=False, has_parent_role=False)
        )


def test_bypass_role_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="bypass"):
        check_runtime_role_isolatable(
            RuntimeRoleFacts("r", exists=True, can_bypass_rls=True, has_parent_role=False)
        )


def test_parent_membership_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="inherit or assume"):
        check_runtime_role_isolatable(
            RuntimeRoleFacts("r", exists=True, can_bypass_rls=False, has_parent_role=True)
        )
