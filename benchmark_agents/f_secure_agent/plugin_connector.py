from typing import Any, Dict, List, Union, get_type_hints, Callable, Optional, Literal
from langchain_core.runnables import Runnable
from langchain_core.tools import tool
from langchain_core.tools.base import BaseTool
from pydantic import BaseModel

Attr = str
Principal = str

class PFIData(BaseModel):
    data: str
    attr: Attr
    principal: Optional[Principal] = None

    def __init__(self, data: Any, attr: Attr):
        super().__init__(data=str(data), attr=attr)

    def __str__(self) -> str:
        return f"PFIData(data={self.data!r}, attr={self.attr!r})"
    def __repr__(self) -> str:
        return self.__str__()
    def print(self) -> str:
        return self.data
    def get_attr(self):
        return self.attr
    def set_attr(self, attr: Attr) -> None:
        self.attr = attr
    def get_principal(self):
        return self.principal
    def set_principal(self, principal: Principal) -> None:
        self.principal = principal

class PFIDataList(BaseModel):
    data: List[PFIData]

    def __str__(self) -> str:
        return f"PFIDataList(data={self.data!r})"
    def __repr__(self) -> str:
        return self.__str__()
    def print(self) -> str:
        return str([x.data for x in self.data])
    def get_attr(self):
        return [x.attr for x in self.data]
    def set_attr(self, attr) -> None:
        if isinstance(attr, list):
            assert len(attr) == len(self.data)
            for i in range(len(self.data)):
                self.data[i].attr = attr[i]
        elif isinstance(attr, Attr):
            for i in range(len(self.data)):
                self.data[i].attr = attr
        else:
            raise ValueError(f"Invalid attr type: {type(attr)}")
    def get_principal(self):
        return [x.principal for x in self.data]

    def set_principal(self, principal) -> None:
        if isinstance(principal, str):
            for i in range(len(self.data)):
                self.data[i].principal = principal
        elif isinstance(principal, list):
            assert len(principal) == len(self.data)
            for i in range(len(self.data)):
                self.data[i].principal = principal[i]
        else:
            raise ValueError(f"Invalid principal type: {type(principal)}")

class PFIDataDict(BaseModel):
    data: Dict[str, PFIData]

    def __str__(self) -> str:
        return f"PFIDataDict(data={self.data!r})"
    def __repr__(self) -> str:
        return self.__str__()
    def print(self) -> str:
        return str({k: v.data for k, v in self.data.items()})    
    def get_attr(self):
        return {k: v.attr for k, v in self.data.items()}
    def set_attr(self, attr) -> None:
        if isinstance(attr, dict):
            assert set(attr.keys()) == set(self.data.keys())
            for k, v in self.data.items():
                v.attr = attr[k]
        elif isinstance(attr, Attr):
            for k, v in self.data.items():
                v.attr = attr
        else:
            raise ValueError(f"Invalid attr type: {type(attr)}")
    def get_principal(self):
        return {k: v.principal for k, v in self.data.items()}
    def set_principal(self, principal) -> None:
        if isinstance(principal, str):
            for k, v in self.data.items():
                v.principal = principal
        elif isinstance(principal, dict):
            for k, v in self.data.items():
                v.principal = principal[k]
        else:
            raise ValueError(f"Invalid principal type: {type(principal)}")
PFIPluginResult = Union[PFIData, PFIDataList, PFIDataDict]

# Definition from langchain_Core/tools.py
def pfi_tool(
    name_or_callable: Optional[Union[str, Callable]] = None,
    runnable: Optional[Runnable] = None,
    *args: Any,
    return_direct: bool = False,
    args_schema: Optional[type] = None,
    infer_schema: bool = True,
    response_format: Literal["content", "content_and_artifact"] = "content",
    parse_docstring: bool = False,
    error_on_invalid_docstring: bool = True,
) -> Union[
        BaseTool,
        Callable[[Union[Callable, Runnable]], BaseTool],
    ]:

    if runnable is not None:
        raise ValueError("Runnable is not supported for PFI tools.")
    
    def _partial(func: Union[str, Callable]) -> BaseTool:
        return_type = get_type_hints(func).get("return")
        
        if return_type is not PFIPluginResult:
            raise ValueError("The return type of a PFI tool must be PFIPluginResult.")
        if return_type is None:
            raise ValueError("The return type of a PFI tool must be specified.")

        return tool(
            name_or_callable=func,
            runnable=None,
            *args,
            return_direct=return_direct,
            args_schema=args_schema,
            infer_schema=infer_schema,
            response_format=response_format,
            parse_docstring=parse_docstring,
            error_on_invalid_docstring=error_on_invalid_docstring,
        )
    return _partial(name_or_callable) if callable(name_or_callable) else _partial
