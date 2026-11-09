"""End-to-end smoke test: tiny corpus through run + score + review app store. No model calls."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.corpus = os.path.join(self.dir, "corpus.json")
        json.dump({"meta": {"name": "tiny same-author smoke corpus"},
                   "cases": [
                       {"id": "s1", "subject": "Fee", "body": "Hi, my name is Dana Whitfield, account ending 4417. "
                        "On October 28 I was charged a $35 overdraft fee on my checking account. Please reverse it. Dana",
                        "expected": {"decision": "route", "queue": "card_services"}},
                       {"id": "s2", "subject": "Help", "body": "Something is wrong.",
                        "expected": {"decision": "hold", "reason": "missing_field:customer_name"}},
                   ]}, open(self.corpus, "w"))
        self.out = os.path.join(self.dir, "out")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_bad_corpus_fails_cleanly(self):
        bad = os.path.join(self.dir, "bad.json")
        json.dump({"cases": [{"id": "x", "subject": "s", "body": "b"}, {"id": "x", "subject": "s", "body": "b"}]},
                  open(bad, "w"))
        p = self.run_mod("complaint_triage.run", "--corpus", bad, "--out", self.out)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("duplicate case id", p.stdout + p.stderr)
        self.assertNotIn("Traceback", p.stdout + p.stderr)

    def run_mod(self, mod, *args):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return subprocess.run([sys.executable, "-m", mod] + list(args),
                              capture_output=True, text=True, cwd=root)

    def test_run_and_score(self):
        r = self.run_mod("complaint_triage.run", "--corpus", self.corpus, "--out", self.out, "--fields-mode", "none")
        self.assertEqual(r.returncode, 0, r.stderr)
        results = json.load(open(os.path.join(self.out, "results.json")))
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["decision"], "route")
        self.assertEqual(results[1]["decision"], "hold")
        self.assertTrue(os.path.exists(os.path.join(self.out, "audit_log.jsonl")))
        self.assertTrue(os.path.exists(os.path.join(self.out, "review.html")))
        s = self.run_mod("complaint_triage.score", "--results", os.path.join(self.out, "results.json"),
                         "--expected", self.corpus)
        self.assertEqual(s.returncode, 0, s.stderr)
        self.assertIn("Decision matches: 2/2", s.stdout)

    def test_review_store_loads(self):
        r = self.run_mod("complaint_triage.run", "--corpus", self.corpus, "--out", self.out, "--fields-mode", "none")
        self.assertEqual(r.returncode, 0, r.stderr)
        from complaint_triage.review_app import Store
        st = Store(self.out, self.corpus)
        self.assertEqual(len(st.results), 2)


if __name__ == "__main__":
    unittest.main()
