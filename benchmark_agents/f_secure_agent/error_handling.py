import re
error_messages = ["Error: ValueError", "Error: ChatGoogleGenerativeAIError"]

def process_error_message(message, state):
    msg = message.content
    
    # Remove the error message and leave only the error prompt
    # e.g., "Error: ValueError('xxx')" -> "xxx"
    for error_message in error_messages:
        if error_message in msg:
            msg = re.sub(rf"{error_message}\((.*)\)", r"\1", msg).strip("'").strip('"')
            break
    # If there is a proxy from the previous tool call, suggest using the proxy
    if state.get("proxies"):
        proxies = state["proxies"]
        msg += " REMINDER: You can use following proxies: " + ", ".join(s['proxy'] for s in proxies)+"."
    message.content = msg
    return message
