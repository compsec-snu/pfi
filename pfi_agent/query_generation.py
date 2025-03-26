from typing import Union, Dict, Tuple, List
import json
import inspect
from langchain_core.messages import (
    SystemMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
    HumanMessage
)
from langgraph.graph.message import add_messages
from langgraph.errors import NodeInterrupt
from .utils import print_debug
from .prompts import QUERY_GENERATION_PROMPT, UNTRUSTED_AGENT_PROMPT
from langchain_anthropic import ChatAnthropic

FORMATS = {
  "bool": "True",
  "int": "123",
  "float": "123.45",
  "email": "example@email.com",
  "url": "https://www.example.com",
  "phone": "010-1234-5678",
  "date": "2024-12-01",
  "datetime": "2024-12-01 12:00",
  "time": "12:00",
  "prompt": "Do something",
  "string": "apple",
}

def validate_query(query) -> Tuple[Union[Dict, List], str]:
    if query.startswith("```json"):
        query = query[7:-3]
     
    query = query.strip() 
    json_start = min(
        (index for index in [query.find("{"), query.find("[")] if index != -1),
        default=-1
    )
    if json_start == -1:
        return None, "Error: Invalid JSON format. You should generate a query with valid JSON format."
    else:
        query = query[json_start:] # Remove the text before the JSON format

    try:
        query = json.loads(query)
    except Exception as e:
        print_debug(e)
        return None, "Error: Generate only a valid JSON object or array starting with '{' or '[', without any additional text or explanation."

    if not isinstance(query, dict):
        return None, "Error: Invalid JSON format."

    if list[query.keys()] == ['query']:
        if not isinstance(query['query'], dict):
            return None, "Error: Invalid JSON format."
        query = query['query']
    
    return validate_ast_format(query)

# Python dict or list of dict format
def validate_ast_format(query):
    error_msg = ""
    if isinstance(query, dict):
        if query == {}:
            error_msg = "Error: Empty dict format"
            return None, error_msg
        for key, value in query.items():
            value_format, error_msg = validate_ast_format(value)
            if value_format is None:
                return None, error_msg
            query[key] = value_format
    elif isinstance(query, list):
        if query == []:
            # error_msg = "Error: Empty list format"
            # return None, error_msg
            query.append("string")
        if len(query) != 1:
            error_msg = "Error: List format should contain one format (bool, int, float, email, url, phone, date, datetime, time, prompt, and string) or a nested type. "
            return None, error_msg
        elem_format = query[0]
        if isinstance(elem_format, dict):
            elem_format, error_msg = validate_ast_format(elem_format)
            if elem_format is None:
                return None, error_msg
            query[0] = elem_format
        elif isinstance(elem_format, str):
            elem_format, error_msg = validate_ast_format(elem_format)
            if elem_format is None:
                error_msg = f"Error: Invalid list value format: {query}. "
                return None, error_msg
            query[0] = elem_format
        else:
            error_msg = f"Error: Invalid list element format: {query}. "
            return None, error_msg
        return query, error_msg
    elif query in FORMATS:
        return query, error_msg
    else: # Invalid format
        # If the format is a value instead of format name, fix it to the format name
        if isinstance(query, bool):
            return "bool", error_msg
        elif isinstance(query, int):
            return "int", error_msg
        elif isinstance(query, float):
            return "float", error_msg
        elif isinstance(query, str):
            return "string", error_msg

        error_msg = f"Error: Invalid format: {query}"
        return None, error_msg
    return query, error_msg

def generate_query(llm, state, tool_calls, all_tools, untrusted_agent_tools):
    query_generator = llm
    
    messages = state["messages"]

    all_tool_descriptions = ""
    for tool in all_tools:
        all_tool_descriptions += f"{tool.name}("
        sig = inspect.signature(tool.func)
        all_tool_descriptions += ", ".join([f"{param}" for _, param in sig.parameters.items()])
        all_tool_descriptions += ")\n"

    query_generation_prompt = QUERY_GENERATION_PROMPT.format(
        tool_call=tool_calls,
        all_tool_descriptions=all_tool_descriptions,
        untrusted_agent_tools=", ".join([tool.name for tool in untrusted_agent_tools]),
    )
    query_generation_messages = add_messages(messages, [HumanMessage(content=query_generation_prompt)])
    
    # For ChatAnthropic, transform all AIMessages and ToolMessages into HumanMessages
    if isinstance(llm, ChatAnthropic):
        for idx, message in enumerate(query_generation_messages):
            if isinstance(message, AIMessage):
                ai_tool_calls = message.tool_calls
                content_with_tool_calls = message.content + "\n" + "\n".join([f"{tool_call}" for tool_call in ai_tool_calls])
                query_generation_messages[idx] = HumanMessage(content=content_with_tool_calls)
            elif isinstance(message, ToolMessage):
                tool_name = message.name
                tool_call_id = message.tool_call_id
                content_with_name_and_id = f"{message.content} \n Tool: {tool_name}, Tool Call ID: {tool_call_id}"
                query_generation_messages[idx] = HumanMessage(content=content_with_name_and_id)
            elif isinstance(message, SystemMessage):
                query_generation_messages[idx] = HumanMessage(content=message.content)
        
        query_generation_messages[-1] = SystemMessage(content=query_generation_prompt)
    
    query = None
    validated_format = None

    print_debug("============================== Generate Query ==============================")
    
    query_generation_count = 0
    MAX_QUERY_GENERATION = 2

    # Retry query generation if the dict format is invalid
    while True:
        print_debug("Query Generation Messages:")
        for message in query_generation_messages:
            print_debug(message)
        result = query_generator.invoke(query_generation_messages)
        query = result.content
        print_debug("Query Generation Result (before):")
        print_debug(f"Query: {query}")

        validated_format, error_msg = validate_query(query)
        
        if validated_format is None:
            error_msg = error_msg + " Please refer to Query Generation Prompt."
            print_debug(error_msg)
            
            query_generation_count += 1
            if query_generation_count >= MAX_QUERY_GENERATION:
                query = "PFI FAILED: Invalid dict format"
                break

            # Retry query generation
            error_msg = HumanMessage(content=error_msg)
            query_generation_messages = add_messages(query_generation_messages, [result, error_msg])
            continue
        else:
            print_debug("Query Generation Result:")
            print_debug(f"Query: {validated_format}")
            query = validated_format
            break

    if query is None:
        raise NodeInterrupt("Query generation failed.")

    untrusted_agent_prompt = UNTRUSTED_AGENT_PROMPT.format(result_format=validated_format)
    ret = HumanMessage(content=untrusted_agent_prompt)

    return ret, query