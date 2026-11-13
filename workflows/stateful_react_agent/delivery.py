"""Validate corpus chat delivery before no-tool termination, with one repair opportunity."""

from frontier_agent.core.loop_types import BaseObserver, Intervention, TurnContext
from plugins.corpus.final_delivery import (
    IDENTITY_ANSWER_RULE,
    identity_manifest,
    prepare_delivery_manifest,
)
from plugins.corpus.ledger import get_run_ledger, verify_and_record
from plugins.tools.corpus_manifest import commit_final_manifest


class CorpusDeliveryObserver(BaseObserver):
    critical = True

    def __init__(self) -> None:
        self._repair_offered = False

    async def on_llm_response(self, ctx: TurnContext) -> Intervention | None:
        if ctx.tool_calls or not ctx.ai_text.strip():
            return None
        ledger = get_run_ledger()
        if not ledger.has_activity() or ledger.replayed_only:
            return None
        content = ctx.ai_text.strip()
        if identity_manifest(content, ledger) is not None:
            payload = prepare_delivery_manifest(content, None, ledger)
            if payload is not None:
                commit_final_manifest(payload)
        verification = verify_and_record(ledger, final_text=content)
        if verification.get("status") == "verified" or self._repair_offered:
            return None
        # A finite opportunity before normal publishing/downgrade; never claim
        # success after exhaustion, and never add a mandatory fetch round.
        if ctx.turn >= ctx.max_turns:
            return None
        self._repair_offered = True
        codes = sorted(
            {
                problem.get("code", "invalid_evidence")
                for row in verification.get("conclusions", [])
                for problem in row.get("problems", [])
            }
        )
        return Intervention(
            continue_to_next_turn=True,
            inject_messages=[
                "[corpus delivery preflight] Final evidence binding is incomplete ("
                + ", ".join(codes or [str(verification.get("status"))])
                + "). Repair once before finishing.\n"
                + IDENTITY_ANSWER_RULE
                + "\nFor source prose, submit/correct corpus_submit_manifest with report_quote "
                "copied exactly from the final answer and evidence_ref from existing receipts; "
                "fetch only missing evidence. Then deliver that same answer."
            ],
        )
