"""Authenticated, run-scoped monitoring operations. No model-supplied owner IDs."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select

from server import business_service as biz
from server import monitor_longterm as longterm
from server import store, watch_rules


async def call(run_id: uuid.UUID, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with biz.business_transaction() as session:
        run = await session.get(store.Run, run_id)
        if run is None or run.status not in {"queued", "running"}:
            raise biz.ValidationError("运行已结束，拒绝执行监控工具")
        await watch_rules._ensure_research(session, user_id=run.user_id, research_id=run.session_id)
        event = await session.scalar(
            select(store.WatchEvent).where(store.WatchEvent.run_id == run_id)
        )
        if event and event.round_id:
            hits = await longterm.live_hits(session, event)
            if not hits:
                raise biz.ValidationError("监控已暂停或取消，停止执行后续工具")
        state = await longterm.settings(session, run.session_id)
        if operation == "guard":
            return {"ok": True}
        rows = await longterm.targets(session, run.session_id)
        if operation == "get":
            return {
                "ok": True,
                "auto_manage": state.auto_manage,
                "remaining": max(0, 3 - len(rows)),
                "targets": [watch_rules.rule_view(r, v) for r, v in rows],
            }
        if operation != "submit":
            raise biz.ValidationError("未知监控操作")
        if not state.auto_manage:
            raise biz.ValidationError("当前会话尚未开启 Agent 自动维护监控")
        raw_intents = payload.get("intents")
        if not isinstance(raw_intents, list) or not 1 <= len(raw_intents) <= 6:
            raise biz.ValidationError("请提交 1 至 6 项明确操作，最终监控目标不能超过三个")
        if not all(isinstance(item, dict) for item in raw_intents):
            raise biz.ValidationError("每项监控操作必须是对象")
        intents: list[dict[str, Any]] = raw_intents
        # An identical request is exactly-once even after a lost socket response.
        digest = hashlib.sha256(
            json.dumps(intents, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

        async def apply() -> dict[str, Any]:
            results = []
            for index, intent in enumerate(
                sorted(intents, key=lambda i: i.get("operation") != "cancel")
            ):
                op = intent.get("operation")
                if op in {"update", "cancel"} and not intent.get("rule_id"):
                    raise biz.ValidationError("修改或取消需要 rule_id 与 expected_version")
                key = str(intent.get("intent_key") or "").strip()
                reason = str(intent.get("reason") or "").strip()
                if not key or len(key) > 120 or not reason:
                    raise biz.ValidationError("每个监控操作需要稳定 intent_key 和具体 reason")
                rule = None
                if intent.get("rule_id"):
                    rule = await session.get(
                        store.WatchRule, uuid.UUID(intent["rule_id"]), with_for_update=True
                    )
                    if (
                        rule is None
                        or rule.user_id != run.user_id
                        or rule.research_id != run.session_id
                    ):
                        raise biz.NotFoundOrForbiddenError("监控目标不属于当前会话")
                previous = await session.scalar(
                    select(store.WatchRule)
                    .where(
                        store.WatchRule.research_id == run.session_id,
                        store.WatchRule.agent_intent == key,
                    )
                    .order_by(store.WatchRule.created_at.desc())
                    .limit(1)
                    .with_for_update()
                )
                if previous and rule and previous.id != rule.id:
                    raise biz.ValidationError("intent_key 已属于另一个监控目标")
                cancelling_paused = bool(
                    op == "cancel" and rule and rule.status == "paused" and event is None
                )
                if previous and previous.status != "active" and not cancelling_paused:
                    raise biz.ValidationError("该监控意图已暂停或取消，不可自动重建")
                if op == "create" and previous:
                    rule = previous
                    op = "update"
                    if intent.get("expected_version") is None:
                        intent = dict(intent, expected_version=rule.current_version)
                if rule and (
                    (rule.status != "active" and not cancelling_paused) or rule.managed_by != "agent"
                ):
                    raise biz.ValidationError("目标已暂停、取消或由人工维护，不能自动覆盖")
                write_key = f"watch-agent:{run_id}:{digest}:{index}"
                if op == "cancel":
                    if rule is None:
                        raise biz.ValidationError("取消需要 rule_id 与 expected_version")
                    result = await watch_rules.set_rule_status(
                        session,
                        user_id=run.user_id,
                        rule_id=rule.id,
                        expected_version=intent.get("expected_version"),
                        target="cancelled",
                        scope="watch_rule.cancel",
                        idempotency_key=write_key,
                    )
                    results.append(result.result)
                    continue
                if op not in {"create", "update"}:
                    raise biz.ValidationError("仅支持 create、update、cancel")
                raw_spec = intent.get("spec", {})
                if not isinstance(raw_spec, dict):
                    raise biz.ValidationError("spec 必须是对象")
                spec: dict[str, Any] = dict(raw_spec)
                if rule is None:
                    spec.setdefault("trigger_mode", "continuous")
                if "trigger_mode" in spec and spec["trigger_mode"] not in watch_rules.LONG_RUNNING_MODES:
                    raise biz.ValidationError("Agent 长期监控请选择 continuous 或 crossing")
                spec.update(on_create_already_met="trigger_now", budget={})
                if rule is None:
                    spec.setdefault("action", "auto_analyze")
                    spec.setdefault("task", "核验价格并综合当前持仓与行情，复核全部监控目标。")
                if rule:
                    if intent.get("expected_version") != rule.current_version:
                        raise biz.ValidationError("监控版本冲突，请重新读取目标")
                    rev = await watch_rules._latest_revision(session, rule.id, rule.current_version)
                    if rev is None:
                        raise biz.ValidationError("监控版本不存在")
                    existing = watch_rules._config_view(rev)
                    if all(existing.get(k) == v for k, v in spec.items()):
                        rule.rationale = {
                            "reason": reason,
                            "evidence_refs": intent.get("evidence_refs", []),
                            "run_id": str(run_id),
                        }
                        results.append(
                            {
                                "rule_id": str(rule.id),
                                "status": "unchanged",
                                "version": rule.current_version,
                            }
                        )
                        continue
                    result = await watch_rules.update_rule(
                        session,
                        user_id=run.user_id,
                        rule_id=rule.id,
                        expected_version=intent.get("expected_version"),
                        patch=spec,
                        idempotency_key=write_key,
                        source_kind="agent",
                        source_ref=str(run_id),
                    )
                else:
                    # Exact executable duplicates cannot acquire another slot by renaming an intent.
                    for _other, rev in await longterm.targets(session, run.session_id):
                        config = watch_rules._config_view(rev)
                        if all(
                            config.get(k) == spec.get(k)
                            for k in (
                                "symbol",
                                "market",
                                "currency",
                                "quote_basis",
                                "direction",
                                "threshold",
                                "action",
                            )
                        ):
                            raise biz.ValidationError("已有相同价格条件，请读取现有目标后处理")
                    result = await watch_rules.create_rule(
                        session,
                        user_id=run.user_id,
                        research_id=run.session_id,
                        plan_id=None,
                        name=str(intent.get("name") or key),
                        spec=spec,
                        idempotency_key=write_key,
                        source_kind="agent",
                        source_ref=str(run_id),
                    )
                    rule = await session.get(store.WatchRule, uuid.UUID(result.result["rule_id"]))
                if rule is None:
                    raise biz.ValidationError("监控保存未返回有效目标")
                rule.managed_by, rule.agent_intent = "agent", key
                rule.rationale = {
                    "reason": reason,
                    "evidence_refs": intent.get("evidence_refs", []),
                    "run_id": str(run_id),
                }
                results.append(result.result)
            await session.flush()
            return {"ok": True, "status": "applied", "results": results}

        result = await biz.run_write(
            session,
            user_id=run.user_id,
            scope="watch_agent.submit",
            idempotency_key=f"watch-agent:{run_id}:{digest}",
            payload=payload,
            execute=apply,
        )
        return result.result
