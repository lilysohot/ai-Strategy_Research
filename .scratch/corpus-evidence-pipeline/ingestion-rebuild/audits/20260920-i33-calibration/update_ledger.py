from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]
tasks = ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md"
text = tasks.read_text()
lines = text.splitlines()
for i, line in enumerate(lines):
    if line.startswith("| I3-1 |"):
        cells = line.rsplit("|", 2)
        cells[1] = " **最新 r38：已完成，8/8 发布、每类≥2、三格式、13 acknowledged/0 blocking，真实取证通过；以下为历史轮次。** " + cells[1].lstrip()
        lines[i] = "|".join(cells)
    if line.startswith("| I3-3 |"):
        cells = line.rsplit("|", 2)
        cells[1] += " **最新 r39：已进入校准，两轮30题均未达标；OR 候选三类 DocRecall=100%，EvidencePass=1/8、2/8、2/8，负例误报6；按预定两轮停止，保留失败，未部署候选。** "
        lines[i] = "|".join(cells)
tasks.write_text("\n".join(lines) + "\n")
