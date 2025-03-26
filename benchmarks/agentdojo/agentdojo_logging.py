import contextvars
import json
import logging
import os
import textwrap
import time
import warnings

from pydantic import BaseModel
from rich.live import Live
from rich.table import Table

from ast_utils import create_python_function_from_tool_call
from agentdojo_types import ChatMessage

LOGGER_STACK = contextvars.ContextVar("logger_stack", default=[])


class Logger:
    def __enter__(self):
        LOGGER_STACK.get().append(self)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        LOGGER_STACK.get().pop()
        return False

    @staticmethod
    def get():
        loggers = LOGGER_STACK.get()
        if len(loggers) == 0:
            return NullLogger()
        return loggers[-1]


class NullLogger(Logger):
    messages: list[ChatMessage]

    def __enter__(self):
        self.messages = []
        self.logdir = None
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def log(self, *args, **kwargs):
        pass

    def log_error(self, *args, **kwargs):
        pass


def assistant(text):
    return f":robot_face: [red]{text}[/red]"


def tool(text):
    return f":wrench: [orange]{text}[/orange]"


def user(text):
    return f":bust_in_silhouette: [green]{text}[/green]"


def system(text):
    return f":book: [blue]{text}[/blue]"


class OutputLogger(Logger):
    def log_error(self, message: str):
        logging.warning(f"[red]API error: {message}[/red]", extra={"markup": True})

    def __init__(self, logdir: str | None, live: Live | None = None):
        self.messages = []
        self.logdir = logdir
        self.live = live
        self.table = Table("Role", "Content", title="Chat log", show_lines=True)
        self.previous_user_task_id = None

    def log(self, messages: list[ChatMessage], **kwargs):
        messages = messages[len(self.messages) :]
        self.messages += messages

        user_task_id = kwargs.get("user_task_id" or "unknown user_task_id")
        injection_task_id = kwargs.get("injection_task_id" or "unknown injection_task_id")
        suite_name = kwargs.get("suite_name" or "unknown suite_name")
        pipeline_name = kwargs.get("pipeline_name" or "pipeline suite_name")

        if user_task_id != self.previous_user_task_id:
            self.table = Table(
                "Role",
                "Content",
                title=f"[{suite_name}][{user_task_id}{injection_task_id}]",
                show_lines=True,
            )
            self.previous_user_task_id = user_task_id

        for message in messages:
            if "role" not in message:
                break
            role = message["role"]
            content = message["content"] or ""
            if message["role"] == "assistant":
                tool_calls = message.get("tool_calls") or []
            else:
                tool_calls = None

            if tool_calls is not None and len(tool_calls) > 0:
                tool_calls_content = "\n------------\nTool calls:"
                for tool_call in tool_calls:
                    python_function = create_python_function_from_tool_call(tool_call)
                    tool_calls_content += f"\n   - {python_function}"
            else:
                tool_calls_content = ""
            if role == "user":
                role = user(role)
            elif role == "assistant":
                role = assistant(role)
            elif role == "tool":
                if "error" in message and message["error"] is not None:
                    content = f"[red]{message['error']}[/red]"
                if "tool_call" in message:
                    role = f"{role} [bold]{message['tool_call'].get('name')}[/bold]"
                role = tool(role)
            else:
                role = system(role)
            if self.live is None:
                logging_content = textwrap.shorten(f"{content}{tool_calls_content}", width=200, placeholder="[...]")
                if injection_task_id is not None:
                    current_task_id = rf"\[{user_task_id}]\[{injection_task_id}]"
                else:
                    current_task_id = rf"\[{user_task_id}]"
                logging.info(
                    rf"\[{pipeline_name}]\[{suite_name}]{current_task_id} {role}: {logging_content}",
                    extra={"markup": True},
                )
            else:
                self.table.add_row(role, content + tool_calls_content)
                self.live.update(self.table)


class NotebookLogger(OutputLogger):
    def log(
        self,
        messages: list[ChatMessage],
        **kwargs,
    ):
        from IPython.display import clear_output

        clear_output(wait=True)
        super().log(messages, **kwargs)


class TraceLogger(Logger):
    """
    Logs agent interactions as JSON files in a directory.

    Organizes log files by metadata (self.set_context) and logs
    """

    def __init__(self, delegate: NullLogger | OutputLogger, **contextargs):
        import os

        self.delegate = delegate
        self.dirpath = delegate.logdir or os.path.join(os.path.dirname(__file__), "../../", "agentdojo_result")
        self.context = contextargs
        self.messages: list[ChatMessage] = []
        self.delegate.messages = []
        self.error: str | None = None
        self.start = None

        if not os.path.exists(self.dirpath):
            os.makedirs(self.dirpath, exist_ok=True)

    def __enter__(self):
        self.start = time.time()
        return super().__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        if self.start is not None:
            self.set_contextarg("duration", time.time() - self.start)
        else:
            self.set_contextarg("duration", None)

        return super().__exit__(exc_type, exc_value, traceback)

    def set_contextarg(self, key, value):
        self.context[key] = value
        if key == "warnings":
            print(self.context) 
        self.save()

    def prune_archived_submessages(self, archived_submessages):
        pruned_archived_submessages = []
        for sublist in archived_submessages:
            pruned_sublist = []
            for message in sublist:
                pruned_message = {
                    "role": "assistant" if message.type == "ai" else message.type, 
                    "name": message.name,
                    "content": message.content,
                    "tool_calls": message.tool_calls if message.type == "ai" else None
                }
                pruned_sublist.append(pruned_message)
            pruned_archived_submessages.append(pruned_sublist)
        return pruned_archived_submessages
    
    def prune_saved_messages(self, saved_messages):
        pruned_saved_messages = {}
        for spoke_id, messages in saved_messages.items():
            pruned_messages = []
            for message in messages:
                pruned_message = {
                    "role": "assistant" if message.type == "ai" else message.type, 
                    "name": message.name,
                    "content": message.content,
                    "tool_calls": message.tool_calls if message.type == "ai" else None
                }
                pruned_messages.append(pruned_message)
            pruned_saved_messages[spoke_id] = pruned_messages
        return pruned_saved_messages
    
    def save(self):
        # Fetches suite_name, user_task_id=user_task.ID, injection_task_id=injection_task_id, injections=task_injections from context
        suite_name = self.context.get("suite_name", "unknown_suite_name")
        user_task_id = self.context.get("user_task_id", "unknown_user_task_id")
        injection_task_id = self.context.get("injection_task_id", "unknown_injection_task_id")
        injections = self.context.get("injections", {})
        attack_type = self.context.get("attack_type", None)
        pipeline_name = self.context.get("pipeline_name", None)
        utility = self.context.get("utility", None)
        security = self.context.get("security", None)
        injection_has_happened = self.context.get("injection_has_happened", None)
        duration = self.context.get("duration", None)
        archived_submessages = self.context.get("archived_submessages", [])
        if archived_submessages is not None:
            archived_submessages = self.prune_archived_submessages(archived_submessages)
        second_run_messages = self.context.get("second_run_messages", None)
        second_run_archived_submessages = self.context.get("second_run_archived_submessages", None)
        if second_run_archived_submessages is not None:
            second_run_archived_submessages = self.prune_archived_submessages(second_run_archived_submessages)
        proxies = self.context.get("proxies", None)
        second_run_proxies = self.context.get("second_run_proxies", None)
        user_task_type = self.context.get("user_task_type", None)
        injection_task_type = self.context.get("injection_task_type", None)
        agent_type = self.context.get("agent_type", None)
        token_usage = self.context.get("token_usage", None)
        model_name = self.context.get("model_name", None)
        unsafe_dataflow_warnings = self.context.get("unsafe_dataflow_warnings", None)
        second_run_unsafe_dataflow_warnings = self.context.get("second_run_unsafe_dataflow_warnings", None)
        # For IsolateGPT
        saved_messages = self.context.get("saved_messages", None)
        if saved_messages is not None:
            saved_messages = self.prune_saved_messages(saved_messages)
        isolate_gpt_warnings = self.context.get("isolate_gpt_warnings", None)
        second_run_saved_messages = self.context.get("second_run_saved_messages", None)
        if second_run_saved_messages is not None:
            second_run_saved_messages = self.prune_saved_messages(second_run_saved_messages)
        second_run_isolate_gpt_warnings = self.context.get("second_run_isolate_gpt_warnings", None)
        
        other_context = {
            k: v
            for k, v in self.context.items()
            if k
            not in [
                "suite_name",
                "user_task_id",
                "injection_task_id",
                "injections",
                "attack_type",
                "pipeline_name",
                "archived_submessages",
                "utility",
                "security",
                "injection_has_happened",
                "duration",
                "user_task_type",
                "injection_task_type",
                "agent_type",
                "token_usage",
                "model_name",
                "proxies",
                "unsafe_dataflow_warnings",
                "second_run_unsafe_dataflow_warnings",
                "second_run_messages",
                "second_run_archived_submessages",
                "second_run_proxies",
                "saved_messages",
                "isolate_gpt_warnings",
                "second_run_saved_messages",
                "second_run_isolate_gpt_warnings",
            ]
        }

        if attack_type is None:
            warnings.warn(
                f"Cannot log executed benchmark (suite_name={suite_name}, user_task_id={user_task_id}, injection_task_id={injection_task_id}, attack_type={attack_type}) because attack_type is not known. Make sure to run the benchmark with the attack_type parameter set (cf. benchmark_suite_with_injections(...))."
            )
            return

        if pipeline_name is None:
            warnings.warn(
                f"Cannot log executed benchmark (suite_name={suite_name}, user_task_id={user_task_id}, injection_task_id={injection_task_id}, attack_type={attack_type}) because pipeline_name is not known. Make sure to run the benchmark with the pipeline_name parameter set (cf. benchmark_suite_with_injections(...))."
            )
            return
        pipeline_name = pipeline_name.replace("/", "_")

        directory = f"{self.dirpath}/{pipeline_name}/{suite_name}/{user_task_id}/{attack_type}"
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        file = f"{directory}/{injection_task_id or 'none'}.json"
        with open(file, "w") as f:
            f.write(
                json.dumps(
                    {
                        "suite_name": suite_name,
                        "pipeline_name": pipeline_name,
                        "agent_type": agent_type,
                        "model_name": model_name,
                        "user_task_id": user_task_id,
                        "injection_task_id": injection_task_id,
                        "user_task_type": user_task_type if user_task_type != "none" else None,
                        "injection_task_type": injection_task_type if injection_task_type != "none" else None,
                        "attack_type": attack_type if attack_type != "none" else None,
                        "injections": injections,
                        "messages": self.messages,
                        "archived_submessages": archived_submessages,
                        "saved_messages": saved_messages,
                        "proxies": proxies,
                        "unsafe_dataflow_warnings": [warning.to_dict() for warning in unsafe_dataflow_warnings] if unsafe_dataflow_warnings is not None else None,
                        "isolate_gpt_warnings": isolate_gpt_warnings,
                        "second_run_messages": second_run_messages,
                        "second_run_archived_submessages": second_run_archived_submessages,
                        "second_run_saved_messages": second_run_saved_messages,
                        "second_run_proxies": second_run_proxies,
                        "second_run_unsafe_dataflow_warnings": [warning.to_dict() for warning in second_run_unsafe_dataflow_warnings] if second_run_unsafe_dataflow_warnings is not None else None,
                        "second_run_isolate_gpt_warnings": second_run_isolate_gpt_warnings,
                        "error": self.error,
                        **other_context,
                        "utility": utility,
                        "security": security,
                        "injection_has_happened": injection_has_happened,
                        "duration": duration,
                        "token_usage": token_usage,
                    },
                    indent=4,
                    default=lambda o: o.model_dump() if isinstance(o, BaseModel) else o,
                )
            )

    def log_error(self, error: str):
        self.error = error
        self.delegate.log_error(error)
        self.save()

    def log(self, messages: list[ChatMessage]):
        user_task_id = self.context.get("user_task_id", "unknown_user_task_id")
        injection_task_id = self.context.get("injection_task_id", "unknown_user_task_id")
        suite_name = self.context.get("suite_name", "unknown_suite_name")
        pipeline_name = self.context.get("pipeline_name", "pipeline_suite_name")
        self.delegate.log(
            messages,
            user_task_id=user_task_id,
            injection_task_id=injection_task_id,
            suite_name=suite_name,
            pipeline_name=pipeline_name,
        )
        self.messages = messages
        self.save()
