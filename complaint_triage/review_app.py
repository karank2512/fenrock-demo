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

CSS = r"""
:root{
  --paper:#f6f4f0; --surface:#ffffff; --ink:#201c17; --ink2:#6f6860; --ink3:#a39a8f;
  --hair:#e4ded4; --hair2:#efeae1;
  --green:#1e5b41; --green-bg:#e7f0eb; --amber:#8a5a10; --amber-bg:#f7eddb;
  --red:#a02c20; --red-bg:#f8e7e3;
  --sans:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  --serif:Georgia,'Times New Roman',serif;
  --mono:ui-monospace,'SF Mono',SFMono-Regular,Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:14px/1.55 var(--sans)}
a{color:inherit}
.masthead{background:var(--surface);border-bottom:1px solid var(--hair)}
.masthead-in{max-width:1060px;margin:0 auto;padding:18px 24px 14px}
.brand{font:400 20px/1.2 var(--serif);letter-spacing:.01em}
.brand .bank{color:var(--ink2)}
.syn{display:inline-block;margin-left:10px;padding:1px 7px;border:1px solid var(--hair);
  border-radius:3px;font:600 10px/1.6 var(--mono);letter-spacing:.08em;color:var(--amber);
  background:var(--amber-bg);vertical-align:3px;text-transform:uppercase}
.subtitle{margin-top:2px;font-size:13px;color:var(--ink2)}
.wrap{max-width:1060px;margin:0 auto;padding:20px 24px 48px}
.summary{display:flex;flex-wrap:wrap;gap:0;margin:0 0 18px;background:var(--surface);
  border:1px solid var(--hair);border-radius:6px;overflow:hidden}
.stat{padding:12px 20px;border-right:1px solid var(--hair2);min-width:130px}
.stat:last-child{border-right:0}
.stat b{display:block;font:400 22px/1.1 var(--serif)}
.stat span{font:11px/1.4 var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--ink2)}
.stat.warn b{color:var(--amber)} .stat.bad b{color:var(--red)} .stat.good b{color:var(--green)}
.filters{margin:0 0 12px;font:12px var(--mono);letter-spacing:.04em}
.filters a{display:inline-block;padding:5px 11px;margin-right:4px;border:1px solid var(--hair);
  border-radius:4px;text-decoration:none;color:var(--ink2);background:var(--surface)}
.filters a.on{color:var(--ink);border-color:var(--ink);font-weight:600}
.queue{background:var(--surface);border:1px solid var(--hair);border-radius:6px;overflow:hidden}
.qrow{display:grid;grid-template-columns:64px minmax(0,1fr) auto;gap:6px 16px;align-items:baseline;
  padding:11px 16px 11px 14px;border-bottom:1px solid var(--hair2);border-left:3px solid transparent;
  text-decoration:none}
.qrow:last-child{border-bottom:0}
.qrow:hover{background:#fbfaf7}
.qrow.route{border-left-color:var(--green)} .qrow.hold{border-left-color:var(--amber)}
.qid{font:12px/1.6 var(--mono);color:var(--ink2)}
.qsubj{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.qmeta{grid-column:2;font-size:12.5px;color:var(--ink2);overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.qright{grid-row:1/3;grid-column:3;text-align:right;white-space:nowrap}
.chip{display:inline-block;padding:2px 9px;border-radius:3px;font:600 10.5px/1.7 var(--mono);
  letter-spacing:.06em;text-transform:uppercase}
.chip.route{color:var(--green);background:var(--green-bg)}
.chip.hold{color:var(--amber);background:var(--amber-bg)}
.chip.mono{text-transform:none;letter-spacing:0;font-weight:400;color:var(--ink2);
  background:var(--hair2)}
.flag{display:inline-block;margin-left:6px;padding:2px 8px;border-radius:3px;
  font:600 10px/1.7 var(--mono);letter-spacing:.06em;text-transform:uppercase}
.flag.inj{color:var(--red);background:var(--red-bg)}
.flag.wd{color:var(--amber);background:var(--amber-bg)}
.qstatus{font:11px var(--mono);color:var(--ink3)}
.qstatus.done{color:var(--green)}
.detail-grid{display:grid;grid-template-columns:minmax(0,7fr) minmax(0,5fr);gap:20px;align-items:start}
.panel{background:var(--surface);border:1px solid var(--hair);border-radius:6px}
.panel-h{padding:11px 18px;border-bottom:1px solid var(--hair2);
  font:600 11px/1.4 var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--ink2)}
.panel-b{padding:16px 18px}
.letter-subj{font:400 19px/1.3 var(--serif);margin:0 0 10px}
.letter-body{white-space:pre-wrap;font-size:14.5px;line-height:1.65}
.kv{display:grid;grid-template-columns:auto minmax(0,1fr);gap:5px 14px;margin:0;font-size:13px}
.kv dt{color:var(--ink2);font:11.5px/1.7 var(--mono);letter-spacing:.03em}
.kv dd{margin:0;font-family:var(--mono);font-size:12.5px;word-break:break-word}
.dec-line{display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap}
.action-rec{margin:0 0 14px;font-size:13.5px}
.btn{display:inline-block;padding:9px 18px;margin:0 8px 8px 0;border:1px solid var(--ink);
  border-radius:4px;background:var(--ink);color:#fff;font:600 13px var(--sans);cursor:pointer}
.btn.sec{background:var(--surface);color:var(--ink)}
select{font:13px var(--sans);padding:8px;border:1px solid var(--hair);border-radius:4px;
  background:var(--surface);margin-right:8px}
.notice{padding:10px 14px;margin:0 0 14px;border:1px solid;border-radius:5px;font-size:13px}
.notice.ok{border-color:#bfd8cc;background:var(--green-bg);color:var(--green)}
.back{font:12px var(--mono);letter-spacing:.04em;text-decoration:none;color:var(--ink2)}
.muted{color:var(--ink2)} .small{font-size:12px}
.footnote{margin-top:20px;font-size:12px;color:var(--ink3)}
@media (max-width:840px){
  .detail-grid{grid-template-columns:1fr}
  .qrow{grid-template-columns:52px minmax(0,1fr);grid-template-rows:auto auto auto}
  .qright{grid-row:auto;grid-column:2;text-align:left;margin-top:2px}
  .stat{flex:1 1 40%;min-width:0;padding:10px 14px;border-bottom:1px solid var(--hair2)}
  .stat b{font-size:19px}
  .btn{padding:11px 18px}
}
"""


def e(x):
    return html.escape("" if x is None else str(x))


FIELD_LABELS = {
    "customer_name": "Customer",
    "account_reference": "Account",
    "product_domains": "Products mentioned",
    "amounts": "Amounts",
    "has_date": "Date given",
    "category": "Category",
}

_REASON_PROSE = {
    "missing_field:customer_name": "Customer name missing",
    "missing_field:account_reference": "No account reference found",
    "missing_field:product_identified": "Product not identified",
    "missing_field:category_clear": "Category unclear",
    "missing_field:amount_present_when_material": "Amount missing for a money dispute",
    "missing_field:date_present_when_material": "Date missing for a dated dispute",
    "escalation:legal": "Escalation - legal threat",
    "escalation:discrimination": "Escalation - discrimination claim",
    "escalation:regulator": "Escalation - regulator mentioned",
    "escalation:amount": "Escalation - amount over threshold",
    "escalation:safety": "Escalation - safety concern",
    "escalation:unauthorized_txn": "Escalation - unauthorized transaction",
    "escalation:duplicate": "Escalation - duplicate complaint",
    "conflicting_instructions": "Customer retracted their own request",
}


def reason_prose(reason):
    """Human wording for a hold reason; the raw code stays available in details."""
    if not reason:
        return ""
    if reason in _REASON_PROSE:
        return _REASON_PROSE[reason]
    if reason.startswith("duplicate_of:"):
        return "Duplicate of case " + reason.split(":", 1)[1]
    if reason.startswith("extraction_disagreement:"):
        return "Model and rule-based extraction disagree (%s)" % reason.split(":", 1)[1]
    if reason.startswith("processing_error:"):
        return "Processing error - needs a person"
    return reason


def _fmt_val(k, v):
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (list, tuple)):
        if not v:
            return "none recorded"
        if k == "amounts":
            return ", ".join("$%.2f" % x if isinstance(x, (int, float)) else str(x) for x in v)
        return ", ".join(str(x) for x in v)
    if v in (None, ""):
        return "none recorded"
    if k == "amounts":
        return str(v)
    return str(v)


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


def _flags(r):
    out = ""
    if r.get("injection_attempt"):
        out += "<span class='flag inj'>injection</span>"
    if r.get("writer_withdrawal"):
        out += "<span class='flag wd'>withdrawal</span>"
    return out


def _shell(title, body):
    return ("<!doctype html><html lang=en><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>%s</title><style>%s</style></head><body>%s</body></html>"
            % (e(title), CSS, body)).encode()


def _masthead(subtitle):
    return ("<div class=masthead><div class=masthead-in>"
            "<div class=brand><span class=bank>Meridian Mutual Bank</span> &middot; Complaint intake"
            "<span class=syn>Synthetic data</span></div>"
            "<div class=subtitle>%s</div></div></div>" % e(subtitle))


def _summary(results, status):
    ids = sorted(results)
    held = [i for i in ids if results[i]["decision"] == "hold"]
    routed = [i for i in ids if results[i]["decision"] == "route"]
    flagged = [i for i in ids if results[i].get("injection_attempt") or results[i].get("writer_withdrawal")]
    open_held = [i for i in held if i not in status]
    open_routed = [i for i in routed if i not in status]
    return ("<div class=summary>"
            "<div class='stat warn'><b>%d</b><span>held for review%s</span></div>"
            "<div class='stat good'><b>%d</b><span>routed, need approval%s</span></div>"
            "<div class='stat bad'><b>%d</b><span>flagged</span></div>"
            "<div class=stat><b>%d</b><span>total cases</span></div></div>"
            % (len(held), " (%d open)" % len(open_held) if len(open_held) != len(held) else "",
               len(routed), " (%d open)" % len(open_routed) if len(open_routed) != len(routed) else "",
               len(flagged), len(ids)))


def _qrow(st, cid):
    r = st.results[cid]
    c = st.cases.get(cid, {})
    s = st.status.get(cid)
    if r["decision"] == "route":
        dec = "<span class='chip route'>routed</span>"
        meta = "to <b>%s</b> &middot; %s" % (e(r.get("queue")), e(r.get("recommended_action")))
    else:
        dec = "<span class='chip hold'>held</span>"
        meta = e(reason_prose(r.get("reason")))
    status_html = ("<div class='qstatus done'>%s</div>" % e(s)) if s else "<div class=qstatus>open</div>"
    return ("<a class='qrow %s' href='/case/%s'>"
            "<span class=qid>%s</span><span class=qsubj>%s</span>"
            "<span class=qright>%s%s%s</span>"
            "<span class=qmeta>%s</span></a>"
            % (r["decision"], e(cid), e(cid), e(c.get("subject", "")), dec, _flags(r), status_html, meta))


def list_page(st, view="all"):
    ids = sorted(st.results)
    if view == "held":
        ids = [i for i in ids if st.results[i]["decision"] == "hold"]
    elif view == "routed":
        ids = [i for i in ids if st.results[i]["decision"] == "route"]
    elif view == "flagged":
        ids = [i for i in ids if st.results[i].get("injection_attempt") or st.results[i].get("writer_withdrawal")]
    tabs = "".join("<a %s href='/?view=%s'>%s</a>" % ("class=on" if view == v else "", v, label)
                   for v, label in (("all", "All"), ("held", "Held"), ("routed", "Routed"), ("flagged", "Flagged")))
    rows = "".join(_qrow(st, i) for i in ids) or "<div class='panel-b muted'>No cases in this view.</div>"
    body = (_masthead("Human review queue - every decision below was made by policy checks; a person finishes each one.")
            + "<div class=wrap>" + _summary(st.results, st.status)
            + "<div class=filters>" + tabs + "</div>"
            + "<div class=queue>" + rows + "</div>"
            + "<p class=footnote>Demo data - fictional bank, invented complaints. Approving a recommendation "
              "records the approval in the audit log; nothing is sent to a customer and nothing is resolved by the system.</p>"
            + "</div>")
    return _shell("Complaint review queue", body)


def detail_page(st, cid, note=None):
    r = st.results[cid]
    c = st.cases.get(cid, {})
    box = "<p class='notice ok'>%s</p>" % e(note) if note else ""
    s = st.status.get(cid)
    raw_fields = r.get("fields") or {}
    fields = "".join("<dt>%s</dt><dd>%s</dd>" % (e(FIELD_LABELS.get(k, k.replace("_", " "))), e(_fmt_val(k, v)))
                     for k, v in raw_fields.items())
    if not fields:
        why = ("Not extracted - this case was held at an earlier check (escalation triggers run first, on the raw text)."
               if (r.get("reason") or "").startswith(("escalation:", "conflicting"))
               else "None recorded.")
        fields = "<dt class=muted colspan=2>%s</dt><dd></dd>" % e(why)
    raw_json = json.dumps({"decision": r["decision"], "queue": r.get("queue"), "reason": r.get("reason"),
                           "fields": raw_fields,
                           "injection_patterns": r.get("injection_patterns"),
                           "withdrawal_patterns": r.get("withdrawal_patterns")}, indent=1)
    tech = ("<details style='margin-top:12px'><summary class='muted small' style='cursor:pointer'>Technical details</summary>"
            "<pre style='font:11px/1.5 var(--mono);background:var(--hair2);padding:10px;border-radius:4px;"
            "overflow-x:auto'>%s</pre></details>" % e(raw_json))
    if r["decision"] == "route":
        dec = "<span class='chip route'>routed</span> <span class='chip mono'>%s</span>" % e(r.get("queue"))
        rec = "<p class=action-rec><b>Recommended next step.</b> %s</p>" % e(r.get("recommended_action"))
        actions = ("<form method=post action='/case/%s/approve'><button class=btn type=submit>Approve recommendation</button></form>"
                   "<form method=post action='/case/%s/reviewed'><button class='btn sec' type=submit>Mark reviewed - no action</button></form>"
                   % (cid, cid))
    else:
        dec = "<span class='chip hold'>held</span> <span class='chip mono'>%s</span>" % e(reason_prose(r.get("reason")))
        rec = "<p class=action-rec><b>Why it is held.</b> The policy checks could not clear this case; a person decides what happens next.</p>"
        opts = "".join("<option>%s</option>" % q for q, _a in policy.CATEGORIES.values())
        actions = ("<form method=post action='/case/%s/assign'><select name=queue aria-label='Assign queue'>%s</select>"
                   "<button class=btn type=submit>Assign queue</button></form>"
                   "<form method=post action='/case/%s/reviewed'><button class='btn sec' type=submit>Mark reviewed - no routing</button></form>"
                   % (cid, opts, cid))
    done = "<p class='notice ok'>Handled: %s.</p>" % e(s) if s else ""
    right = ("<div class=panel><div class=panel-h>Decision</div><div class=panel-b>"
             + box + done
             + "<div class=dec-line>" + dec + _flags(r) + "</div>" + rec
             + "</div></div>"
             + "<div class=panel style='margin-top:16px'><div class=panel-h>Extracted fields</div>"
             + "<div class=panel-b><dl class=kv>" + fields + "</dl>" + tech + "</div></div>"
             + "<div class=panel style='margin-top:16px'><div class=panel-h>Human action</div>"
             + "<div class=panel-b>" + actions
             + "<p class='muted small' style='margin:8px 0 0'>Actions are recorded in the audit log. "
               "Approving never sends anything to the customer.</p></div></div>")
    left = ("<div class=panel><div class=panel-h>Complaint email (synthetic)</div>"
            "<div class=panel-b><p class=letter-subj>%s</p><div class=letter-body>%s</div></div></div>"
            % (e(c.get("subject", "")), e(c.get("body", ""))))
    body = (_masthead("Case %s" % cid)
            + "<div class=wrap><p><a class=back href='/'>&larr; All cases</a></p>"
            + "<div class=detail-grid>" + left + "<div>" + right + "</div></div></div>")
    return _shell("Case %s - complaint review" % cid, body)


def snapshot_html(cases, results):
    """Static held-queue snapshot written by run.py as review.html. Same design, no server."""

    class _St:
        pass

    st = _St()
    st.results = {r["id"]: r for r in results}
    st.cases = {c["id"]: c for c in cases}
    st.status = {}
    held = [i for i in sorted(st.results) if st.results[i]["decision"] == "hold"]
    rows = "".join(_qrow(st, i) for i in held) or "<div class='panel-b muted'>Nothing held.</div>"
    rows = rows.replace("href='/case/", "href='#case-")  # static file: no live case pages
    body = (_masthead("Held for human review - snapshot. Approving or assigning happens in the live review app.")
            + "<div class=wrap>" + _summary(st.results, st.status)
            + "<div class=queue>" + rows + "</div>"
            + "<p class=footnote>Synthetic demo data - fictional Meridian Mutual Bank. "
              "Nothing here was sent to a customer or resolved.</p></div>")
    return _shell("Complaints held for human review", body).decode()


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
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path == "/":
                view = parse_qs(parsed.query).get("view", ["all"])[0]
                if view not in ("all", "held", "routed", "flagged"):
                    view = "all"
                return self.send(list_page(st, view))
            if path.startswith("/case/") and path[6:] in st.results:
                return self.send(detail_page(st, path[6:]))
            self.send(_shell("Not found", "<div class=wrap><p>Not found.</p></div>"), 404)

        def do_POST(self):
            path = unquote(urlparse(self.path).path)
            parts = path.strip("/").split("/")
            if len(parts) != 3 or parts[0] != "case" or parts[1] not in st.results:
                return self.send(_shell("Not found", "<div class=wrap><p>Not found.</p></div>"), 404)
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
            self.send(_shell("Not found", "<div class=wrap><p>Not found.</p></div>"), 404)
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
