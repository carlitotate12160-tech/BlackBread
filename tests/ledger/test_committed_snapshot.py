import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from blackbread.ledger import EventDraft, append_event, verify_chain
from blackbread.ledger import verify as verify_module
from blackbread.models.core import Engagement


def _draft(engagement: Engagement, marker: str) -> EventDraft:
    return EventDraft(
        tenant_id=engagement.tenant_id,
        engagement_id=engagement.id,
        schema_name="test.snapshot",
        schema_version=1,
        producer="test-producer",
        payload={"marker": marker},
        occurred_at=datetime.now(UTC),
    )


async def _seed(
    factory: async_sessionmaker[AsyncSession], engagement: Engagement, count: int
) -> list[str]:
    hashes: list[str] = []
    async with factory() as session:
        for sequence in range(1, count + 1):
            event = await append_event(session, _draft(engagement, f"seed-{sequence}"))
            hashes.append(event.event_hash)
        await session.commit()
    return hashes


async def test_uncommitted_append_does_not_block_or_enter_snapshot(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    engagement: Engagement,
) -> None:
    hashes = await _seed(session_factory, engagement, 2)
    flushed = asyncio.Event()
    release = asyncio.Event()

    async def writer() -> None:
        async with session_factory() as session:
            await append_event(session, _draft(engagement, "uncommitted"))
            flushed.set()
            await release.wait()
            await session.rollback()

    task = asyncio.create_task(writer())
    await flushed.wait()
    try:
        result = await asyncio.wait_for(
            verify_chain(
                engine,
                tenant_id=engagement.tenant_id,
                engagement_id=engagement.id,
            ),
            timeout=2,
        )
        assert result.ok is True
        assert result.tenant_id == engagement.tenant_id
        assert result.engagement_id == engagement.id
        assert result.verified_event_count == 2
        assert result.verified_head_hash == hashes[1]
        assert not release.is_set()
    finally:
        release.set()
        await task


async def test_commit_during_verification_is_excluded_from_exact_snapshot(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    engagement: Engagement,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hashes = await _seed(session_factory, engagement, 3)
    anchor_read = asyncio.Event()
    resume_scan = asyncio.Event()

    async def pause_after_anchor(connection: object) -> None:
        del connection
        anchor_read.set()
        await resume_scan.wait()

    monkeypatch.setattr("blackbread.ledger.verify._after_snapshot_anchor", pause_after_anchor)
    verification = asyncio.create_task(
        verify_chain(engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id)
    )
    await anchor_read.wait()

    async with session_factory() as writer:
        fourth = await append_event(writer, _draft(engagement, "committed-during-verification"))
        await asyncio.wait_for(writer.commit(), timeout=2)
    assert not verification.done()

    resume_scan.set()
    first = await verification
    second = await verify_chain(engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id)

    assert first.verified_event_count == 3
    assert first.verified_head_hash == hashes[2]
    assert second.verified_event_count == 4
    assert second.verified_head_hash == fourth.event_hash


async def test_verifier_uses_real_repeatable_read_read_only_transaction(
    engine: AsyncEngine,
    engagement: Engagement,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: tuple[str, str] | None = None

    async def inspect_transaction(connection: object) -> None:
        nonlocal observed
        isolation = await connection.scalar(text("SHOW transaction_isolation"))  # type: ignore[attr-defined]
        read_only = await connection.scalar(text("SHOW transaction_read_only"))  # type: ignore[attr-defined]
        observed = (isolation, read_only)

    monkeypatch.setattr("blackbread.ledger.verify._after_snapshot_anchor", inspect_transaction)
    result = await verify_chain(engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id)

    assert result.ok is True
    assert observed == ("repeatable read", "on")


async def test_verifier_does_not_touch_caller_transaction(
    engine: AsyncEngine,
    session: AsyncSession,
    engagement: Engagement,
) -> None:
    await session.execute(text("SELECT 1"))
    caller_transaction = session.get_transaction()

    await verify_chain(engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id)

    assert session.in_transaction()
    assert session.get_transaction() is caller_transaction
    await session.rollback()


async def test_cancellation_cleans_up_single_connection_pool(
    engine: AsyncEngine,
    engagement: Engagement,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constrained = create_async_engine(str(engine.url), pool_size=1, max_overflow=0)
    anchor_read = asyncio.Event()
    never_resume = asyncio.Event()

    async def pause(connection: object) -> None:
        del connection
        anchor_read.set()
        await never_resume.wait()

    monkeypatch.setattr("blackbread.ledger.verify._after_snapshot_anchor", pause)
    task = asyncio.create_task(
        verify_chain(
            constrained,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
        )
    )
    await anchor_read.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    monkeypatch.setattr(
        "blackbread.ledger.verify._after_snapshot_anchor",
        verify_module._no_snapshot_hook,
    )
    try:
        result = await asyncio.wait_for(
            verify_chain(
                constrained,
                tenant_id=engagement.tenant_id,
                engagement_id=engagement.id,
            ),
            timeout=2,
        )
        assert result.ok is True
        assert constrained.pool.checkedout() == 0
    finally:
        await constrained.dispose()
