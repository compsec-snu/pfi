import datetime
import json
import os
import random
import threading
import time
from typing import Dict, List, Union
from typing import Tuple, Callable, Iterator
import contextlib
import sys
from tqdm.contrib import DummyTqdmFile

import yaml
from tqdm import tqdm

from src.client.task import TaskError
from .client import TaskClient, AgentClient
from .configs import ConfigLoader
from .typings import AssignmentConfig, SampleIndex, TaskOutput, TaskClientOutput
from .utils import ColorMessage
from .utils import Graph, MaxFlow
import contextlib
import sys
from tqdm import tqdm
from tqdm.contrib import DummyTqdmFile
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage
from langgraph.constants import Interrupt
from src.typings.output import SampleStatus
from .client.agents.model_info import MODEL_INFO
from pfi_agent.unsafe_dataflow_check import UnsafeDataflowWarning

@contextlib.contextmanager
def std_out_err_redirect_tqdm():
    orig_out_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = map(DummyTqdmFile, orig_out_err)
        yield orig_out_err[0]
    # Relay exceptions
    except Exception as exc:
        raise exc
    # Always restore sys.stdout/err if necessary
    finally:
        sys.stdout, sys.stderr = orig_out_err

class Assigner:
    def __init__(self, config: AssignmentConfig, auto_retry: bool = True, agent_type="pfi") -> None:
        """
        Logic:
            1. Check if output folder exists (resume or create)
            2. Walk through all the folders in output folder, and remove the finished samples
            3. Create agents
        """
        self.auto_retry = auto_retry
        self.tqdm_ordered_by_agent = {}
        self.overall_tqdm = None
        self.config = config
        self.free_worker = config.concurrency.copy(deep=True)
        self.agents: Dict[str, AgentClient] = {}
        self.tasks: Dict[str, TaskClient] = {}
        self.task_indices: Dict[str, List[SampleIndex]] = {}
        self.task_worker_fail_count: Dict[str, int] = {}
        self.assignment_lock = threading.Lock()
        self.remaining_tasks: Dict[
            str, Dict[str, List[int]]
        ] = {}  # {agent: {task: [index]}}
        self.completions: Dict[
            str, Dict[str, List[TaskOutput]]
        ] = {}  # {agent: {task: [{index: int, result: JSONSerializable}]}}
        self.finished_count = 0
        self.started_count = 0
        self.running_count = 0
        self.agent_type = agent_type

        # Step 1. Check if output folder exists (resume or create)

        if not os.path.exists(self.config.output):
            os.makedirs(self.config.output)
            # Write config file
            with open(os.path.join(self.config.output, "config.yaml"), "w") as f:
                f.write(yaml.dump(self.config.dict()))

        # Step 2. walk through all the folders in output folder({output}/agent/task/runs.jsonl),
        # and remove the finished samples

        for assignment in self.config.assignments:
            model = assignment.agent
            task = assignment.task
            runs_file = os.path.join(self.get_output_dir(model, task), "runs.jsonl")
            result_file = os.path.join(self.get_output_dir(model, task), "overall.json")
            if os.path.exists(result_file):
                continue
            if model not in self.remaining_tasks:
                self.remaining_tasks[model] = {}
            if task not in self.remaining_tasks[model]:
                self.remaining_tasks[model][task] = []
            if task not in self.tasks:
                print(ColorMessage.green(f"creating {task} client..."))
                self.tasks[task] = self.config.definition.task[task].create()
                self.task_indices[task] = self.tasks[task].get_indices()
            self.remaining_tasks[model][task] = self.task_indices[task].copy()
            if not os.path.exists(runs_file):
                continue
            with open(runs_file, "r") as f:
                for line in f:
                    try:
                        run = json.loads(line)
                        run.pop("time")
                        index = run.pop("index")
                        assert index is not None
                        run = TaskClientOutput.parse_obj(run)
                        assert isinstance(run.output, TaskOutput)
                    except:
                        continue
                    if index in self.remaining_tasks[model][task]:
                        self.remaining_tasks[model][task].remove(index)
                        self.record_completion(model, task, index, run.output)
                    else:
                        print(
                            ColorMessage.yellow(
                                f"Warning: {self.agent_type}/{model}/{task}#{index} is finished, but not in the index list."
                            )
                        )

        count = sum(
            [
                len(self.remaining_tasks[model][task])
                for model in self.remaining_tasks
                for task in self.remaining_tasks[model]
            ]
        )
        print(
            ColorMessage.cyan(f"Message: {count} samples remaining.")
        )

        for agent in self.remaining_tasks:
            agent_ = json.dumps(agent)
            tasks_ = len(self.remaining_tasks[agent])
            samples_ = sum(
                [
                    len(self.remaining_tasks[agent][task])
                    for task in self.remaining_tasks[agent]
                ]
            )
            if samples_ == 0:
                continue
            print(
                ColorMessage.cyan(
                    f"Agent {agent_} needs to run {tasks_} tasks with total {samples_} samples:"
                )
            )
            for task in self.remaining_tasks[agent]:
                print(
                    ColorMessage.cyan(
                        f"    Task {json.dumps(task)}: {len(self.remaining_tasks[agent][task])}"
                    )
                )

        # Create agents

        for agent in self.remaining_tasks:
            self.agents[agent] = self.config.definition.agent[agent].create()

    def get_output_dir(self, model: str, task: str) -> str:
        return os.path.join(self.config.output, self.agent_type, model, task)

    def worker_generator(
        self, interval=10
    ) -> Iterator[Tuple[str, str, SampleIndex]]:

        node_list = ["SRC", "DST"]
        agent_node_index = {}
        task_node_index = {}
        for agent in self.agents:
            node_list.append(agent)
            agent_node_index[agent] = len(node_list) - 1
        for task in self.tasks:
            node_list.append(task)
            task_node_index[task] = len(node_list) - 1

        while True:

            # Step 0. Get real time task free worker

            with self.assignment_lock:
                for task in self.tasks:
                    self.free_worker.task[task] = self.tasks[task].get_concurrency()
                print("Running Count: {}".format(self.running_count))

            # Step 1. init edges: SRC -> agent -> task -> DST

            with self.assignment_lock:
                edges = {}
                for agent in self.agents:
                    edges[(0, agent_node_index[agent])] = self.free_worker.agent[agent]
                for task in self.tasks:
                    edges[(task_node_index[task], 1)] = self.free_worker.task[task]
                tot_remaining_samples = 0
                for agent in self.remaining_tasks:
                    for task in self.remaining_tasks[agent]:
                        tot_remaining_samples += len(self.remaining_tasks[agent][task])
                        edges[(agent_node_index[agent], task_node_index[task])] = len(
                            self.remaining_tasks[agent][task]
                        )
            if tot_remaining_samples == 0:
                if self.running_count == 0:
                    break
                else:
                    time.sleep(interval / 2 + random.random() * interval)
                    continue

            # Step 2. Create graph and calculate max flow

            graph = Graph(node_count=len(node_list), edges=edges)
            max_flow = MaxFlow(graph, src=0, dst=1)

            if max_flow.max_flow == 0:
                time.sleep(interval / 2 + random.random() * interval)
                continue

            # Step 3. yield all (agent, task, index) tuples

            for (src, dst), e in max_flow.edges_dict.items():
                if (
                    src not in agent_node_index.values()
                    or dst not in task_node_index.values()
                ):
                    continue
                if e.flow == 0:
                    continue
                agent = node_list[src]
                task = node_list[dst]
                for _ in range(e.flow):
                    with self.assignment_lock:
                        index = self.remaining_tasks[agent][task].pop()
                        self.free_worker.agent[agent] -= 1
                        self.free_worker.task[task] -= 1
                    print(ColorMessage.green(f"Assigned {agent}/{task}#{index}"))
                    yield agent, task, index

            # Step 4. sleep for a while
            time.sleep(interval / 2 + random.random() * interval)

    def start(self, tqdm_out=None):
        self.started_count = sum(
            [
                len(self.remaining_tasks[agent][task])
                for agent in self.remaining_tasks
                for task in self.remaining_tasks[agent]
            ]
        )
        generator = self.worker_generator()
        self.overall_tqdm = tqdm(
            total=self.started_count,
            desc="Total",
            position=0,
            file=tqdm_out,
        )
        for idx, agent in enumerate(self.remaining_tasks.keys()):
            self.tqdm_ordered_by_agent[agent] = tqdm(
                total=sum(
                    [
                        len(self.remaining_tasks[agent][task])
                        for task in self.remaining_tasks[agent]
                    ]
                ),
                desc=agent,
                position=idx + 1,
                file=tqdm_out,
            )
        while True:
            try:
                agent, task, index = next(generator)
            except StopIteration:
                break
            self.start_worker(agent, task, index, self.finish_callback)

        self.overall_tqdm.close()
        for agent in self.tqdm_ordered_by_agent:
            self.tqdm_ordered_by_agent[agent].close()

        final_message = (
            "\n\n============================================\n"
            + ColorMessage.cyan(f"Message: {self.started_count} sample(s) started. ")
            + "\n"
            + ColorMessage.green(
                f"   >> {self.finished_count} sample(s) finished successfully."
            )
            + "\n"
        )
        if self.started_count != self.finished_count:
            final_message += (
                ColorMessage.red(
                    f"   >> {self.started_count - self.finished_count} sample(s) failed."
                )
                + "\n"
            )
        final_message += (
            ColorMessage.cyan(
                f"   >> results are saved to {self.config.output}"
            )
            + "\n"
        )
        final_message += "============================================\n\n"
        print(final_message)

    def record_completion(
        self, agent: str, task: str, index: SampleIndex, result: TaskOutput
    ):
        def calculate_overall_worker():
            nonlocal agent, task, index, result
            task_client = self.tasks[task]
            
            # If history is None, it means that there was an error in the task          
            for completion in self.completions[agent][task]:
                if completion.history is None:
                    completion.history = []
                    completion.result = {'result': 'error'}
                    completion.status = SampleStatus.AGENT_ERROR
                    print("ERROR: ", completion)
            overall = task_client.calculate_overall(self.completions[agent][task])
            with open(
                os.path.join(self.get_output_dir(agent, task), "overall.json"), "w"
            ) as f:
                f.write(json.dumps(overall, indent=4, ensure_ascii=False))

        with self.assignment_lock:
            if agent not in self.completions:
                self.completions[agent] = {}
            if task not in self.completions[agent]:
                self.completions[agent][task] = []
            result.index = index
            self.completions[agent][task].append(result)
        
        # Always calculate and write overall results
        threading.Thread(target=calculate_overall_worker).start()

    def serialize(self, obj):
        if isinstance(obj, AIMessage):
            return {
                "type": "AIMessage",
                "content": obj.content,
                "name": obj.name,
                "tool_calls": obj.tool_calls,
            }
        elif isinstance(obj, ToolMessage):
            return {
                "type": "ToolMessage",
                "content": obj.content,
                "name": obj.name,
            }
        elif isinstance(obj, HumanMessage):
            return {
                "type": "HumanMessage",
                "content": obj.content,
                "name": obj.name,
            }
        elif isinstance(obj, SystemMessage):
            return {
                "type": "SystemMessage",
                "content": obj.content,
            }
        elif isinstance(obj, Interrupt):
            return {
                "type": "Interrupt",
                "value": obj.value,
            }
        elif isinstance(obj, UnsafeDataflowWarning):
            return {
                "type": "UnsafeDataflowWarning",
                "data_flow_type": obj.data_flow_type,
                "proxy_value": obj.proxy_value,
                "submessage_index": obj.submessage_index,
                "data_attribute": obj.data_attribute,
                "data_sink": obj.data_sink,
            }

        raise TypeError(f"Type {type(obj)} not serializable")

    def remove_oneshot_example(self, messages):
        if not messages:
            return messages
        
        if messages[0].content.startswith("You are an trusted AI agent.") or messages[0].content.startswith("You are an AI agent."):
            return messages[7:] if len(messages) > 7 else messages
        
        return messages

    def process_messages(self, messages):
        messages_without_oneshot = self.remove_oneshot_example(messages)
        return [self.serialize(msg) for msg in messages_without_oneshot]

    def finish_callback(
        self, agent: str, task: str, index: SampleIndex, result: TaskClientOutput
    ):
        if result.error == TaskError.NOT_AVAILABLE.value:
            print(
                ColorMessage.yellow(
                    f"Warning: {task} is not available, retrying."
                )
            )
            with self.assignment_lock:
                self.remaining_tasks[agent][task].insert(0, index)
                self.free_worker.agent[agent] += 1
                self.free_worker.task[task] += 1
                self.running_count -= 1
            return

        if result.error is not None:
            print(ColorMessage.yellow(f"Warning: {agent}/{task}#{index} "
                                      f"failed with error {result.error}"))
            if self.auto_retry:
                with self.assignment_lock:
                    self.remaining_tasks[agent][task].insert(0, index)

        output_folder = self.get_output_dir(agent, task)
        os.makedirs(output_folder, exist_ok=True)
        timestamp: int = int(time.time() * 1000)
        time_str = datetime.datetime.fromtimestamp(timestamp / 1000).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
            
        result_dict = result.dict()
        if hasattr(result, "info") and result.info is not None:
            # Remove history in result_dict["output"]
            if "history" in result_dict["output"]:
                result_dict["output"].pop("history", None)
            
            if isinstance(result.info, str):
                result_dict["info"] = result.info
            elif "first_run" in result.info: # For passive context injection
                result_dict["info"] = {
                    "first_run": result.info["first_run"],
                    "second_run": result.info["second_run"],
                }
                
                first_run_serialized_saved_messages = {
                    key: [self.serialize(message) for message in self.remove_oneshot_example(value)]
                    for key, value in result.info["first_run"].get("saved_messages", {}).items()
                }
                
                second_run_serialized_saved_messages = {
                    key: [self.serialize(message) for message in self.remove_oneshot_example(value)]
                    for key, value in result.info["second_run"].get("saved_messages", {}).items()
                }
                
                result_dict["info"]["first_run"] = {
                    "current_agent": result.info["first_run"].get("current_agent", None),
                    "messages": self.process_messages(result.info["first_run"].get("messages", [])),
                    "sub_messages": self.process_messages(result.info["first_run"].get("sub_messages", [])),
                    "archived_submessages": [
                        [self.serialize(msg) for msg in sublist] for sublist in result.info["first_run"].get("archived_submessages", [])
                    ],
                    "saved_messages": first_run_serialized_saved_messages,
                    "proxies": result.info["first_run"].get("proxies", None),
                    "unsafe_dataflow_warnings": [self.serialize(warning) for warning in result.info["first_run"].get("unsafe_dataflow_warnings", [])],
                    "isolate_gpt_warnings": [warning.to_dict() for warning in result.info["first_run"].get("warnings", [])],
                }
                result_dict["info"]["second_run"] = {
                    "current_agent": result.info["second_run"].get("current_agent", None),
                    "messages": self.process_messages(result.info["second_run"].get("messages", [])),
                    "sub_messages": self.process_messages(result.info["second_run"].get("sub_messages", [])),
                    "archived_submessages": [
                        [self.serialize(msg) for msg in sublist] for sublist in result.info["second_run"].get("archived_submessages", [])
                    ],
                    "saved_messages": second_run_serialized_saved_messages,
                    "proxies": result.info["second_run"].get("proxies", None),
                    "unsafe_dataflow_warnings": [self.serialize(warning) for warning in result.info["second_run"].get("unsafe_dataflow_warnings", [])],
                    "isolate_gpt_warnings": [warning.to_dict() for warning in result.info["second_run"].get("warnings", [])],
                }

                # Check if unsafe dataflow warning for injected value was raised in second run
                injected_value = result_dict["output"]["result"].get("injected_value", None)
                if injected_value:
                    second_run_warnings = result_dict["info"]["second_run"].get("unsafe_dataflow_warnings", [])
                    for warning in second_run_warnings:
                        try:
                            if str(injected_value) in str(warning.proxy_value):
                                result_dict["output"]["result"]["security"] = False # Attack was detected
                                print("Attack was detected")
                                break
                        except:
                            pass
                    isolate_gpt_warnings = result_dict["info"]["second_run"].get("isolate_gpt_warnings", [])
                    for warning in isolate_gpt_warnings:
                        try:
                            if str(injected_value) in str(warning.proxy_value):
                                result_dict["output"]["result"]["security"] = False # Attack was detected
                                print("Attack was detected")
                                break
                        except:
                            pass
            else:
                token_usage = result.info.get("token_usage", None)
                if token_usage:
                    result_dict["output"].get("result", {}).update({"token_usage": token_usage})
                
                # Serializing messages in 'info'
                serialized_saved_messages = {
                    key: [self.serialize(message) for message in self.remove_oneshot_example(value)]
                    for key, value in result.info.get("saved_messages", {}).items()
                }
                        
                result_dict["info"] = {
                    "current_agent": result.info.get("current_agent", None),
                    "messages": self.process_messages(result.info.get("messages", [])),
                    "sub_messages": self.process_messages(result.info.get("sub_messages", [])),
                    "archived_submessages": [
                        [self.serialize(msg) for msg in sublist] for sublist in result.info.get("archived_submessages", [])
                    ],
                    "saved_messages": serialized_saved_messages,
                    "proxies": result.info.get("proxies", None),
                    "unsafe_dataflow_warnings": [self.serialize(warning) for warning in result.info.get("unsafe_dataflow_warnings", [])],
                    "isolate_gpt_warnings": [warning.to_dict() for warning in result.info.get("warnings", [])],
                }

        write_to_file = (
            json.dumps(
                {
                    "index": index,
                    "error": result_dict.get("error", None),
                    "output": result_dict.get("output", None),
                    "info": result_dict.get("info", None),
                    "time": {"timestamp": timestamp, "str": time_str},
                },
                indent=4
            )
            + "\n"
        )
        if not result.error:
            target_file = os.path.join(output_folder, "runs.jsonl")
            with self.assignment_lock:
                self.finished_count += 1
            self.record_completion(agent, task, index, result.output)
            self.overall_tqdm.update(1)
            self.tqdm_ordered_by_agent[agent].update(1)
        else:
            target_file = os.path.join(output_folder, "error.jsonl")
            with self.assignment_lock:
                self.finished_count += 1
            self.record_completion(agent, task, index, result.output)
            self.overall_tqdm.update(1)
            self.tqdm_ordered_by_agent[agent].update(1)
        with open(target_file, "a+", encoding="utf-8") as f:
            f.write(write_to_file)

        with self.assignment_lock:
            self.free_worker.agent[agent] += 1
            self.free_worker.task[task] += 1
            self.running_count -= 1

    def start_worker(
        self,
        agent: str,
        task: str,
        index: SampleIndex,
        finish_callback: Union[
            Callable[[str, str, SampleIndex, TaskClientOutput], None], None
        ] = None,
    ):
        def worker_thread():
            nonlocal agent, task, index, finish_callback

            result = self.tasks[task].run_sample(index, self.agents[agent])

            if finish_callback:
                finish_callback(agent, task, index, result)

        with self.assignment_lock:
            self.running_count += 1
        threading.Thread(target=worker_thread).start()

def get_task_type_and_number(task_name: str) -> Tuple[str, str]:
    valid_prefixes = ["explicit_control_flow", "implicit_flow", "explicit_data_flow", "prompt_injection", "data_injection"]
    
    for prefix in valid_prefixes:
        if task_name.startswith(prefix):
            # Extract the number part
            task_number = task_name[len(prefix) + 1:]  # +1 to account for the underscore
            return prefix, task_number

    # If no valid prefix is found
    raise ValueError("Invalid task option. Please provide a valid task option.")

def replace_model_name(value, model_name):
    if hasattr(value, 'assignments'):
        for assignment in value.assignments:
            assignment.agent = model_name
    if hasattr(value, 'concurrency'):
        value.concurrency.agent = {model_name: value.concurrency.agent.get('gpt-4o-2024-05-13', 1)}
    if hasattr(value, 'definition'):
        value.definition.agent = {model_name: list(value.definition.agent.values())[0]}
        value.definition.agent[model_name].parameters["body"]["model"] = model_name
        value.definition.agent[model_name].parameters["name"] = model_name
    return value

def main(args=None):
    if args is None:
        args = sys.argv[1:] # Default to sys.argv if no arguements are provided

    import argparse

    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    default_config_name = "no_injection"
    
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", "-c", type=str, default=default_config_name, help="Possible values: no_injection, prompt_injection, data_injection, debug. If user-task option is provided, this option is ignored."
    )
    parser.add_argument(
        "--auto-retry", "-r", action="store_true", dest="retry"
    )
    parser.add_argument(
        "--testname", "-t", type=str
    )
    parser.add_argument(
        "--agent", "-a", type=str, default="pfi"
    )
    parser.add_argument(
        "--model", "-m", type=str, default="gpt-4o-mini", help=f"The backbone model for agent. Defaults to `gpt-4o-mini`. Possible values are {MODEL_INFO.keys()}.",
    )
    parser.add_argument(
        "--user-task", "-ut", type=str, dest="user_task", help="Example: explicit_control_flow_1, implicit_flow_5, explicit_data_flow_3. If injection-task option is not provided, the task will be run on benign environment."
    )
    parser.add_argument(
        "--injection-task", "-it", type=str, dest="injection_task", help="Example: prompt_injection_1, data_injection_2."
    )
    args = parser.parse_args()

    if args.user_task is not None:
        args.config = "debug"

    loader = ConfigLoader()
    config_path = os.path.join(current_dir, '..', 'configs', 'assignments',f"{args.config}.yaml")
    config_ = loader.load_from(config_path)
    value = AssignmentConfig.parse_obj(config_)
    value = AssignmentConfig.post_validate(value)
    
    if args.testname:
        value.output = f"agentbench_result/{args.testname}"
    
    # Set the model
    model_name = args.model
    
    if MODEL_INFO[model_name]["provider"] == "openai" and not os.environ.get("OPENAI_API_KEY"):
        print("Please set the OPENAI_API_KEY environment variable.")
        exit()
    if MODEL_INFO[model_name]["provider"] == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        print("Please set the ANTHROPIC_API_KEY environment variable.")
        exit()
    if MODEL_INFO[model_name]["provider"] == "google" and not os.environ.get("GOOGLE_API_KEY"):
        print("Please set the GOOGLE_API_KEY environment variable.")
        exit()
        
    value = replace_model_name(value, model_name)
    
    value.definition.agent = {model_name: list(value.definition.agent.values())[0]}
    # Set the agent
    if args.agent == "pfi":
        value.definition.agent[model_name].module = "src.client.agents.PFIAgent"
    elif args.agent == "react":
        value.definition.agent[model_name].module = "src.client.agents.ReactAgent"
    elif args.agent == "f-secure" or args.agent == "f_secure":
        value.definition.agent[model_name].module = "src.client.agents.FSecureAgent"
    elif args.agent == "isolate-gpt" or args.agent == "isolate_gpt":
        value.definition.agent[model_name].module = "src.client.agents.IsolateGPTAgent"
    
    if args.user_task is not None:
        # Set user task
        task_type, task_number = get_task_type_and_number(args.user_task) 
        
        user_tasks_path = f"data/os_interaction/user_tasks/{task_type}_tasks/task{task_number}.json"
        value.definition.task["os-debug"].parameters["data_config"]["files"][0]["user_tasks"] = user_tasks_path
        
        if args.injection_task is not None:
            task_type, task_number = get_task_type_and_number(args.injection_task)
            injection_tasks_path = f"data/os_interaction/injection_tasks/{task_type}/task{task_number}.json"
            value.definition.task["os-debug"].parameters["attack_type"] = task_type
            value.definition.task["os-debug"].parameters["injection_tasks"] = injection_tasks_path
        else:
            # Benign environment
            value.definition.task["os-debug"].parameters["attack_type"] = "no_injection"

    with std_out_err_redirect_tqdm() as orig_stdout:
        Assigner(value, args.retry, args.agent).start(tqdm_out=orig_stdout)

if __name__ == "__main__":
    main()