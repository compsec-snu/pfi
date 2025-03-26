import sys,os
import io
from langchain_openai import ChatOpenAI
from pfi_agent import *
import logging
from rich.logging import RichHandler

agentdojo_path = os.path.join(os.path.dirname(__file__), 'benchmarks', 'agentdojo')
sys.path.append(agentdojo_path)
from benchmarks.agentdojo.scripts import benchmark

if __name__ == "__main__":
    format = "%(message)s"
    logging.basicConfig(
        format=format,
        level=logging.INFO,
        datefmt="%H:%M:%S",
        handlers=[RichHandler(show_path=False, markup=True)],
    )

    # if testname is not provided in the argument, set it to "test-{last_commit_id}"
    has_testname = False
    for i in range(len(sys.argv)):
        if "--testname" in sys.argv[i]:
            has_testname = True
            break
    if not has_testname:
        last_commit_id = os.popen("git rev-parse --short HEAD").read().strip()
        testname = "pfi-" + last_commit_id
        sys.argv.append("--testname")
        sys.argv.append(testname)

    benchmark.main(sys.argv[1:])