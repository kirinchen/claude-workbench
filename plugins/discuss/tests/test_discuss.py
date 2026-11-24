import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "discuss.py")
spec = importlib.util.spec_from_file_location("discuss", SCRIPT)
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)

SID = "81aa343c-cc3d-4dbd-8346-20cf23d5f02a"


def user(text, **kw):
    return {"type": "user", "message": {"content": text}, "timestamp": "2026-11-24T01:00:00.000Z", **kw}


def bot(text, **kw):
    return {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
        "timestamp": "2026-11-24T01:00:05.000Z",
        **kw,
    }


class Render(unittest.TestCase):
    def test_porthole_headers(self):
        out, _ = D.render([user("hi"), bot("yo")], [])
        self.assertIn("## 🧑 Human · 2026-11-24T01:00:00.000Z\n\nhi\n", out)
        self.assertIn("## 🤖 Assistant · 2026-11-24T01:00:05.000Z\n\nyo\n", out)

    def test_relayed_message_is_not_logged_again(self):
        out, _ = D.render([user("[porthole] hi"), bot("yo")], [])
        self.assertNotIn("Human", out)
        self.assertIn("yo", out)

    def test_relayed_message_wrapped_as_paste(self):
        out, _ = D.render([user('<pasted_content id="ab12">\n[porthole] a\nb\n</pasted_content>')], [])
        self.assertEqual(out, "")
        out, _ = D.render([user('<hc from="t74 x">[porthole] a</hc>')], [])
        self.assertEqual(out, "")

    def test_prompt_logged_on_submit_is_skipped_once(self):
        out, pending = D.render([user("hi"), bot("1"), user("hi"), bot("2")], ["hi"])
        self.assertEqual(out.count("Human"), 1)
        self.assertEqual(pending, [])

    def test_consecutive_assistant_texts_merge(self):
        out, _ = D.render([user("q"), bot("a"), bot("b")], [])
        self.assertEqual(out.count("Assistant"), 1)
        self.assertIn("a\n\nb", out)

    def test_answers_to_different_relayed_messages_stay_apart(self):
        out, _ = D.render([user("[porthole] q1"), bot("a"), user("[porthole] q2"), bot("b")], [])
        self.assertEqual(out.count("Assistant"), 2)

    def test_noise_is_dropped(self):
        recs = [
            user("<command-message>x</command-message>\n<command-name>/x</command-name>"),
            user("meta", isMeta=True),
            user("side", isSidechain=True),
            bot("side", isSidechain=True),
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "r"}]}},
            {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "t"}]}},
            user("<local-command-stdout>x</local-command-stdout>"),
            {},
        ]
        self.assertEqual(D.render(recs, [])[0], "")

    def test_queued_while_working(self):
        rec = {"type": "attachment", "attachment": {"type": "queued_command", "prompt": "later"}}
        self.assertIn("later", D.render([rec], [])[0])
        rec["attachment"]["prompt"] = "[porthole] later"
        self.assertEqual(D.render([rec], [])[0], "")


class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "repo")
        os.makedirs(os.path.join(self.root, "doc", "chat"))
        self.state = os.path.join(self.tmp.name, "state")
        self.thread = os.path.join(self.root, "doc", "chat", "t.md")
        open(self.thread, "w").close()
        self.tr = os.path.join(self.tmp.name, "tr.jsonl")
        self.bp = os.path.join(self.state, "porthole", "bindings", f"{SID}.json")
        self.bind(cursor=0)

    def tearDown(self):
        self.tmp.cleanup()

    def bind(self, **kw):
        os.makedirs(os.path.dirname(self.bp), exist_ok=True)
        b = {"v": 1, "session_id": SID, "repo": "repo", "root": self.root, "thread": "t", "link": "a.md",
             "cwd": self.root, "terminal": "t7", "pid": 1, "ended_at": None, "pending": [], **kw}
        with open(self.bp, "w") as fh:
            json.dump(b, fh)

    def binding(self):
        with open(self.bp) as fh:
            return json.load(fh)

    def write(self, *recs):
        with open(self.tr, "w") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")

    def fire(self, event, env=None, sid=SID, **kw):
        e = {k: v for k, v in os.environ.items() if k not in ("PORTHOLE_RELAY", "PORTHOLE_STATE_DIR", "HC_TERMINAL_ID")}
        e.update({"XDG_STATE_HOME": self.state, **(env or {})})
        r = subprocess.run(
            [sys.executable, SCRIPT, "hook"], text=True, capture_output=True, env=e,
            input=json.dumps({"hook_event_name": event, "session_id": sid, "transcript_path": self.tr, **kw}),
        )
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def text(self):
        with open(self.thread) as fh:
            return fh.read()

    def test_submit_then_stop_logs_each_side_once(self):
        self.fire("UserPromptSubmit", prompt="hi")
        self.assertEqual(self.text().count("hi"), 1)
        self.write(user("hi"), bot("yo"))
        self.fire("Stop", last_assistant_message="yo")
        self.fire("Stop", last_assistant_message="")
        self.assertEqual((self.text().count("hi"), self.text().count("yo")), (1, 1))
        self.assertEqual(self.binding()["pending"], [])

    def test_relayed_prompt_not_logged_on_submit(self):
        self.fire("UserPromptSubmit", prompt="[porthole] hi")
        self.assertEqual(self.text(), "")

    def test_resumed_by_porthole_only_moves_the_cursor(self):
        self.write(user("hi"), bot("yo"))
        self.bind(cursor=0, ended_at="2026-11-24T00:00:00Z")
        relay = {"PORTHOLE_RELAY": "1"}
        self.fire("SessionStart", relay)
        self.fire("UserPromptSubmit", relay, prompt="hi")
        self.fire("Stop", relay, last_assistant_message="yo")
        self.fire("SessionEnd", relay)
        self.assertEqual(self.text(), "")
        self.assertEqual(self.binding()["cursor"], 2)
        self.assertEqual(self.binding()["ended_at"], "2026-11-24T00:00:00Z")

    def test_end_marks_closed_and_start_reopens(self):
        self.write()
        self.fire("SessionEnd")
        self.assertTrue(self.binding()["ended_at"])
        self.fire("SessionStart")
        b = self.binding()
        self.assertIsNone(b["ended_at"])
        self.assertIsNone(b["terminal"])  # no hc here → one-way

    def test_turns_porthole_ran_while_closed_are_not_logged_on_return(self):
        self.write(user("a"), bot("b"))
        self.fire("SessionEnd")
        self.write(user("a"), bot("b"), user("via porthole"), bot("ok"))
        self.fire("SessionStart")
        self.write(user("a"), bot("b"), user("via porthole"), bot("ok"), user("back"), bot("hello"))
        self.fire("Stop", last_assistant_message="hello")
        self.assertNotIn("via porthole", self.text())
        self.assertIn("hello", self.text())

    def test_renamed_thread_is_followed_and_deleted_binding_stops(self):
        self.write(user("a"), bot("b"))
        os.rename(self.thread, os.path.join(self.root, "doc", "chat", "new.md"))
        self.bind(cursor=0, thread="new")
        self.fire("Stop", last_assistant_message="b")
        self.assertFalse(os.path.exists(self.thread))
        os.remove(self.bp)
        self.write(user("a"), bot("b"), user("c"), bot("d"))
        self.fire("Stop", last_assistant_message="d")
        with open(os.path.join(self.root, "doc", "chat", "new.md")) as fh:
            self.assertNotIn("d\n", fh.read().split("b\n")[-1])

    def test_unbound_session_and_bad_input_are_ignored(self):
        self.fire("Stop", sid="00000000-0000-0000-0000-000000000000")
        self.fire("Stop", sid="../../x")
        self.assertEqual(self.text(), "")

    def test_thread_name_cannot_escape(self):
        self.bind(cursor=0, thread="../../x")
        self.write(user("a"), bot("b"))
        self.fire("Stop", last_assistant_message="b")
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "x.md")))


class Locate(unittest.TestCase):
    def test_base_and_files(self):
        with tempfile.TemporaryDirectory() as t:
            t = os.path.realpath(t)
            root = os.path.join(t, "demo")
            os.makedirs(os.path.join(root, "sub"))
            self.assertEqual(D.locate_repo(t, os.path.join(root, "sub")), ("demo", root))
            for bad in (t, os.path.dirname(t)):
                with self.assertRaises(D.Fail):
                    D.locate_repo(t, bad)
            rel, path, created = D.resolve_file(root, os.path.join(root, "sub"), "note")
            self.assertEqual((rel, created), ("sub/note.md", True))
            self.assertEqual(D.resolve_file(root, root, "sub/note.md")[2], False)
            for bad in ("../x.md", "sub", ".git/x.md", "nope.png"):
                with self.assertRaises(D.Fail):
                    D.resolve_file(root, root, bad)


if __name__ == "__main__":
    unittest.main()
