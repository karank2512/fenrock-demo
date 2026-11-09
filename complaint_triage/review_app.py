"""Local human-review app for the triage queue. Standard library only, binds 127.0.0.1.

Shows every complaint, its decision and why. For held complaints a human can mark them
reviewed or assign a queue by hand; for routed complaints a human can approve the
recommended action. Approving never sends anything to a customer - it records that a
human approved the recommendation. Every action is appended to review_log.jsonl.
Synthetic demo data only.
"""
import argparse
import html
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import policy

CSS = ("body{font:15px system-ui;margin:24px;max-width:1000px}table{border-collapse:collapse;width:100%}"
       "td,th{border:1px solid #ccc;padding:6px 8px;text-align:left;vertical-align:top}th{background:#f3f3f3}"
       "button{padding:6px 14px;margin-right:8px;cursor:pointer}"
       ".tag{font-size:12px;padding:2px 8px;border-radius:10px;background:#eee}"
       ".ok{background:#e7f6e7;padding:8px 12px;border:1px solid #9c9}.muted{color:#666}")


def e(x):
    return html.escape("" if x is None else str(x))


class Store:
    def __init__(self, out, corpus):
        self.results = {r["id"]: r for r in json.load(open(os.path.join(out, "results.json")))}
        self.cases = {c["id"]: c for c in json.load(open(corpus))["cases"]}
        self.log_path = os.path.join(out, "review_log.jsonl")
        self.status = {}
        if os.path.exists(self.log_path):
            for line in open(self.log_path):
                d = json.loads(line)
                self.status[d["id"]] = d["action"] + (":" + d.get("queue", "") if d.get("queue") else "")

    def log(self, **d):
        d["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_path, "a") as f:
            f.write(json.dumps(d) + "\n")


def page(title, body):
    return ("<!doctype html><meta charset=utf-8><title>%s</title><style>%s</style>%s" % (e(title), CSS, body)).encode()


def list_page(st):
    rows = []
    for cid in sorted(st.results):
        r = st.results[cid]
        s = st.status.get(cid, "open")
        if r["decision"] == "route":
            why = "route to <b>%s</b>: %s" % (e(r.get("queue")), e(r.get("recommended_action")))
        else:
            why = "held: <b>%s</b>" % e(r.get("reason"))
        inj = ""
        if r.get("injection_attempt"):
            inj += " <span class=tag>injection flagged</span>"
        if r.get("writer_withdrawal"):
            inj += " <span class=tag>writer withdrawal</span>"
        rows.append("<tr><td><a href='/case/%s'>%s</a>%s</td><td><span class=tag>%s</span></td><td>%s</td></tr>"
                    % (e(cid), e(cid), inj, e(s), why))
    return page("Complaint queue", "<h1>Synthetic complaint queue - Meridian Mutual Bank (fictional)</h1>"
                "<p class=muted>Demo data. Approving a recommendation records the approval; nothing is sent to a customer.</p>"
                "<table><tr><th>Case</th><th>Status</th><th>Decision</th></tr>%s</table>" % "".join(rows))


def detail_page(st, cid, note=None):
    r = st.results[cid]
    c = st.cases.get(cid, {})
    box = "<p class=ok>%s</p>" % e(note) if note else ""
    s = st.status.get(cid)
    done = "<p class=muted>Already %s.</p>" % e(s) if s else ""
    fields = "".join("<li>%s: %s</li>" % (e(k), e(v)) for k, v in (r.get("fields") or {}).items())
    head = ("<p><a href='/'>Back to queue</a></p><h1>%s</h1>%s%s"
            "<h3>Email (synthetic)</h3><p><b>%s</b></p><p>%s</p>"
            "<h3>Decision</h3><p>%s %s</p><h3>Extracted fields</h3><ul>%s</ul>"
            % (e(cid), done, box, e(c.get("subject", "")), e(c.get("body", "")).replace("\n", "<br>"),
               e(r["decision"]), e(r.get("queue") or r.get("reason") or ""), fields))
    if r["decision"] == "route":
        actions = ("<form method=post action='/case/%s/approve'><button type=submit>Approve recommended action</button></form>"
                   "<form method=post action='/case/%s/reviewed'><button type=submit>Mark reviewed (no action)</button></form>"
                   % (cid, cid))
    else:
        opts = "".join("<option>%s</option>" % q for q, _a in policy.CATEGORIES.values())
        actions = ("<form method=post action='/case/%s/assign'>Assign queue: <select name=queue>%s</select>"
                   "<button type=submit>Assign</button></form>"
                   "<form method=post action='/case/%s/reviewed'><button type=submit>Mark reviewed (no routing)</button></form>"
                   % (cid, opts, cid))
    return page(cid, head + actions)


def make_handler(st):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, body, code=200):
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            if path == "/":
                return self.send(list_page(st))
            if path.startswith("/case/") and path[6:] in st.results:
                return self.send(detail_page(st, path[6:]))
            self.send(page("Not found", "<p>Not found</p>"), 404)

        def do_POST(self):
            path = unquote(urlparse(self.path).path)
            parts = path.strip("/").split("/")
            if len(parts) != 3 or parts[0] != "case" or parts[1] not in st.results:
                return self.send(page("Not found", "<p>Not found</p>"), 404)
            cid, action = parts[1], parts[2]
            if st.status.get(cid):
                return self.send(detail_page(st, cid, note="Already %s. No change made." % st.status[cid]))
            if action == "approve" and st.results[cid]["decision"] == "route":
                st.status[cid] = "approved"
                st.log(id=cid, action="approved", queue=st.results[cid].get("queue"))
                return self.send(detail_page(st, cid, note="Recommendation approved. Recorded; nothing was sent."))
            if action == "reviewed":
                st.status[cid] = "reviewed"
                st.log(id=cid, action="reviewed")
                return self.send(detail_page(st, cid, note="Marked reviewed."))
            if action == "assign" and st.results[cid]["decision"] == "hold":
                form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
                queue = form.get("queue", [""])[0]
                if queue not in {q for q, _a in policy.CATEGORIES.values()}:
                    return self.send(detail_page(st, cid, note="Unknown queue. No change made."))
                st.status[cid] = "assigned:%s" % queue
                st.log(id=cid, action="assigned", queue=queue)
                return self.send(detail_page(st, cid, note="Assigned to %s by a human." % queue))
            self.send(page("Not found", "<p>Not found</p>"), 404)
    return H


def serve(out, corpus, port=8766):
    st = Store(out, corpus)
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(st))
    return srv, st


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--port", type=int, default=8766)
    a = ap.parse_args()
    srv, _ = serve(a.out, a.corpus, a.port)
    print("Review app on http://127.0.0.1:%d  (Ctrl+C to stop)" % a.port)
    srv.serve_forever()
