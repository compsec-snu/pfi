# Prompt Flow Integrity (PFI)

[Juhee Kim](https://juppytt.github.io)<sup>1</sup>, [Woohyuk Choi](https://github.com/cw00h)<sup>1</sup>, [Byoungyoung Lee](https://lifeasageek.github.io)<sup>1</sup>
<sup>1</sup> Seoul National University


Prompt Flow Integrity (PFI) is a Language Language Model (LLM) agent
designed to protect LLM agents and user data from privilege escalation
attacks. Read more about PFI in our paper on
[ArXiv](https://arxiv.org/abs/2503.15547).


## Design Overview

PFI separates an LLM agent into **trusted agent** and **untrusted
agent**. Trusted agent handles **trusted data** (e.g., user input,
trusted plugin results), while untrusted agent processes **untrusted
data** retrieved from plugins. PFI grants trusted agent full access to
all plugins, but restricts untrusted agent to access only a subset of
plugins defined by policy.

Even if untrusted agent is compromised by the attacker, the untrusted
agent's capabilities are limited. Furthermore, when the untrusted
agent returns the result to the trusted agent, PFI tracks the data
flow and raises an alert if any unsafe data flow occurs.

Through **agent isolation** and **data tracking**, PFI effectively
prevents privilege escalation attacks in LLM agents. Evaluated on
[Agentdojo](https://github.com/ethz-spylab/agentdojo) and
[AgentBench](https://github.com/THUDM/AgentBench) benchmarks, PFI
enhances the security of LLM agents, achieving a **10x higher
secure-utility rate** compared to the baseline ReAct.

## Setup

### Requirements
- Python 3.11.11
- LLM API Key: To use PFI, you need to obtain an API key to access the
  LLM API you want to use, and set it as an environment variable. 
  You can obtain an API key from the LLM API provider. PFI currently supports following LLM APIs:
    - [OpenAI API](https://platform.openai.com/api-keys) (`OPENAI_API_KEY`)
    - [Anthropic API](https://console.anthropic.com/settings/keys) (`ANTHROPIC_API_KEY`)
    - [Gemini API](https://aistudio.google.com/app/apikey) (`GOOGLE_API_KEY`)

### Installation
To use PFI, follow the steps below:
```shell
# Clone the repository
git clone https://github.com/compsec-snu/pfi.git
cd pfi/src

# (Optional but recommended) Create a conda environment
conda create -n pfi_env python=3.11.11
conda activate pfi_env

# Install the required packages
pip install -r requirements.txt
```

### Run Benchmarks
To run Agentdojo benchmark, use the following command:
```shell
# Run Agentdojo
python run_agentdojo.py --testname={test_name} --agent pfi {agentdojo_args}
```
- Use `--attack important_instructions` for prompt injection tests.
- Use `--attack data_injection` for data injection tests.
- Omit `--attack` for utility tests.

To run the AgentBench benchmark, ensure Docker is installed:
```shell
docker ps
```
Then, build the required Docker image.
```shell
docker pull ubuntu
docker build -f ./benchmarks/AgentBench/data/os_interaction/res/dockerfiles/default ./benchmarks/AgentBench/data/os_interaction/res/dockerfiles --tag local-os/default
```

Finally, run the AgentBench benchmark:
```shell
# Run Agentbench server
python run_agentbench_server.py -a

# Open another terminal and run Agentbench client
python run_agentbench.py --testname={test_name} --agent pfi --model={model_name} -c={test_type}
```
- Use `-c prompt_injection` for prompt injection tests.
- Use `-c data_injection` for data injection tests.
- Use `-c no_injection` for utility tests.

Note that to obtain additional metrics such as SUR and ATR, beyond Utility Score and Attack Success Rate, you must **run all test types (Utility tests, Prompt Injection tests, and Data Injection tests) under the same test name for a single agent and model**. 

### Obtain Results
The results of the benchmarks will be saved in the `agentbench_result` and `agentdojo_result` directories respectively.
Run evaluation scripts to obtain the results in a readable format.
```shell
python summarize_agentdojo.py {test_name}
python summarize_agentbench.py {test_name}
```

## Policies

PFI supports developers to define policies that specify the 
**data trustworthiness** and **agent privileges**. The policies are
written in `.yaml` format.

### How to Write Policies

**`include`**: Specifies a list of configuration files to include. The
included files are merged with the current configuration file.

**`TrustedAgent`**: Defines a list of plugins that trusted agent can
access. By default, trusted agent has full access to all plugins.

Example:
```yaml
TrustedAgent:
  - "*" # Allowing all plugins
```

**`UntrustedAgent`**: Defines a list of plugins that untrusted agent
can access. By default, untrusted agent has no access to any plugins.

Example:
```yaml
UntrustedAgent:
  - get_webpage
```

**`Attributes`**: Specifies the trustworthiness of data attributes,
which can be either trusted (`t`) or untrusted (`u`). A data attribute
is metadata associated with data that indicates its source or
privilege level. By default, all data attributes are untrusted (`u`). 
Wildcard `*` can be used to specify all attributes.

PFI assigns data attributes to all data passed to the agent. If
multiple attributes are specified, the most restrictive attribute is
applied to the data. For example, if data has both trusted and
untrusted attributes, the untrusted attribute is applied.

Example:
```yaml
Attributes:
  - user: t
  - system: t
  - slack:channel:External_*: u
```

# Paper
Read more about Prompt Flow Integrity in our paper! (https://arxiv.org/abs/2503.15547)
## Authors
[Juhee Kim*](https://juppytt.github.io), [Woohyuk Choi*](https://github.com/cw00h), and [Byoungyoung Lee](https://lifeasageek.github.io) (CompSec Lab, Seoul National University) (*: equal contribution)

## Citation
```
@misc{kim2025promptflowintegrityprevent,
      title={Prompt Flow Integrity to Prevent Privilege Escalation in LLM Agents}, 
      author={Juhee Kim and Woohyuk Choi and Byoungyoung Lee},
      year={2025},
      eprint={2503.15547},
      archivePrefix={arXiv},
      primaryClass={cs.CR},
      url={https://arxiv.org/abs/2503.15547}, 
}
```