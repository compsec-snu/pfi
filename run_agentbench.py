import sys,os
from pfi_agent import *

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'benchmarks/AgentBench')))
from benchmarks.AgentBench.src import assigner

if not os.environ.get("OPENAI_API_KEY"):
    print("Please set the OPENAI_API_KEY environment variable.")
    exit()

if __name__ == "__main__":
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
    
    assigner.main(sys.argv[1:])