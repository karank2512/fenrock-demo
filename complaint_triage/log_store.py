"""Append-only audit log. One JSON record per decision, never rewritten.

The log is what makes a decision reconstructable afterward: inputs, checks that fired,
and the reason. It is also how duplicate complaints are found. This is a demo artifact -
it shows the method, not any compliance property.
"""
import json
import os
import threading
import time


class AuditLog:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.records = []
        if os.path.exists(path):
            for line in open(path):
                line = line.strip()
                if line:
                    self.records.append(json.loads(line))

    def append(self, record):
        record = dict(record)
        record["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with self.lock:
            with open(self.path, "a") as f:
                f.write(json.dumps(record, default=str) + "\n")
            self.records.append(record)
        return record

    def find_duplicate(self, account_reference, token_set, threshold):
        """Most similar prior complaint from the same account, by containment."""
        best, best_sim = None, 0.0
        for r in self.records:
            if r.get("account_reference") != account_reference:
                continue
            from .checks import containment
            sim = containment(token_set, set(r.get("tokens", [])))
            if sim >= threshold and sim > best_sim:
                best, best_sim = r, sim
        return best, best_sim
