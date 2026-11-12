"""Test doubles shared by several test files."""


class FakeTelegram:
    """Stands in for TelegramClient: feed it incoming messages, read what was sent."""

    def __init__(self, incoming=None, files=None):
        self.incoming = list(incoming or [])
        self.files = dict(files or {})
        self.sent: list[tuple[int, str]] = []

    def get_updates(self):
        out, self.incoming = self.incoming, []
        return out

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))

    def download_file(self, file_id):
        return self.files[file_id]


class FakeClaude:
    """Stands in for `anthropic.Anthropic`: `messages.create` returns queued replies.

    Pass it as the `client` of `llm.Claude`. `calls` keeps every request's keyword arguments.
    """

    def __init__(self, replies=(), input_tokens=1000, output_tokens=200):
        self.replies = list(replies)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        from types import SimpleNamespace as NS

        self.calls.append(kwargs)
        text = self.replies.pop(0) if self.replies else "ok"
        return NS(
            content=[NS(type="text", text=text)],
            usage=NS(input_tokens=self.input_tokens, output_tokens=self.output_tokens),
        )
