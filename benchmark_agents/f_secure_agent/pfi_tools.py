from langchain_core.tools import tool
from typing import Annotated, List, Any, Union, Dict
from pydantic import BaseModel, Field
import ast
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from .plugin_connector import PFIPluginResult, PFIData, PFIDataList, PFIDataDict, pfi_tool

query_succeeded_message = "True if the query has succeded, False if the query has failed."

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
