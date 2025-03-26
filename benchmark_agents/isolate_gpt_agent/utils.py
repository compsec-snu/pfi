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

def append_to_stream_list(stream, stream_list):
    """
    Append items from the stream to the stream_list.
    """
    for s in stream:
        stream_list.append(s)
        yield s

def detect_value_in_stream(stream, value_to_detect):
    """
    Check if the specified value is detected in the stream messages.
    """
    for message in stream["messages"]:
        if message.type == "tool" and value_to_detect in message.content:
            return True
    return False

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

def print_stream_message(message):
    """
    Print the message to the console.
    """
    if isinstance(message, tuple):
        print(message)
    else:
        print_benchmark(message)

def process_stream(stream, stream_list, value_to_detect=None):
    """
    Process the stream: store it, detect values, and print messages.
    """
    for s in append_to_stream_list(stream, stream_list):
        if len(s["messages"]) == 0:
            continue
        
        # Detect value if specified
        if value_to_detect and detect_value_in_stream(s, value_to_detect):
            return True
        
        # Print the last message
        message = s["messages"][-1]
        current_agent = s.get("current_agent", "unknown")
        print_stream_message(message)

    return False
