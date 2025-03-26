import importlib
import logging
from itertools import repeat
from multiprocessing import Pool
from pathlib import Path

import click
# from dotenv import load_dotenv
from rich import print
from rich.live import Live
from rich.logging import RichHandler

from agent_pipeline.agent_pipeline import DEFENSES, AgentPipeline, ModelsEnum, PipelineConfig, MODEL_INFO
from attacks.attack_registry import ATTACKS, load_attack
from benchmark import SuiteResults, benchmark_suite_with_injections, benchmark_suite_without_injections
from benchmark_langgraph import ( 
    benchmark_suite_without_injections as benchmark_suite_without_injections_langgraph,
    benchmark_suite_with_injections as benchmark_suite_with_injections_langgraph
)
from agentdojo_logging import OutputLogger
from task_suite.load_suites import get_suite, get_suites
from task_suite.task_suite import TaskSuite

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from pfi_agent import *
from benchmark_agents import *
from config import config

AVAILABLE_MODELS = ["gpt-4o-mini", "gpt-4o", "claude-3.5-sonnet", "gemini-1.5-pro"]

def benchmark_suite(
    suite: TaskSuite,
    model: str,
    agent_type: str,
    testname: str,
    logdir: Path,
    force_rerun: bool,
    user_tasks: tuple[str, ...] = (),
    injection_tasks: tuple[str, ...] = (),
    attack: str | None = None,
    defense: str | None = None,
    system_message_name: str | None = None,
    system_message: str | None = None,
    live: Live | None = None,
) -> SuiteResults:
    # if not load_dotenv(".env"):
    #     warnings.warn("No .env file found")
    print(f"Running benchmark for suite: '{suite.name}'")
    print(f"Using model: '{model}'")
    print(f"Using agent: '{agent_type}'")
    if attack is not None:
        print(f"Using attack: '{attack}'")
    if defense is not None:
        print(f"Using defense: '{defense}'")
    if len(user_tasks) > 0:
        print(f"Using user tasks: {', '.join(user_tasks)}")

    pipeline = AgentPipeline.from_config(
        PipelineConfig(
            llm=model, defense=defense, system_message_name=system_message_name, system_message=system_message
        )
    )

    # Create Agent
    # Instantiate backbone model
    
    provider = MODEL_INFO[ModelsEnum(model)]["provider"]
    version = MODEL_INFO[ModelsEnum(model)]["version"]
    
    token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "total_expense": 0,}
    
    def token_usage_tracker():
        def decorator(func):
            def wrapper(*args, **kwargs):
                result = func(*args, **kwargs)
                usage_metadata = result.usage_metadata
                
                input_tokens = usage_metadata.get("input_tokens", 0)
                output_tokens = usage_metadata.get("output_tokens", 0)
                
                token_usage["input_tokens"] += input_tokens
                token_usage["output_tokens"] += output_tokens
                token_usage["total_tokens"] += input_tokens + output_tokens
                
                input_cost_per_token = MODEL_INFO[ModelsEnum(model)]['input_cost_per_token']
                output_cost_per_token = MODEL_INFO[ModelsEnum(model)]['output_cost_per_token']
                
                token_usage["total_expense"] = (
                    token_usage["input_tokens"] * input_cost_per_token + 
                    token_usage["output_tokens"] * output_cost_per_token
                )
                
                return result
            return wrapper
        return decorator

    if provider == "openai":
        llm = ChatOpenAI(model=version, temperature=0)
    elif provider == "anthropic":
        llm = ChatAnthropic(model=version, temperature=0)
    elif provider == "google":
        llm = ChatGoogleGenerativeAI(model=version, temperature=0)
    else:
        raise ValueError(f"Invalid provider specified: {provider}")

    llm.__dict__["invoke"] = token_usage_tracker()(llm.invoke)

    for tool in suite.tools:
        description = tool.description
        # if description length is over 1024, raise an error
        if len(description) > 1024:
            raise ValueError(f"tool description length is over 1024\n{tool}") 

    global config
    config = config.set_options(
        unsafe_dataflow_choice="UNSAFE_DATAFLOW_YES",
        log_level="BENCHMARK",
        policy="./configs/pfi-policy-agentdojo.yaml"
    )

    if agent_type == "pfi":
        agent = create_pfi_agent(
            llm, 
            suite.tools,
            config
        )
    elif agent_type == "react":
        agent = create_react_agent(
            llm, 
            suite.tools, 
        )
    elif agent_type == "f-secure" or agent_type == "f_secure":
        agent = create_f_secure_agent(
            llm, 
            suite.tools, 
            config
        )
    elif agent_type == "isolate_gpt" or agent_type == "isolate-gpt":
        agent = create_isolate_gpt_agent(
            llm,
            suite.tools,
        )
    else:
        raise ValueError(f"Unknown agent: '{agent_type}'. Use 'pfi' or 'react'.")

    with OutputLogger(str(logdir), live=live):
        if attack is None:
           results = benchmark_suite_without_injections_langgraph(
                agent,
                suite,
                testname,
                user_tasks=user_tasks if len(user_tasks) != 0 else None,
                logdir=logdir,
                force_rerun=force_rerun,
                agent_type=agent_type,
                model_name=model,
                token_usage=token_usage
            )
        else:
            attacker_ = load_attack(attack, suite, pipeline)
            results = benchmark_suite_with_injections_langgraph(
                agent,
                suite,
                testname,
                attacker_,
                user_tasks=user_tasks if len(user_tasks) != 0 else None,
                injection_tasks=injection_tasks if len(injection_tasks) != 0 else None,
                logdir=logdir,
                force_rerun=force_rerun,
                agent_type=agent_type,
                model_name=model,
                token_usage=token_usage
            )
    print(f"Finished benchmark for suite: '{suite.name}'")

    return results


def show_results(suite_name: str, results: SuiteResults, show_security_results: bool):
    utility_results = results["utility_results"].values()
    avg_utility = sum(utility_results) / len(utility_results)

    print(f"Results for suite {suite_name}")
    print(f"Average utility: {avg_utility * 100:.2f}%")

    if show_security_results:
        passed_injection_tasks = sum(results["injection_tasks_utility_results"].values())
        total_injection_tasks = len(results["injection_tasks_utility_results"])
        print(f"\nPassed injection tasks as user tasks: {passed_injection_tasks}/{total_injection_tasks}")

        security_results = results["security_results"].values()
        avg_security = sum(security_results) / len(security_results)
        print(f"Average security: {avg_security * 100:.2f}%")


@click.command()
@click.option(
    "--model",
    default="gpt-4o-mini",
    type=str,
    help=f"The backbone model for agent. Defaults to `gpt-4o-mini`. Possible values are {AVAILABLE_MODELS}.",
)
@click.option(
    "--benchmark-version",
    default="v1.1",
    type=str,
    help="The version of the benchmark to run. Defaults to `v1`.",
)
@click.option(
    "--logdir",
    default="./agentdojo_result",
    type=Path,
    help="The directory to save logs. Defaults to `./agentdojo_result`.",
)
@click.option(
    "--attack",
    type=str,
    default=None,
    help=f"The attack to use. `None` by default. It should be one of {ATTACKS}, or a custom attack defined and registered in of of the `--module-to-load`. If `None`, no attack is used.",
)
@click.option(
    "--defense",
    type=click.Choice(DEFENSES),
    default=None,
    help="The defense to use. `None` by default.",
)
@click.option(
    "--system-message-name",
    type=str,
    default=None,
    help="The name of the system message to use among the default ones in `data/system_messages.yaml`.",
)
@click.option(
    "--system-message",
    type=str,
    default=None,
    help="The system message to use (as a string). If provided, `--system-message-name` is ignored.",
)
@click.option(
    "--user-task",
    "-ut",
    "user_tasks",
    type=str,
    multiple=True,
    default=tuple(),
    help="The user tasks to benchmark. If not provided, all tasks in the suite are run.",
)
@click.option(
    "--injection-task",
    "-it",
    "injection_tasks",
    type=str,
    multiple=True,
    default=tuple(),
    help="The user tasks to benchmark. If not provided, all tasks in the suite are run.",
)
@click.option(
    "--suite",
    "-s",
    "suites",
    type=str,
    multiple=True,
    default=tuple(),
    help="The user tasks to benchmark. If not provided, all tasks in the suite are run.",
)
@click.option(
    "--max-workers",
    type=int,
    default=1,
    help="How many suites can be benchmarked in parallel through multithreading. Nothing is parallelized by default.",
)
@click.option(
    "--force-rerun",
    "-f",
    is_flag=True,
    help="Whether to re-run tasks that have already been run.",
)
@click.option(
    "--module-to-load",
    "-ml",
    "modules_to_load",
    type=str,
    multiple=True,
    default=tuple(),
    help="The modules to load before running the benchmark. Useful for registering custom attacks, defenses, or suites.",
)
@click.option(
    "--testname",
    "testname",
    type=str,
    default="pfi",
    help="The name of the test to run.",
)
@click.option(
    "--agent",
    "-a",
    "agent_type",
    type=str,
    default="pfi",
    help="The agent to use. Defaults to `pfi`. Currently, 'pfi' and 'react' are supported.",
)

def main(
    suites: tuple[str, ...],
    model: str,
    testname: str = "pfi",
    benchmark_version: str = "v1.1",
    logdir: Path = Path("./agentdojo_result"),
    user_tasks: tuple[str, ...] = (),
    injection_tasks: tuple[str, ...] = (),
    attack: str | None = None,
    defense: str | None = None,
    system_message_name: str | None = None,
    system_message: str | None = None,
    max_workers: int = 1,
    force_rerun: bool = False,
    modules_to_load: tuple[str, ...] = (),
    agent_type: Literal["pfi", "react"] = None,
):
    for module in modules_to_load:
        importlib.import_module(module)

    if len(suites) == 0:
        suites = tuple(get_suites(benchmark_version).keys())

    if len(suites) != 1:
        print(f"Benchmarking suites {', '.join(suites)}")

    if len(suites) != 1 and len(user_tasks) != 0:
        raise ValueError("A user task can be specified only when one suite is being executed")

    if model not in AVAILABLE_MODELS:
        raise ValueError(f"Model '{model}' not available. Available models are: {AVAILABLE_MODELS}")

    if model == "gpt-4o-mini" or model == "gpt-4o":
        if not os.environ.get("OPENAI_API_KEY"):
            print("Please set the OPENAI_API_KEY environment variable.")
            exit()
    elif model == "claude-3.5-sonnet":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("Please set the ANTHROPIC_API_KEY environment variable.")
            exit()
    elif model == "gemini-1.5-pro":
        if not os.environ.get("GOOGLE_API_KEY"):
            print("Please set the GOOGLE_API_KEY environment variable.")
            exit()

    if max_workers == 1:
        results = {}
        for suite_name in suites:
            suite = get_suite(benchmark_version, suite_name)
            results[suite_name] = benchmark_suite(
                suite,
                model,
                agent_type,
                testname,
                logdir,
                user_tasks=user_tasks,
                injection_tasks=injection_tasks,
                attack=attack,
                defense=defense,
                system_message_name=system_message_name,
                system_message=system_message,
                force_rerun=force_rerun,
            )
        for suite_name, result in results.items():
            show_results(suite_name, result, attack is not None)
    else:
        with Pool(max_workers) as p:
            arguments = zip(
                suites,
                repeat(model),
                repeat(logdir),
                repeat(user_tasks),
                repeat(injection_tasks),
                repeat(attack),
                repeat(defense),
                repeat(system_message_name),
                repeat(system_message),
                repeat(force_rerun),
            )
            results = p.starmap(benchmark_suite, arguments)

        for suite_name, result in zip(suites, results):
            show_results(suite_name, result, attack is not None)


if __name__ == "__main__":
    format = "%(message)s"
    logging.basicConfig(
        format=format,
        level=logging.INFO,
        datefmt="%H:%M:%S",
        handlers=[RichHandler(show_path=False, markup=True)],
    )
    main()
