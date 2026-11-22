"""Test doubles shared by several test files."""


class FakeTelegram:
    """Stands in for TelegramClient: feed it incoming messages, read what was sent."""

    def __init__(self, incoming=None, files=None):
        self.incoming = list(incoming or [])
        self.files = dict(files or {})
        self.sent: list[tuple[int, str]] = []
        self.markups: list = []  # each text's reply_markup (None for a plain one)
        self.albums: list[tuple[int, list]] = []
        self.pictures: list[tuple[int, list, str]] = []

    def get_updates(self):
        out, self.incoming = self.incoming, []
        return out

    def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text))
        self.markups.append(reply_markup)

    def send_chat_action(self, chat_id, action="typing"):
        pass

    def send_album(self, chat_id, photos):
        self.albums.append((chat_id, list(photos)))

    def send_pictures(self, chat_id, images, caption):
        self.pictures.append((chat_id, list(images), caption))

    def download_file(self, file_id):
        return self.files[file_id]


def tool_use(name, input, id=None):
    """A scripted `tool_use` block for `FakeClaude` replies (an SDK-like object)."""
    from types import SimpleNamespace as NS

    tool_use.count += 1
    return NS(type="tool_use", id=id or f"toolu_{tool_use.count}", name=name, input=input)


tool_use.count = 0


class FakeClaude:
    """Stands in for `anthropic.Anthropic`: `messages.create` returns queued replies.

    Pass it as the `client` of `llm.Claude`. `calls` keeps every request's keyword arguments.
    Each reply is a string (one text block) or a list of blocks, where a string is a text
    block and `tool_use(name, input)` is a tool call, e.g.
    `FakeClaude([[tool_use("log_sets", {...})], "Logged."])` scripts one tool round, then text.
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
        reply = self.replies.pop(0) if self.replies else "ok"
        blocks = reply if isinstance(reply, list) else [reply]
        content = [NS(type="text", text=b) if isinstance(b, str) else b for b in blocks]
        return NS(
            content=content,
            usage=NS(input_tokens=self.input_tokens, output_tokens=self.output_tokens),
        )
