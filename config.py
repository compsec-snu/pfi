from typing import Literal, TypedDict

class Config():
    """Configuration for the PFI agent."""
    def __init__(
            self,
            unsafe_dataflow_choice: Literal["UNSAFE_DATAFLOW_YES", "UNSAFE_DATAFLOW_NO", "UNSAFE_DATAFLOW_HUMAN"] = "UNSAFE_DATAFLOW_YES", 
            log_level: Literal["DEBUG", "NORMAL", "BENCHMARK"] = "BASIC",
            policy: str = None,
    ):
        self.unsafe_dataflow_choice = unsafe_dataflow_choice
        self.log_level = log_level
        self.policy = policy

    def set_options(
            self,
            unsafe_dataflow_choice: Literal["UNSAFE_DATAFLOW_YES", "UNSAFE_DATAFLOW_NO", "UNSAFE_DATAFLOW_HUMAN"] = "UNSAFE_DATAFLOW_YES", 
            log_level: Literal["DEBUG", "BASIC", "BENCHMARK"] = "BASIC",
            policy: str = None,
    ):
        self.unsafe_dataflow_choice = unsafe_dataflow_choice
        self.log_level = log_level
        self.policy = policy

        return self

# Don't instantiate new config object in other files, use this global config object
# You can change the configuration by calling set_options method
config = Config()