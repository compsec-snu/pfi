from typing import Annotated

from pydantic import BaseModel

from functions_runtime import Depends
from langchain_core.tools import tool
from pfi_agent import pfi_tool, PFIData, PFIDataList, PFIDataDict, PFIPluginResult

class File(BaseModel):
    path: str
    content: str
    creator: str

class Filesystem(BaseModel):
    files: list[File]

class FilesystemEnvironment(BaseModel):
    filesystem: Filesystem

filesystem = Filesystem(files=[])
env = FilesystemEnvironment(filesystem=filesystem)

@pfi_tool
def read_file(file_path: str) -> PFIPluginResult:
    """
    Reads the contents of the file at the given path.

    :param file_path: The path to the file to read.
    """

    result = None
    for file in env.filesystem.files:
        if file.path == file_path:
            result = file
            break
    
    if not result:
        return PFIData(data=f"File not found: {file_path}", attr="tool:file_reader")

    return PFIData(data=result.content, attr=result.creator)