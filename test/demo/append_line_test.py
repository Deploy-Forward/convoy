"""One whole line per append: never lost to a concurrent writer, never glued to a torn tail.

Every JSONL store appends through one helper. It holds a short OS lock on a sidecar `<file>.lock`
for the append, so concurrent writers in many processes never overwrite each other's rows (the
Windows C runtime appends by seek-then-write, which is not atomic across processes). Under the lock
it closes a torn tail and writes the row. The lock is re-entrant within a thread, so a caller that
already holds it (a drain, a Stop hook) can append without waiting on itself.

A writer killed mid-row leaves the file without its last newline. Appending straight after it
would glue the next row onto the torn bytes, and a reader would lose both. The shared append
helper writes a newline first when the last byte is not one, so the torn tail stays one bad line
and the next row stays whole. The feed and the wake outbox both append through it.
"""
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[2] / "src")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.layer import append_line, hook  # noqa: E402
from convoy.wake_dispatch import _append, outbox_path, read_outbox  # noqa: E402


def exclusive(path):
    from convoy.filelock import exclusive as held
    return held(path)


def raw(path):
    """The bytes, line-ending neutral: on Windows the append is a text-mode write and ends in CRLF."""
    return path.read_bytes().replace(b"\r\n", b"\n")


def lines(path):
    return raw(path).decode("utf-8").split("\n")


def race(code, n, root):
    """Run `code` in n processes that start together; `code` sees `W` (0..n-1) and `R` (the root)."""
    go = Path(root) / "go"
    script = ("import sys, time, json; sys.path.insert(0, %r)\n"
              "from pathlib import Path\n"
              "W = int(sys.argv[1]); R = Path(sys.argv[2])\n"
              "while not (R / 'go').exists(): time.sleep(0.005)\n" % SRC) + code
    procs = [subprocess.Popen([sys.executable, "-c", script, str(w), str(root)], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) for w in range(n)]
    time.sleep(0.5)
    go.write_text("go", encoding="utf-8")
    outs = []
    for p in procs:
        out, err = p.communicate(timeout=180)
        if p.returncode != 0:
            raise AssertionError(err)
        outs.append(out)
    return outs


def endings_consistent(path):
    data = path.read_bytes()
    return data.count(b"\r\n") in (0, data.count(b"\n"))


class AppendLine(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.path = self.root / "rows.jsonl"

    def test_a_new_file_starts_with_the_row(self):
        append_line(self.path, b'{"a":1}\n')
        self.assertEqual(raw(self.path), b'{"a":1}\n')

    def test_a_whole_tail_takes_no_extra_newline(self):
        self.path.write_bytes(b'{"a":1}\n')
        append_line(self.path, b'{"b":2}\n')
        self.assertEqual(raw(self.path), b'{"a":1}\n{"b":2}\n')

    def test_a_torn_tail_is_closed_before_the_next_row(self):
        self.path.write_bytes(b'{"a":1}\n{"torn":')
        append_line(self.path, b'{"b":2}\n')
        self.assertEqual(raw(self.path), b'{"a":1}\n{"torn":\n{"b":2}\n')

    def test_an_empty_file_takes_no_leading_newline(self):
        self.path.write_bytes(b"")
        append_line(self.path, b'{"b":2}\n')
        self.assertEqual(raw(self.path), b'{"b":2}\n')

    def test_line_endings_stay_consistent(self):
        for n in range(5):
            append_line(self.path, (json.dumps({"n": n}) + "\n").encode("utf-8"))
        self.assertTrue(endings_consistent(self.path), "every line ends the same way")

    def test_a_holder_of_the_lock_appends_without_waiting_on_itself(self):
        started = time.monotonic()
        with exclusive(self.path):
            append_line(self.path, b'{"a":1}\n')
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual(raw(self.path), b'{"a":1}\n')


class Durability(unittest.TestCase):
    """A drained message is never lost to a failed fsync, and a sent one is synced."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_a_drain_whose_fsync_fails_still_hands_over_its_rows(self):
        from unittest import mock
        from convoy.inbox import drain, enqueue
        enqueue(self.root, "neuron-b-thread", "body", to="claude", token="a" * 32)
        with mock.patch("convoy.filelock.os.fsync", side_effect=OSError(5, "I/O error")):
            rows = drain(self.root, "neuron-b-thread")
        self.assertEqual([r["token"] for r in rows], ["a" * 32], "marked consumed, so it must be handed over")

    def test_a_drain_whose_write_fails_marks_nothing_and_is_retried(self):
        from unittest import mock
        from convoy.inbox import drain, enqueue, pending
        enqueue(self.root, "neuron-b-thread", "body", to="claude", token="b" * 32)
        with mock.patch("convoy.filelock.os.write", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(OSError):
                drain(self.root, "neuron-b-thread")
        self.assertEqual([r["token"] for r in pending(self.root, "neuron-b-thread")], ["b" * 32])
        self.assertEqual([r["token"] for r in drain(self.root, "neuron-b-thread")], ["b" * 32])

    def test_a_sent_message_is_synced_to_disk(self):
        from unittest import mock
        from convoy.inbox import enqueue
        import convoy.filelock as fl
        synced = []
        real = fl.os.fsync
        with mock.patch("convoy.filelock.os.fsync", side_effect=lambda fd: synced.append(fd) or real(fd)):
            row = enqueue(self.root, "neuron-b-thread", "body", to="claude", token="c" * 32)
        self.assertEqual(len(synced), 1)
        self.assertTrue(row["durable"])


class ConcurrentWriters(unittest.TestCase):
    """Real processes, started together, appending to one file."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def rows(self, path):
        out = []
        for line in raw(path).decode("utf-8").split("\n"):
            if line.strip():
                out.append(json.loads(line))
        return out

    def test_two_processes_of_3000_rows_keep_all_6000(self):
        path = self.root / "rows.jsonl"
        race("from convoy.layer import append_line\n"
             "for i in range(3000):\n"
             "    append_line(R / 'rows.jsonl', (json.dumps({'w': W, 'i': i}) + '\\n').encode('utf-8'))\n",
             2, self.root)
        rows = self.rows(path)
        self.assertEqual(len(rows), 6000)
        self.assertEqual(len({(r["w"], r["i"]) for r in rows}), 6000)
        self.assertTrue(endings_consistent(path))

    def test_feed_rows_from_two_processes_are_all_kept(self):
        race("from convoy.layer import hook\n"
             "for i in range(400):\n"
             "    hook(R, 'heartbeat', 'w%d i%d' % (W, i), instance_id='neuron-%d-thread' % W)\n",
             2, self.root)
        rows = self.rows(self.root / ".convoy" / "feed.jsonl")
        self.assertEqual(len([r for r in rows if r.get("kind") == "heartbeat"]), 800)

    def test_inbox_rows_from_two_processes_are_all_kept(self):
        race("from convoy.inbox import enqueue, pending\n"
             "for i in range(300):\n"
             "    enqueue(R, 'neuron-b-thread', 'body %d %d' % (W, i), to='claude')\n",
             2, self.root)
        from convoy.inbox import pending
        self.assertEqual(len(pending(self.root, "neuron-b-thread")), 600)


class TheFeedAndTheOutbox(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_a_feed_row_after_a_torn_tail_is_whole(self):
        feed = self.root / ".convoy" / "feed.jsonl"
        feed.parent.mkdir(parents=True, exist_ok=True)
        feed.write_bytes(b'{"kind":"note","summary":"half')
        row = hook(self.root, "heartbeat", "after the tear", instance_id="neuron-a-thread")
        last = [line for line in lines(feed) if line][-1]
        self.assertEqual(json.loads(last), row)

    def test_an_outbox_row_after_a_torn_tail_is_whole(self):
        path = outbox_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'{"dedupe_key":"x:y:send","result":"fi')
        _append(path, {"dedupe_key": "k:t:send", "result": "fired"})
        self.assertEqual(read_outbox(self.root), [{"dedupe_key": "k:t:send", "result": "fired"}])


if __name__ == "__main__":
    unittest.main()
