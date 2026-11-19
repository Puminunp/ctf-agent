"""Translation tests for the Anthropic adapter. No network: we only exercise the OpenAI<->Messages-API
message/tool translation and the response parser against a fake SDK response."""

import json
import unittest

from ctfagent.anthropic_client import (
    _messages_to_anthropic, _tools_to_anthropic, parse_anthropic,
)
from ctfagent.tools import TOOL_SPECS


class FakeBlock:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none=True):
        return {k: v for k, v in self.__dict__.items() if not (exclude_none and v is None)}


class FakeUsage:
    input_tokens = 123
    output_tokens = 45


class FakeResp:
    def __init__(self, content, stop_reason="tool_use"):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = FakeUsage()
        self.stop_details = None


class ToolTranslation(unittest.TestCase):
    def test_openai_specs_become_anthropic_specs(self):
        out = _tools_to_anthropic(TOOL_SPECS)
        self.assertEqual([t["name"] for t in out], ["run_shell", "read_file", "submit_flag"])
        for t in out:
            self.assertIn("input_schema", t)
            self.assertEqual(t["input_schema"]["type"], "object")
            self.assertNotIn("function", t)


class MessageTranslation(unittest.TestCase):
    def test_system_is_extracted_and_user_text_kept(self):
        system, msgs = _messages_to_anthropic([
            {"role": "system", "content": "be good"},
            {"role": "user", "content": "hi"},
        ])
        self.assertEqual(system, "be good")
        self.assertEqual(msgs, [{"role": "user", "content": [{"type": "text", "text": "hi"}]}])

    def test_assistant_tool_call_and_tool_results_coalesce(self):
        history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "ok",
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "run_shell", "arguments": json.dumps({"command": "ls"})}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "exit_code: 0\nfile.txt"},
        ]
        system, msgs = _messages_to_anthropic(history)
        self.assertEqual(system, "sys")
        # user, assistant(text+tool_use), user(tool_result)
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])
        asst = msgs[1]["content"]
        self.assertEqual(asst[0], {"type": "text", "text": "ok"})
        self.assertEqual(asst[1]["type"], "tool_use")
        self.assertEqual(asst[1]["input"], {"command": "ls"})
        tr = msgs[2]["content"][0]
        self.assertEqual(tr["type"], "tool_result")
        self.assertEqual(tr["tool_use_id"], "c1")

    def test_raw_anthropic_content_is_replayed_verbatim(self):
        raw = [{"type": "thinking", "thinking": "...", "signature": "sig"},
               {"type": "tool_use", "id": "c9", "name": "run_shell", "input": {"command": "id"}}]
        history = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": None, "_anthropic_content": raw},
            {"role": "tool", "tool_call_id": "c9", "content": "root"},
        ]
        _system, msgs = _messages_to_anthropic(history)
        self.assertEqual(msgs[1]["content"], raw)        # thinking signature preserved

    def test_consecutive_tool_results_merge_into_one_user_message(self):
        history = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": None,
             "_anthropic_content": [{"type": "tool_use", "id": "a", "name": "run_shell", "input": {}},
                                    {"type": "tool_use", "id": "b", "name": "read_file", "input": {}}]},
            {"role": "tool", "tool_call_id": "a", "content": "one"},
            {"role": "tool", "tool_call_id": "b", "content": "two"},
        ]
        _system, msgs = _messages_to_anthropic(history)
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])
        self.assertEqual(len(msgs[2]["content"]), 2)      # both tool_results in one user turn, not split


class ResponseParsing(unittest.TestCase):
    def test_text_and_tool_use_parsed(self):
        resp = FakeResp([
            FakeBlock(type="text", text="let me try"),
            FakeBlock(type="tool_use", id="x1", name="run_shell", input={"command": "whoami"}),
        ])
        r = parse_anthropic(resp, 1.0)
        self.assertEqual(r.content, "let me try")
        self.assertEqual(len(r.tool_calls), 1)
        self.assertEqual(r.tool_calls[0].name, "run_shell")
        self.assertEqual(json.loads(r.tool_calls[0].arguments_raw), {"command": "whoami"})
        self.assertEqual(r.input_tokens, 123)
        self.assertEqual(r.output_tokens, 45)
        # the raw blocks travel on the assistant message for replay
        self.assertEqual(len(r.assistant_message["_anthropic_content"]), 2)

    def test_empty_content_gets_a_placeholder_block(self):
        r = parse_anthropic(FakeResp([], stop_reason="end_turn"), 0.1)
        self.assertTrue(r.assistant_message["_anthropic_content"])  # never empty


if __name__ == "__main__":
    unittest.main()
