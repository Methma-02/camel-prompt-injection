from camel.local_openai_client import LocalOpenAIClient


class _FakeCompletions:
    def __init__(self):
        self.sent = None

    def create(self, **kwargs):
        self.sent = kwargs
        return "ok"


def _client_with_fake():
    client = LocalOpenAIClient(api_key="test", base_url="http://localhost:1/v1")
    fake = _FakeCompletions()
    client.chat.completions._real = fake
    return client, fake


def test_developer_role_becomes_system():
    client, fake = _client_with_fake()
    client.chat.completions.create(
        model="m", messages=[{"role": "developer", "content": [{"type": "text", "text": "RULES"}]}]
    )
    assert fake.sent["messages"] == [{"role": "system", "content": "RULES"}]


def test_text_parts_are_joined_and_other_fields_kept():
    client, fake = _client_with_fake()
    client.chat.completions.create(
        model="m",
        temperature=0,
        messages=[{"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}],
    )
    assert fake.sent["messages"][0] == {"role": "user", "content": "ab"}
    assert fake.sent["temperature"] == 0


def test_none_content_is_left_alone():
    client, fake = _client_with_fake()
    client.chat.completions.create(model="m", messages=[{"role": "assistant", "content": None, "tool_calls": []}])
    assert fake.sent["messages"][0]["content"] is None