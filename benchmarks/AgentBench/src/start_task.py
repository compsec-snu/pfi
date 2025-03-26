import argparse
import os
import subprocess
import time
from urllib.parse import urlparse
from typing import Tuple
import requests

from src.configs import ConfigLoader

def get_task_type_and_number(task_name: str) -> Tuple[str, str]:
    valid_prefixes = ["explicit_control_flow", "implicit_flow", "explicit_data_flow", "prompt_injection", "data_injection"]
    
    for prefix in valid_prefixes:
        if task_name.startswith(prefix):
            # Extract the number part
            task_number = task_name[len(prefix) + 1:]  # +1 to account for the underscore
            return prefix, task_number

    # If no valid prefix is found
    raise ValueError("Invalid task option. Please provide a valid task option.")

def _start_worker(name, port, controller, definition, user_task=None, injection_task=None):
    conf = definition[name]
    if "docker" in conf and "image" in conf["docker"]:
        docker = conf["docker"]
        project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        subprocess.Popen(
            [
                "docker",
                "run",
                "--rm",
                "-p",
                f"{port}:{port}",
                "--add-host",
                "host.docker.internal:host-gateway",
                "-v",
                f"{project_root}:/root/workspace",
                "-w",
                "/root/workspace",
                docker["image"],
                "bash",
                "-c",
                docker.get("command", "") + f" python -m src.server.task_worker {name}"
                                            f" --self http://localhost:{port}/api"
                                            f" --port {port}"
                                            f" --controller {controller.replace('localhost', 'host.docker.internal')}",
            ]
        )
    else:
        subprocess.Popen(
            [
                "python",
                "-m",
                "src.server.task_worker",
                name,
                "--self",
                f"http://localhost:{port}/api",
                "--port",
                str(port),
                "--controller",
                controller,
                "--user-task",
                user_task if user_task is not None else "None",
                "--injection-task",
                injection_task if injection_task is not None else "None", 
            ],
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=str,
        help="Config file to load",
        default="configs/start_task.yaml",
    )
    parser.add_argument(
        "--start",
        "-s",
        dest="start",
        type=str,
        nargs="*",
        help="name num_worker name num_worker ...",
    )
    parser.add_argument("--controller", "-l", dest="controller_addr", default="")
    parser.add_argument(
        "--auto-controller", "-a", dest="controller", action="store_true"
    )
    parser.add_argument("--base-port", "-p", dest="port", type=int, default=5001)
    parser.add_argument("--user-task", "-ut", type=str, dest="user_task", help="Example: explicit_control_flow_1, implicit_flow_5, explicit_data_flow_3. If injection-task option is not provided, the task will be run on benign environment.")
    parser.add_argument("--injection-task", "-it", type=str, dest="injection_task", help="Example: prompt_injection_1, data_injection_2.")

    args = parser.parse_args()

    config = ConfigLoader().load_from(args.config)
    
    if args.user_task is not None:
        task_type, task_number = get_task_type_and_number(args.user_task)
        user_tasks_path = f"data/os_interaction/user_tasks/{task_type}_tasks/task{task_number}.json"
        config["definition"]["os-debug"]["parameters"]["data_config"]["files"][0]["user_tasks"] = user_tasks_path

        if args.injection_task is not None:
            task_type, task_number = get_task_type_and_number(args.injection_task)
            injection_tasks_path = f"data/os_interaction/injection_tasks/{task_type}/task{task_number}.json"
            config["definition"]["os-debug"]["parameters"]["attack_type"] = task_type
            config["definition"]["os-debug"]["parameters"]["injection_tasks"] = injection_tasks_path
            config["definition"]["os-debug"]["parameters"]["data_config"]["files"][0]["index_prefix"] = task_type
        else:
            config["definition"]["os-debug"]["parameters"]["attack_type"] = "no_injection"
            config["definition"]["os-debug"]["parameters"]["data_config"]["files"][0]["index_prefix"] = "no_injection"

    root = os.path.dirname(os.path.abspath(__file__))

    if args.controller:
        if "controller" in config:
            try:
                requests.get(config["controller"] + "/list_workers")
            except Exception as e:
                print("Specified controller not responding, trying to start a new one")
                o = urlparse(config["controller"])
                subprocess.Popen(
                    [
                        "python",
                        "-m",
                        "src.server.task_controller",
                        "--port",
                        str(o.port),
                    ]
                )
        else:
            subprocess.Popen(
                ["python", "-m", "src.server.task_controller", "--port", "5000"]
            )
        for i in range(10):
            try:
                requests.get("http://localhost:5000/api/list_workers")
                break
            except Exception as e:
                print("Waiting for controller to start...")
                time.sleep(0.5)
        else:
            raise Exception("Controller failed to start")

    base_port = args.port

    if args.controller_addr:
        controller_addr = args.controller_addr
    elif "controller" in config:
        controller_addr = config["controller"]
    else:
        controller_addr = "http://localhost:5000/api"

    if args.user_task is not None:
        _start_worker("os-debug", base_port, controller_addr, config["definition"], args.user_task, args.injection_task)
    elif "start" in config.keys() and not args.start:
        for key, val in config.get("start", {}).items():
            for _ in range(val):
                _start_worker(key, base_port, controller_addr, config["definition"], args.user_task, args.injection_task)
                base_port += 1

    n = len(args.start) if args.start else 0
    if n % 2 != 0:
        raise ValueError(
            "--start argument should strictly follow the format: name1 num1 name2 num2 ..."
        )
    for i in range(0, n, 2):
        for _ in range(int(args.start[i + 1])):
            _start_worker(args.start[i], base_port, controller_addr, config["definition"])
            base_port += 1

    while True:
        input()

# try: python start_task.py ../configs/server/test.yaml -a
