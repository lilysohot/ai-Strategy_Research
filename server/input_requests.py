"""Durable input requests and logical continuation with a new Run (DATA-07)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from server import business_events, dispatch_outbox, store
from server import business_service as biz
from server import investment_snapshot as snapshots
from server.config import get_config, run_dir_for

PENDING = "pending"
ANSWERED = "answered"
CANCELLED = "cancelled"
EXPIRED = "expired"
TERMINAL = frozenset({ANSWERED, CANCELLED, EXPIRED})


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _field_names(fields: list[dict[str, Any]]) -> set[str]:
    return {str(field.get("name") or "") for field in fields}


def validate_fields(fields: Any) -> list[dict[str, Any]]:
    if not isinstance(fields, list) or not fields:
        raise biz.ValidationError("补数请求缺少字段", fields={"fields": "至少需要一个待补字段"})
    allowed = {"name", "unit", "currency", "known_value", "reason"}
    validated: list[dict[str, Any]] = []
    for index, item in enumerate(fields):
        if not isinstance(item, dict):
            raise biz.ValidationError("补数字段格式不正确", fields={f"fields.{index}": "需要对象"})
        unknown = set(item) - allowed
        name = str(item.get("name") or "").strip()
        if unknown or "." not in name:
            raise biz.ValidationError(
                "补数字段格式不正确",
                fields={f"fields.{index}": "name 必须是 account.field/plan.field/trade.field"},
            )
        group, field = name.split(".", 1)
        if group not in biz.GROUP_FIELDS or field not in biz.GROUP_FIELDS[group]:
            raise biz.UnknownFieldError("补数请求包含未知字段", fields={name: "字段不属于业务契约"})
        validated.append({key: item.get(key) for key in allowed if key in item})
    if len(_field_names(validated)) != len(validated):
        raise biz.ValidationError("补数字段重复", fields={"fields": "同一字段只能出现一次"})
    return validated


def request_view(
    row: store.InputRequest,
    *,
    answers: list[store.InputRequestAnswer] | None = None,
    current_versions: dict[str, int] | None = None,
) -> dict[str, Any]:
    collected = dict(row.collected_json or {})
    submitted = {f"{group}.{name}" for group, values in collected.items() for name in values}
    requested = _field_names(row.fields_json or [])
    return {
        "id": str(row.id),
        "research_id": str(row.research_id),
        "source_run_id": row.source_run_id.hex if row.source_run_id else None,
        "watch_event_id": str(row.watch_event_id) if row.watch_event_id else None,
        "follow_up_run_id": row.follow_up_run_id.hex if row.follow_up_run_id else None,
        "use_case": row.use_case,
        "status": row.status,
        "revision": row.revision,
        "fields": list(row.fields_json or []),
        "known_versions": dict(row.known_versions_json or {}),
        "current_versions": current_versions or dict(row.known_versions_json or {}),
        "collected": collected,
        "remaining_fields": sorted(requested - submitted),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "answers": [
            {
                "revision": answer.revision,
                "answer": answer.answer_text,
                "declared": dict(answer.declared_json or {}),
                "outcome": answer.outcome,
                "created_at": answer.created_at.isoformat() if answer.created_at else None,
            }
            for answer in (answers or [])
        ],
    }


async def load_current_versions(
    session: AsyncSession, *, row: store.InputRequest
) -> dict[str, int]:
    """Resolve mutable business-object revisions for an explicit UI acknowledgement."""
    spec = snapshots.parse_investment_input(
        dict(row.continuation_json or {}).get("investment_input")
    )
    if spec is None:
        return dict(row.known_versions_json or {})
    versions: dict[str, int] = {}
    for group, model in (("account", store.InvestmentAccount), ("plan", store.InvestmentPlan)):
        ref = getattr(spec, group)
        if ref is None:
            continue
        current = await session.get(model, ref.id)
        if current is not None and current.user_id == row.user_id:
            versions[group] = current.current_revision
    return versions


def _spec_json(spec: snapshots.InvestmentInputSpec) -> dict[str, Any]:
    def ref(value: snapshots.ObjectRef | None) -> dict[str, Any] | None:
        return {"id": str(value.id)} if value else None

    return {
        "use_case": spec.use_case,
        "account": ref(spec.account),
        "plan": ref(spec.plan),
        "trade": ref(spec.trade),
        "position": ref(spec.position),
    }


async def create_request(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    research_id: uuid.UUID,
    use_case: str,
    fields: Any,
    idempotency_key: str,
    source_run_id: uuid.UUID | None = None,
    watch_event_id: uuid.UUID | None = None,
    continuation: dict[str, Any] | None = None,
    expires_at: datetime | None = None,
) -> biz.WriteOutcome:
    requested = validate_fields(fields)
    payload = {
        "research_id": str(research_id),
        "source_run_id": str(source_run_id) if source_run_id else None,
        "watch_event_id": str(watch_event_id) if watch_event_id else None,
        "use_case": use_case,
        "fields": requested,
        "continuation": continuation or {},
        "expires_at": expires_at,
    }

    async def execute() -> dict[str, Any]:
        research = await session.get(store.Session, research_id, with_for_update=True)
        if research is None or research.user_id != user_id:
            raise biz.NotFoundOrForbiddenError("研究不存在或无权访问")
        if research.deleted_at is not None:
            raise biz.RevisionConflictError("研究已删除", current={"deleted": True})

        continuation_data = dict(continuation or {})
        known_versions: dict[str, int] = {}
        source_run = None
        if source_run_id is not None:
            source_run = await session.get(store.Run, source_run_id, with_for_update=True)
            if (
                source_run is None
                or source_run.user_id != user_id
                or source_run.session_id != research_id
            ):
                raise biz.NotFoundOrForbiddenError("来源运行不存在或不属于该研究")
            snapshot = await snapshots.get_snapshot(session, user_id=user_id, run_id=source_run_id)
            if snapshot is None:
                raise biz.SnapshotAbsentError("来源运行没有业务快照，无法建立补数续接")
            spec = snapshots.spec_from_snapshot(snapshot)
            if use_case != snapshot.use_case:
                raise biz.ValidationError(
                    "补数用途与来源快照不一致", fields={"use_case": snapshot.use_case}
                )
            continuation_data = {
                "message": source_run.prompt,
                "investment_input": _spec_json(spec),
                "pipeline_id": source_run.pipeline_id,
            }
            if snapshot.account_revision is not None:
                known_versions["account"] = snapshot.account_revision
            if snapshot.plan_revision is not None:
                known_versions["plan"] = snapshot.plan_revision
            if source_run.status in store.ACTIVE_RUN_STATUSES:
                await dispatch_outbox.abandon_for_run(
                    session, run_id=source_run.id, reason="等待补充业务资料"
                )
                source_run.status = "stopped"
                source_run.stopped_by = "input_required"
                source_run.finished_at = _now()
        else:
            raw_spec = continuation_data.get("investment_input")
            if (
                not continuation_data.get("message")
                or snapshots.parse_investment_input(raw_spec) is None
            ):
                raise biz.ValidationError(
                    "无来源 Run 的补数请求需要续接信息",
                    fields={"continuation": "需要 message 和 investment_input"},
                )
            parsed = snapshots.parse_investment_input(raw_spec)
            if parsed and parsed.account and parsed.account.expected_revision:
                known_versions["account"] = parsed.account.expected_revision
            if parsed and parsed.plan and parsed.plan.expected_revision:
                known_versions["plan"] = parsed.plan.expected_revision

        row = store.InputRequest(
            user_id=user_id,
            research_id=research_id,
            source_run_id=source_run_id,
            watch_event_id=watch_event_id,
            use_case=use_case,
            fields_json=requested,
            known_versions_json=known_versions,
            continuation_json=continuation_data,
            collected_json={},
            expires_at=expires_at,
        )
        session.add(row)
        await session.flush()
        await business_events.add_event(
            session,
            user_id=user_id,
            research_id=research_id,
            kind="input_required",
            title="有资料需要补充",
            summary="补齐明确事实后才能继续依赖这些字段的分析。",
            request_id=row.id,
            run_id=source_run_id,
            detail={"fields": [field["name"] for field in requested]},
        )
        await session.flush()
        return {"request_id": str(row.id), "status": row.status, "revision": row.revision}

    return await biz.run_write(
        session,
        user_id=user_id,
        scope="input_request.create",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=execute,
    )


def _state_error(row: store.InputRequest) -> biz.BusinessError:
    if row.status == ANSWERED:
        return biz.RequestAlreadyAnsweredError(
            "补数请求已回答", current={"follow_up_run_id": str(row.follow_up_run_id or "")}
        )
    if row.status == CANCELLED:
        return biz.RequestCancelledError("补数请求已取消")
    return biz.RequestExpiredError("补数请求已过期")


def _merge_collected(
    existing: dict[str, Any], declared: dict[str, Any]
) -> tuple[dict[str, Any], set[str], bool]:
    """Return effective collected values, answered qualified fields, and ambiguity."""
    merged = {group: dict(values) for group, values in existing.items()}
    answered: set[str] = set()
    ambiguous = False
    groups = snapshots.group_declared(declared)
    for group, raw_values in groups.items():
        effective: dict[str, Any] = {}
        for name, raw in raw_values.items():
            status = (
                str(raw.get("status") or "user_provided")
                if isinstance(raw, dict)
                else "user_provided"
            )
            if status in biz.REJECTED_STATUSES or status in biz.PENDING_STATUSES:
                ambiguous = True
                target = merged.get(group)
                if target is not None:
                    target.pop(name, None)
                    if not target:
                        merged.pop(group, None)
                continue
            effective[name] = raw
        admission = biz.admit_group(group, effective)
        ambiguous = ambiguous or bool(admission.incomplete)
        if not admission.values:
            continue
        target = merged.setdefault(group, {})
        for name in admission.values:
            target[name] = effective[name]
            answered.add(f"{group}.{name}")
    return merged, answered, ambiguous


def _with_expected_versions(
    spec: snapshots.InvestmentInputSpec,
    known: dict[str, Any],
    supplied: dict[str, Any],
) -> snapshots.InvestmentInputSpec:
    updates: dict[str, Any] = {}
    for group in ("account", "plan"):
        ref = getattr(spec, group)
        if ref is None:
            continue
        raw = supplied.get(group, known.get(group))
        if type(raw) is not int or raw < 1:
            raise biz.ValidationError(
                "回答缺少资料版本", fields={f"expected_versions.{group}": "需要正整数版本"}
            )
        updates[group] = snapshots.ObjectRef(ref.id, raw)
    return replace(spec, **updates)


async def answer_request(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    request_id: uuid.UUID,
    answer_text: str,
    declared: dict[str, Any],
    expected_versions: dict[str, Any],
    idempotency_key: str,
) -> biz.WriteOutcome:
    payload = {
        "request_id": str(request_id),
        "answer": answer_text,
        "declared": declared,
        "expected_versions": expected_versions,
    }

    async def execute() -> dict[str, Any]:
        row = (
            await session.execute(
                select(store.InputRequest)
                .where(store.InputRequest.id == request_id, store.InputRequest.user_id == user_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise biz.NotFoundOrForbiddenError("补数请求不存在或无权访问")
        if row.status != PENDING:
            raise _state_error(row)
        if _aware(row.expires_at) is not None and _aware(row.expires_at) <= _now():
            raise biz.RequestExpiredError("补数请求已过期")
        research = await session.get(store.Session, row.research_id, with_for_update=True)
        if research is None or research.user_id != user_id or research.deleted_at is not None:
            raise biz.RevisionConflictError("研究已删除或不可用", current={"deleted": True})
        if not isinstance(declared, dict):
            raise biz.ValidationError("回答字段格式不正确", fields={"declared": "需要对象"})
        if not answer_text.strip() and not declared:
            raise biz.ValidationError("回答不能为空", fields={"answer": "请填写回答或结构化字段"})

        collected, answered_now, ambiguous = _merge_collected(row.collected_json or {}, declared)
        requested = _field_names(row.fields_json or [])
        submitted_fields = {
            f"{group}.{name}" for group, values in collected.items() for name in values
        }
        extra = submitted_fields - requested
        if extra:
            raise biz.UnknownFieldError(
                "回答包含未请求的字段", fields={name: "请只回答本次待补字段" for name in extra}
            )
        row.collected_json = collected
        row.revision += 1
        complete = bool(requested) and requested <= submitted_fields and not ambiguous
        outcome_name = ANSWERED if complete else "pending_clarification"
        answer = store.InputRequestAnswer(
            request_id=row.id,
            user_id=user_id,
            revision=row.revision,
            answer_text=answer_text.strip(),
            declared_json=declared,
            outcome=outcome_name,
        )
        session.add(answer)
        if not complete:
            await session.flush()
            return {
                "request_id": str(row.id),
                "status": PENDING,
                "revision": row.revision,
                "remaining_fields": sorted(requested - submitted_fields),
                "accepted_fields": sorted(answered_now),
                "follow_up_run_id": None,
            }

        continuation = dict(row.continuation_json or {})
        spec = snapshots.parse_investment_input(continuation.get("investment_input"))
        if spec is None:
            raise biz.ValidationError("补数请求缺少有效续接输入")
        spec = _with_expected_versions(
            replace(spec, declared=collected, idempotency_key=idempotency_key),
            row.known_versions_json or {},
            expected_versions,
        )
        saved_spec, saved = await snapshots.persist_declared(
            session, user_id=user_id, research_id=row.research_id, spec=spec
        )
        resolution = await snapshots.resolve_for_run(
            session, user_id=user_id, research_id=row.research_id, spec=saved_spec
        )
        cfg = get_config()
        depth = await dispatch_outbox.research_queue_depth(session, row.research_id)
        if depth >= cfg.dispatch_research_queue_limit:
            raise biz.QueueFullError(
                "该研究的待执行任务已达上限",
                current={"queue_depth": depth, "queue_limit": cfg.dispatch_research_queue_limit},
            )
        source_run = await session.get(store.Run, row.source_run_id) if row.source_run_id else None
        run_id = uuid.uuid4()
        prompt = str(continuation.get("message") or "补充资料后继续分析")
        pipeline_id = str(
            continuation.get("pipeline_id")
            or (source_run.pipeline_id if source_run else cfg.pipeline_id)
        )
        store.add_run(
            session,
            run_id=run_id,
            session_id=row.research_id,
            user_id=user_id,
            prompt=prompt,
            pipeline_id=pipeline_id,
            run_dir=str(run_dir_for(run_id.hex)),
            llm_config_id=source_run.llm_config_id if source_run else None,
            llm_snapshot_json=source_run.llm_snapshot_json if source_run else None,
        )
        snapshot = snapshots.build_snapshot(
            run_id=run_id,
            user_id=user_id,
            research_id=row.research_id,
            spec=saved_spec,
            resolution=resolution,
            source="input_answer",
            rerun_of_run_id=row.source_run_id,
        )
        session.add(snapshot)
        await store.append_turn_in(
            session,
            session_id=row.research_id,
            role="user",
            content=answer_text.strip() or "已补充所需资料",
            run_id=run_id,
        )
        dispatch = await dispatch_outbox.enqueue(
            session,
            run_id=run_id,
            user_id=user_id,
            research_id=row.research_id,
            session_key=str(row.research_id),
            prompt=prompt,
            prompt_addendum=f"Continue input request {row.id}; use the frozen business snapshot.",
        )
        row.status = ANSWERED
        row.answered_at = _now()
        row.follow_up_run_id = run_id
        answer.outcome = ANSWERED
        await business_events.add_event(
            session,
            user_id=user_id,
            research_id=row.research_id,
            kind="input_answered",
            title="补充资料已采用",
            summary="业务资料已保存，后续分析已进入队列。",
            request_id=row.id,
            run_id=run_id,
        )
        await session.flush()
        return {
            "request_id": str(row.id),
            "status": ANSWERED,
            "revision": row.revision,
            "follow_up_run_id": run_id.hex,
            "snapshot_id": str(snapshot.id),
            "saved": saved,
            "dispatch": dispatch_outbox.dispatch_view(dispatch),
        }

    outcome = await biz.run_write(
        session,
        user_id=user_id,
        scope="input_request.answer",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=execute,
    )
    # The operation row exists after run_write returns; bind the append-only
    # answer for lookup without affecting idempotency semantics.
    answer = (
        await session.execute(
            select(store.InputRequestAnswer)
            .where(store.InputRequestAnswer.request_id == request_id)
            .order_by(store.InputRequestAnswer.revision.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if answer is not None and answer.operation_id is None:
        answer.operation_id = uuid.UUID(outcome.operation_id)
        await session.flush()
    return outcome


async def cancel_request(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    request_id: uuid.UUID,
    idempotency_key: str,
) -> biz.WriteOutcome:
    async def execute() -> dict[str, Any]:
        row = (
            await session.execute(
                select(store.InputRequest)
                .where(store.InputRequest.id == request_id, store.InputRequest.user_id == user_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise biz.NotFoundOrForbiddenError("补数请求不存在或无权访问")
        if row.status != PENDING:
            raise _state_error(row)
        row.status = CANCELLED
        row.cancelled_at = _now()
        row.revision += 1
        await session.flush()
        return {"request_id": str(row.id), "status": CANCELLED, "revision": row.revision}

    return await biz.run_write(
        session,
        user_id=user_id,
        scope="input_request.cancel",
        idempotency_key=idempotency_key,
        payload={"request_id": str(request_id)},
        execute=execute,
    )


async def expire_due(session: AsyncSession, *, user_id: uuid.UUID) -> None:
    # The status predicate is re-evaluated after any row-lock wait. A stale
    # reader therefore cannot overwrite an answer/cancel that committed first.
    await session.execute(
        update(store.InputRequest)
        .where(
            store.InputRequest.user_id == user_id,
            store.InputRequest.status == PENDING,
            store.InputRequest.expires_at.is_not(None),
            store.InputRequest.expires_at <= _now(),
        )
        .values(status=EXPIRED, revision=store.InputRequest.revision + 1)
    )
    await session.flush()


async def list_requests(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    research_id: uuid.UUID | None,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[store.InputRequest], int]:
    await expire_due(session, user_id=user_id)
    filters = [store.InputRequest.user_id == user_id]
    if research_id is not None:
        filters.append(store.InputRequest.research_id == research_id)
    if status is not None:
        filters.append(store.InputRequest.status == status)
    total = (
        await session.execute(select(func.count()).select_from(store.InputRequest).where(*filters))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                select(store.InputRequest)
                .where(*filters)
                .order_by(store.InputRequest.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)
