import os
import requests
import traceback
import time
from typing import List

from ..agent import AgentClient
from pfi_agent import *
from config import config
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.errors import GraphRecursionError
from src.typings import InteractRequest, AgentOutput, CancelRequest, SampleStatus, TaskOutput
from ..task import TaskError
from .tools import pfi_os_tools
from .prompts import prompts
from src.server.tasks.os_interaction.task import DEFAULT_INJECTION_VALUE
from src.client.agents.model_info import MODEL_INFO

class PFIAgent(AgentClient):
    def __init__(self, *args, **_config):
        super().__init__(*args, **_config)
       
        # Set the model
        model_name = _config['body']['model']
        
        if MODEL_INFO[model_name]["provider"] == "openai":       
            self.model = ChatOpenAI(model=MODEL_INFO[model_name]["version"], temperature=0)
        elif MODEL_INFO[model_name]["provider"] == "anthropic":
            self.model = ChatAnthropic(model=MODEL_INFO[model_name]["version"], temperature=0) 
        elif MODEL_INFO[model_name]["provider"] == "google":
            self.model = ChatGoogleGenerativeAI(model=MODEL_INFO[model_name]["version"], temperature=0)
        else:
            raise ValueError("Invalid model")

        self.token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "total_expense": 0}

        def token_usage_tracker():
            def decorator(func):
                def wrapper(*args, **kwargs):
                    result = func(*args, **kwargs)
                    usage_metadata = result.usage_metadata

                    input_tokens = usage_metadata.get("input_tokens", 0)
                    output_tokens = usage_metadata.get("output_tokens", 0)
                
                    self.token_usage["input_tokens"] += input_tokens
                    self.token_usage["output_tokens"] += output_tokens
                    self.token_usage["total_tokens"] += input_tokens + output_tokens
                
                    input_cost_per_token = MODEL_INFO[model_name]['input_cost_per_token']
                    output_cost_per_token = MODEL_INFO[model_name]['output_cost_per_token']
                
                    self.token_usage["total_expense"] = (
                        self.token_usage["input_tokens"] * input_cost_per_token + 
                        self.token_usage["output_tokens"] * output_cost_per_token
                    )
                    
                    self.token_usage["input_tokens"] += usage_metadata.get("input_tokens", 0)
                    self.token_usage["output_tokens"] += usage_metadata.get("output_tokens", 0)
                    self.token_usage["total_tokens"] += usage_metadata.get("total_tokens", 0)
                    return result
                return wrapper
            return decorator
        
        self.model.__dict__["invoke"] = token_usage_tracker()(self.model.invoke)
        
        self.agent_type = "pfi"

    def agent_switch_callback(self, switching_to: str):
        print(f"================================ Callback: {switching_to} ================================")

        try:
            if switching_to == "untrusted":  # trusted -> untrusted
                stop_trusted_shell = "kill -STOP $$"
                self.send_command(stop_trusted_shell, self.session_id, self.controller_address)
                time.sleep(0.3)

                # Mount an empty directory to the target directories
                start_untrusted_shell = "nsjail -Mo --user 99999 --group 99999 -R /bin -R /lib -R /lib64 -B /external:/external -T /tmp --disable_proc --disable_clone_newnet -- /bin/bash -i"
                self.send_command(start_untrusted_shell, self.session_id, self.controller_address)
                time.sleep(0.3)
            else:  # untrusted -> trusted
                stop_untrusted_shell = "exit"
                self.send_command(stop_untrusted_shell, self.session_id, self.controller_address)
                time.sleep(0.3)
                start_trusted_shell = "kill -CONT $(grep -l \"TRUSTED_SHELL=1\" /proc/[0-9]*/environ | cut -d '/' -f3) && fg %1"
                self.send_command(start_trusted_shell, self.session_id, self.controller_address)
                time.sleep(0.3)
        except Exception as e:
            print(f"Error: {e}")

    def transform_history_to_langchain_messages(self, history: List[dict]) -> List[BaseMessage]:
        if isinstance(self.model, ChatGoogleGenerativeAI):
            messages = [HumanMessage(content=prompts.OS_SYSTEM_PROMPT)]
        else:
            messages = [SystemMessage(content=prompts.OS_SYSTEM_PROMPT)]
        messages.append(HumanMessage(content=history[0]['content']))
        if len(history) > 1:
            for i in range(1, len(history) - 2):
                if history[i]['role'] == "user":
                    messages.append(ToolMessage(content=history[i]['content'], name="bash_tool", tool_call_id=f'call_abc{i-1}'))
                elif history[i]['role'] == "agent":
                    think = history[i]['content'].split("\n\n")[0].strip()
                    command = history[i]['content'].split("```bash\n")[1].split("\n```")[0].strip()
                    messages.append(AIMessage(content=think, tool_calls=[{'name': 'bash_tool', 'args': {'command': command}, 'id': f'call_abc{i}', 'type': 'tool_call'}]))
            messages.append(AIMessage(content=history[-2]['content']))
            messages.append(HumanMessage(content=history[-1]['content']))
        return messages

    def send_final_answer(
        self, 
        final_answer: str, 
        history: List[dict], 
        first_run_stream_list: List[dict], 
        second_run_stream_list: List[dict] = None
    ) -> dict:
        try:
            result = requests.post(
                self.controller_address + "/interact",
                json=InteractRequest(
                    session_id=self.session_id,
                    agent_response=AgentOutput(content=final_answer)
                ).dict()
            )
        except Exception as e:
            print("Error while sending final answer: ", e)
            if second_run_stream_list:
                info = {
                    "first_run": first_run_stream_list[-1],
                    "second_run": second_run_stream_list[-1]
                }
            else:
                info = first_run_stream_list[-1]
                
            return {
                'error': TaskError.NETWORK_ERROR.value,
                'info': info,
                'output': TaskOutput(status=SampleStatus.TASK_ERROR, result=None, history=history)
            }, False
        if result.status_code != 200:
            print("Task limit reached: result.status_code != 200")
            requests.post(
                self.controller_address + "/cancel",
                json=CancelRequest(session_id=self.session_id).dict()
            )
            if second_run_stream_list:
                info = {
                    "first_run": first_run_stream_list[-1],
                    "second_run": second_run_stream_list[-1]
                }
            else:
                info = first_run_stream_list[-1]
            
            return {
                'info': info,
                'output': TaskOutput(
                    status=SampleStatus.COMPLETED, 
                    result= {
                        "utility": False, 
                        "security": False, 
                        "injection_has_happened": False, 
                        "reason": "Task limit reached",
                    },
                    history=history
                )
            }, False
        return result, True
    
    def finish_task(self, final_answer, history, first_run_stream_list, second_run_stream_list = None):
        result, success = self.send_final_answer(final_answer, history, first_run_stream_list, second_run_stream_list)
        if not success:
            return result
        
        result = result.json()
        
        if second_run_stream_list:
            result['info'] = {
                "first_run": first_run_stream_list[-1],
                "second_run": second_run_stream_list[-1]
            }
        else:
            result['info'] = {**first_run_stream_list[-1], "token_usage": self.token_usage}

        return result

    def run(
        self, 
        history: List[dict], 
        session_id: int, 
        controller_address: str = "http://localhost:5000/api"
    ) -> dict:
        self.session_id = session_id
        self.controller_address = controller_address
        
        bash_tool, bash_tool_u = pfi_os_tools.create_bash_tool(controller_address=controller_address, session_id=session_id)
        TOOLS = [bash_tool, bash_tool_u]
        untrusted_agent_prompt = prompts.OS_UNTRUSTED_AGENT_PROMPT

        # Create PFI Agent
        try:
            policy_path = os.path.join(".", "configs", "pfi-policy-agentbench.yaml")

            global config
            config = config.set_options(
                unsafe_dataflow_choice="UNSAFE_DATAFLOW_YES", 
                log_level="DEBUG",
                policy=policy_path
            )
       
            pfi_agent = create_pfi_agent(
                llm=self.model, 
                tools=TOOLS,
                config=config,
                untrusted_agent_prompt=untrusted_agent_prompt,
                parallel_tool_calls=False
            )
            self.pfi_agent = pfi_agent
        except Exception as e:
            print(f"Error while creating agent: {e}")
            traceback.print_exc()
            raise ValueError

        # Initialize token usage
        self.token_usage["input_tokens"] = 0
        self.token_usage["output_tokens"] = 0
        self.token_usage["total_tokens"] = 0

        # Transform one shot example history from AgentBench into langchain messages
        messages = self.transform_history_to_langchain_messages(history)
                
        # Run the PFI agent
        stream_list = []
        try:
            process_stream(
                    self.pfi_agent.stream({"messages":messages}, stream_mode="values"), 
                    stream_list, 
                    agent_switch_callback=self.agent_switch_callback
                )
        except GraphRecursionError as e:
            print("GraphRecursionError: ", e)
            print("Finishing the task without error.")
            return self.finish_task("Act: answer(Recursion limit reached.)", history, stream_list)
        except Exception as e:
            print("Error: ", e)
            traceback.print_exc()
            requests.post(
                controller_address + "/cancel",
                json=CancelRequest(session_id=session_id).dict()
            )
            return {
                'error': str(e),
                'output': TaskOutput(status=SampleStatus.AGENT_ERROR, result=None, history=history),
                'info': {**stream_list[-1], "token_usage": self.token_usage}
            }

        # Send the final answer of PFI agent to the task server
        final_answer = stream_list[-1]['messages'][-1].content
        return self.finish_task(final_answer, history, stream_list)
    
    def run_for_data_injection(
        self, 
        history: List[dict],
        session_id: int,
        controller_address: str = "http://localhost:5000/api"
    ) -> str:
        self.session_id = session_id
        self.controller_address = controller_address

        bash_tool, bash_tool_u = pfi_os_tools.create_bash_tool(controller_address=controller_address, session_id=session_id)
        TOOLS = [bash_tool, bash_tool_u]
        untrusted_agent_prompt = prompts.OS_UNTRUSTED_AGENT_PROMPT

        # Create PFI Agent
        try:
            policy_path = os.path.join(".", "configs", "pfi-policy-agentbench.yaml")

            global config
            config = config.set_options(
                unsafe_dataflow_choice="UNSAFE_DATAFLOW_YES", 
                log_level="DEBUG",
                policy=policy_path
            )
       
            pfi_agent = create_pfi_agent(
                llm=self.model, 
                tools=TOOLS,
                config=config,
                untrusted_agent_prompt=untrusted_agent_prompt,
                parallel_tool_calls=False
            )
            self.pfi_agent = pfi_agent
        except Exception as e:
            print(f"Error while creating agent: {e}")
            traceback.print_exc()
            raise ValueError
        
        # Transform one shot example history from AgentBench into langchain messages
        messages = self.transform_history_to_langchain_messages(history)
        
        # Run the PFI agent
        stream_list = []
        try:
            injection_has_happened = process_stream(
                    self.pfi_agent.stream({"messages":messages}, stream_mode="values"), 
                    stream_list, 
                    agent_switch_callback=self.agent_switch_callback,
                    value_to_detect=DEFAULT_INJECTION_VALUE
                )
        except GraphRecursionError as e:
            print("GraphRecursionError: ", e)
            print("Finishing the task without error.")
            return self.finish_task("Act: answer(Recursion limit reached.)", history, stream_list)
        except Exception as e:
            print("Error: ", e)
            traceback.print_exc()
            requests.post(
                controller_address + "/cancel",
                json=CancelRequest(session_id=session_id).dict()
            )
            return {
                'error': str(e),
                'output': TaskOutput(status=SampleStatus.AGENT_ERROR, result=None, history=history),
                'info': stream_list[-1],
            }
        
        if not injection_has_happened:
            print("Injection has not happened.")
            return self.finish_task("Act: answer(Injection has not happened.)", history, stream_list)
        first_run_state = stream_list[-1]
        first_run_stream_list = stream_list
        second_run_state = copy.deepcopy(first_run_state)
        second_run_stream_list = copy.deepcopy(first_run_stream_list)
        
        print("FIRST RUN")
        try:
            process_stream(
                self.pfi_agent.stream(first_run_state, stream_mode="values"),
                first_run_stream_list,
                agent_switch_callback=self.agent_switch_callback 
            )
        except GraphRecursionError as e:
            print("First run GraphRecursionError: ", e)
            first_run_stream_list[-1]['messages'].append(AIMessage(content="Act: answer(Recursion limit reached.)"))
        except Exception as e:
            print("Error: ", e)
            traceback.print_exc()
            requests.post(
                controller_address + "/cancel",
                json=CancelRequest(session_id=session_id).dict()
            )
            return {
                'error': str(e),
                'output': TaskOutput(status=SampleStatus.AGENT_ERROR, result=None, history=history),
                'info': first_run_stream_list[-1],
            }
        
        # Send the first run's final answer
        final_answer = first_run_stream_list[-1]['messages'][-1].content
        result, success = self.send_final_answer(final_answer, history, first_run_stream_list)
        if not success:
            print("Failed to send first run's final answer")
            return result
        
        print("FINISHED FIRST RUN")
            
        # Get saved ToolMessage with passive context injection from server
        output = self.send_command("get_tool_result", session_id, controller_address)
        
        # inject the received tool message to the second run's state
        second_run_state["messages"] = second_run_state["messages"][:-1]
        last_tool_call_id = second_run_state["messages"][-1].tool_calls[-1]["id"]
        output = re.sub(r'UNTRUSTED - ', '', output)
            
        second_run_state["messages"].append(ToolMessage(content=output, name="bash_tool", tool_call_id=last_tool_call_id))

        # Run the second run
        try:
            process_stream(
                self.pfi_agent.stream(second_run_state, stream_mode="values"),
                second_run_stream_list,
                agent_switch_callback=self.agent_switch_callback
            )
        except GraphRecursionError as e:
            print("GraphRecursionError: ", e)
            print("Finishing the second run without error.")
            second_run_stream_list[-1]['messages'].append(AIMessage(content="Act: answer(Recursion limit reached.)"))
        except Exception as e:
            print("Error: ", e)
            traceback.print_exc()
            requests.post(
                controller_address + "/cancel",
                json=CancelRequest(session_id=session_id).dict()
            )
            return {
                'error': str(e),
                'output': TaskOutput(status=SampleStatus.AGENT_ERROR, result=None, history=history),
                'info': {
                    "first_run": first_run_stream_list[-1],
                    "second_run": second_run_stream_list[-1]
                },
            }
        
        # Send the second run's final answer
        final_answer = second_run_stream_list[-1]['messages'][-1].content
        return self.finish_task(final_answer, history, first_run_stream_list, second_run_stream_list)
    
    # Debug functions
    def send_command(self, command: str, session_id: int, controller_address: str = "http://localhost:5000/api", finish = False) -> str:
        if not finish:
            query = (
                "Think: I'm running the command.\n\n"
                "Act: bash\n\n"
                "```bash\n"
                f"{command}\n"
                "```\n\n"
            )
        else:
            query = (
                "Think: Now I get the answer, it is 220.\n\n"
                "Act: answer(220)"
            )
        
        try:
            result = requests.post(
                controller_address + "/interact",
                json=InteractRequest(
                    session_id=session_id,
                    agent_response=AgentOutput(content=query)
                ).dict()
            )
        except Exception as e:
            raise Exception(f"Error: {e}")
        
        result = result.json()
        os_output = result["output"]["history"][-1]["content"]
        return os_output

    def debug(self, session_id: int, controller_address: str = "http://localhost:5000/api"):
        print("Debugging PFI agent...")
        self.session_id = session_id
        self.controller_address = controller_address
        current_agent = "trusted"

        finish_command = (
            "Think: Now I get the answer, it is 220.\n\n"
            "Act: answer(220)"
        )

        while True:
            # Get input from user
            print("Enter a command to run:")
            user_input = input()

            if user_input == "fin":
                output = self.send_command(finish_command, session_id, controller_address, finish=True)
                break
            else:
                output = pfi_os_tools.execute_bash_command(user_input, controller_address, self.session_id, current_agent)

            # Print the response
            try:
                print("------Agent response------")
                print(output.data)
                print("attr: ", output.attr)
                print("--------------------------")
            except:
                print(output)
            
        return output