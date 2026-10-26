import hashlib
import json
from pathlib import Path

from server.continuity_resources import continuity_resource_prompt, stage_continuity_resources


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_stages_upload_and_verified_handoff_with_real_run_provenance(tmp_path: Path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    (old / "inputs").mkdir(parents=True)
    (old / "inputs" / "brief.pdf").write_bytes(b"pdf bytes")
    handoff_dir = old / "ws/outputs/scratch/handoffs/reader/extract"
    handoff_dir.mkdir(parents=True)
    body = b"bounded extraction"
    file = handoff_dir / "abc-extract.txt"
    file.write_bytes(body)
    ref = "/outputs/scratch/handoffs/reader/extract/abc-extract.txt"
    Path(f"{file}.handoff.json").write_text(
        json.dumps(
            {
                "ref": ref,
                "sha256": digest(body),
                "producer": "reader",
                "job_id": "job.1",
            }
        )
    )
    (old / "summary.json").write_text(
        json.dumps(
            {
                "report_contract": {
                    "verification_checks": [
                        {
                            "check_id": "amount",
                            "criterion": "Recompute amount",
                            "binding_id": "b" * 64,
                            "verdict": "pass",
                            "verdict_job_id": "job.2",
                            "subject": {"job_id": "job.1", "ref": ref},
                            "evidence": [],
                        }
                    ],
                }
            }
        )
    )

    manifest = stage_continuity_resources(
        target_run_dir=new,
        source_runs=[("0123456789abcdef0123456789abcdef", old)],
    )

    assert [item["kind"] for item in manifest["resources"]] == ["upload", "handoff"]
    handoff = manifest["resources"][1]
    assert handoff["source_run_id"] == "0123456789abcdef0123456789abcdef"
    assert handoff["source_ref"] == ref
    assert handoff["verification_status"] == "passed_for_declared_checks"
    assert handoff["verification_checks"][0]["check_id"] == "amount"
    staged = new / handoff["path"].removeprefix("/inputs/")
    assert (new / "inputs" / staged.relative_to(new)).read_bytes() == body
    prompt = continuity_resource_prompt(manifest)
    assert "bounded extraction" not in prompt
    assert handoff["sha256"] in prompt


def test_tampered_handoff_is_not_inherited(tmp_path: Path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    handoff_dir = old / "ws/outputs/scratch/handoffs/reader/extract"
    handoff_dir.mkdir(parents=True)
    file = handoff_dir / "extract.txt"
    file.write_text("changed")
    Path(f"{file}.handoff.json").write_text(
        json.dumps(
            {
                "ref": "/outputs/scratch/handoffs/reader/extract/extract.txt",
                "sha256": digest(b"original"),
            }
        )
    )

    manifest = stage_continuity_resources(
        target_run_dir=new,
        source_runs=[("run-one", old)],
    )

    assert manifest["resources"] == []
    assert manifest["limitations"] == [
        {
            "source_run_id": "run-one",
            "reason": "invalid_handoff_bytes",
        }
    ]
    assert "invalid_handoff_bytes" in continuity_resource_prompt(manifest)
