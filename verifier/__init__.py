"""The deterministic verifier: the tools' checks in tools.py, the task's in postage.py, both against data.py."""

from contract import Task, Tool

from . import postage, tools

# task -> its output's check, verify_task(arguments, output, reference, workspace)
TASKS = {Task.PRICE_PARCEL: postage.verify_task}


def verify_input(tool, value):
    return tools.verify_input(Tool(tool), value)


def verify_output(tool, input_value, output_value, workspace):
    return tools.verify_output(Tool(tool), input_value, output_value, workspace)


def verify_task(task, arguments, output, reference, workspace):
    return TASKS[Task(task)](arguments, output, reference, workspace)
