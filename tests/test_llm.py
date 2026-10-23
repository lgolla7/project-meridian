"""The chat client posts a real chat-completions request. The test stubs the socket."""

import json
import os
import unittest
from unittest import mock

from app.llm import ChatClient, client_from_env


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps({
            "choices": [{"message": {"content": "The window frame is 6061 on drawing D-005."}}]
        }).encode()


class LlmTests(unittest.TestCase):
    def test_complete_posts_chat_completions(self):
        client = ChatClient("test-key", "gpt-4o-mini", "https://api.openai.com/v1")
        with mock.patch("app.llm.urllib.request.urlopen", return_value=FakeResponse()) as opened:
            text = client.complete("What is the window frame made of?", "D-005 material callout: 6061")
        self.assertIn("6061", text)
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        body = json.loads(request.data.decode())
        self.assertEqual(body["model"], "gpt-4o-mini")
        self.assertIn("D-005", body["messages"][1]["content"])
        self.assertIn("window frame", body["messages"][1]["content"])

    def test_client_from_env_requires_a_key(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            self.assertIsNone(client_from_env())
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test", "OPENAI_MODEL": "demo"}, clear=False):
            client = client_from_env()
        self.assertEqual(client.model, "demo")
        self.assertEqual(client.api_key, "sk-test")


if __name__ == "__main__":
    unittest.main()
