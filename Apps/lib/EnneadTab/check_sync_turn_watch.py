"""Guardrails for sync-turn desktop watch + toast payload.

    python -m unittest Apps.lib.EnneadTab.check_sync_turn_watch
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import SYNC_TURN_WATCH


def _watch(**kwargs):
    item = {
        "model_guid": "guid-1",
        "model_name": "2534_A_EA_NYU HQ",
        "dashboard_url": "https://enneadtab.com/sync/queue/guid-1",
        "toasted_as_head": False,
    }
    item.update(kwargs)
    return item


class EvaluateWatch(unittest.TestCase):
    def test_drop_when_absent_from_queue(self):
        action, watch = SYNC_TURN_WATCH.evaluate_watch(
            _watch(), [{"username": "other"}], "szhang")
        self.assertEqual(action, "drop")

    def test_toast_when_becoming_head(self):
        action, watch = SYNC_TURN_WATCH.evaluate_watch(
            _watch(), [{"username": "szhang"}, {"username": "other"}], "szhang")
        self.assertEqual(action, "toast")
        self.assertTrue(watch["toasted_as_head"])

    def test_keep_silent_while_still_head_after_toast(self):
        action, watch = SYNC_TURN_WATCH.evaluate_watch(
            _watch(toasted_as_head=True),
            [{"username": "szhang"}],
            "szhang")
        self.assertEqual(action, "keep")
        self.assertTrue(watch["toasted_as_head"])

    def test_reset_flag_when_someone_else_is_head(self):
        action, watch = SYNC_TURN_WATCH.evaluate_watch(
            _watch(toasted_as_head=True),
            [{"username": "bshapiro"}, {"username": "szhang"}],
            "szhang")
        self.assertEqual(action, "keep")
        self.assertFalse(watch["toasted_as_head"])

    def test_empty_queue_drops(self):
        action, _watch_out = SYNC_TURN_WATCH.evaluate_watch(
            _watch(), [], "szhang")
        self.assertEqual(action, "drop")

    def test_malformed_head_while_still_waiting_is_keep_not_toast(self):
        action, watch = SYNC_TURN_WATCH.evaluate_watch(
            _watch(),
            [{"username": ""}, {"username": "szhang"}],
            "szhang")
        self.assertEqual(action, "keep")
        self.assertFalse(watch["toasted_as_head"])


class ToastPayload(unittest.TestCase):
    def test_copy_and_actions(self):
        payload = SYNC_TURN_WATCH.build_toast_payload(_watch())
        self.assertEqual(payload["title"], "Your turn to sync")
        self.assertEqual(
            payload["main_text"],
            "2534_A_EA_NYU HQ\nGo sync in Revit.")
        self.assertEqual(payload["level"], "warning")
        self.assertTrue(payload["sticky"])
        labels = [a["label"] for a in payload["actions"]]
        self.assertEqual(labels, ["I'm on it", "See queue"])
        self.assertEqual(payload["actions"][0]["type"], "dismiss")
        self.assertEqual(payload["actions"][1]["type"], "open_url")
        self.assertEqual(
            payload["actions"][1]["payload"],
            "https://enneadtab.com/sync/queue/guid-1")
        joined = " ".join(labels).lower()
        self.assertNotIn("sync now", joined)

    def test_omits_see_queue_without_url(self):
        payload = SYNC_TURN_WATCH.build_toast_payload(
            _watch(dashboard_url=""))
        self.assertEqual(len(payload["actions"]), 1)
        self.assertEqual(payload["actions"][0]["label"], "I'm on it")


class WatchFile(unittest.TestCase):
    def setUp(self):
        self._orig_load = SYNC_TURN_WATCH.load_state
        self._orig_save = SYNC_TURN_WATCH.save_state
        self.state = {"username": "", "watches": []}
        SYNC_TURN_WATCH.load_state = lambda: self.state
        def _save(s):
            self.state = s
        SYNC_TURN_WATCH.save_state = _save

    def tearDown(self):
        SYNC_TURN_WATCH.load_state = self._orig_load
        SYNC_TURN_WATCH.save_state = self._orig_save

    def test_add_then_duplicate_guid_updates_not_duplicates(self):
        SYNC_TURN_WATCH.add_watch("g1", "Model A", "szhang", "https://enneadtab.com/sync/queue/g1")
        SYNC_TURN_WATCH.add_watch("g1", "Model A renamed", "szhang", "https://enneadtab.com/sync/queue/g1")
        self.assertEqual(len(self.state["watches"]), 1)
        self.assertEqual(self.state["watches"][0]["model_name"], "Model A renamed")
        self.assertEqual(self.state["username"], "szhang")

    def test_cap_drops_oldest(self):
        for i in range(SYNC_TURN_WATCH.MAX_WATCHES + 2):
            SYNC_TURN_WATCH.add_watch("g{}".format(i), "M{}".format(i), "szhang")
        self.assertEqual(len(self.state["watches"]), SYNC_TURN_WATCH.MAX_WATCHES)
        guids = [w["model_guid"] for w in self.state["watches"]]
        self.assertNotIn("g0", guids)
        self.assertIn("g9", guids)

    def test_remove(self):
        SYNC_TURN_WATCH.add_watch("g1", "A", "szhang")
        SYNC_TURN_WATCH.remove_watch("g1")
        self.assertEqual(self.state["watches"], [])

    def test_skip_empty_guid_or_user(self):
        SYNC_TURN_WATCH.add_watch("", "A", "szhang")
        SYNC_TURN_WATCH.add_watch("g1", "A", "  ")
        self.assertEqual(self.state["watches"], [])


class PollOnce(unittest.TestCase):
    def setUp(self):
        self.state = {
            "username": "szhang",
            "watches": [_watch(toasted_as_head=False)],
        }
        self.toasts = []
        self._orig_load = SYNC_TURN_WATCH.load_state
        self._orig_save = SYNC_TURN_WATCH.save_state
        SYNC_TURN_WATCH.load_state = lambda: self.state
        def _save(s):
            self.state = s
        SYNC_TURN_WATCH.save_state = _save

    def tearDown(self):
        SYNC_TURN_WATCH.load_state = self._orig_load
        SYNC_TURN_WATCH.save_state = self._orig_save

    def test_fires_once_then_silent(self):
        statuses = {
            "guid-1": {"queue": [{"username": "szhang"}],
                       "dashboard_url": "https://enneadtab.com/sync/queue/guid-1"},
        }
        def get_status(guid):
            return statuses.get(guid)
        def notify(payload):
            self.toasts.append(payload)
        n1 = SYNC_TURN_WATCH.poll_once(get_status, notify)
        n2 = SYNC_TURN_WATCH.poll_once(get_status, notify)
        self.assertEqual(n1, 1)
        self.assertEqual(n2, 0)
        self.assertEqual(self.toasts[0]["title"], "Your turn to sync")

    def test_drops_when_gone(self):
        def get_status(guid):
            return {"queue": [], "dashboard_url": ""}
        n = SYNC_TURN_WATCH.poll_once(get_status, lambda p: self.toasts.append(p))
        self.assertEqual(n, 0)
        self.assertEqual(self.state["watches"], [])

    def test_status_none_keeps_watch(self):
        def get_status(guid):
            return None
        n = SYNC_TURN_WATCH.poll_once(get_status, lambda p: self.toasts.append(p))
        self.assertEqual(n, 0)
        self.assertEqual(len(self.state["watches"]), 1)


if __name__ == "__main__":
    unittest.main()
