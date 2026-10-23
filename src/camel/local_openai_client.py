"""OpenAI-compatible client wrapper for local servers such as Ollama.

AgentDojo sends system instructions with the newer OpenAI role "developer"
and as a list of text parts. Ollama expects role "system" and plain text, so
without this wrapper the planner never sees CaMeL's instructions.
"""

import openai


def _to_text(content):
    """Join a list of text parts into one string; leave strings and None alone."""
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content


class _Completions:
    def __init__(self, real_completions):
        self._real = real_completions

    def create(self, **kwargs):
        fixed = []
        for message in kwargs.get("messages", []):
            message = dict(message)
            if message.get("role") == "developer":
                message["role"] = "system"
            message["content"] = _to_text(message.get("content"))
            fixed.append(message)
        kwargs["messages"] = fixed
        return self._real.create(**kwargs)


class _Chat:
    def __init__(self, real_chat):
        self.completions = _Completions(real_chat.completions)


class LocalOpenAIClient:
    """Drop-in replacement for openai.OpenAI when talking to a local server."""

    def __init__(self, **kwargs):
        self._client = openai.OpenAI(**kwargs)
        self.chat = _Chat(self._client.chat)

    def __getattr__(self, name):
        return getattr(self._client, name)