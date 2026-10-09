"""补数回答字段集/续接修复：本机 SQLite 证据（无 PG 可用时）。

本机没有 PostgreSQL（`tests/pg` 需要 PG_INTEGRATION=1 + 登记测试库，见
tests/pg/conftest.py），因此这份 harness 用 tests/conftest.py 同款的隔离 SQLite +
``store.init_db()``（create_all）在服务层驱动真实代码路径：

    A. 报告的真实路径：研究无账户/无计划 → worker 意图落库的请求含 8 个字段 →
       弹窗"先创建主账户"后回答携带风险/盈利（**未被请求**但属契约）→ 不再 400，
       值被记入 collected；契约外字段（``plan_price``）仍被拒。
    B. 无快照续接 + 账户/计划在请求之后才建立 → 回答能落库并生成后续 Run
       （`_adopt_research_bindings`）。
    C. 无快照续接 + 当时已有对象 → 续接冻结里记录 expected_revision（known_versions），
       回答可用它完成续接。

用法：``uv run --no-sync python .scratch/web-input-request-fix-20261009/evidence/input-answer-harness.py``
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from pathlib import Path

PASS: list[str] = []


def ok(label: str, condition: bool, detail: object = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label} {detail}")
    if not condition:
        raise SystemExit(1)
    PASS.append(label)


async def _bootstrap(session: object, store: object, *, name: str) -> tuple[uuid.UUID, uuid.UUID]:
    uid, rid = uuid.uuid4(), uuid.uuid4()
    session.add(store.User(id=uid, username=f"harness-{name}-{uid.hex}", password_hash="x"))
    await session.flush()
    session.add(store.Session(id=rid, user_id=uid, title=f"harness-{name}"))
    await session.flush()
    return uid, rid


async def _staged_run(
    session: object,
    store: object,
    *,
    uid: uuid.UUID,
    rid: uuid.UUID,
    tmp: Path,
    run_dir_name: str,
) -> uuid.UUID:
    run_id = uuid.uuid4()
    run_dir = tmp / "runs" / run_dir_name
    run_dir.mkdir(parents=True, exist_ok=True)
    store.add_run(
        session,
        run_id=run_id,
        session_id=rid,
        user_id=uid,
        prompt="按当前资料给个仓位结论",
        pipeline_id="stateful-react-agent",
        run_dir=str(run_dir),
    )
    (run_dir / "input-request.json").write_text(
        json.dumps(
            {
                "schema_version": "input-request/1",
                "use_case": "plan_analysis",
                "reason": "要给仓位结论，但没有本标的规划资金",
            }
        ),
        encoding="utf-8",
    )
    return run_id


async def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="input-answer-fix-"))
    os.environ["SERVER_RUNS_ROOT"] = str(tmp / "runs")

    from server import business_service as biz
    from server import input_requests, store
    from server.config import get_config
    from server.store import reset_engine

    cfg = get_config()
    cfg.database_url = f"sqlite+aiosqlite:///{tmp / 'harness.db'}"
    cfg.runs_root = tmp / "runs"
    await reset_engine()
    await store.init_db()
    print(f"harness root: {tmp}")

    try:
        # ——— A：报告的真实路径 ——————————————————————————————————————————
        async with biz.business_transaction() as session:
            uid, rid = await _bootstrap(session, store, name="a")
            run_id = await _staged_run(session, store, uid=uid, rid=rid, tmp=tmp, run_dir_name="a")
            outcome = await input_requests.materialize_worker_intent(session, run_id=run_id)
            request_id = uuid.UUID(outcome["request_id"])
            row = await session.get(store.InputRequest, request_id)
            requested = sorted(f["name"] for f in row.fields_json)
        print(f"A 请求字段：{requested}")
        ok(
            "A1 无账户/无计划时，请求含账户事实与标的字段",
            requested
            == [
                "account.as_of",
                "account.capital_basis",
                "account.currency",
                "account.total_capital",
                "plan.allocated_capital",
                "plan.direction",
                "plan.market",
                "plan.symbol",
            ],
        )

        # 弹窗"先创建主账户"：账户走账户接口，随后回答携带弹窗采集的三项。
        async with biz.business_transaction() as session:
            account = await biz.create_account(
                session,
                user_id=uid,
                name="主账户",
                base_currency="CNY",
                declared={
                    "total_capital": "200000",
                    "available_capital": "200000",
                    "capital_basis": "tradable_assets",
                    "as_of": "2026-10-09T00:00:00Z",
                },
                idempotency_key="harness-a-account",
            )
            await biz.set_research_link(
                session,
                user_id=uid,
                research_id=rid,
                account_id=uuid.UUID(account.result["account_id"]),
                primary_plan_id=None,
                idempotency_key="harness-a-link",
            )

        # 报告里的那条回答：plan.allocated_capital + 未被请求的两项（可后补）。
        # 回答单独开一个事务（与 HTTP 端点一致）。
        async with biz.business_transaction() as session:
            answer = await input_requests.answer_request(
                session,
                user_id=uid,
                request_id=request_id,
                answer_text="本标的规划资金：20000；可承受风险：10（percent）",
                declared={
                    "plan": {
                        "allocated_capital": {"value": "20000"},
                        "risk_budget_value": {"value": "10"},
                        "risk_budget_unit": {"value": "percent"},
                        "target_profit_value": {"value": "10"},
                        "target_profit_unit": {"value": "percent"},
                    }
                },
                expected_versions={},
                idempotency_key="harness-a-answer",
            )
            result = answer.result
            row = await session.get(store.InputRequest, request_id)
            collected = dict(row.collected_json)
            remaining = list(result.get("remaining_fields", []))
        ok("A2 未被请求但属契约的字段不再 400", result["status"] == "pending", result["status"])
        ok(
            "A3 风险/盈利被记入 collected（可后补项能保存）",
            collected.get("plan", {}).get("risk_budget_value") == {"value": "10"}
            and collected.get("plan", {}).get("target_profit_unit") == {"value": "percent"},
            collected,
        )
        ok(
            "A4 仍缺的字段如实返回",
            remaining
            == [
                "account.as_of",
                "account.capital_basis",
                "account.currency",
                "account.total_capital",
                "plan.direction",
                "plan.market",
                "plan.symbol",
            ],
            remaining,
        )

        # 负例：契约外字段仍然被拒（放宽的只是"未被请求"，不是"契约外"）。
        async with biz.business_transaction() as session:
            try:
                await input_requests.answer_request(
                    session,
                    user_id=uid,
                    request_id=request_id,
                    answer_text="",
                    declared={"plan": {"plan_price": "25"}},
                    expected_versions={},
                    idempotency_key="harness-a-negative",
                )
            except biz.UnknownFieldError as exc:
                rejected = exc.to_payload()["error"]
            else:
                raise SystemExit("FAIL A5 契约外字段未被拒绝")
        ok(
            "A5 契约外字段仍是 unknown_field_rejected",
            rejected["code"] == "unknown_field_rejected" and "plan_price" in rejected["fields"],
            rejected["fields"],
        )

        # ——— B：对象在请求之后才建立 → 回答能落库并续接 ——————————————————
        async with biz.business_transaction() as session:
            uid_b, rid_b = await _bootstrap(session, store, name="b")
            run_b = await _staged_run(
                session, store, uid=uid_b, rid=rid_b, tmp=tmp, run_dir_name="b"
            )
            outcome_b = await input_requests.materialize_worker_intent(session, run_id=run_b)
            request_b = uuid.UUID(outcome_b["request_id"])
            row_b = await session.get(store.InputRequest, request_b)
            print(f"B 续接冻结：{json.dumps(row_b.continuation_json, ensure_ascii=False)}")
            ok(
                "B1 无快照续接的引用冻结为 null（用户要靠引导先建对象）",
                row_b.continuation_json["investment_input"]["account"] is None
                and row_b.continuation_json["investment_input"]["plan"] is None,
                row_b.continuation_json["investment_input"],
            )

        # 用户随后按引导建好账户 + 主计划（会话计划入口）并绑定。
        async with biz.business_transaction() as session:
            acct_b = await biz.create_account(
                session,
                user_id=uid_b,
                name="主账户",
                base_currency="CNY",
                declared={
                    "total_capital": "200000",
                    "available_capital": "200000",
                    "capital_basis": "tradable_assets",
                    "currency": "CNY",
                    "as_of": "2026-10-09T00:00:00Z",
                },
                idempotency_key="harness-b-account",
            )
            plan_b = await biz.create_plan(
                session,
                user_id=uid_b,
                research_id=rid_b,
                name="计划A",
                declared={
                    "symbol": "600519.SH",
                    "market": "CN",
                    "direction": "buy",
                    "allocated_capital": "20000",
                    "currency": "CNY",
                },
                idempotency_key="harness-b-plan",
            )
            await biz.set_research_link(
                session,
                user_id=uid_b,
                research_id=rid_b,
                account_id=uuid.UUID(acct_b.result["account_id"]),
                primary_plan_id=uuid.UUID(plan_b.result["plan_id"]),
                idempotency_key="harness-b-link",
            )

        async with biz.business_transaction() as session:
            answered_b = await input_requests.answer_request(
                session,
                user_id=uid_b,
                request_id=request_b,
                answer_text="补数中心逐项填写",
                declared={
                    "account": {
                        "total_capital": "200000",
                        "available_capital": "200000",
                        "capital_basis": "tradable_assets",
                        "currency": "CNY",
                        "as_of": "2026-10-09T00:00:00Z",
                    },
                    "plan": {
                        "symbol": "600519.SH",
                        "market": "CN",
                        "direction": "buy",
                        "allocated_capital": "20000",
                    },
                },
                expected_versions={},
                idempotency_key="harness-b-answer",
            )
            result_b = answered_b.result
        ok(
            "B2 冻结引用为 null 时仍能落库并生成后续 Run",
            result_b["status"] == "answered" and bool(result_b.get("follow_up_run_id")),
            {k: result_b.get(k) for k in ("status", "follow_up_run_id", "saved")},
        )

        # ——— C：当时已有对象 → 续接记录版本，回答可用它完成 ————————————————
        async with biz.business_transaction() as session:
            uid_c, rid_c = await _bootstrap(session, store, name="c")
            draft = await biz.create_account(
                session,
                user_id=uid_c,
                name="主账户",
                base_currency="CNY",
                declared={"total_capital": "150000"},
                allow_incomplete=True,
                idempotency_key="harness-c-account",
            )
            account_id_c = uuid.UUID(draft.result["account_id"])
            await biz.set_research_link(
                session,
                user_id=uid_c,
                research_id=rid_c,
                account_id=account_id_c,
                primary_plan_id=None,
                idempotency_key="harness-c-link",
            )
            run_c = await _staged_run(
                session, store, uid=uid_c, rid=rid_c, tmp=tmp, run_dir_name="c"
            )
            outcome_c = await input_requests.materialize_worker_intent(session, run_id=run_c)
            request_c = uuid.UUID(outcome_c["request_id"])
            row_c = await session.get(store.InputRequest, request_c)
            known_c = dict(row_c.known_versions_json)
            frozen_c = dict(row_c.continuation_json["investment_input"])
            requested_c = sorted(f["name"] for f in row_c.fields_json)
        print(f"C 请求字段：{requested_c}")
        print(f"C known_versions={known_c} frozen={json.dumps(frozen_c, ensure_ascii=False)}")
        ok(
            "C1 已有对象的续接记下当时版本（否则回答撞『回答缺少资料版本』）",
            known_c == {"account": frozen_c["account"]["expected_revision"]},
            known_c,
        )
        ok(
            "C2 已填过的账户事实不再重复索要",
            "account.total_capital" not in requested_c and "account.currency" not in requested_c,
            requested_c,
        )

        # 用户补齐后（这里直接把计划建出来并绑定），用记录版本回答。
        async with biz.business_transaction() as session:
            plan_c = await biz.create_plan(
                session,
                user_id=uid_c,
                research_id=rid_c,
                name="计划A",
                declared={
                    "symbol": "600519.SH",
                    "market": "CN",
                    "direction": "buy",
                    "allocated_capital": "20000",
                    "currency": "CNY",
                },
                idempotency_key="harness-c-plan",
            )
            await biz.set_research_link(
                session,
                user_id=uid_c,
                research_id=rid_c,
                account_id=account_id_c,
                primary_plan_id=uuid.UUID(plan_c.result["plan_id"]),
                idempotency_key="harness-c-link2",
            )
        async with biz.business_transaction() as session:
            answered_c = await input_requests.answer_request(
                session,
                user_id=uid_c,
                request_id=request_c,
                answer_text="按记录版本补齐",
                declared={
                    "account": {
                        "available_capital": "150000",
                        "capital_basis": "total",
                        "currency": "CNY",
                        "as_of": "2026-10-09T00:00:00Z",
                    },
                    "plan": {
                        "symbol": "600519.SH",
                        "market": "CN",
                        "direction": "buy",
                        "allocated_capital": "20000",
                    },
                },
                expected_versions=known_c,
                idempotency_key="harness-c-answer",
            )
            result_c = answered_c.result
        ok(
            "C3 记录版本可用（账户字段的版本来自续接而不是问答双方都空）",
            result_c["status"] == "answered" and bool(result_c.get("follow_up_run_id")),
            {k: result_c.get(k) for k in ("status", "follow_up_run_id")},
        )
    finally:
        await reset_engine()

    print(f"\n全部通过：{len(PASS)} 项")
    print("证据目录：", tmp)


if __name__ == "__main__":
    asyncio.run(main())
