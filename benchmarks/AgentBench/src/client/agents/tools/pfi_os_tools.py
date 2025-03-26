import requests
import re
import bashlex
from src.typings import *
from src.utils import *
from pfi_agent import pfi_tool, PFIData, PFIPluginResult

DISALLOWED_COMMANDS = ['exit', 'kill']

def contains_if_statement(command: str) -> bool:
    if_patterns = [
        r'\bif\b',               # Multi-line or standard if block
        r'\[\[?.*?]]?\s*then\b', # Inline condition and then
        r'\btest\s',             # The test command followed by a space
        r';\s*then\b',           # Inline then after an if or condition
    ]
    
    combined_pattern = '|'.join(if_patterns)
    return bool(re.search(combined_pattern, command))

def parse_command(command: str):
    try:
        return bashlex.split(command)
    except ValueError:
        return None

def command_to_message(command: str) -> str:
    # Transform the bash command into a message in the format that AgentBench expects
    return (
        "Think: I'm running the command.\n\n"
        "Act: bash\n\n"
        "```bash\n"
        f"{command}\n"
        "```\n\n"
    )

def is_safe_command(command: str) -> bool:
    disallowed_commands_pattern = r'\b(' + '|'.join(re.escape(cmd) for cmd in DISALLOWED_COMMANDS) + r')\b'

    command_parts = parse_command(command)
    if command_parts is None: # Parsing failed
        return False

    for part in command_parts:
        if re.search(disallowed_commands_pattern, part):
            return False

    if contains_if_statement(command):
        return False
    
    return True

def trustworthiness_check(result: str) -> str:
    # If result starts with UNTRUSTED - , remove the prefix and return untrusted
    if re.search(r'UNTRUSTED - ', result):
        return "untrusted"
    return "trusted"

def execute_bash_command(
        command: str,
        controller_address: str, # This argument is not visible to LLM
        session_id: str, # This argument is not visible to LLM
    ) -> str:
    
    # If untrusted agent called priv command, return error message to the agent
    if is_safe_command(command) == False:
        return PFIData(data="Error: You are not allowed to run this command.", attr="os:internal")
    
    agent_response = command_to_message(command)

    # Send the command to the task server
    try:
        result = requests.post(
            controller_address + "/interact",
            json=InteractRequest(
                session_id=session_id,
                agent_response=AgentOutput(content=agent_response)
            ).dict()
        )
    except Exception as e:
        raise Exception(f"Error: {e}")
    if result.status_code != 200:
        requests.post(
            controller_address + "/cancel",
            json=CancelRequest(session_id=session_id).dict()
        )
        raise Exception(f"Error({result.status_code}): {result.text}")

    result = result.json()
    
    os_output = result["output"]["history"][-1]["content"]

    result_trustworthiness = trustworthiness_check(os_output)

    if result_trustworthiness == "untrusted":
        os_output = re.sub(r'UNTRUSTED - ', '', os_output)
        os_output = PFIData(data = os_output, attr="os:external")
    else:
        os_output = PFIData(data = os_output, attr="os:internal")

    return os_output

def create_bash_tool(controller_address: str, session_id: str):
    @pfi_tool
    def bash_tool(
        command: str,
    ) -> PFIPluginResult:
        ''' 
        Execute the bash command.
        
        Args:
            command: The command to execute
        '''
        return execute_bash_command(command, controller_address, session_id)
    
    @pfi_tool
    def bash_tool_u(
        command: str,
    ) -> PFIPluginResult:
        ''' 
        Execute the bash command.
        
        Args:
            command: The command to execute
        '''
        return execute_bash_command(command, controller_address, session_id)
     
    return bash_tool, bash_tool_u
