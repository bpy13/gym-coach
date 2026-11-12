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
