from default_suites.v1.tools.slack import (
    Slack,
    add_user_to_channel,
    get_channels,
    get_users_in_channel,
    get_user_count_in_channel,
    invite_user_to_slack,
    read_channel_messages,
    read_inbox,
    remove_user_from_slack,
    send_channel_message,
    send_direct_message,
    env as slack_env,
)
from default_suites.v1.tools.web import (
    Web, get_webpage, post_webpage,
    env as web_env,
)
from functions_runtime import TaskEnvironment
from task_suite.task_suite import TaskSuite

class SlackEnvironment(TaskEnvironment):
    slack: Slack
    web: Web

ENVS = {
    "slack": slack_env,
    "web": web_env,
}

TOOLS = [
    get_channels,
    add_user_to_channel,
    read_channel_messages,
    read_inbox,
    send_direct_message,
    send_channel_message,
    get_users_in_channel,
    get_user_count_in_channel,
    invite_user_to_slack,
    remove_user_from_slack,
    get_webpage,
    post_webpage,
]

task_suite = TaskSuite[SlackEnvironment]("slack", SlackEnvironment, TOOLS, ENVS)
