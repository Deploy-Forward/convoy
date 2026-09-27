"""What the pane host types for a nudge.

Receiver-side evidence: `--keys Enter` arrived in the chair's prompt as the literal
text "Enter" and the trailing carriage return, written with no virtual key code,
did not submit. A bare key name must become one VK_RETURN key event and no
characters; typed text must end in a VK_RETURN event, not a bare '\r' character.
"""
import unittest

from convoy.pane_host import console_key_records, VK_RETURN


class PaneHostKeyRecords(unittest.TestCase):
    def test_nudge_keys_enter_sends_vk_return(self):
        for name in ("Enter", "enter", "Return", "C-m"):
            records = console_key_records(name)
            self.assertEqual(records, [(VK_RETURN, "\r")], name)
            self.assertNotIn("E", [ch for _vk, ch in records])

    def test_typed_text_ends_in_a_vk_return_event(self):
        records = console_key_records("hi nudge=abc")
        self.assertEqual(records[-1], (VK_RETURN, "\r"))
        self.assertEqual([ch for _vk, ch in records[:-1]], list("hi nudge=abc"))
        self.assertTrue(all(vk == 0 for vk, _ch in records[:-1]))

    def test_no_stray_prefix_before_the_key(self):
        self.assertEqual(console_key_records("Enter")[0][1], "\r")


if __name__ == "__main__":
    unittest.main()
