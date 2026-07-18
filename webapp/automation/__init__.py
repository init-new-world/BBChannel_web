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
from webapp.automation.quest import (
    FREE_QUEST_ENTER_JOB_KIND,
    MAIN_STORY_ENTER_JOB_KIND,
    create_free_quest_entry_handler,
    create_main_story_entry_handler,
    register_free_quest_entry_job,
    register_main_story_entry_job,
)
from webapp.automation.recovery import (
    BATTLE_RESTART_GAME_JOB_KIND,
    create_recovery_handler,
    register_recovery_job,
)
from webapp.automation.run import (
    FULL_RUN_JOB_KIND,
    create_full_run_handler,
    register_full_run_job,
)
from webapp.automation.stage import (
    BATTLE_DETECT_STAGE_JOB_KIND,
    create_stage_handler,
    register_stage_job,
)

__all__ = [
    "ASSIST_SELECT_JOB_KIND",
    "BATTLE_COMPLETE_JOB_KIND",
    "BATTLE_DETECT_STAGE_JOB_KIND",
    "BATTLE_DRY_RUN_JOB_KIND",
    "BATTLE_EXECUTE_PLAN_JOB_KIND",
    "BATTLE_EXECUTE_SKILLS_JOB_KIND",
    "BATTLE_PREPARE_JOB_KIND",
    "BATTLE_RESTART_GAME_JOB_KIND",
    "FULL_RUN_JOB_KIND",
    "FREE_QUEST_ENTER_JOB_KIND",
    "MAIN_STORY_ENTER_JOB_KIND",
    "compile_battle_program",
    "create_assist_handler",
    "create_battle_entry_handler",
    "create_battle_execute_plan_handler",
    "create_completion_handler",
    "create_full_run_handler",
    "create_free_quest_entry_handler",
    "create_main_story_entry_handler",
    "create_recovery_handler",
    "create_stage_handler",
    "register_assist_job",
    "register_battle_jobs",
    "register_completion_job",
    "register_battle_entry_job",
    "register_diagnostic_job",
    "register_full_run_job",
    "register_free_quest_entry_job",
    "register_main_story_entry_job",
    "register_recovery_job",
    "register_stage_job",
]
