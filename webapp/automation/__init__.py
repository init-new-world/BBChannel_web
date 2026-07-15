from webapp.automation.assist import (
    ASSIST_SELECT_JOB_KIND,
    create_assist_handler,
    register_assist_job,
)
from webapp.automation.battle import (
    BATTLE_DRY_RUN_JOB_KIND,
    BATTLE_EXECUTE_PLAN_JOB_KIND,
    BATTLE_EXECUTE_SKILLS_JOB_KIND,
    create_battle_execute_plan_handler,
    register_battle_jobs,
)
from webapp.automation.diagnostic import register_diagnostic_job
from webapp.automation.completion import (
    BATTLE_COMPLETE_JOB_KIND,
    create_completion_handler,
    register_completion_job,
)
from webapp.automation.entry import (
    BATTLE_PREPARE_JOB_KIND,
    create_battle_entry_handler,
    register_battle_entry_job,
)
from webapp.automation.program import compile_battle_program
from webapp.automation.run import FULL_RUN_JOB_KIND, register_full_run_job

__all__ = [
    "ASSIST_SELECT_JOB_KIND",
    "BATTLE_COMPLETE_JOB_KIND",
    "BATTLE_DRY_RUN_JOB_KIND",
    "BATTLE_EXECUTE_PLAN_JOB_KIND",
    "BATTLE_EXECUTE_SKILLS_JOB_KIND",
    "BATTLE_PREPARE_JOB_KIND",
    "FULL_RUN_JOB_KIND",
    "compile_battle_program",
    "create_assist_handler",
    "create_battle_entry_handler",
    "create_battle_execute_plan_handler",
    "create_completion_handler",
    "register_assist_job",
    "register_battle_jobs",
    "register_completion_job",
    "register_battle_entry_job",
    "register_diagnostic_job",
    "register_full_run_job",
]
