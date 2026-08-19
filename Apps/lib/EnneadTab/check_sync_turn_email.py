"""Guardrails for the sync-turn gateway payload.

Stdlib unittest. Run:

    python -m unittest Apps.lib.EnneadTab.check_sync_turn_email
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import SYNC_TURN_EMAIL


class SyncTurnBlocks(unittest.TestCase):
    def test_cid_not_disk_path(self):
        blocks = SYNC_TURN_EMAIL.build_blocks(
            "2534_A_EA_NYU HQ", "bshapiro", "szhang", [], "https://enneadtab.com/sync/queue/abc")
        images = [b for b in blocks if b["type"] == "image"]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["src"], "cid:meme_you_sync_first")
        self.assertFalse(images[0]["src"].startswith("C:"))
        self.assertFalse(images[0]["src"].startswith("http"))
        types = [b["type"] for b in blocks]
        self.assertEqual(types[:3], ["heading", "image", "paragraph"])

    def test_attachment_is_url_with_matching_content_id(self):
        atts = SYNC_TURN_EMAIL.build_attachments()
        self.assertEqual(len(atts), 1)
        self.assertTrue(atts[0]["url"].startswith("https://"))
        self.assertEqual(atts[0]["contentId"], SYNC_TURN_EMAIL.MEME_CID)
        self.assertIn("/sync-turn/you-sync-first.jpg", atts[0]["url"])
        self.assertNotIn("enneadtab.com/email/", atts[0]["url"])

    def test_escapes_nothing_but_does_not_inject_html_tags_as_blocks(self):
        blocks = SYNC_TURN_EMAIL.build_blocks(
            "<script>x</script>", "a", "b", [], None)
        para = [b for b in blocks if b["type"] == "paragraph"][0]
        self.assertIn("<script>x</script>", para["text"])
        # The gateway renderer HTML-escapes; we must not pre-wrap as HTML.
        types = [b["type"] for b in blocks]
        self.assertNotIn("markdown", types)

    def test_remaining_list_and_last_in_line(self):
        last = SYNC_TURN_EMAIL.build_blocks("M", "a", "b", [], None)
        kv = [b for b in last if b["type"] == "keyValue"][0]
        self.assertEqual(kv["pairs"][2]["value"], "You are the last in line.")

        more = SYNC_TURN_EMAIL.build_blocks("M", "a", "b", ["c", "d"], None)
        kv = [b for b in more if b["type"] == "keyValue"][0]
        self.assertEqual(kv["pairs"][2]["value"], "c, d")

    def test_button_omitted_without_guid(self):
        blocks = SYNC_TURN_EMAIL.build_blocks("M", "a", "b", [], None)
        self.assertFalse(any(b["type"] == "button" for b in blocks))
        self.assertTrue(SYNC_TURN_EMAIL.queue_url_for("abc").endswith("/abc"))
        self.assertIsNone(SYNC_TURN_EMAIL.queue_url_for(""))

    def test_empty_next_user_does_not_send(self):
        result = SYNC_TURN_EMAIL.send("M", "a", "  ", [], model_guid="g")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "empty next_user")

    def test_idempotency_is_namespaced(self):
        key = SYNC_TURN_EMAIL.idempotency_key("guid", "szhang", "bshapiro")
        self.assertTrue(key.startswith("enneadtab-os:sync-turn:"))
        self.assertLessEqual(len(key), 256)

    def test_emailer_fallback_exists_for_signed_out_send(self):
        self.assertTrue(callable(getattr(SYNC_TURN_EMAIL, "_send_via_emailer")))


if __name__ == "__main__":
    unittest.main()
