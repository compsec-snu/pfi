from default_suites.v1.travel.injection_tasks import (
    InjectionTask0,
    InjectionTask1,
    InjectionTask2,
    InjectionTask3,
    InjectionTask4,
    InjectionTask5,
    # InjectionTask6,
)
from default_suites.v1.travel.task_suite import TravelEnvironment
from default_suites.v1.travel.task_suite import task_suite as travel_task_suite_v1
from task_suite.task_suite import TaskSuite

task_suite = TaskSuite[TravelEnvironment]("travel",
                                        TravelEnvironment, 
                                        travel_task_suite_v1.tools,
                                        travel_task_suite_v1.envs)
injection_tasks = [
    InjectionTask0,
    InjectionTask1,
    InjectionTask2,
    InjectionTask3,
    InjectionTask4,
    InjectionTask5,
    # InjectionTask6,
]

for inj_task in injection_tasks:
    task_suite.register_injection_task(inj_task)
