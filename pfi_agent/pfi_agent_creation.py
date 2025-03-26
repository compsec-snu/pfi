import re, ast, copy, yaml, os
import fnmatch
from typing import Dict, List, Literal, Sequence, TypedDict, Union
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph.message import add_messages
from langchain_core.messages import (
    AIMessage,
    ToolMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langgraph.graph import END, StateGraph, START
from langgraph.prebuilt import ToolNode
from langgraph.errors import NodeInterrupt
from langgraph.prebuilt import ToolNode
import langgraph.prebuilt.tool_node
from pydantic import BaseModel, Field
from .utils import print_debug, bind_tools, get_tool_messages
from .sealing import (
    get_result,
    seal,
    replace_proxies_in_message,
    replace_proxies_in_messages,
    get_query,
    seal_message,
    extract_proxies_with_positions,
    extract_prompt_values
)
from .query_generation import generate_query
from .pfi_tools import (
    initialize_condition_llm,
    conditional_prompt,
    return_query_result,
)
from .plugin_connector import PFIData, PFIDataList, PFIDataDict
from .prompts import AGENT_PROMPT, TRUSTED_AGENT_PROMPT, PROXY
from .unsafe_dataflow_check import UnsafeDataflowWarning
from langchain_google_genai import ChatGoogleGenerativeAI
from .error_handling import(
    error_messages,
    process_error_message,
)

langgraph.prebuilt.tool_node.TOOL_CALL_ERROR_TEMPLATE = "Error: {error}"

class PFIPermission(BaseModel):
    trusted: List[str] = Field(default_factory=list)
    untrusted: List[str] = Field(default_factory=list)

class PFIPolicy(BaseModel):
    attr: Dict[str, List[str]] = Field(default_factory=lambda: {"Trusted": [], "Untrusted": []})
    permission: PFIPermission = Field(default_factory=PFIPermission)

def deserialize_plugin_result(plugin_result):
    pfi_data = None
    try:
        pfi_data = eval(plugin_result)
        if isinstance(pfi_data, PFIData) or isinstance(pfi_data, PFIDataList) or isinstance(pfi_data, PFIDataDict):
            pass
        else:
            raise Exception(f"Invalid plugin result type: {type(pfi_data)}")
    except Exception as e:
        print(f"Failed to deserialize the plugin result: {plugin_result} ({e})")
        # By default, return the plugin result as a untrusted data
        pfi_data = PFIData(data=plugin_result, attr="Unknown")
    return pfi_data

def create_pfi_agent(
    llm, 
    tools,
    config,
    trusted_agent_prompt = TRUSTED_AGENT_PROMPT.format(PROXY=PROXY),
    untrusted_agent_prompt = "",
    parallel_tool_calls = True,
):
    policy = PFIPolicy()
    trusted_agent_tools = []
    untrusted_agent_tools = []

    def load_policy(path):
        nonlocal policy
        this_policy = yaml.safe_load(open(path, "r"))
        
        if 'include' in this_policy:
            for included_file in this_policy['include']:
                included_path = os.path.join(os.path.dirname(path), included_file)
                load_policy(included_path)
    
        trusted_tools = policy.permission.trusted
        untrusted_tools = policy.permission.untrusted
        
        if 'TrustedAgent' in this_policy and this_policy['TrustedAgent'] is not None:
            trusted_tools.extend(this_policy['TrustedAgent'])
        if 'UntrustedAgent' in this_policy and this_policy['UntrustedAgent'] is not None:
            untrusted_tools.extend(this_policy['UntrustedAgent'])

        if 'conditional_prompt' not in trusted_tools:
            trusted_tools.append('conditional_prompt')
        if 'return_query_result' not in untrusted_tools:
            untrusted_tools.append('return_query_result')
            
        if 'Attributes' in this_policy:
            if isinstance(this_policy['Attributes'], list):
                for attr in this_policy['Attributes']:
                    if attr.endswith(" u"):
                        attr = attr[:-2]
                        policy.attr["Untrusted"].append(attr)
                    elif attr.endswith(" t"):
                        attr = attr[:-2]
                        policy.attr["Trusted"].append(attr)
            else:
                raise Exception("Attributes should be a list")

    def load_configs():
        nonlocal policy
        if config.policy is not None:
            load_policy(config.policy)

        for tool in tools:
            if not tool.name.endswith("_u"):
                trusted_agent_tools.append(tool)
            if tool.name in policy.permission.untrusted:
                untrusted_agent_tools.append(tool)
                
        trusted_agent_tools.append(conditional_prompt)

    def create_agent(llm, agent_tools, system_message: str, tool_call_only: bool = False, parallel_tool_calls: bool = True):
        """Create an agent."""
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", AGENT_PROMPT),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )
        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in agent_tools]))
        
        tool_binded_llm = bind_tools(llm, agent_tools, enable_parallel_tool_calls=parallel_tool_calls, tool_call_only=tool_call_only)

        return prompt | tool_binded_llm

    class ProxyDict(TypedDict):
        proxy: str
        value: str

    class AgentState(TypedDict):
        """The state of the agent."""
        current_agent: Literal["trusted", "untrusted"] # Current agent
        messages: Sequence[BaseMessage] # List of messages of the agent in action
        sub_messages: Sequence[BaseMessage] # Buffer for messages of agent not in action
        archived_submessages: Sequence[BaseMessage]
        proxies: Sequence[ProxyDict]
        unsafe_dataflow_warnings: Sequence[UnsafeDataflowWarning]
    
    # TODO(REFACTOR): transparent attribute
    def get_tool_res_trustworthiness(tool_message):
        principal = tool_message.additional_kwargs.get("principal", None)
        if isinstance(principal, str):
            if principal == "Untrusted":
                return "untrusted"
            elif principal == "Trusted":
                return "trusted"
            elif principal == "Transparent":
                return "transparent"
        elif isinstance(principal, list):
            if all([elem == "Trusted" for elem in principal]):
                return "trusted"
            if all([elem == "Trusted" or elem == "Transparent" for elem in principal]):
                return "transparent"
            return "untrusted"
        elif isinstance(principal, dict):
            if all([value == "Trusted" for value in principal.values()]):
                return "trusted"
            if all([value == "Trusted" or value == "Transparent" for value in principal.values()]):
                return "transparent"
            return "untrusted"

        return "untrusted"
        
    def get_tool_priv(tool):
        if tool in [tool.name for tool in untrusted_agent_tools + [return_query_result]]:
            return "untrusted"
        else:
            return "trusted"

    def evaluate_principal(attr):
        """
        Evaluate the principal of the attribute.
        If every attribute is trusted, return "Trusted".
        If every attribute is trusted or transparent, return "Transparent".
        Otherwise, return "Untrusted".
        """
        if isinstance(attr, str):
            attrs = attr.split(";")
            principals = []
            for attr in attrs:
                if attr == "Transparent":
                    principals.append("Transparent")
                else:
                    is_trusted = False
                    for pattern in policy.attr["Trusted"]:
                        if fnmatch.fnmatch(attr, pattern):
                            is_trusted = True
                            break
                    for pattern in policy.attr["Untrusted"]:
                        if fnmatch.fnmatch(attr, pattern):
                            is_trusted = False
                            break
                    if is_trusted:
                        principals.append("Trusted")
                    else:
                        principals.append("Untrusted")

            if all([principal == "Trusted" for principal in principals]):
                return "Trusted"
            if all([principal == "Trusted" or principal == "Transparent" for principal in principals]):
                return "Transparent"
            return "Untrusted"
        elif isinstance(attr, list):
            return [evaluate_principal(elem) for elem in attr]
        elif isinstance(attr, dict):
            return {key: evaluate_principal(value) for key, value in attr.items()}
        else:
            print(f"Invalid attr type: {type(attr)}")
            return "Untrusted"

    def trustworthiness_check(state, call_idx):
        """
        Check if current agent can trust the tool result.
        call_idx: Index of the tool call in the tool messages. (-1 for iterative tool call)
        Returns True if the tool result is trusted, False otherwise.
        """
        tool_call_message, tool_messages = get_tool_messages(state["messages"])

        tool_message = tool_messages[call_idx]
        is_sealed = tool_message.content.startswith("PFI SEALED: ")
        is_failed = tool_message.content.startswith("PFI FAILED: ")
        is_error = any([error_message in tool_message.content for error_message in error_messages])

        if is_sealed or is_error or is_failed:
            return True

        if call_idx == -1:
            for idx in range(len(tool_messages)):
                if not trustworthiness_check(state, idx):
                    return False
            return True
        
        tool_res_trustworthiness = get_tool_res_trustworthiness(tool_message)
        if tool_res_trustworthiness == "untrusted":
            return False
        if tool_res_trustworthiness == "transparent":
            if call_idx == -1:
                for idx, tool_call in enumerate(tool_call_message.tool_calls):
                    extracted_proxies = extract_proxies(tool_call["args"], state)
                    if len(extracted_proxies) > 0:
                        proxy = extracted_proxies[0] # JH: FIXME: Handle multiple proxies
                        metadata={
                            "submessage_index": proxy["submessage_index"],
                            "attr": proxy["attr"],
                            "principal": proxy["principal"],
                        }   
                        sealed = seal(tool_message.content, "string", state, metadata)
                        tool_messages[idx].content = f"{sealed}"
            else:
                extracted_proxies = extract_proxies(tool_call_message.tool_calls[call_idx]["args"], state)
                if len(extracted_proxies) > 0:
                    proxy = extracted_proxies[0] # JH: FIXME: Handle multiple proxies
                    metadata={
                        "submessage_index": proxy["submessage_index"],
                        "attr": proxy["attr"],
                        "principal": proxy["principal"],
                    }   
                    sealed = seal(tool_message.content, "string", state, metadata)
                    tool_message.content = f"{sealed}"
        return True
    
    def flow_check(tool_call):
        """
        Check if the tool call contains an unsafe data flow that
        calls a privileged tool with untrusted data (proxies).
        Return True if the tool call contains an unsafe data flow, False otherwise.
        """
        # Final Answer
        if isinstance(tool_call, AIMessage):
            if PROXY in tool_call.content:
                return True
        else: # Tool Call
            tool_priv = get_tool_priv(tool_call['name'])
            if tool_priv == "trusted": 
                for key, value in tool_call['args'].items():
                    if PROXY in str(value):
                        return True
        return False

    def strip_pfi_prefix(message, state):
        if message.content.startswith("PFI SEALED: "):
            message.content = message.content.split("PFI SEALED: ")[1]
        elif message.content.startswith("PFI FAILED: "):
            message.content = message.content.split("PFI FAILED: ")[1]
        else: # is_error
            for error_message in error_messages:
                if error_message in message.content:
                    if state.get("proxies"):
                        seal_message(message, state["proxies"])
                    message = process_error_message(message, state)
                    break
        return

    def detect_infinite_loop(messages, max_repeats=2):
        """
        Infinite loop is detected if one of the following conditions is met:
        1. All current tool calls are included in the previous tool calls.
        2. All previous tool calls are included in current tool calls.  
        """
        this_tool_calls = messages[-1].tool_calls
        count = 0

        # No tool calls (Final answer)
        if len(this_tool_calls) == 0:
            return False

        for msg in reversed(messages[:-1]):
            if msg.type != "ai":
                continue
            if len(msg.tool_calls) == 0:
                break
            
            prev_tool_calls = msg.tool_calls
            prev_tool_calls = [{"name": tool_call["name"], "args": tool_call["args"]} for tool_call in prev_tool_calls]    
    
            # Check if the tool calls are repeated
            repeated = True
            for tool_call in this_tool_calls:
                tool = tool_call["name"]
                args = tool_call["args"]
                if not any(tool == prev_tool_call["name"] and args == prev_tool_call["args"] for prev_tool_call in prev_tool_calls):
                    repeated = False
                    break
            for tool_call in prev_tool_calls:
                tool = tool_call["name"]
                args = tool_call["args"]
                if not any(tool == this_tool_call["name"] and args == this_tool_call["args"] for this_tool_call in this_tool_calls):
                    repeated = False
                    break

            if repeated:
                count += 1

            if count >= max_repeats:
                return True     
        return False

    def infinite_loop_check(state, agent):
        """
        Check if the tool calls are repeated in the previous tool calls
        If an infinite loop is detected, add a system message and invoke the agent again.
        Repeat this process at most MAX_RETRY_COUNT times.
        Return True if the infinite loop is broken, False otherwise.
        """
        MAX_RETRY_COUNT = 1
        retry_count = 0
        
        while detect_infinite_loop(state["messages"]):
            if retry_count >= MAX_RETRY_COUNT:
                return False

            # Add a system message to instruct the agent to try different tool call.
            print_debug("Infinite loop detected:")
            print_debug(state)

            # Pop previous call and add a system message to instruct the agent to use other tools
            state["messages"].pop() # Remove the last ai tool call
            tool_call_prompt = "Do not repeat the previous tool(s) because the agent will shut down. "
            if state.get("proxies"):
                tool_call_prompt = tool_call_prompt + f"Or, use the proxy(s): {', '.join([proxy['proxy'] for proxy in state['proxies']])}."

            if isinstance(llm, ChatGoogleGenerativeAI):
                state["messages"] = add_messages(state["messages"], [HumanMessage(content=tool_call_prompt)])
            else:
                state["messages"] = add_messages(state["messages"], [SystemMessage(content=tool_call_prompt)])

            # Invoke the agent again
            result = agent.invoke({"messages": state["messages"]})
            result = AIMessage(**result.dict(exclude={"type", "name", "additional_kwargs"}), name="trusted")

            # If Claude's output returns a list of content blocks as the result, take the first one with type "text"
            if isinstance(result.content, list):
                for content_block in result.content:
                    if content_block["type"] == "text":
                        result.content = content_block["text"]
                        break
                else: # If no text block is found, remove the content
                    result.content = ""
            
            state["messages"] = add_messages(state["messages"], [result])
            
            if state["messages"][-1].tool_calls:
                retry_count += 1
            else: # Final answer (no tool call).
                state["messages"][-1] = replace_proxies_in_message(state, state["messages"][-1])
                return True
        return True

    def generate_untrusted_agent_prompt(state, call_idx):
        """
        Generate a query prompt for the untrusted agent.
        Return True if the query prompt is generated successfully, False otherwise.
        """
        _, tool_messages = get_tool_messages(state["messages"])
        num_tool_calls = len(tool_messages)
        ai_call_message = None
    
        saved_tool_results = None
        if call_idx >= 0: # Single or combined tool call
            tool_message = tool_messages[call_idx]
            assert trustworthiness_check(state, call_idx) == False

            saved_tool_results = [copy.deepcopy(tool_message)]
            tool_message.content = ""
            query_generation_messages = copy.deepcopy(state["messages"])
            ai_call_message, _ = get_tool_messages(query_generation_messages)
            ai_call_message.tool_calls = copy.deepcopy(ai_call_message.tool_calls)
            
            tool_name = ai_call_message.tool_calls[call_idx]["name"]
            tool_args = ai_call_message.tool_calls[call_idx]["args"]

            # Remove unprocessed tool calls and tool results
            trim_num = num_tool_calls - call_idx - 1
            ai_call_message.tool_calls = ai_call_message.tool_calls[:-trim_num] if trim_num > 0 else ai_call_message.tool_calls
            query_generation_messages = query_generation_messages[:-trim_num] if trim_num > 0 else query_generation_messages
            
            # Add tool description of this tool
            tool_description = ""
            for tool in tools:
                if tool.name == tool_name:
                    tool_description = tool.description
                    break
            tool_calls = f"{tool_name}({tool_args}): {tool_description}"
            
            query_prompt, format = generate_query(llm, {"messages": query_generation_messages}, tool_calls, tools, untrusted_agent_tools)

            original_call_message, _  = get_tool_messages(state["messages"])
            
            original_call_message.tool_calls[call_idx]["query"] = format

            # Leave only the tool call that needs to be processed
            for tool_call in ai_call_message.tool_calls:
                if tool_call["id"] == tool_message.tool_call_id:
                    ai_call_message.tool_calls = [tool_call]

        else: # Iterative tool call
            assert trustworthiness_check(state, -1) == False
            saved_tool_results = copy.deepcopy(tool_messages)
            for tool_message in tool_messages:
                tool_message.content = "see the last tool message"
            query_generation_messages = copy.deepcopy(state["messages"])
            ai_call_message, _ = get_tool_messages(query_generation_messages)
            ai_call_message.tool_calls = copy.deepcopy(ai_call_message.tool_calls)

            tool_name_list = [tool_call["name"] for tool_call in ai_call_message.tool_calls]
            tool_args_list = [tool_call["args"] for tool_call in ai_call_message.tool_calls]
            tool_calls = ", ".join([f"{tool_name}({tool_args})" for tool_name, tool_args in zip(tool_name_list, tool_args_list)])

            # Generate query prompt
            query_prompt, format = generate_query(llm, {"messages": query_generation_messages}, tool_calls, tools, untrusted_agent_tools)
            
            # Extract corresponding AI message in the copied messages
            original_call_message, _ = get_tool_messages(state["messages"])
            original_call_message.tool_calls[-1]["query"] = format
        
        if isinstance(format, str) and format.startswith("PFI FAILED:"):
            return False
        
        # Initialize Untrusted context with the query prompt and the tool call
        state["sub_messages"] = add_messages(add_messages([query_prompt], [ai_call_message]), saved_tool_results)

        # Unseal proxies in tool call message before passing it to untrusted agent
        state["sub_messages"][1] = replace_proxies_in_message(state, state["sub_messages"][1])

        return True

    def spawn_untrusted_agent(state):
        print_debug("================================ Trusted -> Untrusted ================================")
        print_debug(state)

        # Agent switch
        state["current_agent"] = "untrusted"
        state["messages"], state["sub_messages"] = state["sub_messages"], state["messages"]

    def get_result_type(state, call_idx):
        _, tool_messages = get_tool_messages(state["messages"])
        if call_idx == -1:
            call_idx = 0
        tool_message = tool_messages[call_idx]
        principal = tool_message.additional_kwargs.get("principal", "Untrusted")
        if isinstance(principal, list):
            return "list"
        elif isinstance(principal, dict):
            return "dict"
        else:
            return "single"    

    # TODO(REFACTOR): comments
    def separate_tool_results(messages, call_idx):
        ai_tool_call, tool_messages = get_tool_messages(messages)
        if call_idx == -1:
            # for tool_message in tool_messages:
            #     metadata = {
            #         "submessage_index": -1,
            #         "attr": tool_message.additional_kwargs.get("attr", None),
            #         "principal": tool_message.additional_kwargs.get("principal", None),
            #     }
            #     sealed = seal(tool_message.content, "pfi_list", state, config.sealing_option, metadata)
            #     tool_message.content = f"PFI SEALED: {sealed}"
            pass
        else:
            tool_call = ai_tool_call.tool_calls[call_idx]
            tool_message = tool_messages[call_idx]
            
            # Copy the tool call and tool message for trusted list element
            call_copy = copy.deepcopy(tool_call)
            call_copy["id"] = call_copy["id"]+"_trusted"
            ai_tool_call.tool_calls.insert(call_idx+1, call_copy)
            message_copy = copy.deepcopy(tool_message)
            message_copy.id = message_copy.id+"_trusted"
            message_copy.tool_call_id = message_copy.tool_call_id+"_trusted"
            tool_call["id"] = tool_call["id"]+"_untrusted"
            tool_message.id = tool_message.id+"_untrusted"
            tool_message.tool_call_id = tool_message.tool_call_id+"_untrusted"

            # Leave only untrusted data in the original tool message
            list_data = ast.literal_eval(tool_message.content)
            new_list_data = []
            new_attr = []
            new_principal = []
            principal = tool_message.additional_kwargs["principal"]
            attr = tool_message.additional_kwargs["attr"]
            for idx, elem in enumerate(list_data):
                if principal[idx] == "Untrusted":
                    new_list_data.append(elem)
                    new_attr.append(attr[idx])
                    new_principal.append(principal[idx])
        
            tool_message.content = str(new_list_data)
            tool_message.additional_kwargs["attr"] = new_attr
            tool_message.additional_kwargs["principal"] = new_principal    

            # Leave only trusted data from the copied tool message
            list_data = ast.literal_eval(message_copy.content)
            new_list_data = []
            new_attr = []
            new_principal = []
            principal = message_copy.additional_kwargs["principal"]
            attr = message_copy.additional_kwargs["attr"]
            for idx, elem in enumerate(list_data):
                if principal[idx] == "Trusted":
                    new_list_data.append(elem)
                    new_attr.append(attr[idx])
                    new_principal.append(principal[idx])
            message_copy.content = str(new_list_data)
            message_copy.additional_kwargs["attr"] = new_attr
            message_copy.additional_kwargs["principal"] = new_principal

            # insert the copied tool message at call_idx+1
            insert_idx = -1
            for idx, message in enumerate(messages):
                if message.id == tool_message.id:
                    insert_idx = idx
                    break
            messages.insert(insert_idx+1, message_copy) 
    
    def combine_tool_results(messages, untrusted_call_idx):
        """
        Combine the trusted and untrusted tool results.
        """
        ai_tool_call, tool_messages = get_tool_messages(messages)
        untrusted_tool_call = ai_tool_call.tool_calls[untrusted_call_idx]
        untrusted_tool_message = tool_messages[untrusted_call_idx]
        trusted_tool_message = tool_messages[untrusted_call_idx+1]

        # Combine tool calls
        untrusted_tool_call["id"] = untrusted_tool_call["id"].replace("_untrusted", "")

        # Combine tool messages
        untrusted_tool_message.id = untrusted_tool_message.id.replace("_untrusted", "")
        untrusted_tool_message.tool_call_id = untrusted_tool_message.tool_call_id.replace("_untrusted", "")
        untrusted_tool_message.content = trusted_tool_message.content +" and "+ untrusted_tool_message.content
        untrusted_tool_message.additional_kwargs["attr"] += trusted_tool_message.additional_kwargs["attr"]
        untrusted_tool_message.additional_kwargs["principal"] += trusted_tool_message.additional_kwargs["principal"]

    def trusted_node(state):
        state["current_agent"] = "trusted"
        last_message = state["messages"][-1]

        if last_message.type == "tool":
            # Retrieve tool messages
            ai_tool_call, tool_messages = get_tool_messages(state["messages"])

            # Determine if the tool calls are iterative (same tool called multiple times)
            unique_tool_names = {msg.name for msg in tool_messages}
            is_single_tool_call = len(tool_messages) == 1
            is_iterative_tool_call = len(unique_tool_names) == 1 and len(tool_messages) > 1
            is_combined_tool_call = len(unique_tool_names) > 1 and len(tool_messages) > 1

            if is_single_tool_call:
                call_idx = 0
                if trustworthiness_check(state, call_idx) == False:
                    if get_result_type(state, call_idx) == "list":
                        separate_tool_results(state["messages"], call_idx)

                    # Switch to untrusted agent.
                    if generate_untrusted_agent_prompt(state, call_idx) == False: # Failed to generate a query
                        state["messages"] = add_messages(state["messages"], [AIMessage(content="Failed to generate a query. Exiting the graph.")])
                        return state
                    spawn_untrusted_agent(state)
                    return state
            elif is_combined_tool_call:
                for call_idx, tool_message in enumerate(tool_messages):
                    if trustworthiness_check(state, call_idx) == False:
                        if get_result_type(state, call_idx) == "list":
                            separate_tool_results(state["messages"], call_idx)

                        # Switch to untrusted agent.
                        if generate_untrusted_agent_prompt(state, call_idx) == False: # Failed to generate a query
                            state["messages"] = add_messages(state["messages"], [AIMessage(content="Failed to generate a query. Exiting the graph.")])
                            return state
                        spawn_untrusted_agent(state)
                        return state
            elif is_iterative_tool_call: # Iterative tool call
                # JH: TODO: Separate into trusted and untrusted on list/dict result
                if trustworthiness_check(state, -1) == False:
                    # Switch to untrusted agent.
                    if generate_untrusted_agent_prompt(state, -1) == False: # Failed to generate a query
                        state["messages"] = add_messages(state["messages"], [AIMessage(content="Failed to generate a query. Exiting the graph.")])
                        return state
                    spawn_untrusted_agent(state)
                    return state

            # Do not switch to untrusted agent.
            for tool_message in tool_messages:
                strip_pfi_prefix(tool_message, state)
        
            remove_idx = []
            for idx, tool_message in enumerate(tool_messages):
                if tool_message.tool_call_id.endswith("_untrusted"):
                    combine_tool_results(state["messages"], idx)
                    remove_idx.append(idx+1) # Remove the trusted tool message
            for idx in reversed(remove_idx):
                ai_tool_call.tool_calls.remove(ai_tool_call.tool_calls[idx])
                state["messages"].remove(tool_messages[idx])
        
        print_debug("================================ Trusted Agent ================================")

        # Run LLM inference 
        result = trusted_agent.invoke({"messages": state["messages"]})
        result = AIMessage(**result.dict(exclude={"type", "name", "additional_kwargs"}), name="trusted")

        # If Claude's output returns a list of content blocks as the result, take the first one with type "text"
        if isinstance(result.content, list):
            for content_block in result.content:
                if content_block["type"] == "text":
                    result.content = content_block["text"]
                    break
            else: # If no text block is found, remove the content
                result.content = ""
            
        state["messages"] = add_messages(state["messages"], [result])

        print_debug(state)

        if not result.tool_calls:
            # Final answer (no tool call).
            return state

        # Tool call(s)
        if infinite_loop_check(state, trusted_agent) == False:
            # Failed to break the infinite loop
            state["messages"]= add_messages(state["messages"], [AIMessage(content="Failed to break the infinite loop. Exiting the graph.")])
            return state

        # Misc sanity checks
        for tool_call in result.tool_calls:
            if tool_call["name"] == "conditional_prompt":
                is_error = False
                condition = tool_call["args"].get("condition", None)
                if condition is None or not isinstance(condition, Union[list,str]):
                    is_error = True
                else:
                    # Error if no proxy is used in the condition
                    if isinstance(condition, list):
                        if all([not isinstance(cond, str) or not cond.startswith(PROXY) for cond in condition]):
                            is_error = True
                if is_error:
                    tool_call["args"]["error"] = "Invalid condition. Use proxy or list of proxies in the condition."
    
        return state

    def untrusted_node(state):
        print_debug("================================ Untrusted Agent ================================")
        print_debug(state)
        query = get_query(state["messages"])
        # JH: TODO: Move this to Trusted->Untrusted switch

        last_message = state["messages"][-1]
        if last_message.type == "tool":
            if "return_query_result" in last_message.name:

                print_debug("================================ Untrusted -> Trusted ================================")
                # Untrusted agent finished the query. 
                # Get the tool call id of the corresponding untrusted result tool from trusted agent
                tool_call_id = state["messages"][1].tool_calls[-1]["id"]
                
                untrusted_res_tool_message = None # Tool message with corresponding tool call id
                _, tool_messages = get_tool_messages(state["sub_messages"])
                
                for idx, message in enumerate(tool_messages):
                    if message.tool_call_id == tool_call_id:
                        untrusted_res_tool_message = message
                        break
                if untrusted_res_tool_message is None:
                    raise Exception("Tool message not found")
                
                final_answer_call = state["messages"][-2]
                final_answer_result = state["messages"][-1]
                query_result = None

                try:
                    # Get final result of the untrusted agent
                    query_result = get_result(final_answer_call, query)
                    metadata={
                        "submessage_index": len(state.get("archived_submessages", [])),
                        "attr": final_answer_result.additional_kwargs.get("attr", "Unknown"),
                        "principal": final_answer_result.additional_kwargs.get("principal", "Untrusted"),
                    }
                    # Seal the result
                    untrusted_sealed = seal(query_result, query, state, metadata)
                    
                    # Seal the corresponding tool message in trusted agent's messages
                    untrusted_res_tool_message.content = f"PFI SEALED: {untrusted_sealed}"
                except Exception as e:
                    if str(e) == "PFI FAILED: Query failed":
                        error_message = "PFI FAILED: Failed to accomplish the query. Try again with a different tool or different arguments."
                        untrusted_res_tool_message.content = error_message
                    elif str(e) == "PFI FAILED: Result validation failed":
                        error_message = "PFI FAILED: The untrusted agent returned an invalid result."
                        untrusted_res_tool_message.content = error_message
                    else:
                        error_message = "PFI FAILED: An error occurred while processing the result."
                        untrusted_res_tool_message.content = error_message
                        
                # If the output format was prompt, ask for user's permission to return the result to trusted agent
                if query_result and not untrusted_res_tool_message.content.startswith("PFI FAILED:"):
                    prompt_values = extract_prompt_values(query, query_result)
                    if prompt_values:
                        unsafe_dataflow_warning = UnsafeDataflowWarning(
                            data_flow_type = "Explicit control flow",
                            proxy_value = prompt_values,
                            submessage_index=metadata["submessage_index"],
                            data_attribute=metadata["attr"],
                            data_sink = {"type": "trusted_agent_context"},
                        )
                            
                        # Save the unsafe dataflow warnings in the state
                        state.setdefault("unsafe_dataflow_warnings", []).append(unsafe_dataflow_warning)
                    
                        print(unsafe_dataflow_warning)
                        if config.unsafe_dataflow_choice == "UNSAFE_DATAFLOW_YES" or config.unsafe_dataflow_choice == "UNSAFE_DATAFLOW_AUTO":
                            print("Continuing the agent execution.")
                        elif config.unsafe_dataflow_choice == "UNSAFE_DATAFLOW_NO":
                            print("Exiting the graph.")
                            raise NodeInterrupt("User has chosen not to return the query to the trusted agent.")
                        else: # config.unsafe_dataflow_choice == "UNSAFE_DATAFLOW_HUMAN"
                            print("Do you want to continue? (y/n)")
                            user_input = input().strip().lower()
                            if user_input != "y":
                                raise NodeInterrupt("User has chosen not to return the query to the trusted agent.")
                else:
                    # No need to ask for permission if the query failed
                    pass
                                
                # Agent switch
                state["current_agent"] = "trusted"
                state["messages"], state["sub_messages"] = state["sub_messages"], state["messages"]
                state.setdefault("archived_submessages", []).append(state["sub_messages"])
                state["sub_messages"] = [] # Clear stale messages from Untrusted agent
                if hasattr(untrusted_node, "untrusted_agent"):
                    del untrusted_node.untrusted_agent # Clear the untrusted_agent attribute
                
                print_debug(state)
                return state
        
        untrusted_agent = getattr(untrusted_node, 'untrusted_agent', None)
        if untrusted_agent is None:
            untrusted_agent = create_agent(
                llm,
                untrusted_agent_tools + [return_query_result],
                system_message=untrusted_agent_prompt,
                tool_call_only=True,
                parallel_tool_calls=False,
            )
            untrusted_node.untrusted_agent = untrusted_agent

        retry_count = 0
        MAX_RETRY_COUNT = 1
        while retry_count < MAX_RETRY_COUNT:
            result = untrusted_agent.invoke({"messages":state["messages"]})
            result = AIMessage(**result.dict(exclude={"type", "name", "additional_kwargs"}), name="untrusted")
        
            # If Claude's output returns a list of content blocks as the result, take the first one with type "text"
            if isinstance(result.content, list):
                for content_block in result.content:
                    if content_block["type"] == "text":
                        result.content = content_block["text"]
                        break
                else: # If no text block is found, remove the content
                    result.content = ""
 
            # Check if the untrusted agent has called a tool that is only binded to trusted agent
            # (LLMs sometimes call tools that are not binded to itself due to hallucination)
            retry = False
            if result.tool_calls:
                for tool_call in result.tool_calls:
                    if get_tool_priv(tool_call["name"]) == "trusted":
                        retry = True
                        state["messages"] = add_messages(state["messages"], [result])
                        state["messages"] = add_messages(state["messages"], [ToolMessage(content="Permission denied. You are not allowed to call that tool. Try different tool.", tool_call_id=tool_call["id"], name=f"{tool_call['name']}")])
            
            if retry:
                retry_count += 1
            else:
                break
               
        if retry_count == MAX_RETRY_COUNT and retry:
            state["messages"] = add_messages(state["messages"], [AIMessage(content="", tool_calls=[{"name": "return_query_result", "args": {"query_succeeded": False, "result": ""}, "id": "toolu_012345asdf", "type": "tool_call"}])])
            return state
            
        state["messages"] = add_messages(state["messages"], [result])
        print_debug(state)
        
        return state

    def format_final_answer(tool_call):
        """ Format untrusted agent's final answer. """
        args = tool_call["args"]
        if args.get("query_succeeded") is None:
            args["query_succeeded"] = False
        if args.get("result") is None:
            args["result"] = ""
        return tool_call
    
    def format_final_answer_attr(result_obj, state):
        """
        Add attribute to the final answer.
        The attributes are aggregated from every tool call in current untrusted agent context.
        """
        attrs = []
        for message in state["messages"]:
            if message.type == "tool" and message.additional_kwargs is not None:
                attr = message.additional_kwargs.get("attr", "Unknown")
                if isinstance(attr, str):
                    if attr not in attrs:
                        attrs.append(attr)
                elif isinstance(attr, list):
                    for elem in attr:
                        if elem not in attrs:
                            attrs.append(elem)
                elif isinstance(attr, dict):
                    for key, value in attr.items():
                        if value not in attrs:
                            attrs.append(value)

        result_obj.set_attr(";".join(attrs))
        return result_obj

    # TODO(REFACTOR): Is this function used?
    def propagate_transparent_attr(result_obj, tool_call, state):
        attr = result_obj.get_attr()
        has_transparent_attr = False
        if isinstance(attr, str) and attr == "Transparent":
            has_transparent_attr = True
        if isinstance(attr, list) and "Transparent" in attr:
            has_transparent_attr = True
        if isinstance(attr, dict) and "Transparent" in attr.values():
            has_transparent_attr = True
        
        if has_transparent_attr:        
            for key, value in tool_call["args"].items():
                extracted_proxies = extract_proxies(value, state)
        else:
            return

        if isinstance(attr, str):
            attrs = result_obj.attr.split(";")
            for proxy in extracted_proxies:
                if proxy["attr"] not in attrs:
                    attrs.append(proxy["attr"])
            attr = ";".join(attrs)
        if isinstance(attr, list):
            for idx, elem in enumerate(attr):
                attrs = elem.split(";")
                for proxy in extracted_proxies:
                    if proxy["attr"] not in attrs:
                        attrs.append(proxy["attr"])
                attr[idx] = ";".join(attrs)
        if isinstance(attr, dict):
            for key, value in attr.items():
                attrs = value.split(";")
                for proxy in extracted_proxies:
                    if proxy["attr"] not in attrs:
                        attrs.append(proxy["attr"])
                attr[key] = ";".join(attrs)

        result_obj.set_attr(attr)
        return

    def tool_node(state):
        all_tools = tools + [return_query_result, conditional_prompt]
        tool_node = ToolNode(all_tools)

        # If parallel tool call is disabled, remove all tool calls except the first one (For Gemini)
        if not parallel_tool_calls:
            ai_tool_call, _ = get_tool_messages(state["messages"])
            ai_tool_call.tool_calls = ai_tool_call.tool_calls[:1]

        # Replace proxies with their values in the tool call
        original_messages = state["messages"].copy()
        replace_proxies_in_messages(state, AIMessage)
        ai_tool_call, _ = get_tool_messages(state["messages"])
        original_tool_call, _ = get_tool_messages(original_messages)

        # Invoke tools in a separate state for hooks and error handling
        tool_calls = []
        tool_errors = []

        # pre-tool hooks
        for tool_call in ai_tool_call.tool_calls:
            if tool_call["name"] == "return_query_result":
                tool_call = format_final_answer(tool_call)
                tool_calls.append(tool_call)
            elif tool_call["args"].get("error") is not None:
                # Invalid condition error message for conditional_prompt
                tool_call["args"].pop("error")
                tool_errors.append(ToolMessage(content="PFI FAILED: Invalid condition. ", tool_call_id=tool_call["id"], name=tool_call["name"]))
            elif tool_call["name"] == "bash_tool" or tool_call["name"] == "bash_tool_u":
                # AgentBench OS - put current agent as the second argument for bash tool
                tool_call["args"]["current_agent"] = state["current_agent"]
                tool_calls.append(tool_call)
            else:
                tool_calls.append(tool_call)
            
        tool_state = copy.deepcopy(state)
        tool_call_message = copy.deepcopy(ai_tool_call)
        tool_call_message.tool_calls = tool_calls
        tool_state["messages"] = [tool_call_message]
        tool_result = tool_node.invoke(tool_state)["messages"]
        tool_result.extend(tool_errors)

        # post-tool hooks
        for tool_call in ai_tool_call.tool_calls:
            if tool_call["name"] == "bash_tool" or tool_call["name"] == "bash_tool_u":
                del tool_call["args"]["current_agent"]

        for message in tool_result:
            if message.name == "conditional_prompt":
                if state.get("proxies"):
                    seal_message(message, state["proxies"])
    
        # Sort tool_result as the order of tool calls in the last AI message
        sorted_tool_result = []
        for tool_call in original_tool_call.tool_calls:
            for message in tool_result:
                if message.tool_call_id == tool_call["id"]:
                    # Deserialize the plugin result to PFIPluginResult object
                    pfi_data = deserialize_plugin_result(message.content)
                    message.content = pfi_data.print()

                    propagate_transparent_attr(pfi_data, tool_call, state)

                    if tool_call["name"] == "return_query_result":
                        pfi_data = format_final_answer_attr(pfi_data, state)

                    # Update principal
                    attr = pfi_data.get_attr()
                    principal = evaluate_principal(attr)
                    pfi_data.set_principal(principal)
                    
                    if message.additional_kwargs is None:
                        message.additional_kwargs = {}
                    message.additional_kwargs["attr"] = pfi_data.get_attr()
                    message.additional_kwargs["principal"] = pfi_data.get_principal()
                    
                    sorted_tool_result.append(message)
                    break
        
        # Revert the proxies in the tool call
        state["messages"] = add_messages(original_messages, sorted_tool_result)
        
        return state

    def extract_proxies(value, state):
        """Get the proxies from the value."""
        extracted_proxy_strings = re.findall(rf"{re.escape(PROXY)}\d+", str(value))
        extracted_proxies = []
        if state.get("proxies") is None:
            return extracted_proxies
        for proxy_dict in state["proxies"]:
            for proxy_string in extracted_proxy_strings:
                if proxy_dict["proxy"] == proxy_string:
                    extracted_proxies.append(proxy_dict)
        return extracted_proxies

    def unsafe_dataflow_node(state):
        # Find the tool call with unsafe dataflow
        last_message = state["messages"][-1]
        tool_calls = last_message.tool_calls
        unsafe_dataflow_warnings: List[UnsafeDataflowWarning] = []
        
        # Create unsafe dataflow warnings
        if len(tool_calls) == 0 and PROXY in last_message.content:
            # proxy is used in the final answer
            proxies_with_positions = extract_proxies_with_positions(state, last_message, untrusted_agent_tools)
            proxies_list = []
            
            for proxy_with_position in proxies_with_positions:
                proxies_list.append(proxy_with_position["proxy"])
                
            if len(proxies_list) > 0:
                unsafe_dataflow_warnings.append(UnsafeDataflowWarning(
                    data_flow_type="Explicit data flow",
                    proxy_value = [proxy["value"] for proxy in proxies_list],
                    submessage_index = [proxy["submessage_index"] for proxy in proxies_list],
                    data_attribute= [proxy["attr"] for proxy in proxies_list],
                    data_sink={"type": "content"},
                ))
        else:
            proxies_with_positions = extract_proxies_with_positions(state, last_message, untrusted_agent_tools)
            for proxies_with_positions in proxies_with_positions:
                proxies = proxies_with_positions["proxy"]
                position = proxies_with_positions["position"]
                
                warning = UnsafeDataflowWarning(
                    data_flow_type="Explicit data flow" if position.get("tool_name", "") != "conditional_prompt" else "Implicit flow",
                    proxy_value = [proxy["value"] for proxy in proxies],
                    submessage_index = [proxy["submessage_index"] for proxy in proxies],
                    data_attribute= [proxy["attr"] for proxy in proxies],
                    data_sink = position,
                    args=position["arg_name"],
                )
                
                unsafe_dataflow_warnings.append(warning)

        # Save the unsafe dataflow warnings in the state
        for warning in unsafe_dataflow_warnings:
            state.setdefault("unsafe_dataflow_warnings", []).append(warning)

        # Print unsafe dataflow warning message
        if config.unsafe_dataflow_choice == "UNSAFE_DATAFLOW_YES":
            for warning in unsafe_dataflow_warnings:
                print(warning)
                print("Continuing the agent execution.")
                
            if len(tool_calls) == 0:
                # Replace the proxies in the final answer
                state["messages"][-1] = replace_proxies_in_message(state, state["messages"][-1], is_final_answer=True)
                
            return state
        elif config.unsafe_dataflow_choice == "UNSAFE_DATAFLOW_NO":
            for warning in unsafe_dataflow_warnings:
                print(warning)
                print("Exiting the graph.")
            raise NodeInterrupt("Unsafe data flow detected. Exiting the graph.")
        else: # config.unsafe_dataflow_choice == "UNSAFE_DATAFLOW_HUMAN"
            for warning in unsafe_dataflow_warnings:
                print(warning)
                print("Do you want to continue? (y/n)")
                user_input = input().strip().lower()
                if user_input != "y":
                    raise NodeInterrupt("Unsafe data flow detected. Exiting the graph.")
            
            if len(tool_calls) == 0:
                # Replace the proxies in the final answer
                state["messages"][-1] = replace_proxies_in_message(state, state["messages"][-1], is_final_answer=True)
                
            return state

    load_configs()

    # Disable parallel tool calls for gemini-1.5-pro-002
    if isinstance(llm, ChatGoogleGenerativeAI):
        parallel_tool_calls = False
    
    trusted_agent = create_agent(
        llm,
        trusted_agent_tools,
        system_message=trusted_agent_prompt,
        tool_call_only=False,
        parallel_tool_calls=parallel_tool_calls,
    )
    initialize_condition_llm(llm)

    workflow = StateGraph(AgentState)
    workflow.add_node("trusted_node", trusted_node)
    workflow.add_node("untrusted_node", untrusted_node)
    workflow.add_node("tool_node", tool_node)
    workflow.add_node("unsafe_dataflow_node", unsafe_dataflow_node)

    # TODO(REFACTOR): Simplify this part?
    # The router functions (Caution: router functions cannot modify the state)
    def trusted_node_router(state):
        last_message = state["messages"][-1]
        if last_message.type == "ai":
            if len(last_message.tool_calls) > 0:
                # Trusted agent called a tool.
                unsafe_dataflow = False
                if state.get("proxies"):
                    for tool_call in last_message.tool_calls:
                        if flow_check(tool_call):
                            unsafe_dataflow = True
                            break
                    
                if unsafe_dataflow:
                    return "unsafe_dataflow_node"
                else:
                    return "tool_node"
            else:
                # Final answer (no tool call). End the agent.
                if flow_check(last_message):
                    return "unsafe_dataflow_node"
                else:
                    return "__end__"
        elif last_message.type == "tool":
            # If tool result is untrusted, switch to untrusted agent.
            if state["current_agent"] == "untrusted":
                    return "untrusted_node"
            else:
                return "trusted_node"
        else:
            raise Exception("Invalid message type")

    def untrusted_node_router(state):
        # If untrusted agent called a tool, go to tool_node. Else, go to trusted
        if hasattr(state["messages"][-1], "tool_calls"):
            if len(state["messages"][-1].tool_calls) > 0:
                return "tool_node"
        return "trusted_node"
        
    def tool_node_router(state):
        if state["current_agent"] == "untrusted":
            return "untrusted_node"
        else:
            return "trusted_node"

    def unsafe_dataflow_router(state):
        if hasattr(state["messages"][-1], "tool_calls") and len(state["messages"][-1].tool_calls) == 0:
            return "__end__"
        return "tool_node"
       
    workflow.add_conditional_edges(
        "trusted_node",
        trusted_node_router,
        {
            "tool_node": "tool_node",
            "untrusted_node": "untrusted_node",    
            "unsafe_dataflow_node": "unsafe_dataflow_node",
            "__end__": END
        },
    )
    workflow.add_conditional_edges(
        "untrusted_node",
        untrusted_node_router,
        {"tool_node": "tool_node", "trusted_node": "trusted_node"},
    )
    workflow.add_conditional_edges(
        "tool_node",
        tool_node_router,
        {"trusted_node": "trusted_node", "untrusted_node": "untrusted_node"},
    )
    workflow.add_conditional_edges(
        "unsafe_dataflow_node", 
        unsafe_dataflow_router,
        {"tool_node": "tool_node", "__end__": END}
    )
    workflow.add_edge(START, "trusted_node")

    graph = workflow.compile()
    
    return graph