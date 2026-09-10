import copy
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from blackbread.policy.runtime_gate import RuntimeGateResult
from tests.policy._policy_record_builders import decision_row, insert_decision, insert_proposal, proposal_row

TENANT = "lineage-test-tenant"



@pytest.fixture
async def lineage_base(session: AsyncSession) -> dict[str, Any]:
    """Create a coherent proposal + decision + engagement and return building blocks.

    Uses the admin (migration) connection to insert proposals and decisions
    (the recorder cannot do this from the runtime session, and the runtime
    role lacks INSERT on those tables).
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from tests.conftest import TEST_MIGRATION_DATABASE_URL
    admin_url = TEST_MIGRATION_DATABASE_URL
    admin = create_async_engine(admin_url)

    engagement_id = uuid.uuid4()
    try:
        async with admin.begin() as conn:
            # Set tenant GUC
            await conn.execute(text(f"SET LOCAL blackbread.tenant_id = '{TENANT}'"))
            # Create engagement
            await conn.execute(
                text(
                    "INSERT INTO engagements (id, client_id, tenant_id, status) "
                    "VALUES (:id, :cid, :tid, 'created')"
                ),
                {"id": engagement_id, "cid": uuid.uuid4(), "tid": TENANT},
            )
    finally:
        await admin.dispose()

    # Build proposal and decision
    p = proposal_row(tenant_id=TENANT, engagement_id=engagement_id)
    d = decision_row(p, tenant_id=TENANT, engagement_id=engagement_id)
    e = policy_event_row(p, d)

    admin = create_async_engine(admin_url)
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f"SET LOCAL blackbread.tenant_id = '{TENANT}'"))
            await insert_proposal(conn, p)
            await insert_decision(conn, d)
    finally:
        await admin.dispose()

    return {"proposal": p, "decision": d, "event": e, "engagement_id": engagement_id}



async def _assert_event_rejected(
    session: AsyncSession,
    event: dict[str, Any],
    engagement_id: uuid.UUID,
    match: str = "",

def _mutate_payload(base_event: dict, key: str, value: Any) -> dict:
    event = copy.deepcopy(base_event)
    event["payload"][key] = value
    return event


