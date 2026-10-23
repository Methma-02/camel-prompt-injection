"""I0 feasibility spike for the counterfactual label oracle.

Nothing in this package changes CaMeL's interpreter or security policies. The label
logger wraps the policy engine from the outside, and the oracle re-runs a fixed plan
on edited untrusted data and compares the tool calls.
"""

# AgentDojo has a circular import if a suite module is imported before
# `agentdojo.task_suite`; importing it first (as CaMeL's main.py does via get_suite) avoids it.
import agentdojo.task_suite  # noqa: F401
