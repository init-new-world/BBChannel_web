from webapp.automation.battle import BATTLE_DRY_RUN_JOB_KIND, register_battle_jobs
from webapp.automation.diagnostic import register_diagnostic_job
from webapp.automation.program import compile_battle_program

__all__ = [
    "BATTLE_DRY_RUN_JOB_KIND",
    "compile_battle_program",
    "register_battle_jobs",
    "register_diagnostic_job",
]
