import json
import re
import logging
import warnings
from collections.abc import Sequence
from pathlib import Path

# from cohere.core.api_error import ApiError
from openai import BadRequestError
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator
from typing_extensions import Self, TypedDict, Literal

from attacks.base_attacks import BaseAttack
from base_tasks import BaseInjectionTask, BaseUserTask
from functions_runtime import Env
from agentdojo_logging import Logger, TraceLogger
from task_suite.load_suites import get_suite
from task_suite.task_suite import TaskSuite, read_suite_file
from agentdojo_types import ChatMessage

from langgraph.graph.state import CompiledStateGraph

class SuiteResults(TypedDict):
    """The results of running a suite of tasks with a given pipeline."""

    utility_results: dict[tuple[str, str], bool]
    """The utility results for each injection task and user task couple. The
    key is a tuple of the user task ID and the injection task ID."""
    security_results: dict[tuple[str, str], bool]
    """The security results for each injection task and user task couple. The
    key is a tuple of the user task ID and the injection task ID."""
    injection_tasks_utility_results: dict[str, bool]
    """The utility results for each injection task. The key is the injection task ID."""
    injection_results: dict[tuple[str, str], bool]
    """The injection results(if injection ever happened) for each injection task and user task couple. The
    key is a tuple of the user task ID and the injection task ID."""


def aggregate_results(results: list[dict[tuple[str, str], bool]]) -> float:
    all_results = [result for results in results for result in results.values()]
    return sum(all_results) / len(all_results)


def run_task_with_injection_tasks(
    suite: TaskSuite,
    agent_graph: CompiledStateGraph,
    testname: str,
    user_task: BaseUserTask,
    attack: BaseAttack,
    logdir: Path | None,
    force_rerun: bool,
    injection_tasks: Sequence[str] | None = None,
    agent_type: Literal["pfi", "react"] = "pfi",
    model_name: Literal["gpt-4o-mini", "gpt-4o", "claude-3.5-sonnet", "gemini-1.5-pro"]="gpt-4o-mini",
    token_usage: dict[str, int] = {},
) -> tuple[dict[tuple[str, str], bool], dict[tuple[str, str], bool]]:
    """Runs the given user tasl with the given injection tasks (or all tasks if no injection
    task is provided) by injecting the environment by using the given attack.

    Args:
        suite: The task suite to run.
        agent_graph: The agent graph to use.
        user_task: The user task to run.
        attack: The attack to run.
        logdir: The directory to save logs to.
        force_rerun: Whether to force rerun the task in case in the logdir there already exists
            a log for the task.
        injection_tasks: The injection tasks to run. If None, all injection tasks in the suite will be run.
        agent_type: The type of agent to use. Either "pfi" or "react".

    Returns:
        A tuple of two dictionaries. The first dictionary contains the utility results for each injection
            task and user task couple. The second dictionary contains the security results for each
            injection and user task couple.

    """
    utility_results: dict[tuple[str, str], bool] = {}
    security_results: dict[tuple[str, str], bool] = {}
    injection_results: dict[tuple[str, str], bool] = {}

    if attack.is_dos_attack or attack.is_data_injection:
        # No need to run all injection tasks since we don't care about the injection target!
        injection_tasks_to_run = [next(iter(suite.injection_tasks.keys()))]
    else:
        injection_tasks_to_run = suite.injection_tasks

    if injection_tasks is not None and not attack.is_dos_attack:
        injection_tasks_to_run = injection_tasks

    for injection_task_id in injection_tasks_to_run:
        injection_task = suite.get_injection_task_by_id(injection_task_id)
        if attack.is_data_injection:
            task_injections = user_task.DATA_INJECTION_PROMPT
        else:
            task_injections = attack.attack(user_task, injection_task)

        if logdir is not None:
            try:
                task_result = load_task_results(
                    testname,
                    suite.name,
                    user_task.ID,
                    attack_name=attack.name,
                    injection_task=injection_task.ID,
                    logdir=logdir,
                )
            except (ValidationError, FileNotFoundError):
                task_result = None
        else:
            task_result = None

        if task_result is not None and not force_rerun:
            logging.info(f"Skipping task '{user_task.ID}' with '{injection_task.ID}' because it was already run.")
            utility, security, injection_has_happened = task_result.utility, task_result.security, task_result.injection_has_happened
        else:
            # a trace logger captures logs and saves them, but also passes them to the delegate logger
            with TraceLogger(
                delegate=Logger.get(),
                suite_name=suite.name,
                user_task_id=user_task.ID,
                injection_task_id=injection_task_id,
                injections=task_injections,
                attack_type=attack.name,
                pipeline_name=testname,
            ) as logger:
                try:
                    if attack.is_data_injection:
                        utility, security, injection_has_happened, user_task_type, injection_task_type = suite.run_task_with_graph_with_data_injection(
                            agent_graph, user_task, task_injections
                        )
                    else:
                        utility, security, injection_has_happened, user_task_type, injection_task_type = suite.run_task_with_graph(
                            agent_graph, user_task, injection_task, task_injections
                        )
                except BadRequestError as e:
                    if e.code == "context_length_exceeded" or e.param == "max_tokens":
                        logger.log_error(
                            f"Skipping task '{user_task.ID}' with '{injection_task.ID}' due to context_length_exceeded: {e}"
                        )
                        utility = False
                        security = True
                        injection_has_happened = True
                        user_task_type = None
                        injection_task_type = None
                    else:
                        raise e

                if attack.is_dos_attack:
                    security = not utility

            logger.set_contextarg("utility", utility)
            logger.set_contextarg("security", security)
            logger.set_contextarg("injection_has_happened", injection_has_happened)
            logger.set_contextarg("user_task_type", user_task_type)
            logger.set_contextarg("injection_task_type", injection_task_type)
            logger.set_contextarg("agent_type", agent_type)
            logger.set_contextarg("model_name", model_name)
            logger.set_contextarg("token_usage", token_usage)

        utility_results[(user_task.ID, injection_task_id)] = utility
        security_results[(user_task.ID, injection_task_id)] = security
        injection_results[(user_task.ID, injection_task_id)] = injection_has_happened
    return utility_results, security_results, injection_results


def benchmark_suite_with_injections(
    agent_graph: CompiledStateGraph,
    suite: TaskSuite[Env],
    testname: str,
    attack: BaseAttack,
    logdir: Path | None,
    force_rerun: bool,
    user_tasks: Sequence[str] | None = None,
    injection_tasks: Sequence[str] | None = None,
    verbose: bool = True,
    agent_type: Literal["pfi", "react"] = "pfi",
    model_name: Literal["gpt-4o-mini", "gpt-4o", "claude-3.5-sonnet", "gemini-1.5-pro"]="gpt-4o-mini",
    token_usage: dict[str, int] = {},
) -> SuiteResults:
    """Benchmark a suite with injections.

    Args:
        agent_graph: The agent graph to use.
        suite: The suite to benchmark.\
        attack: The attack to use.
        logdir: The directory to save logs to.
        force_rerun: Whether to force rerun the task in case in the logdir there already exists
            a log for the task.
        user_tasks: A subset of user tasks to run. If None, all user tasks are run.
        injection_tasks: A subset of injection tasks to run. If None, all injection tasks are run.
        verbose: Whether to print the results.
        agent_type: The type of agent to use. Either "pfi" or "react".
    """
    suite_utility_results: dict[tuple[str, str], bool] = {}
    suite_security_results: dict[tuple[str, str], bool] = {}
    suite_injection_results: dict[tuple[str, str], bool] = {}

    if user_tasks is not None:
        user_tasks_to_run = [suite.get_user_task_by_id(user_task_id) for user_task_id in user_tasks]
    else:
        user_tasks_to_run = suite.user_tasks.values()

    if injection_tasks is not None:
        injection_tasks_to_run = {
            injection_task_id: suite.get_injection_task_by_id(injection_task_id)
            for injection_task_id in injection_tasks
        }
    else:
        injection_tasks_to_run = suite.injection_tasks

    injection_tasks_utility_results = {}
    if not attack.is_dos_attack and not attack.is_data_injection:
        for injection_task_id, injection_task in injection_tasks_to_run.items():
            successful, _ = run_task_without_injection_tasks(suite, agent_graph, testname, injection_task, logdir, force_rerun, agent_type, model_name, token_usage)
            injection_tasks_utility_results[injection_task_id] = successful

        if not all(injection_tasks_utility_results.values()):
            warnings.warn("Not all injection tasks were solved as user tasks.")

    for user_task in user_tasks_to_run:
        utility, security, injection = run_task_with_injection_tasks(
            suite,
            agent_graph,
            testname,
            user_task,
            attack,
            logdir,
            force_rerun,
            injection_tasks,
            agent_type,
            model_name,
            token_usage
        )
        suite_utility_results.update(utility)
        suite_security_results.update(security)
        suite_injection_results.update(injection)

    return SuiteResults(
        utility_results=suite_utility_results,
        security_results=suite_security_results,
        injection_tasks_utility_results=injection_tasks_utility_results,
        injection_results=suite_injection_results,
    )


def run_task_without_injection_tasks(
    suite: TaskSuite,
    agent_graph: CompiledStateGraph,
    testname: str,
    task: BaseUserTask | BaseInjectionTask,
    logdir: Path | None,
    force_rerun: bool,
    agent_type: Literal["pfi", "react"],
    model_name: Literal["gpt-4o-mini", "gpt-4o", "claude-3.5-sonnet", "gemini-1.5-pro"],
    token_usage: dict[str, int] = {},
) -> tuple[bool, bool]:
    """Run a task without injections. Useful to benchmark the utility of a graph.

    Args:
        suite: The suite to use to run the benchmark.
        agent_graph: The agent graph to benchmark.
        task: The task to run.
        logdir: The directory to save logs to.
        force_rerun: Whether to force rerun the task in case in the logdir there already exists
            a log for the task.
        agent_type: The type of agent to use. Either "pfi" or "react".

    Returns:
        A tuple with the utility and security of the task. The security is always True.
    """
    if logdir is not None:
        try:
            task_result = load_task_results(
                testname,
                suite.name,
                task.ID,
                attack_name="none",
                injection_task="none",
                logdir=logdir,
            )
        except (ValidationError, FileNotFoundError):
            task_result = None
    else:
        task_result = None

    if task_result is not None and not force_rerun:
        logging.info(f"Skipping task '{task.ID}' with no injections because it was already run.")
        return task_result.utility, task_result.security

    with TraceLogger(
        delegate=Logger.get(),
        suite_name=suite.name,
        user_task_id=task.ID,
        injection_task_id=None,
        injections={},
        attack_type="none",
        pipeline_name=testname,
    ) as logger:
        # Initialize token usage here
        token_usage["input_tokens"] = 0
        token_usage["output_tokens"] = 0
        token_usage["total_tokens"] = 0
        try:
            utility, security, injection_has_happened, user_task_type, injection_task_type = suite.run_task_with_graph(agent_graph, task, injection_task=None, injections={})
        except BadRequestError as e:
            if e.code == "context_length_exceeded" or e.param == "max_tokens":
                logger.log_error(f"Skipping task {task.ID} due to context_length_exceeded: {e}")
                utility = False
                security = True
            else:
                raise e

        logger.set_contextarg("utility", utility)
        logger.set_contextarg("security", security)
        logger.set_contextarg("user_task_type", user_task_type)
        logger.set_contextarg("injection_task_type", injection_task_type)
        logger.set_contextarg("agent_type", agent_type)
        logger.set_contextarg("model_name", model_name)
        logger.set_contextarg("token_usage", token_usage)
        
    return utility, security

def benchmark_suite_without_injections(
    agent_graph: CompiledStateGraph,
    suite: TaskSuite,
    testname: str,
    logdir: Path | None,
    force_rerun: bool,
    user_tasks: Sequence[str] | None = None,
    agent_type: Literal["pfi", "react"] = "pfi",
    model_name: Literal["gpt-4o-mini", "gpt-4o", "claude-3.5-sonnet", "gemini-1.5-pro"]="gpt-4o-mini",
    token_usage: dict[str, int] = {},
) -> SuiteResults:
    """Benchmark a suite without injections.

    Args:
        agent_graph: The agent graph to use.
        suite: The suite to benchmark.\
        attack: The attack to use.
        logdir: The directory to save logs to.
        force_rerun: Whether to force rerun the task in case in the logdir there already exists
            a log for the task.
        user_tasks: A subset of user tasks to run. If None, all user tasks are run.
        agent_type: The type of agent to use. Either "pfi" or "react".
    """

    suite_utility_results: dict[tuple[str, str], bool] = {}
    suite_security_results: dict[tuple[str, str], bool] = {}

    # Clear the cache to get the latest environment
    read_suite_file.cache_clear()
    
    if user_tasks is not None:
        user_tasks_to_run = [suite.get_user_task_by_id(user_task_id) for user_task_id in user_tasks]
    else:
        user_tasks_to_run = suite.user_tasks.values()

    for user_task in user_tasks_to_run:
        logging.info(f"Running task {user_task.ID} without injections.")
        utility, security = run_task_without_injection_tasks(suite, agent_graph, testname, user_task, logdir, force_rerun, agent_type, model_name, token_usage)
        suite_utility_results[(user_task.ID, "")] = utility
        suite_security_results[(user_task.ID, "")] = security
    
    return SuiteResults(
        utility_results=suite_utility_results,
        security_results=suite_security_results,
        injection_tasks_utility_results={},
    )


class TaskResults(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    suite_name: str
    pipeline_name: str
    user_task_id: str
    injection_task_id: str | None
    attack_type: str | None
    injections: dict[str, str]
    messages: list
    error: str | None
    utility: bool
    security: bool
    injection_has_happened: bool
    duration: float

    @model_validator(mode="after")
    def check_messages(self) -> Self:
        # if len(self.messages) < 2 and "claude-3-opus" not in self.pipeline_name:
        #     raise ValueError("TaskResults must have at least two messages.")
        return self


def load_task_results(
    pipeline_name: str,
    suite_name: str,
    user_task: str,
    attack_name: str,
    injection_task: str,
    logdir: Path,
) -> TaskResults:
    path = logdir / pipeline_name / suite_name / user_task / attack_name / f"{injection_task}.json"

    with path.open() as f:
        res_dict = json.load(f)
    if res_dict["injection_has_happened"] is None:
        res_dict["injection_has_happened"] = False
    return TaskResults(**res_dict)

def load_suite_results(
    suite_name: str,
    pipeline_name: str,
    attack_name: str,
    logdir=Path("../agentdojo_result"),
    benchmark_version: str = "v1.1",
) -> tuple[dict[tuple[str, str], TaskResults], dict[tuple[str, str], TaskResults]]:
    suite = get_suite(benchmark_version, suite_name)
    results_without_injections = {}
    results_with_injections = {}

    for user_task_id in suite.user_tasks.keys():
        results_without_injections[(user_task_id, None)] = load_task_results(
            pipeline_name, suite_name, user_task_id, "none", "none", logdir
        )
        if "dos" in attack_name:
            injection_task_id = next(iter(suite.injection_tasks.keys()))
            results_with_injections[(user_task_id, injection_task_id)] = load_task_results(
                pipeline_name, suite_name, user_task_id, attack_name, injection_task_id, logdir
            )
        elif attack_name != "none":
            for injection_task_id in suite.injection_tasks.keys():
                results_with_injections[(user_task_id, injection_task_id)] = load_task_results(
                    pipeline_name, suite_name, user_task_id, attack_name, injection_task_id, logdir
                )
    return results_without_injections, results_with_injections
