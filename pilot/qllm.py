# The quarantined LLM used by the pilot.
#
# - "stub": a simple rule-based extractor written for these 4 plans. It always gives the
#   same answer, so it tests the oracle without any model noise.
# - anything else, for example "openai:llama31-camel": the model name is passed to CaMeL's
#   own query_quarantined_llm, the same way PrivilegedLLM does. With uv run --env-file .env,
#   OPENAI_BASE_URL sends it to the local Ollama server, same as the main.py runs.

import re
from typing import TypeVar

from pydantic import BaseModel

from camel import quarantined_llm

_T = TypeVar("_T", bound=str | int | float | BaseModel)

_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
_TOTAL = re.compile(r"Total\s+([0-9]+(?:\.[0-9]+)?)")
_INCREASE = re.compile(r"increased\s+by\s+([0-9]+(?:\.[0-9]+)?)")


def _stub_extract(query: str, output_schema: type) -> object:
    fields = set(getattr(output_schema, "model_fields", {}).keys())
    text = query.replace("\\t", "\t").replace("\\n", "\n")
    out: dict[str, object] = {}
    if "iban" in fields:
        m = _IBAN.search(text)
        if m is None:
            raise quarantined_llm.NotEnoughInformationError()
        out["iban"] = m.group(0)
    if "amount" in fields and "increase" not in fields:
        m = _TOTAL.search(text)
        if m is None:
            raise quarantined_llm.NotEnoughInformationError()
        out["amount"] = float(m.group(1))
    if "increase" in fields:
        m = _INCREASE.search(text)
        out["increase"] = m is not None
        out["amount"] = float(m.group(1)) if m else 0.0
    if "street" in fields or "city" in fields:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        street = next((ln for ln in lines if re.search(r"\d", ln) and "Street" in ln), None)
        city = next((ln.split(",")[0] for ln in lines if re.search(r",\s*[A-Z]{2}\s*\d{5}", ln)), None)
        if street is None or city is None:
            raise quarantined_llm.NotEnoughInformationError()
        out["street"], out["city"] = street, city
    missing = fields - set(out)
    if missing:
        raise quarantined_llm.NotEnoughInformationError()
    return output_schema(**out)


# CaMeL's PrivilegedLLM also gives the quarantined LLM 10 retries.
QLLM_RETRIES = 10


# Makes the query_ai_assistant function that the plans call.
def make_query_ai_assistant(backend: str):
    if backend == "stub":

        def query_ai_assistant(query: str, output_schema: type[_T]) -> _T:
            return _stub_extract(query, output_schema)  # type: ignore[return-value]

    else:
        model = backend

        def query_ai_assistant(query: str, output_schema: type[_T]) -> _T:
            return quarantined_llm.query_quarantined_llm(
                llm=model, query=query, output_schema=output_schema, retries=QLLM_RETRIES
            )

    query_ai_assistant.__doc__ = quarantined_llm.query_quarantined_llm.__doc__
    return query_ai_assistant
