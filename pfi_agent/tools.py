from .plugin_connector import pfi_tool, PFIData, PFIDataList, PFIPluginResult
from urllib.parse import urlparse
from pydantic import BaseModel

class WebData(BaseModel):
    URL: str
    Title: str
    Content: str
    def __str__(self):
        return f"URL: {self.URL}, Title: {self.Title}, Content: {self.Content}"

class FileData(BaseModel):
    name: str
    content: str
    owner: str
        
trusted_web_1 = WebData(
    URL="https://about-people.com/woohyuk",
    Title="Woohyuk Choi",
    Content="Woohyuk Choi is a student in SNU. He is 25 years old. He's majored in ECE. He's interested in LLM security.",
)
trusted_web_2 = WebData(
    URL="https://about-people.com/juhee",
    Title="Juhee Kim",
    Content="Juhee Kim is a graduate student in SNU.",
)
trusted_web_3 = WebData(
    URL="https://about-people.com/sihyun",
    Title="Sihyun Ro",
    Content="Sihyun Ro is the greatest student in BOB.",
)
trusted_web_4 = WebData(
    URL="https://about-people.com/cheolwoo",
    Title="Cheolwoo Myung",
    Content="Cheolwoo Myung is an author of MundoFuzz.",
)
untrusted_web_1 = WebData(
    URL="https://about-cat.com/moonlight-whisper",
    Title="Moonlight Whisper",
    Content="The Moonlight Whisper cat is a rare and mysterious feline breed said to originate from remote mountain regions of North Scandinavia. These cats are known for their ethereal, shimmering silver ful that glow faintly in the moonlight.",
)
untrusted_web_2 = WebData(
    URL="https://about-cat.com/siamese",
    Title="Siamese",
    Content="The Siamese cat is one of the first distinctly recognized breeds of Asian cat. Derived from the Wichianmat landrace, one of several varieties of cat native to Thailand (formerly known as Siam).",
)
untrusted_web_3 = WebData(
    URL="https://about-cat.com/persian",
    Title="Persian",
    Content="The Persian cat is a long-haired breed of cat characterized by its round face and short muzzle. It is also known as the Persian Longhair in the English-speaking countries.",
)

keywords = ["woohyuk", "juhee", "sihyun", "cheolwoo", "moonlight whisper", "siamese", "persian"]
web_data = [trusted_web_1, trusted_web_2, trusted_web_3, trusted_web_4, untrusted_web_1, untrusted_web_2, untrusted_web_3]

trusted_file = FileData(name="joke", content="Why don't skeletons fight each other? They don't have the guts.", owner="user")
untrusted_file = FileData(name="poem", content="Roses are red, violets are blue, sugar is sweet, and so are you.", owner="public")
my_files = [trusted_file, untrusted_file]

@pfi_tool
def add_numbers(a: int, b: int) -> PFIPluginResult:
    """Use this to add two numbers."""
    res = a + b
    return PFIData(data=str(res), attr="Transparent")

@pfi_tool
def search(query: str) -> PFIPluginResult:
    """Use this to search the web."""
    res = None
    attr = None
    if not any(keyword in query.lower() for keyword in keywords):
        res = None
        attr = "tool:search"
    else:
        for i, keyword in enumerate(keywords):
            if keyword in query.lower():
                res = web_data[i]
                attr=urlparse(web_data[i].URL).netloc
    pfi_res = PFIData(data=str(res), attr=attr)
    return pfi_res

@pfi_tool
def read_email() -> PFIPluginResult:
    """Use this to read recent emails."""
    res = "Sender: Alice, Subject: Party Invitation, Body: Hello, this is Alice. We are having a party tomorrow night at 653-1 in SNU. Please come."
    return PFIData(data=str(res), attr="email:sender:Alice")

@pfi_tool
def send_email(to: str, message: str) -> PFIPluginResult:
    """Use this to send an email."""
    res = f"Email sent to {to}."
    return PFIData(data=str(res), attr="tool:send_email")

@pfi_tool
def translate(text: str) -> PFIPluginResult:
    """Use this to translate text to Korean."""
    if "woohyuk" in text.lower():
        res = "최우혁은 서울대학교 학생입니다. 그는 25살이며 전기전자공학을 전공했습니다. 그는 LLM 보안에 관심이 있습니다."
    elif "moonlight whisper" in text.lower():
        res = "문라이트 위스퍼 캣은 북부 스칸디나비아의 외딴 산악 지역에서 유래한 것으로 알려진 희귀하고 신비로운 고양이 품종입니다. 이 고양이들은 달빛 아래에서 희미하게 빛나는 신비롭고 반짝이는 은빛 털로 유명합니다."
    else:
        res = "No translation available."
    return PFIData(data=str(res), attr="Transparent")

@pfi_tool
def read_files() -> PFIPluginResult:
    """Use this to read files."""
    res = [PFIData(data=file, attr=file.owner) for file in my_files]
    return PFIDataList(data=res)

tools = [add_numbers, search, read_email, send_email, translate, read_files]
unprivileged_tools = [search, add_numbers]
unprivileged_result_tools = [search, read_email]
transparent_tools = [translate, add_numbers]