import pytest

from blackbread.tenancy import TENANT_GUC, TenantContext, TenantContextError


def test_tenant_guc_is_namespaced() -> None:
    assert TENANT_GUC == "blackbread.tenant_id"
    assert "." in TENANT_GUC


def test_valid_tenant_id_is_preserved() -> None:
    context = TenantContext("tenant-a")
    assert context.tenant_id == "tenant-a"


def test_context_is_frozen() -> None:
    context = TenantContext("tenant-a")
    with pytest.raises(AttributeError):
        context.tenant_id = "tenant-b"  # type: ignore[misc]


@pytest.mark.parametrize(
    "value",
    ["", "   ", "\t", "\n"],
)
def test_blank_tenant_id_is_rejected(value: str) -> None:
    with pytest.raises(TenantContextError):
        TenantContext(value)


def test_oversized_tenant_id_is_rejected() -> None:
    with pytest.raises(TenantContextError):
        TenantContext("t" * 101)


def test_nul_byte_tenant_id_is_rejected() -> None:
    with pytest.raises(TenantContextError):
        TenantContext("tenant\x00a")


@pytest.mark.parametrize("value", [None, 123, b"tenant", object()])
def test_non_string_tenant_id_is_rejected(value: object) -> None:
    with pytest.raises(TenantContextError):
        TenantContext(value)  # type: ignore[arg-type]


def test_boundary_length_tenant_id_is_accepted() -> None:
    value = "t" * 100
    assert TenantContext(value).tenant_id == value


def test_surrogate_tenant_id_is_rejected() -> None:
    with pytest.raises(TenantContextError):
        TenantContext("tenant-\ud800")
