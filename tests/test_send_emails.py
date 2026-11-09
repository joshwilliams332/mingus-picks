import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import send_emails as S  # noqa: E402


def put(store, path, subject=None, **extra):
    f = Path(store) / path
    f.parent.mkdir(parents=True, exist_ok=True)
    doc = dict(extra)
    if subject:
        doc["email"] = {"subject": subject, "html": "<p>x</p>", "text": "x"}
    f.write_text(json.dumps(doc))


class SendEmails(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = self.tmp.name
        self.outbox = []

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, to, email):
        self.outbox.append((to, email["subject"]))

    def test_first_run_marks_old_files_without_sending(self):
        put(self.store, "picks/2026-11-05.json", "TNF picks")
        self.assertEqual(S.send_new(self.store, self.send, "j@x"), [])
        self.assertEqual(self.outbox, [])
        put(self.store, "picks/2026-11-09.json", "MNF picks")
        self.assertEqual(S.send_new(self.store, self.send, "j@x"), ["picks/2026-11-09.json"])
        self.assertEqual(self.outbox, [("j@x", "MNF picks")])
        self.assertEqual(S.send_new(self.store, self.send, "j@x"), [])      # never twice

    def test_one_email_per_window(self):
        S.send_new(self.store, self.send, "j@x")                            # first run: nothing yet
        put(self.store, "picks/2026-11-15.json", "SNF picks")               # Sunday night: in the Sunday email instead
        put(self.store, "picks/sun-early/2026-11-15.json", "1 PM picks")    # slate files: in the Sunday email
        put(self.store, "picks/sunday/2026-11-15.json", "Sunday picks")
        put(self.store, "picks/headsup/2026-11-15-night.json", changed=False)   # nothing changed: no email
        put(self.store, "picks/2026-11-14-quick.json", "quick")
        put(self.store, "picks/status.json", "not an email")
        put(self.store, "picks/2026-11-13-results.json", "TNF results")
        S.send_new(self.store, self.send, "j@x")
        self.assertEqual(sorted(s for _, s in self.outbox), ["Sunday picks", "TNF results"])
        put(self.store, "picks/headsup/2026-11-15-night.json", "SNF update", changed=True)
        put(self.store, "picks/sunday/2026-11-15-results.json", "Sunday results")
        S.send_new(self.store, self.send, "j@x")
        self.assertEqual(sorted(s for _, s in self.outbox),
                         ["SNF update", "Sunday picks", "Sunday results", "TNF results"])

    def test_no_secrets_does_nothing(self):
        put(self.store, "picks/2026-11-09.json", "MNF picks")
        S.main([self.store])                                                # env not set in tests
        self.assertFalse((Path(self.store) / "picks" / "sent.json").exists())


if __name__ == "__main__":
    unittest.main()
