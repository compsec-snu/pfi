import re
import copy
import ast
import json
from langgraph.graph.message import add_messages
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from typing import Tuple
from .utils import print_state, print_debug # For debugging
from .prompts import PROXY

def validate_result(result, query):
    # result: the final answer from the untrusted agent
    # query: the expected format of the result (JSON format)
    if isinstance(query, list):
        if not isinstance(result, list):
            return False
        if query:
            query_elem = query[0]
            return all(validate_result(item, query_elem) for item in result)
        else:
            return True # Return True for empty list for now
    elif isinstance(query, dict):
        if not isinstance(result, dict):
            return False
        # Check if all query keys are present in the result
        for key in query:
            if key not in result:
                return False
        # Remove the keys from the result if the query does not have the key
        keys_to_remove = [key for key in result if key not in query]
        for key in keys_to_remove:
            result.pop(key)
            
        for key in query:
            if not validate_result(result[key], query[key]):
                return False
    # If query is neither a dict nor list, it is a leaf node - just check key existence
    return True

def extract_prompt_values(query, query_result):
    extracted_values = []
    
    if isinstance(query, list):
        if not isinstance(query_result, list):
            print_debug("Query validation failed?")
            return []
        query_elem = query[0] if query else None
        for result_item in query_result:
            extracted_values.extend(extract_prompt_values(query_elem, result_item))
    
    elif isinstance(query, dict):
        if not isinstance(query_result, dict):
            print_debug("Query validation failed?")
            return []
        for key, value in query.items():
            if key in query_result:
                extracted_values.extend(extract_prompt_values(value, query_result[key]))
    
    elif query == "prompt":
        extracted_values.append(query_result)
        
    return extracted_values
    
def normalize_string(text):
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    # Replace literal "\n" with a space
    text = text.replace("\\n", " ")
    # Remove all newline characters
    text = re.sub(r'[\n\r]+', ' ', text)
    # Replace consecutive spaces with a single space
    text = re.sub(r'\s+', ' ', text)
    # Strip leading and trailing whitespace
    return text.strip()
    
def add_proxy(result, state, data_format, metadata):
    # Initialize state["proxies"] if it doesn't exist
    if not state.get("proxies"):
        state["proxies"] = []
    
    # Add the proxy - value pair to the state
    proxy_num = len(state["proxies"])
    
    state["proxies"] = state["proxies"] + [{
        "id": proxy_num, 
        "proxy": f"{PROXY}{proxy_num}", 
        "value": result, 
        "submessage_index": metadata["submessage_index"], # Index of untrusted agent's message that is used to generate the proxy
        "format": data_format,
        "attr": metadata.get("attr", "Unknown"),
        "principal": metadata.get("principal", "Untrusted"),
    }]
    
    return proxy_num

def get_query(messages):
    # Get the query from the first message
    content = messages[0].content
    match = re.search(r"Query: (.+)", content)
    if match:
        query = match.group(1)
        query = ast.literal_eval(query)
        return query
    else:
        raise Exception("Query not found")

def get_query_message(state):
    # The first message is the query message in Unpriv agent
    return state["messages"][0]

def get_result(final_answer, query):
    if final_answer.tool_calls[0]["args"].get("query_succeeded", False) == False:
        raise Exception("PFI FAILED: Query failed")
    result = final_answer.tool_calls[0]["args"].get("result", None)
    if result is None:
        raise Exception("PFI FAILED: Result not found")
    if isinstance(result, str):
        if result.startswith("```json"):
            result = result[7:-3]
        result = result.replace("\\'", "\'")
        try:
            result = json.loads(result)
        except:
            raise Exception("PFI FAILED: Result validation failed")
        # result = ast.literal_eval(result)
    
    if validate_result(result, query) == False:
        raise Exception("PFI FAILED: Result validation failed")
    return result

def seal(result, query, state, metadata):
    if isinstance(query, list):
        for i, item in enumerate(result):
            if i < len(query):
                elem_format = query[i]
            else:
                elem_format = query[0]
            m = metadata
            if isinstance(metadata["attr"], list):
                m["attr"] = metadata["attr"][i]
            if isinstance(metadata["principal"], list):
                m["principal"] = metadata["principal"][i]
            result[i] = seal(item, elem_format, state, m)
    elif isinstance(query, dict):
        for key, value in result.items():
            m = metadata
            if isinstance(metadata["attr"], dict):
                m["attr"] = metadata["attr"][key]
            if isinstance(metadata["principal"], dict):
                m["principal"] = metadata["principal"][key]
            result[key] = seal(value, query[key], state, m)
    elif query == "string":
        proxy_num = add_proxy(result, state, query, metadata)
        result = f"{PROXY}{proxy_num}"
    elif query == "pfi_list":
        # Seal PFIDataList format
        print_debug(f"Sealing PFIDataList format: {result} ({type(result)})")
        result_list = ast.literal_eval(result)
        for i, item in enumerate(result_list):
            if metadata["principal"][i] == "Untrusted":
                m = {
                    "submessage_index": metadata["submessage_index"],
                    "attr": metadata["attr"][i],
                    "principal": metadata["principal"][i]
                }
                proxy_num = add_proxy(item, state, "string", m)
                result_list[i] = f"{PROXY}{proxy_num}"
        result = str(result_list)
    else: # other formats
        # Make proxy for all formats except for 'prompt' format
        if query != "prompt":
            proxy_num = add_proxy(result, state, query, metadata)
            result = f"{PROXY}{proxy_num}"
    return result

def replace_proxy_wrapper(state, is_final_answer=False):
    def replace_proxy(match):
        proxy_id = int(match.group(1))
        if proxy_id < len(state["proxies"]):
            print(f"Replacing {state['proxies'][proxy_id]['proxy']} to:")
            print(f"{state['proxies'][proxy_id]['value']}")
            if is_final_answer:
                return f"{PROXY}{proxy_id}: " + str(state["proxies"][proxy_id]["value"])
            return str(state["proxies"][proxy_id]["value"])
        else:
            return f"{PROXY}{proxy_id}"
    return replace_proxy

def replace_proxies(value, state):
    full_pattern = rf"^{re.escape(PROXY)}(\d+)$"
    search_pattern = rf"{re.escape(PROXY)}(\d+)"

    if isinstance(value, str):
        match = re.fullmatch(full_pattern, value)
        if match:
            proxy_num = int(match.group(1))
            if proxy_num < len(state["proxies"]):
                proxy_val = state["proxies"][proxy_num]["value"]
            else:
                proxy_val = "Unknown proxy"
            print(f"{value} -> {proxy_val}")
            return proxy_val
        else:
            return re.sub(search_pattern, replace_proxy_wrapper(state), value)
    elif isinstance(value, list):
        for i in range(len(value)):
            value[i] = replace_proxies(value[i], state)
        return value
    elif isinstance(value, dict):
        for key, val in value.items():
            value[key] = replace_proxies(val, state)
        return value
    elif isinstance(value, tuple):
        return tuple(replace_proxies(list(value), state))
    elif isinstance(value, (int, float, bool)):
        return value

    print(f"Unknown type: {type(value)}")
    return re.sub(search_pattern, replace_proxy_wrapper(state), value)
        
def replace_proxies_in_tool_call(tool_call, state):
    search_pattern = rf"{re.escape(PROXY)}(\d+)"

    for key, value in tool_call['args'].items():
        if re.search(search_pattern, str(value)):
            print("================================================================================")
            print(f"Replacing the proxy in the tool call arguments: arg[{key}]={value}")
            tool_call['args'][key] = replace_proxies(value, state)
            print(f"Replaced with: arg[{key}]={tool_call['args'][key]}")
            print("================================================================================")
    
def replace_proxies_in_message(state, message, is_final_answer=False):
    # If the result from the trusted agent contains a proxy, replace the proxy with the actual value
    search_pattern = rf"{re.escape(PROXY)}(\d+)"
    
    if 'proxies' in state:
        if re.search(search_pattern, message.content):
            message = copy.deepcopy(message)
        elif message.tool_calls:
             if any(re.search(search_pattern, str(message.tool_calls[i]['args'])) for i in range(len(message.tool_calls))):
                message = copy.deepcopy(message)
        
        if re.search(search_pattern, message.content):
            print("================================================================================")
            print(f"Replacing proxies in the result: {message.content}")
            message.content = re.sub(search_pattern, replace_proxy_wrapper(state, is_final_answer), message.content)
            print("================================================================================")
        if message.tool_calls:
            for tool_call in message.tool_calls:
                replace_proxies_in_tool_call(tool_call, state)
                
        return message
    else:
        return message

def replace_proxies_in_messages(state, msg_type):
    for i, message in enumerate(state["messages"]):
        # If the message's type is msg_type e.g., AIMessage(tool call from agent), replace the proxy in the message
        if isinstance(message, msg_type):
            state["messages"][i] = replace_proxies_in_message(state, message)
            

def replace_proxies_in_tool_calls(tool_calls, state):
    result = copy.deepcopy(tool_calls)
    for i in range(len(result)):
        replace_proxies_in_tool_call(result[i], state)
    return result      

# Seal the proxy in the message (tool error message)
def seal_message(message, proxies):
    for proxy in proxies:
        msg = message.content.replace("\\n", "\n")
        if isinstance(proxy["value"], str) and proxy["value"] in msg:
            message.content = msg.replace(proxy["value"], proxy["proxy"])

def extract_proxies_with_positions(state, message, untrusted_agent_tools) -> Tuple[list, dict]:
    """
    Return the list of proxies in the message content and tool calls, along with each proxy's position in the message.
    Example of the return value:
    [
        {
            "proxy": {"id": 0, "proxy": "#DATA0", "value": "John Doe", "format": "string"},
            "position": {"type": "content"}
        },
        {
            "proxy": [{"id": 1, "proxy": "#DATA1", "value": "123-456-7890", "format": "string"}],
            "position": {
                "type": "tool_call",
                "tool_name": "send_sms"
                "arg_name": ["phone_number"],
            }
        }
    ]
    """
    proxies = []

    if "proxies" not in state:
        return proxies
    
    if "proxies" in state and state["proxies"]:
        pattern = '|'.join(re.escape(proxy["proxy"]) for proxy in state["proxies"])
        regex = re.compile(pattern)
    
    if len(message.tool_calls) == 0: # Final answer
        matches = regex.findall(message.content)
        for match in matches:
            proxy = next((p for p in state["proxies"] if p["proxy"] == match), None)
            if proxy:
                proxies.append({
                    "proxy": proxy,
                    "position": {
                        "type": "content"
                    }
                })
    
    # Tool calls
    for tool_call in message.tool_calls:
        if tool_call in untrusted_agent_tools:
            continue
        
        proxies_in_single_tool_call = []
        for key, value in tool_call["args"].items():
            try:
                matches = regex.findall(str(value))
                for match in matches:
                    proxy = next((p for p in state["proxies"] if p["proxy"] == match), None)
                    if proxy and not any(item["proxy"] == proxy for item in proxies_in_single_tool_call):
                        proxies_in_single_tool_call.append({"proxy": proxy, "arg": key})
            except Exception as e:
                pass

        if proxies_in_single_tool_call:
            proxies.append({
                "proxy": [proxy["proxy"] for proxy in proxies_in_single_tool_call],
                "position": {
                    "type": "tool_call",
                    "tool_name": tool_call["name"],
                    "arg_name": [proxy["arg"] for proxy in proxies_in_single_tool_call],
                }
            })
    
    return proxies
 