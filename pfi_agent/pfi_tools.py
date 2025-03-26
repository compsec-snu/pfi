from langchain_core.tools import tool
from typing import Annotated, List, Any, Union, Dict
from pydantic import BaseModel, Field
import ast
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from .prompts import CONDITIONAL_PROMPT_MESSAGE
from .plugin_connector import PFIPluginResult, PFIData, PFIDataList, PFIDataDict, pfi_tool

query_succeeded_message = "True if the query has succeded, False if the query has failed."
condition_llm = None


@pfi_tool
def return_query_result(
    query_succeeded: bool,
    result: str,
)-> PFIPluginResult:
    """
    params:
    - query_succeeded: True if the query has succeded, False if the query has failed.
    - result: Return the query result in JSON format.
    """
    if query_succeeded:
        return PFIData(data=result, attr="untrusted_agent")
        # if isinstance(result, str):
        #     return PFIData(data=result, attr="untrusted_agent")
        # elif isinstance(result, list):
        #     pfi_list = [PFIData(data=data, attr="untrusted_agent") for data in result]
        #     return PFIDataList(data=pfi_list)
        # elif isinstance(result, dict):
        #     pfi_dict = {key: PFIData(data=value, attr="untrusted_agent") for key, value in result.items()}
        #     return PFIDataDict(data=pfi_dict)
        # else:
        #     return PFIData(data=result, attr="untrusted_agent")
    else:
        return PFIData(data="Query failed", attr="system")

def initialize_condition_llm(llm):
    global condition_llm
    condition_llm = llm

# Decide which prompt to use based on the condition with LLM
def run_llm(data, prompts, code):
    prompt = ChatPromptTemplate.from_messages(
        [
            HumanMessage(content=CONDITIONAL_PROMPT_MESSAGE.format(data=data, code=code, prompts=prompts))
        ]
    )
    chain = prompt | condition_llm
    choice = chain.invoke({"messages": []})
    print("Choice:", choice.content)
    
    max_retry_count = 3
    retry_count = 0
    
    while choice is not None and choice.content is not None and choice.content not in prompts:
        retry_count += 1
        if retry_count > max_retry_count:
            break
        error_message = HumanMessage(content="Invalid prompt choice. Please choose from the given prompts.")
        prompt.append(choice)
        prompt.append(error_message)
        choice = chain.invoke({"messages": []})
        print("Choice:", choice.content)

    return choice.content

@pfi_tool
def conditional_prompt(
    condition: List[Any],
    prompts: List[Any],
    code: str,
    use_llm: bool = False
)-> PFIPluginResult:
    """
    Choose a prompt based on the condition.
    params:
    - condition: A list of proxies used as condition(s)
    - prompts: List of prompts to use based on the condition
    - code: Code to evaluate the condition
    - use_llm: Using LLM if code involves non-trivial logic
    
    Example 1 (Boolean condition):
    - condition: ["#DATA0"]
    - prompts: ["Prompt 1", "Prompt 2"]
    - code: "return prompts[0] if condition[0] else None"

    Example 2 (String condition):
    - condition: ["#DATA0"]
    - prompts: ["Prefix"]
    - code: "return [data for data in condition if data.startswith("Prefix")]"

    Example 3 (Integer condition):
    - condition: ["#DATA0", "#DATA1"]
    - prompts: ["Prompt 1", "Prompt 2"]
    - code: "return prompts[max(condition)]"
    """

    code = code.replace('\n', '\n    ')
    function_string = f"def condition_check(condition, prompts):\n    {code}"

    if use_llm:
        return PFIData(data=run_llm(condition, prompts, code), attr="system")
    result = None
    try:
        local_namespace = {}
        exec(function_string, globals(), local_namespace)
        condition_check = local_namespace["condition_check"]
        result = condition_check(condition, prompts)
        return PFIData(data=str(result), attr="system")
    except SyntaxError:
        print(f"Syntax Error of the condition code: {code} Running with LLM instead.")
        return PFIData(data=run_llm(condition, prompts, code), attr="system")
    except Exception as e:
        print(f"Error in the condition code: {e}. Running with LLM instead.")
        return PFIData(data=run_llm(condition, prompts, code), attr="system") 
