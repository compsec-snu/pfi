import requests
import re
from src.typings import *
from src.utils import *
from pfi_agent import pfi_tool, PFIData, PFIPluginResult

def command_to_message(command: str) -> str:
    # Transform the bash command into a message in the format that AgentBench expects
    return (
        "Think: I'm running the command.\n\n"
        "Act: bash\n\n"
        "```bash\n"
        f"{command}\n"
        "```\n\n"
    )

def execute_bash_command(
        command: str,
        controller_address: str, # This argument is not visible to LLM
        session_id: str, # This argument is not visible to LLM
    ) -> str:
    
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
    os_output = re.sub(r'UNTRUSTED - ', '', os_output)
    os_output = PFIData(data=os_output, attr="os:internal")
    
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
        
    return bash_tool
