# The label logger (FR2): records every tool call together with the labels CaMeL gives it.
#
# It wraps CaMeL's policy engine. Every time CaMeL checks a policy, it records:
# - the tool name and the value of each argument
# - for each argument, whether CaMeL labels it trusted, and where it came from (sources)
# - the control context (the dependencies CaMeL passes in: if conditions, for loops and,
#   in STRICT mode, the inputs of query_ai_assistant) and whether any of it is untrusted
# - what the policy would have decided
#
# In observe mode it always returns Allowed, so a denied call still runs. The oracle needs
# this because it compares the calls the plan tries to make, even if a policy would block them.
# With observe=False it returns the real policy decision, so logging never changes behaviour.

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable, Mapping
from typing import Any

from camel.capabilities import get_all_sources, is_public, is_trusted
from camel.interpreter.value import CaMeLValue
from camel.security_policy import Allowed, Denied, SecurityPolicyEngine, SecurityPolicyResult


# Gets the plain Python value out of a CaMeL value, in a form that can be saved as JSON.
def _safe_raw(v: CaMeLValue) -> Any:
    raw = v.raw
    try:
        json.dumps(raw)
        return raw
    except TypeError:
        return repr(raw)


# Lists where a value came from (its sources), as text.
def _sources(v: CaMeLValue) -> list[str]:
    srcs, _ = get_all_sources(v)
    return sorted(str(s) for s in srcs)


# One argument of one call, with its label.
@dataclasses.dataclass
class ArgRecord:
    name: str
    value: Any
    trusted: bool
    public: bool
    sources: list[str]


# One tool call, its arguments, its control context and the policy decision.
@dataclasses.dataclass
class CallRecord:
    index: int
    tool: str
    args: list[ArgRecord]
    control_untrusted: bool
    control_non_public: bool
    control_sources: list[str]
    decision: str
    reason: str | None

    def arg(self, name: str) -> ArgRecord | None:
        return next((a for a in self.args if a.name == name), None)

    def to_json(self) -> dict:
        return dataclasses.asdict(self)


# Wraps CaMeL's policy engine and records every check on an AgentDojo tool.
class LoggingPolicyEngine(SecurityPolicyEngine):
    def __init__(self, inner: SecurityPolicyEngine, logged_tools: Iterable[str], observe: bool = True) -> None:
        self.inner = inner
        self.policies = inner.policies
        self.no_side_effect_tools = inner.no_side_effect_tools
        self.logged_tools = set(logged_tools)
        self.observe = observe
        self.records: list[CallRecord] = []

    def check_policy(
        self,
        tool_name: str,
        kwargs: Mapping[str, CaMeLValue],
        dependencies: Iterable[CaMeLValue],
    ) -> SecurityPolicyResult:
        dependencies = list(dependencies)
        try:
            decision = self.inner.check_policy(tool_name, kwargs, dependencies)
        except Exception as e:  # a policy that crashes is recorded, not hidden
            decision = Denied(f"policy raised {type(e).__name__}: {e}")

        if tool_name in self.logged_tools:
            args = [
                ArgRecord(
                    name=name,
                    value=_safe_raw(v),
                    trusted=is_trusted(v),
                    public=is_public(v),
                    sources=_sources(v),
                )
                for name, v in kwargs.items()
            ]
            control_sources = sorted({s for d in dependencies for s in _sources(d)})
            self.records.append(
                CallRecord(
                    index=len(self.records),
                    tool=tool_name,
                    args=args,
                    control_untrusted=any(not is_trusted(d) for d in dependencies),
                    control_non_public=any(not is_public(d) for d in dependencies),
                    control_sources=control_sources,
                    decision="allowed" if isinstance(decision, Allowed) else "denied",
                    reason=getattr(decision, "reason", None),
                )
            )

        if self.observe:
            return Allowed()
        return decision
