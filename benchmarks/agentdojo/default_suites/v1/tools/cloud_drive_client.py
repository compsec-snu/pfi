import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, model_validator
from typing_extensions import Self

from default_suites.v1.tools.types import CloudDriveFile, CloudDriveFileID, SharingPermission
from functions_runtime import Depends
from langchain_core.tools import tool
from pfi_agent import pfi_tool, PFIData, PFIDataList, PFIDataDict, PFIPluginResult

class CloudDrive(BaseModel):
    initial_files: list[CloudDriveFile]
    account_email: EmailStr
    files: dict[CloudDriveFileID, CloudDriveFile] = {}

    @model_validator(mode="after")
    def _create_files(self) -> Self:
        all_ids = [file.id_ for file in self.initial_files]
        if len(all_ids) != len(set(all_ids)):
            duplicate_ids = [id_ for id_ in all_ids if all_ids.count(id_) > 1]
            raise ValueError(f"File IDs must be unique.")
        self.files = {file.id_: file for file in self.initial_files}
        return self

    def _get_next_id(self) -> CloudDriveFileID:
        largest_id = max((int(key) for key in self.files.keys()), default=0)
        return CloudDriveFileID(largest_id + 1)

    def get_file_by_id(self, file_id: CloudDriveFileID) -> CloudDriveFile:
        if file_id not in self.files:
            raise ValueError(f"File with given ID not found.")
        return self.files[file_id]

    def create_file(self, filename: str, content: str) -> CloudDriveFile:
        new_file = CloudDriveFile(
            id_=self._get_next_id(),
            filename=filename,
            content=content,
            size=len(content),
            owner=self.account_email,
            last_modified=datetime.datetime.now(),
        )
        self.files[new_file.id_] = new_file
        return new_file

    def delete_file(self, file_id: CloudDriveFileID) -> str:
        if file_id not in self.files:
            raise ValueError(f"File with given ID not found.")
        self.files.pop(file_id)
        return "File deleted successfully."

    def search_files_by_filename(self, filename: str, permissions: list[str]) -> list[CloudDriveFile]:
        return [file for file in self.files.values() 
                if all(word in file.filename.lower() for word in filename.lower().split())
                and file.get_privilege() in permissions]

    def search_files(self, query: str, permissions: list[str]) -> list[CloudDriveFile]:
        return [file for file in self.files.values() 
                if all(word in file.content.lower() for word in query.lower().split())
                and file.get_privilege() in permissions]


    def append_to_file(self, file_id: CloudDriveFileID, content: str) -> CloudDriveFile:
        file = self.get_file_by_id(file_id)
        file.content += content
        file.size = len(file.content)
        file.last_modified = datetime.datetime.now()
        return file

    def get_file_sizes(self) -> dict[str, int]:
        return {file.id_: file.size for file in self.files.values()}

class CloudDriveEnvironment(BaseModel):
    cloud_drive: CloudDrive

cloud_drive = CloudDrive(
    initial_files=[],
    account_email="test@gmail.com",
    files={},
)
env = CloudDriveEnvironment(cloud_drive=cloud_drive)

@pfi_tool
def search_files_by_filename(filename: str) -> PFIPluginResult:
    """Get a file from a cloud drive by its filename. It returns a list of files.
    Each file contains the file id, the content, the file type, and the filename.

    :param filename: The name of the file to retrieve.
    """
    res = env.cloud_drive.search_files_by_filename(filename, ["cloud:public", "cloud:private"])
    if len(res) == 0:
        raise ValueError(f"No files found with the given filename. Try a different filename.")
    res = [PFIData(data=file, attr=file.get_privilege()) for file in res]
    return PFIDataList(data=res)

@pfi_tool
def search_files_by_filename_u(filename: str) -> PFIPluginResult:
    """Get a file from a cloud drive by its filename. It returns a list of files.
    Each file contains the file id, the content, the file type, and the filename.

    :param filename: The name of the file to retrieve.
    """
    res = env.cloud_drive.search_files_by_filename(filename, ["cloud:public"])
    if len(res) == 0:
        raise ValueError(f"No files found with the given filename. Try a different filename.")
    res = [PFIData(data=file, attr=file.get_privilege()) for file in res]
    return PFIDataList(data=res)


@pfi_tool
def create_file(
    filename: str,
    content: str,
) -> PFIPluginResult:
    """Create a new file in the cloud drive.

    :param filename: The name of the file to create.
    :param content: The content of the file to create.
    """
    res = env.cloud_drive.create_file(filename, content)
    return PFIData(data=res, attr=res.get_privilege())

@pfi_tool
def delete_file(file_id: str) -> PFIPluginResult:
    """Delete a file from the cloud drive by its filename.

    :param file_id: The name of the file to delete.
    """
    res = env.cloud_drive.delete_file(CloudDriveFileID(file_id))
    return PFIData(data=res, attr="tool:cloud_drive")

@pfi_tool
def get_file_by_id(file_id: str) -> PFIPluginResult:
    """Get a file from a cloud drive by its ID.

    :param file_id: The ID of the file to retrieve.
    """
    res = env.cloud_drive.get_file_by_id(file_id)
    return PFIData(data=res, attr=res.get_privilege())

@pfi_tool
def get_file_by_id_u(file_id: str) -> PFIPluginResult:
    """Get a file from a cloud drive by its ID.

    :param file_id: The ID of the file to retrieve.
    """
    res = env.cloud_drive.get_file_by_id(file_id)
    if res.get_privilege() != "cloud:public":
        raise ValueError(f"File with given ID is not public.")
    return PFIData(data=res, attr=res.get_privilege())

@pfi_tool
def list_files() -> PFIPluginResult:
    """Retrieve all files in the cloud drive."""
    res = list(env.cloud_drive.files.values())
    res = [PFIData(data=file, attr=file.get_privilege()) for file in res]
    return PFIDataList(data=res)

@pfi_tool
def list_files_u() -> PFIPluginResult:
    """Retrieve all files in the cloud drive."""
    res = [file for file in env.cloud_drive.files.values() 
           if file.get_privilege() == "cloud:public"]
    res = [PFIData(data=file, attr=file.get_privilege()) for file in res]
    return PFIDataList(data=res)

@pfi_tool
def share_file(
    file_id: str,
    email: str,
    permission: SharingPermission,
) -> PFIPluginResult:
    """Share a file with a user.

    :param file_id: The ID of the file to share.
    :param email: The email of the user to share the file with.
    :param permission: The permission level to grant the user.
    """
    file = env.cloud_drive.get_file_by_id(CloudDriveFileID(file_id))
    file.shared_with[email] = permission
    res = f"File {file_id} has been shared with {email} with permission level {permission}."
    return PFIData(data=res, attr="tool:cloud_drive")
    # return PFIData(data=file, attr=file.get_privilege())

@pfi_tool
def append_to_file(
    file_id: str,
    content: str,
) -> PFIPluginResult:
    """Append content to a file in the cloud drive.

    :param file_id: The ID of the file to append content to.
    :param content: The content to append to the file.
    """
    res = env.cloud_drive.append_to_file(CloudDriveFileID(file_id), content)
    res = f"Content appended to file {file_id}."
    return PFIData(data=res, attr="tool:cloud_drive")
    # return PFIData(data=res, attr=res.get_privilege())

@pfi_tool
def search_files(query: str) -> PFIPluginResult:
    """Search for files in the cloud drive by content.

    :param query: The string to search for in the files.
    """
    matches = env.cloud_drive.search_files(query, ["cloud:public", "cloud:private"])
    if len(matches) == 0:
        raise ValueError(f"No files found with the given query. Try a different search term.")
    res = [PFIData(data=file, attr=file.get_privilege()) for file in matches]
    return PFIDataList(data=res)

@pfi_tool
def search_files_u(query: str) -> PFIPluginResult:
    """Search for files in the cloud drive by content.

    :param query: The string to search for in the files.
    """
    matches = env.cloud_drive.search_files(query, ["cloud:public"])
    if len(matches) == 0:
        raise ValueError(f"No files found with the given query. Try a different search term.")
    res = [PFIData(data=file, attr=file.get_privilege()) for file in matches]
    return PFIDataList(data=res)
