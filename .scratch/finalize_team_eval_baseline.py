from pathlib import Path

from benchmarks.team_workflow.run import mark_unassessed

mark_unassessed(
    Path("results/team-workflow-v1-semantic"),
    "Manual stop requested after F01/F02 execution errors; F03 also finished with an error before interruption took effect. F04 partial trace retained; F05 not started.",
    mode="manual_after_execution_errors",
)
