import asyncio, json, os, sys, unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ministral_tools as mt

NAMES = {"read_file", "list_dir"}


def resp(content, tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")])


def run(data, response):
    return asyncio.run(mt.handler.async_post_call_success_hook(data, None, response))


class ParseCalls(unittest.TestCase):
    def test_single_call(self):
        self.assertEqual(mt.parse_calls('read_file[ARGS]{"path": "/workspace/notes.txt"}', NAMES), [("read_file", '{"path": "/workspace/notes.txt"}')])

    def test_marker_prefix_and_whitespace(self):
        self.assertEqual(mt.parse_calls('  [TOOL_CALLS]list_dir[ARGS]{"path": "."}\n', NAMES), [("list_dir", '{"path": "."}')])

    def test_several_calls_in_a_row(self):
        got = mt.parse_calls('read_file[ARGS]{"path": "a"}\nlist_dir[ARGS]{"path": "b"}', NAMES)
        self.assertEqual([n for n, _ in got], ["read_file", "list_dir"])

    def test_nested_json_and_braces_in_strings(self):
        got = mt.parse_calls('read_file[ARGS]{"path": "a}b", "opts": {"x": [1, {"y": 2}]}}', NAMES)
        self.assertEqual(json.loads(got[0][1])["opts"]["x"][1]["y"], 2)

    def test_not_a_call_is_left_alone(self):
        for text in ("Hello there", "", None, "I will call read_file[ARGS]{broken", 'read_file[ARGS]{"path": "a"} and then some prose',
                     'unknown_tool[ARGS]{"a": 1}', 'read_file[ARGS][1, 2]', 'The tag [ARGS] appears in prose.'):
            self.assertIsNone(mt.parse_calls(text, NAMES), text)


class Hook(unittest.TestCase):
    TOOLS = [{"type": "function", "function": {"name": "read_file"}}]

    def test_text_tool_call_becomes_structured(self):
        r = run({"tools": self.TOOLS}, resp('read_file[ARGS]{"path": "/x"}'))
        m = r.choices[0].message
        self.assertIsNone(m.content)
        self.assertEqual(r.choices[0].finish_reason, "tool_calls")
        self.assertEqual((m.tool_calls[0].function.name, json.loads(m.tool_calls[0].function.arguments)), ("read_file", {"path": "/x"}))
        self.assertTrue(m.tool_calls[0].id.startswith("call_"))

    def test_no_tools_in_request_leaves_the_text(self):
        r = run({}, resp('read_file[ARGS]{"path": "/x"}'))
        self.assertEqual(r.choices[0].message.content, 'read_file[ARGS]{"path": "/x"}')
        self.assertIsNone(r.choices[0].message.tool_calls)

    def test_tool_not_in_the_request_is_not_converted(self):
        r = run({"tools": self.TOOLS}, resp('delete_all[ARGS]{"path": "/"}'))
        self.assertIsNone(r.choices[0].message.tool_calls)

    def test_existing_tool_calls_and_plain_answers_are_untouched(self):
        existing = [SimpleNamespace(id="c1")]
        self.assertEqual(run({"tools": self.TOOLS}, resp(None, existing)).choices[0].message.tool_calls, existing)
        r = run({"tools": self.TOOLS}, resp("The file says hello."))
        self.assertEqual((r.choices[0].message.content, r.choices[0].message.tool_calls), ("The file says hello.", None))

    def test_a_malformed_response_never_raises(self):
        for bad in (None, SimpleNamespace(), SimpleNamespace(choices=[SimpleNamespace(message=None)]), SimpleNamespace(choices=7)):
            run({"tools": self.TOOLS}, bad)


if __name__ == "__main__":
    unittest.main()
