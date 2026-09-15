"""Regression controls for the P0 audit tool; all mutations are temporary fixtures."""

import json
from pathlib import Path

import p0_baseline as p0
import pytest


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    monkeypatch.setattr(p0, "ROOT", tmp_path)
    monkeypatch.setattr(p0, "environment", lambda: {"python": "fixed"})
    monkeypatch.setattr(p0, "git", lambda *args: b"head\n")
    source = tmp_path / "plugins/example.py"
    source.parent.mkdir()
    source.write_text("value = 1\n")
    asset = tmp_path / "response.json"
    asset.write_text('{"value": 1}')
    patch = tmp_path / "workspace-code.patch"
    patch.write_bytes(b"code-only-diff")
    protected = {"file_sha256": p0.inventory(tmp_path)}
    guard = tmp_path / "protected-paths.json"
    guard.write_bytes(p0.encoded(protected))
    manifest = {
        "schema": "r2-p0-baseline-1",
        "head": "head",
        "environment": p0.environment(),
        "protected_paths_sha256": p0.sha(guard.read_bytes()),
        "asset_sha256": {"response.json": p0.sha(asset.read_bytes())},
        "workspace_code_diff_sha256": p0.sha(patch.read_bytes()),
    }
    path = tmp_path / "baseline-manifest.json"
    path.write_bytes(p0.encoded(manifest))
    return path, p0.sha(path.read_bytes())


def test_valid_baseline_passes(bundle: tuple[Path, str]) -> None:
    assert p0.verify(*bundle)["head"] == "head"


@pytest.mark.parametrize(
    "target,change",
    [
        ("plugins/example.py", "modify"),
        ("plugins/example.py", "delete"),
        ("plugins/new.py", "add"),
        ("response.json", "modify"),
        ("response.json", "delete"),
        ("protected-paths.json", "modify"),
        ("workspace-code.patch", "modify"),
        ("baseline-manifest.json", "modify"),
    ],
)
def test_drift_fails_closed(bundle: tuple[Path, str], target: str, change: str) -> None:
    path, trusted = bundle
    victim = path.parent / target
    if change == "delete":
        victim.unlink()
    else:
        victim.write_text("changed\n")
    with pytest.raises((ValueError, FileNotFoundError)):
        p0.verify(path, trusted)


def test_rehashed_manifest_still_requires_external_pin(bundle: tuple[Path, str]) -> None:
    path, trusted = bundle
    payload = json.loads(path.read_bytes())
    payload["head"] = "attacker-rehashed-baseline"
    path.write_bytes(p0.encoded(payload))
    with pytest.raises(ValueError, match="externally pinned"):
        p0.verify(path, trusted)


@pytest.mark.parametrize("kind", ["head", "environment"])
def test_runtime_drift_fails(
    bundle: tuple[Path, str], monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    if kind == "head":
        monkeypatch.setattr(p0, "git", lambda *args: b"other\n")
    else:
        monkeypatch.setattr(p0, "environment", lambda: {"python": "other"})
    with pytest.raises(ValueError, match="baseline drift"):
        p0.verify(*bundle)


@pytest.mark.parametrize("relative", ["../escape", "/etc/passwd"])
def test_manifest_paths_cannot_escape(tmp_path: Path, relative: str) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        p0.safe_path(tmp_path, relative)


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    (tmp_path / "escape").symlink_to("/etc/passwd")
    with pytest.raises(ValueError, match="escaped"):
        p0.safe_path(tmp_path, "escape")


def test_write_once_preserves_previous_result(tmp_path: Path) -> None:
    target = tmp_path / "result.json"
    p0.write_once(target, b"first")
    with pytest.raises(FileExistsError):
        p0.write_once(target, b"second")
    assert target.read_bytes() == b"first"


def test_service_audit_ignores_only_private_method_body() -> None:
    source = "class CorpusService:\n def understand_material(self): return 1\n def search(self): return 2\n"
    expected = p0.service_public_fingerprint(source)
    assert p0.service_public_fingerprint(source.replace("return 1", "return 3")) == expected
    assert p0.service_public_fingerprint(source.replace("return 2", "return 3")) != expected
    assert p0.service_public_fingerprint("import os\n" + source) != expected


def test_public_snapshot_control() -> None:
    result = p0.snapshot()
    assert float(result["calculation"]["value"]) == 20
    assert result["legacy_sqlite"]["inserted"] == [True, False]
    assert result["cli"]["exit_code"] == 0
    assert result["rejected"] == {"wrong_revision": "KeyError", "reversed_period": "ValueError"}
