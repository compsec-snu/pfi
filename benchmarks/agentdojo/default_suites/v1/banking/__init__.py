from default_suites.v1.banking.injection_tasks import BankingInjectionTask  # noqa: F401 - Register tasks
from default_suites.v1.banking.task_suite import task_suite as banking_task_suite
from default_suites.v1.banking.user_tasks import BankingUserTask  # noqa: F401 - Register tasks

__all__ = ["banking_task_suite"]
