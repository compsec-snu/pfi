from typing import Annotated
from pydantic import BaseModel
from functions_runtime import Depends
from langchain_core.tools import tool
from urllib.parse import urlparse
from pfi_agent import pfi_tool, PFIData, PFIPluginResult

class Web(BaseModel):
    web_content: dict[str, str] # URL: Content
    web_requests: list[str]

class WebEnvironment(BaseModel):
    web: Web

web = Web(web_content={}, web_requests=[])
env = WebEnvironment(web=web)

def standardize_url(url):
    if url.startswith("www."):
        url = "https://" + url
    return url

@pfi_tool
def post_webpage(url: str, content: str) -> PFIPluginResult:
    """Posts a webpage at a given URL with the given content.

    :param url: The URL of the webpage.
    :param content: The content of the webpage.
    """
    url = standardize_url(url)
    env.web.web_requests.append(url)
    env.web.web_content[url] = content
    return PFIData(data="Success", attr="tool:web")

@pfi_tool
def get_webpage(url: str) -> PFIPluginResult:
    """Returns the content of the webpage at a given URL.

    :param url: The URL of the webpage.
    """
    standard_url = standardize_url(url)
    env.web.web_requests.append(standard_url)
    if standard_url not in env.web.web_content:
        return PFIData(data="404 Not Found", attr="tool:web")
    return PFIData(data=env.web.web_content.get(standard_url), attr=urlparse(url).netloc)

@pfi_tool
def download_file(url: str, file_name: str) -> PFIPluginResult:
    """Downloads a file from a given URL to the local folder.

    :param url: The URL of the file.
    :param file_name: The name of the file to download.
    """
    url = standardize_url(url)
    env.web.web_requests.append(url)
    if url not in env.web.web_content:
        return PFIData(data="404 Not Found", attr="tool:web")
    else:
        return PFIData(data="Success", attr="tool:web")
