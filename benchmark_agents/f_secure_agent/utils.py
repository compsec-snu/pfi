import json
import copy
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    ToolMessage,
    SystemMessage,
)
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.constants import Interrupt
from config import config
from typing import List
from pydantic import BaseModel, Field

def serialize(obj):
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
            "tool_call_id": obj.tool_call_id,
            "kwargs": obj.additional_kwargs,
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
    raise TypeError(f"Type {type(obj)} not serializable")

def get_tool_messages(messages):
    """
    Retrieve tool messages from the end of the messages list.
    
    Returns:
        - ai_message: AI message that contains the tool calls
        - tool_messages: List of tool messages
    """
    ai_message = None
    tool_messages = []
    for message in reversed(messages):
        if message.type == "tool":
            tool_messages.append(message)
        elif message.type == "ai":
            ai_message = message
            break
    tool_messages.reverse()
    return ai_message, tool_messages

def print_state(state):
    state_copy = copy.deepcopy(state)
    # remove sub_messages
    state_copy.pop("sub_messages", None)
    if state["current_agent"] == "untrusted":
        state_copy.pop("proxies", None)
    
    print(json.dumps(state_copy, indent=2, default=serialize))

def truncate_message(message, max_length=500):
    message = str(message)
    if len(message) > max_length:
        return message[:max_length] + "..."
    return message

def print_benchmark(message):
    if isinstance(message, HumanMessage):
        print("================================ Human Message =================================")
        print(truncate_message(message.content), "\n")
    elif isinstance(message, AIMessage):
        # print(message)
        print("================================== AI Message ==================================")
        print(f"Name: {message.name}")
        if message.content:
            print(truncate_message(message.content), "\n")
        if message.tool_calls:
            print("Tool Call:")
            for tool_call in message.tool_calls:
                print(f"Tool: {tool_call['name']}, Args: {tool_call['args']}", "\n")
    elif isinstance(message, ToolMessage):
        message.pretty_print()
    elif isinstance(message, SystemMessage):
        print("================================ System Message ================================")
        print(truncate_message(message.content), "\n")

def print_debug(message):
    if config.log_level == "DEBUG":
        if isinstance(message, dict):
            print_state(message)
        elif isinstance(message, (HumanMessage, AIMessage, ToolMessage, SystemMessage)):
            print(json.dumps(message, indent=2, default=serialize))
        else:
            print(message)

def print_stream(stream):
    for s in stream:
        message = s["messages"][-1]
        if config.log_level == "BASIC" or config.log_level == "DEBUG":
            if isinstance(message, tuple):
                print(message)
            else:
                if isinstance(message, ToolMessage) and s.get("current_agent", None) == "trusted":
                    continue # Don't print duplicated tool message
                message.pretty_print()

def store_and_print_stream(stream, stream_list, agent_switch_callback = None):
    """
    This function is deprecated. Use process_stream instead.
    """
    for s in stream:
        message = s["messages"][-1]
        stream_list.append(s)
        if agent_switch_callback and len(stream_list) > 2 and s["current_agent"] != stream_list[-2]["current_agent"]:
            if s["current_agent"] == "untrusted": # Trusted -> Untrusted
                print("================================ Switching to untrusted mode ================================")
                agent_switch_callback("untrusted")
            else:
                print("================================ Switching to trusted mode ================================")
                agent_switch_callback("trusted")
        
        if isinstance(message, tuple):
            print(message)
        else:
            if isinstance(message, ToolMessage) and s["current_agent"] == "trusted":
                continue # Don't print duplicated tool message
            print_benchmark(message)

def append_to_stream_list(stream, stream_list):
    """
    Append items from the stream to the stream_list.
    """
    for s in stream:
        stream_list.append(s)
        yield s

def detect_value_in_stream(stream, value_to_detect, last_checked_index):
    """
    Check if the specified value is detected in the stream messages.
    """
    new_messages = stream["messages"][last_checked_index:]
    for message in new_messages:
        if message.type == "tool" and value_to_detect in message.content:
            return True
    return False

def handle_agent_switch(s, stream_list, agent_switch_callback):
    """
    Handle agent switching logic and call the callback if needed.
    """
    current_agent = s.get("current_agent", "unknown")
    
    if len(stream_list) > 2:
        previous_agent = stream_list[-2].get("current_agent", "unknown")
        if current_agent != previous_agent:
            if s["current_agent"] == "untrusted":  # Trusted -> Untrusted
                print("================================ Switching to untrusted mode ================================")
                agent_switch_callback("untrusted")
            else:
                print("================================ Switching to trusted mode ================================")
                agent_switch_callback("trusted")

def print_stream_message(message, current_agent):
    """
    Print the message to the console.
    """
    if isinstance(message, tuple):
        print(message)
    elif not (isinstance(message, ToolMessage) and current_agent == "trusted"):
        print_benchmark(message)

def process_stream(stream, stream_list, agent_switch_callback=None, value_to_detect=None):
    """
    Process the stream: store it, detect values, handle agent switches, and print messages.
    """
    last_checked_index = 0

    for s in append_to_stream_list(stream, stream_list):
        # Detect value if specified
        if value_to_detect and detect_value_in_stream(s, value_to_detect, last_checked_index):
            return True
        
        # Handle agent switch
        if agent_switch_callback:
            handle_agent_switch(s, stream_list, agent_switch_callback)
        
        # Print the last message
        message = s["messages"][-1]
        current_agent = s.get("current_agent", "unknown")
        print_stream_message(message, current_agent)
        
        # Update last checked index
        last_checked_index = len(s["messages"])

    return False

def print_invoke(res, option="all"):
    if option == "result":
        message = res["messages"][-1]
        if isinstance(message, tuple):
            print(message)
        else:
            message.pretty_print()        
    elif option == "all":
        for m in res["messages"]:
            if isinstance(m, tuple):
                print(m)
            else:
                m.pretty_print()
class AttachmentItem(BaseModel):
    type: str = Field("file", description="The type of attachment, must be 'file'")
    file_id: int = Field(..., description="The unique identifier for the file")

class SendEmailInput(BaseModel): # Only for Gemini
    recipients: list[str]
    subject: str
    body: str
    attachments: List[AttachmentItem] = None
    cc: list[str] = None
    bcc: list[str] = None

class CondPromptInput(BaseModel):
    condition: List[str]
    prompts: List[str]
    code: str

def bind_tools(
    llm,
    tools, 
    enable_parallel_tool_calls:bool = False,
    tool_call_only:bool = False
):
    if isinstance(llm, ChatOpenAI):
        tool_choice = "required" if tool_call_only else "auto"
        parallel_tool_calls = enable_parallel_tool_calls
        return llm.bind_tools(tools, parallel_tool_calls=parallel_tool_calls, tool_choice=tool_choice)
    elif isinstance(llm, ChatAnthropic):
        tool_choice = {
            "type": "any" if tool_call_only else "auto",
            "disable_parallel_tool_use": not enable_parallel_tool_calls,
        }
        return llm.bind_tools(tools, tool_choice=tool_choice)
    elif isinstance(llm, ChatGoogleGenerativeAI):
        tool_choice = "any" if tool_call_only else "auto"

        for tool in tools:
            if tool.name == "send_email":
                tool.args_schema = SendEmailInput
        
        return llm.bind_tools(tools, tool_choice=tool_choice)
    else:
        raise ValueError("Invalid LLM type")
