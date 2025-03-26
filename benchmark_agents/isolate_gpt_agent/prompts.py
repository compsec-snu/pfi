HUB_PROMPT = """
Objective:
Your objective is to create a sequential workflow based on the users query.

Create a plan represented in JSON by only using the tools listed below. 
The workflow should be a valid JSON array containing only the tool name, function name and input. 
A step in the workflow can receive the output from a previous step as input.

Output example 1:
{output_format}

Tools: {tools}

You MUST STRICTLY follow the above provided output examples. DO NOT include any comments, explanations, or extra text — only return the valid JSON output.
"""

HUB_OUTPUT_FORMAT = """
{
    "steps": 
    [
        {
            "name": "Tool name 1",
            "input": {
                "query": str
            },
            "output": "result_1"
        },
        {
            "name": "Tool name 2",
            "input": {
                "input": "<result_1>"
            },
            "output": "result_2"
        },
        {
            "name": "Tool name 3",
            "input": {
                "query": str
            },
            "output": "result_3"
        }
    ]
}
"""

SPOKE_PROMPT = """
Respond to the human as helpfully and accurately as possible. 
Use tools if necessary. 
"""