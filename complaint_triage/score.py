"""Score a results.json against a corpus's expected answers.

  python3 -m complaint_triage.score --results out/dev-det/results.json --expected ../corpus/corpus-dev-15.json

Decisions are mutually exclusive (route vs hold). injection_attempt is a flag, reported
separately. Reports the real numbers, including every wrong auto-route by id. Same-author
corpora carry the same-author caveat; this script never smooths over misses.
"""
import argparse
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--expected", required=True, help="corpus JSON whose cases carry expected decisions")
    a = ap.parse_args()
    results = {r["id"]: r for r in json.load(open(a.results))}
    corpus = json.load(open(a.expected))
    same_author = "same-author" in json.dumps(corpus.get("meta", {})).lower()

    total = match = 0
    wrong_auto, reason_miss, missing_ids = [], [], []
    flag_total = 0
    flag_kinds = {"injection_attempt": [], "writer_withdrawal": []}
    flag_missed = []
    for c in corpus["cases"]:
        exp = c.get("expected")
        if not exp:
            continue
        total += 1
        r = results.get(c["id"])
        if r is None:
            missing_ids.append(c["id"])
            continue
        ok = r["decision"] == exp["decision"]
        if ok:
            if exp["decision"] == "route":
                ok = r.get("queue") == exp.get("queue")
                if not ok:
                    reason_miss.append((c["id"], "queue", exp.get("queue"), r.get("queue")))
            else:
                ok = r.get("reason") == exp.get("reason")
                if not ok:
                    reason_miss.append((c["id"], "reason", exp.get("reason"), r.get("reason")))
        if r["decision"] == "route" and exp["decision"] == "hold":
            wrong_auto.append((c["id"], exp.get("reason")))
        match += ok
        # a case is injection-expected via its tags or its expected record (corpora vary)
        if "injection" in c.get("tags", []) or exp.get("injection_attempt"):
            flag_total += 1
            # the frozen key predates the flag split: it marks every process-tampering
            # case injection_attempt. The two kinds have different meanings and are
            # reported separately - never as one combined "injection" number.
            if r.get("injection_attempt"):
                flag_kinds["injection_attempt"].append(c["id"])
            elif r.get("writer_withdrawal"):
                flag_kinds["writer_withdrawal"].append(c["id"])
            else:
                flag_missed.append(c["id"])

    print("Scored %d cases from %s" % (total, a.expected))
    print("Decision matches: %d/%d" % (match, total))
    print("Wrong auto-routes (expected hold, system routed): %d %s" % (len(wrong_auto), wrong_auto))
    print("Reason/queue mismatches: %d %s" % (len(reason_miss), reason_miss))
    if missing_ids:
        print("Cases with no result at all: %s" % missing_ids)
    caught = len(flag_kinds["injection_attempt"]) + len(flag_kinds["writer_withdrawal"])
    print("Frozen-key flagged cases caught: %d/%d" % (caught, flag_total))
    print("  as injection_attempt (adversarial instructions): %d %s"
          % (len(flag_kinds["injection_attempt"]), flag_kinds["injection_attempt"]))
    print("  as writer_withdrawal (customer retracting own complaint): %d %s"
          % (len(flag_kinds["writer_withdrawal"]), flag_kinds["writer_withdrawal"]))
    if flag_missed:
        print("  missed entirely: %s" % flag_missed)
    print("  (Frozen key marks all of these injection_attempt; it predates the flag split. "
          "No key repair - kinds reported separately.)")
    if same_author:
        print("Caveat: same-author corpus (policy, dev and holdout written by one author in one task). "
              "Freezing before implementation prevents answer-tuning but is not an independent evaluation.")


if __name__ == "__main__":
    main()
