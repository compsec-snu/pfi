from typing import Literal, Any, List

class UnsafeDataflowWarning:
    def __init__(
        self, 
        data_flow_type: Literal["Explicit control flow", "Explicit data flow", "Implicit flow"],
        proxy_value: List[Any], 
        submessage_index: List[int],
        data_sink: dict[str, str],
        args: List[str] | None = None,
        data_attribute: List[str] | None = None,
    ):
        # Dataflow Type
        self.data_flow_type = data_flow_type
        # Data Source
        self.proxy_value = proxy_value
        self.submessage_index = submessage_index
        self.data_attribute = data_attribute
        # Data Sink
        # - Message content: {"type": "content"}
        # - Tool call: {"type": "tool_call", "tool_name": send_sms}
        # - Trusted agent context: {"type": "trusted_agent_context"}
        self.data_sink = data_sink
        self.args = args

    def __str__(self):
        if self.data_sink.get("type") == "tool_call":
            data_sink_str = (
                f"Untrusted data was used in a tool call with the tool '{self.data_sink.get('tool_name')}' "
                f"and the argument '{self.args}'"
            )
        elif self.data_sink.get("type") == "content":
            data_sink_str = "Untrusted data was included in the agent's final answer."
        elif self.data_sink.get("type") == "trusted_agent_context":
            data_sink_str = "Untrusted data was used in the trusted agent's context."
        else:
            data_sink_str = "The location where untrusted data is being used is unknown."

        return (
            "================================================================================\n"
            f"Warning: Potential Unsafe Data Flow Detected!\n"
            f"- Data Flow Type: {self.data_flow_type}\n"
            f"- Proxy Value: {self.proxy_value}\n"
            f"- Submessage Index: {self.submessage_index}\n"
            f"- Data Attribute: {self.data_attribute if self.data_attribute else 'None specified'}\n"
            f"- Data Sink: {data_sink_str}\n"
            "================================================================================\n"
        )

    def to_dict(self):
        return {
            "data_flow_type": self.data_flow_type,
            "proxy_value": self.proxy_value,
            "submessage_index": self.submessage_index,
            "data_attribute": self.data_attribute,
            "data_sink": self.data_sink,
            "args": self.args,
        }
