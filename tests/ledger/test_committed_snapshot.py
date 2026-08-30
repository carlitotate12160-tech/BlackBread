import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from blackbread.ledger import EventDraft, append_event, verify_chain
from blackbread.models.core import Engagement
from blackbread.tenancy import TenantContext, bind_tenant_context


async def _bind(binder: AsyncSession, tenant_id: str) -> None:
    await bind_tenant_context(binder, TenantContext(tenant_id))


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
        await _bind(session, engagement.tenant_id)
        for sequence in range(1, count + 1):
            event_record = await append_event(
                session,
                _draft(engagement, f"seed-{sequence}"),
                tenant_context=TenantContext(engagement.tenant_id),
            )
            hashes.append(event_record.event_hash)
        await session.commit()
    return hashes


def _pause_connection_stream(
    monkeypatch: pytest.MonkeyPatch,
    stream_entered: asyncio.Event,
    resume_stream: asyncio.Event,
) -> None:
    original_stream = AsyncConnection.stream

    async def paused_stream(
        connection: AsyncConnection,
        *args: object,
        **kwargs: object,
    ) -> object:
        stream_entered.set()
        await resume_stream.wait()
        return await original_stream(connection, *args, **kwargs)

    monkeypatch.setattr(AsyncConnection, "stream", paused_stream)


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
            await _bind(session, engagement.tenant_id)
            await append_event(
                session,
                _draft(engagement, "uncommitted"),
                tenant_context=TenantContext(engagement.tenant_id),
            )
            flushed.set()
            await release.wait()
            await session.rollback()

    task = asyncio.create_task(writer())
    await asyncio.wait_for(flushed.wait(), timeout=2)
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
    stream_entered = asyncio.Event()
    resume_stream = asyncio.Event()
    _pause_connection_stream(monkeypatch, stream_entered, resume_stream)

    verification = asyncio.create_task(
        verify_chain(engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id)
    )
    await asyncio.wait_for(stream_entered.wait(), timeout=2)

    async with session_factory() as writer:
        await _bind(writer, engagement.tenant_id)
        fourth = await append_event(
            writer,
            _draft(engagement, "committed-during-verification"),
            tenant_context=TenantContext(engagement.tenant_id),
        )
        await asyncio.wait_for(writer.commit(), timeout=2)
    assert not verification.done()

    resume_stream.set()
    first = await verification
    monkeypatch.undo()
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
    original_stream = AsyncConnection.stream

    async def inspect_transaction(
        connection: AsyncConnection,
        *args: object,
        **kwargs: object,
    ) -> object:
        nonlocal observed
        isolation = await connection.scalar(text("SHOW transaction_isolation"))
        read_only = await connection.scalar(text("SHOW transaction_read_only"))
        observed = (isolation, read_only)
        return await original_stream(connection, *args, **kwargs)

    monkeypatch.setattr(AsyncConnection, "stream", inspect_transaction)
    result = await verify_chain(engine, tenant_id=engagement.tenant_id, engagement_id=engagement.id)

    assert result.ok is True
    assert result.verified_event_count == 0
    assert result.verified_head_hash == "0" * 64
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
    database_url = engine.url.render_as_string(hide_password=False)
    constrained = create_async_engine(database_url, pool_size=1, max_overflow=0)
    stream_entered = asyncio.Event()
    never_resume = asyncio.Event()
    _pause_connection_stream(monkeypatch, stream_entered, never_resume)
    task = asyncio.create_task(
        verify_chain(
            constrained,
            tenant_id=engagement.tenant_id,
            engagement_id=engagement.id,
        )
    )
    await asyncio.wait_for(stream_entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    monkeypatch.undo()
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


async def test_connection_acquisition_failure_cannot_return_success(
    engine: AsyncEngine,
    engagement: Engagement,
) -> None:
    def reject_checkout(*args: object) -> None:
        del args
        raise RuntimeError("injected checkout failure")

    event.listen(engine.sync_engine.pool, "checkout", reject_checkout)
    try:
        with pytest.raises(RuntimeError, match="injected checkout failure"):
            await verify_chain(
                engine,
                tenant_id=engagement.tenant_id,
                engagement_id=engagement.id,
            )
    finally:
        event.remove(engine.sync_engine.pool, "checkout", reject_checkout)
    assert engine.pool.checkedout() == 0


async def test_isolation_setup_failure_cannot_return_success(
    engine: AsyncEngine,
    engagement: Engagement,
) -> None:
    def reject_execution_options(*args: object) -> None:
        del args
        raise RuntimeError("injected isolation setup failure")

    event.listen(
        engine.sync_engine,
        "set_connection_execution_options",
        reject_execution_options,
    )
    try:
        with pytest.raises(RuntimeError, match="injected isolation setup failure"):
            await verify_chain(
                engine,
                tenant_id=engagement.tenant_id,
                engagement_id=engagement.id,
            )
    finally:
        event.remove(
            engine.sync_engine,
            "set_connection_execution_options",
            reject_execution_options,
        )
    assert engine.pool.checkedout() == 0


async def test_read_only_setup_failure_cannot_return_success(
    engine: AsyncEngine,
    engagement: Engagement,
) -> None:
    def reject_read_only(*args: object) -> None:
        statement = args[2]
        if isinstance(statement, str) and statement.strip().upper() == "SET TRANSACTION READ ONLY":
            raise RuntimeError("injected read-only setup failure")

    event.listen(engine.sync_engine, "before_cursor_execute", reject_read_only)
    try:
        with pytest.raises(RuntimeError, match="injected read-only setup failure"):
            await verify_chain(
                engine,
                tenant_id=engagement.tenant_id,
                engagement_id=engagement.id,
            )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", reject_read_only)
    assert engine.pool.checkedout() == 0
