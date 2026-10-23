# The pilot for the counterfactual label oracle.
# None of this changes CaMeL's interpreter or policies. The logger wraps the policy engine
# from the outside, and the oracle re-runs a fixed plan on edited data and compares the calls.

# AgentDojo breaks (circular import) if a suite is imported before agentdojo.task_suite,
# so we import it first. CaMeL's main.py does the same thing through get_suite.
import agentdojo.task_suite  # noqa: F401
