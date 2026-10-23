"""FR2: Record tool calls and the labels CaMeL assigns to them.

LoggingPolicyEngine wraps the existing CaMeL security policy engine and records
the details of each tool call, including:

- the tool name and argument values,
- whether each argument is trusted and public, and its sources,
- whether the control dependencies contain untrusted or non-public data,
- whether the original policy allows or denies the call.

In observe mode, every call is allowed to continue, even if the original
policy would deny it. This lets the oracle compare the calls the plan makes
with the labels CaMeL assigns to them.

In enforce mode, the original policy decision is kept, so the logger does
not change whether a call is allowed or denied.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable, Mapping
from typing import Any

from camel.capabilities import get_all_sources, is_public, is_trusted
from camel.interpreter.value import CaMeLValue
from camel.security_policy import Allowed, Denied, SecurityPolicyEngine, SecurityPolicyResult


def _safe_raw(v: CaMeLValue) -> Any:
    """A JSON-friendly version of a CaMeL value's raw Python value."""
    raw = v.raw
    try:
        json.dumps(raw)
        return raw
    except TypeError:
        return repr(raw)


def _sources(v: CaMeLValue) -> list[str]:
    srcs, _ = get_all_sources(v)
    return sorted(str(s) for s in srcs)


@dataclasses.dataclass
class ArgRecord:
    name: str
    value: Any
    trusted: bool
    public: bool
    sources: list[str]


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


class LoggingPolicyEngine(SecurityPolicyEngine):
    """Wraps a CaMeL policy engine and records every check on an AgentDojo tool."""

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
