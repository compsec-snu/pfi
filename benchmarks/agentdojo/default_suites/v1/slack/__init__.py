from default_suites.v1.slack.injection_tasks import SlackInjectionTask  # noqa: F401 - Register tasks
from default_suites.v1.slack.task_suite import task_suite as slack_task_suite
from default_suites.v1.slack.user_tasks import SlackUserTask  # noqa: F401 - Register tasks

__all__ = ["slack_task_suite"]
