from default_suites.v1.tools.banking_client import (
    BankAccount,
    get_balance,
    get_iban,
    get_most_recent_transactions,
    get_scheduled_transactions,
    schedule_transaction,
    send_money,
    update_scheduled_transaction,
    env as banking_env,
)
from default_suites.v1.tools.file_reader import (
    Filesystem, read_file,
    env as file_env,
)
from default_suites.v1.tools.user_account import (
    UserAccount, get_user_info, update_password, update_user_info,
    env as user_env,
)
from functions_runtime import TaskEnvironment
from task_suite.task_suite import TaskSuite


class BankingEnvironment(TaskEnvironment):
    bank_account: BankAccount
    filesystem: Filesystem
    user_account: UserAccount

ENVS = {
    "bank_account": banking_env,
    "filesystem": file_env,
    "user_account": user_env,
}

TOOLS = [
    get_iban,
    send_money,
    schedule_transaction,
    update_scheduled_transaction,
    get_balance,
    get_most_recent_transactions,
    get_scheduled_transactions,
    read_file,
    get_user_info,
    update_password,
    update_user_info,
]

task_suite = TaskSuite[BankingEnvironment]("banking", BankingEnvironment, TOOLS, ENVS)
