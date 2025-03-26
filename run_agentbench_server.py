import os
import subprocess
import argparse

def run_agentbench_server():
    # Change directory to the required path relative to the current script
    current_dir = os.path.dirname(os.path.abspath(__file__))
    agentbench_path = os.path.join(current_dir, "benchmarks", "AgentBench")
    os.chdir(agentbench_path)

    # Parse arguments to dynamically construct the command
    parser = argparse.ArgumentParser(description="Run AgentBench server.")
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

    # Construct the command dynamically based on provided arguments
    command = ["python", "-m", "src.start_task"]

    if args.controller:
        command.append("-a")

    if args.config:
        command.extend(["--config", args.config])

    if args.port:
        command.extend(["--base-port", str(args.port)])

    if args.user_task:
        command.extend(["--user-task", args.user_task])

    if args.injection_task:
        command.extend(["--injection-task", args.injection_task])

    if args.start:
        command.extend(["--start"] + args.start)

    if args.controller_addr:
        command.extend(["--controller", args.controller_addr])
    
    # Run the server with the constructed command
    subprocess.run(command)

if __name__ == "__main__":
    run_agentbench_server()