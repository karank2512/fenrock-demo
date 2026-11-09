"""Run complaint triage over a synthetic corpus JSON.

  python3 -m complaint_triage.run --corpus ../corpus/corpus-dev-15.json --out out/dev-det --fields-mode none

Writes <out>/results.json (decisions), <out>/audit_log.jsonl (append-only log, the same
records), <out>/review.html (held queue snapshot). Prints a short summary. Scoring is
separate: complaint_triage.score. Synthetic data only.
"""
import argparse
import json
import os
import time

from .extract import LLMExtractor
from .log_store import AuditLog
from .pipeline import process

MAX_CASE_CHARS = 50000  # one complaint email; the demo does not ingest documents


def load_corpus(path):
    """Read and validate a corpus file. Clear errors beat tracebacks on bad input."""
    try:
        with open(path) as f:
            corpus = json.load(f)
    except (OSError, ValueError) as e:
        raise SystemExit("Cannot read corpus %s: %s" % (path, e))
    if not isinstance(corpus, dict) or not isinstance(corpus.get("cases"), list):
        raise SystemExit("Corpus %s must be a JSON object with a 'cases' list." % path)
    seen = set()
    for i, c in enumerate(corpus["cases"]):
        where = "case %d" % i
        if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not c["id"].strip():
            raise SystemExit("Corpus %s: %s needs a non-empty string 'id'." % (path, where))
        if c["id"] in seen:
            raise SystemExit("Corpus %s: duplicate case id %r." % (path, c["id"]))
        seen.add(c["id"])
        for field in ("subject", "body"):
            if not isinstance(c.get(field, ""), str):
                raise SystemExit("Corpus %s: %s (%s) needs a string '%s'." % (path, where, c["id"], field))
        if len(c.get("subject", "")) + len(c.get("body", "")) > MAX_CASE_CHARS:
            raise SystemExit("Corpus %s: %s (%s) exceeds %d characters." % (path, where, c["id"], MAX_CASE_CHARS))
    return corpus


def main():
    ap = argparse.ArgumentParser(description="Synthetic bank complaint triage (Meridian Mutual Bank - fictional).")
    ap.add_argument("--corpus", required=True, help="JSON file with a cases list: id, subject, body")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fields-mode", choices=["none", "llm"], default="none",
                    help="llm adds the FENROCK_LLM_CMD extraction cross-check. Default runs deterministic checks only.")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--keep-going", action="store_true", help="llm only: do not stop at the first failed call")
    a = ap.parse_args()

    corpus = load_corpus(a.corpus)
    cases = corpus["cases"][: a.limit] if a.limit else corpus["cases"]
    os.makedirs(a.out, exist_ok=True)
    log = AuditLog(os.path.join(a.out, "audit_log.jsonl"))
    ext = LLMExtractor() if a.fields_mode == "llm" else None

    results = []
    for case in cases:
        t0 = time.time()
        try:
            rec = process(case, log, ext)
        except Exception as e:  # extractor failure etc: hold for a person, keep going only if asked
            rec = log.append({"id": case["id"], "decision": "hold", "reason": "processing_error:%s" % str(e)[:100],
                              "tokens": []})
            if a.fields_mode == "llm" and not a.keep_going:
                results.append(rec)
                print("Stopped at the first failed extraction:", case["id"], rec["reason"])
                break
        rec = dict(rec)
        rec.pop("tokens", None)  # results.json stays readable; the audit log keeps them
        rec["seconds"] = round(time.time() - t0, 1)
        results.append(rec)
        print("%s: %s %s" % (case["id"], rec["decision"], rec.get("queue") or rec.get("reason") or ""))

    json.dump(results, open(os.path.join(a.out, "results.json"), "w"), indent=1, default=str)
    write_review(cases, results, os.path.join(a.out, "review.html"))
    n_route = sum(1 for r in results if r["decision"] == "route")
    n_inj = sum(1 for r in results if r.get("injection_attempt"))
    n_wd = sum(1 for r in results if r.get("writer_withdrawal"))
    print("Processed %d complaints: %d routed, %d held, %d injection_attempt, %d writer_withdrawal." %
          (len(results), n_route, len(results) - n_route, n_inj, n_wd))
    print("Synthetic demo data. No replies sent, nothing resolved, no real accounts.")


def write_review(cases, results, path):
    from .review_app import snapshot_html
    open(path, "w").write(snapshot_html(cases, results))


if __name__ == "__main__":
    main()
