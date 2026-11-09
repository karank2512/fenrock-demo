"""Local human-review app for the triage queue. Standard library only, binds 127.0.0.1.

Two-pane inbox: the queue stays on the left, the selected case opens on the right.
For held complaints a human can mark them reviewed or assign a queue by hand; for
routed complaints a human can approve the recommended action. Approving never sends
anything to a customer - it records that a human approved the recommendation. Every
action is appended to review_log.jsonl. Works fully without JavaScript; with it, the
right pane loads inline and j/k move between cases. Synthetic demo data only.
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
  --paper:#f6f4f0; --surface:#ffffff; --ink:#201c17; --ink2:#5d564f; --ink3:#756d63;
  --hair:#e4ded4;
  --green:#1e5b41; --amber:#8a5a10; --red:#a02c20; --amber-bg:#f7eddb; --red-bg:#f8e7e3;
  --sans:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  --serif:Georgia,'Times New Roman',serif;
  --mono:ui-monospace,'SF Mono',SFMono-Regular,Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:14px/1.55 var(--sans)}
a{color:inherit}
.masthead{background:var(--surface);border-bottom:1px solid var(--hair)}
.masthead-in{max-width:1180px;margin:0 auto;padding:14px 24px 12px;display:flex;
  align-items:baseline;gap:12px;flex-wrap:wrap}
.brand{font:400 19px/1.2 var(--serif);letter-spacing:.01em}
.brand .bank{color:var(--ink2)}
.syn{font:600 10px/1.6 var(--mono);letter-spacing:.08em;color:var(--amber);text-transform:uppercase}
.subtitle{font-size:12.5px;color:var(--ink2)}
.triage-progress{margin-left:auto;font-size:12.5px;color:var(--ink2)}
.triage-progress b{color:var(--ink);font-weight:600}
.inbox{max-width:1180px;margin:0 auto;padding:16px 24px 32px;display:grid;
  grid-template-columns:340px minmax(0,1fr);gap:24px;align-items:start}
.queue-col{position:sticky;top:16px}
.filters{margin:0 0 6px}
.filters a{display:inline-block;padding:4px 10px;margin-right:2px;border-radius:4px;
  text-decoration:none;color:var(--ink2);font-size:12.5px}
.filters a.on{color:var(--ink);background:var(--surface);font-weight:600;
  box-shadow:inset 0 0 0 1px var(--hair)}
.qsection{margin:16px 2px 6px;font-size:12px;color:var(--ink2)}
.qsection:first-of-type{margin-top:8px}
.qsection .n{color:var(--ink3)}
.qrow{display:block;padding:10px 12px;text-decoration:none;border-radius:6px;
  border-left:2px solid transparent}
.qrow:hover{background:#efebe3}
.qrow:focus-visible{outline:2px solid var(--ink);outline-offset:1px}
.qrow.sel{background:var(--surface);border-left-color:var(--ink);
  box-shadow:inset 0 0 0 1px var(--hair)}
.qtop{display:flex;min-width:0;justify-content:space-between;align-items:baseline;gap:8px}
.qsubj{display:block;flex:1;min-width:0;font-weight:600;font-size:13.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.qid{font:11px/1.6 var(--mono);color:var(--ink3);white-space:nowrap}
.qmeta{display:block;margin-top:1px;font-size:12px;color:var(--ink2);overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.qflags{margin-top:4px;display:flex;gap:6px;align-items:center}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px;vertical-align:0}
.dot.held{background:var(--amber)} .dot.route{background:var(--green)}
.flag{font:600 10px/1.7 var(--mono);letter-spacing:.06em;text-transform:uppercase;
  padding:1px 7px;border-radius:3px}
.flag.inj{color:var(--red);background:var(--red-bg)}
.flag.wd{color:var(--amber);background:var(--amber-bg)}
.qstatus{font-size:11.5px;color:var(--green)}
.detail-col{min-width:0}
.empty{padding:72px 24px;text-align:center;color:var(--ink2)}
.empty .keys{font:12px var(--mono);color:var(--ink3);margin-top:8px}
.case{background:var(--surface);border:1px solid var(--hair);border-radius:8px;
  padding:24px 28px 20px}
.case-subj{font:400 21px/1.3 var(--serif);margin:0 0 12px}
.letter-body{white-space:pre-wrap;font-size:14.5px;line-height:1.65}
.case h2{font:600 13px/1.4 var(--sans);margin:26px 0 8px}
.case hr{border:0;border-top:1px solid var(--hair);margin:22px 0 0}
.status-line{display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:14px}
.status-line b{font-weight:600}
.status-why{margin:6px 0 0;color:var(--ink2);font-size:13px}
.kv{display:grid;grid-template-columns:150px minmax(0,1fr);gap:6px 16px;margin:0;font-size:13.5px}
.kv dt{color:var(--ink2)}
.kv dd{margin:0;font-family:var(--mono);font-size:12.5px;word-break:break-word}
.kv dd.none{color:var(--ink3);font-family:var(--sans);font-size:13px}
.btn{display:inline-block;padding:9px 18px;margin:0 8px 8px 0;border:1px solid var(--ink);
  border-radius:6px;background:var(--ink);color:#fff;font:600 13px var(--sans);cursor:pointer}
.btn.sec{background:var(--surface);color:var(--ink)}
.btn:hover{opacity:.88}
select{font:13px var(--sans);padding:8px;border:1px solid var(--hair);border-radius:6px;
  background:var(--surface);margin-right:8px}
.notice{padding:10px 14px;margin:0 0 14px;border-radius:6px;font-size:13px;
  background:#e9f1ed;color:var(--green);border:1px solid #c9dcd2}
.back{font-size:12.5px;text-decoration:none;color:var(--ink2)}
.backlink{display:none;font-size:13px;margin:0}
.muted{color:var(--ink2)} .small{font-size:12px}
.footnote{font-size:12px;color:var(--ink3);margin:14px 2px}
.tech{margin-top:14px}
.tech summary{cursor:pointer}
.tech pre{font:11px/1.5 var(--mono);background:var(--paper);padding:10px;border-radius:6px;overflow-x:auto}
@media (max-width:900px){
  .inbox{grid-template-columns:1fr;padding:12px 14px 28px}
  .inbox.has-sel .queue-col{display:none}
  .queue-col{position:static}
  .backlink{display:block;margin:0 0 14px}
  .qsubj{white-space:normal}
  .kv{grid-template-columns:1fr;gap:0 0}
  .kv dd{margin-bottom:6px}
  .btn{padding:11px 18px}
}
"""

JS = r"""
(function(){
  var pane = document.getElementById('pane');
  if (!pane) return;
  var seq = 0;
  var inflight = null;
  function rows(){ return Array.prototype.slice.call(document.querySelectorAll('.qrow')); }
  function current(){ return document.querySelector('.qrow.sel'); }
  function markSel(row){
    var prev = current();
    if (prev){ prev.classList.remove('sel'); prev.removeAttribute('aria-current'); }
    row.classList.add('sel');
    row.setAttribute('aria-current', 'true');
  }
  function select(row, push, focusRow){
    if (!row) return;
    markSel(row);
    if (focusRow) row.focus();
    var url = row.getAttribute('href');
    var my = ++seq;
    if (inflight && inflight.abort) inflight.abort();
    var ctrl = ('AbortController' in window) ? new AbortController() : null;
    inflight = ctrl;
    var opts = ctrl ? {signal: ctrl.signal} : {};
    fetch(url + (url.indexOf('?') >= 0 ? '&' : '?') + 'partial=1', opts).then(function(r){ return r.text(); })
      .then(function(html){
        if (my !== seq) return;
        pane.innerHTML = html;
        pane.scrollIntoView({block:'nearest'});
        if (push === 'replace') history.replaceState(null, '', url);
        else if (push !== false) history.pushState(null, '', url);
        wireForms();
      }).catch(function(err){ if (!err || err.name !== 'AbortError') throw err; });
  }
  function wireForms(){
    Array.prototype.forEach.call(pane.querySelectorAll('form'), function(f){
      f.addEventListener('submit', function(ev){
        ev.preventDefault();
        var my = ++seq;
        fetch(f.action, {method:'POST', body:new URLSearchParams(new FormData(f)),
          headers:{'X-Partial':'1'}}).then(function(r){ return r.text(); }).then(function(html){
          if (my !== seq) return;
          pane.innerHTML = html; wireForms(); refreshQueue();
        });
      });
    });
  }
  function refreshQueue(){ location.reload(); }
  Array.prototype.forEach.call(rows(), function(row){
    row.addEventListener('click', function(ev){ ev.preventDefault(); select(row); });
  });
  document.addEventListener('keydown', function(ev){
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    var t = ev.target;
    if (t && (t.isContentEditable || /INPUT|SELECT|TEXTAREA/.test(t.tagName || ''))) return;
    var rs = rows(); if (!rs.length) return;
    var i = rs.indexOf(current());
    if (ev.key === 'j' || ev.key === 'ArrowDown'){ ev.preventDefault(); select(rs[Math.min(i + 1, rs.length - 1)], 'replace', true); }
    if (ev.key === 'k' || ev.key === 'ArrowUp'){ ev.preventDefault(); select(rs[Math.max(i - 1, 0)], 'replace', true); }
  });
  window.addEventListener('popstate', function(){
    var id = location.pathname.replace('/case/', '');
    var row = document.querySelector(".qrow[href='/case/" + id + "']");
    if (row) select(row, false); else location.reload();
  });
  wireForms();
})();
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



def queue_label(q):
    """Human-facing queue name; raw value stays in forms, logs and technical details."""
    return (q or "").replace("_", " ").capitalize()


def status_label(s):
    if s and s.startswith("assigned:"):
        return "assigned to " + queue_label(s.split(":", 1)[1])
    return s or ""


def _view_ids(st, view):
    ids = sorted(st.results)
    if view == "held":
        ids = [i for i in ids if st.results[i]["decision"] == "hold"]
    elif view == "routed":
        ids = [i for i in ids if st.results[i]["decision"] == "route"]
    elif view == "flagged":
        ids = [i for i in ids if st.results[i].get("injection_attempt") or st.results[i].get("writer_withdrawal")]
    return ids


def _first_pending(st, view):
    for _title, members in _queue_groups(st, _view_ids(st, view)):
        for i in members:
            if i not in st.status:
                return i
    return None


def _flags(r):
    out = ""
    if r.get("injection_attempt"):
        out += "<span class='flag inj'>injection</span>"
    if r.get("writer_withdrawal"):
        out += "<span class='flag wd'>withdrawal</span>"
    return out


def _shell(title, body, with_js=False):
    js = "<script>%s</script>" % JS if with_js else ""
    return ("<!doctype html><html lang=en><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>%s</title><style>%s</style></head><body>%s%s</body></html>"
            % (e(title), CSS, body, js)).encode()


def _open_counts(st):
    held_open = sum(1 for i, r in st.results.items() if r["decision"] == "hold" and i not in st.status)
    routed_open = sum(1 for i, r in st.results.items() if r["decision"] == "route" and i not in st.status)
    return held_open, routed_open


def _masthead(st, subtitle):
    held_open, routed_open = _open_counts(st)
    done = sum(1 for i in st.status if i in st.results)
    total = len(st.results)
    return ("<div class=masthead><div class=masthead-in>"
            "<div class=brand><span class=bank>Meridian Mutual Bank</span> &middot; Complaint intake</div>"
            "<span class=syn>Synthetic data</span>"
            "<span class=subtitle>%s</span>"
            "<span class=triage-progress><b>%d</b> of %d handled &middot; %d to review &middot; %d to approve</span>"
            "</div></div>"
            % (e(subtitle), done, total, held_open, routed_open))


def _qrow(st, cid, selected):
    r = st.results[cid]
    c = st.cases.get(cid, {})
    s = st.status.get(cid)
    if r["decision"] == "route":
        meta = "to <b>%s</b> &middot; %s" % (e(queue_label(r.get("queue"))), e(r.get("recommended_action")))
    else:
        meta = e(reason_prose(r.get("reason")))
    flags = _flags(r)
    status_html = ""
    if s:
        status_html = " <span class=qstatus>&#10003; %s</span>" % e(status_label(s))
    flag_row = "<div class=qflags>%s%s</div>" % (flags, status_html) if flags or status_html else ""
    return ("<a class='qrow%s' href='/case/%s'%s>"
            "<span class=qtop><span class=qsubj>%s</span><span class=qid>%s</span></span>"
            "<span class=qmeta>%s</span>%s</a>"
            % (" sel" if selected else "", e(cid),
               " aria-current='true'" if selected else "",
               e(c.get("subject", "")), e(cid), meta, flag_row))


def _section(title, count):
    return "<div class=qsection>%s <span class=n>%d</span></div>" % (e(title), count)


def _queue_groups(st, ids):
    """Group for triage order: escalations, other holds, duplicates, then routed approvals."""
    esc, other_hold, dup, routed = [], [], [], []
    for i in ids:
        r = st.results[i]
        if r["decision"] == "route":
            routed.append(i)
        elif (r.get("reason") or "").startswith("escalation:"):
            esc.append(i)
        elif (r.get("reason") or "").startswith("duplicate_of:"):
            dup.append(i)
        else:
            other_hold.append(i)
    groups = []
    if esc:
        groups.append(("Escalations", esc))
    if other_hold:
        groups.append(("Held for review", other_hold))
    if dup:
        groups.append(("Duplicates", dup))
    if routed:
        groups.append(("Ready to approve", routed))
    return groups


def _queue_html(st, view, selected):
    ids = _view_ids(st, view)
    tabs = "".join("<a %s href='/?view=%s'>%s</a>" % ("class=on" if view == v else "", v, label)
                   for v, label in (("all", "All"), ("held", "Held"), ("routed", "Routed"), ("flagged", "Flagged")))
    parts = ["<div class=filters>" + tabs + "</div>"]
    groups = _queue_groups(st, ids)
    if not groups:
        parts.append("<p class='muted small' style='padding:0 12px'>No cases in this view.</p>")
    for title, members in groups:
        parts.append(_section(title, len(members)))
        parts.append("<div class=queue>" + "".join(_qrow(st, i, i == selected) for i in members) + "</div>")
    parts.append("<p class=footnote>Demo data - fictional bank, invented complaints. "
                 "Approving records the approval in the audit log; nothing is sent to a customer.</p>")
    return "".join(parts)


def detail_pane(st, cid, note=None):
    """The right-pane (or standalone) case view: one surface, sections by spacing and headings."""
    r = st.results[cid]
    c = st.cases.get(cid, {})
    s = st.status.get(cid)
    raw_fields = r.get("fields") or {}
    out = ["<div class=case>", "<p class=backlink><a href='/'>&larr; Back to queue</a></p>"]
    if note:
        out.append("<p class=notice>%s</p>" % e(note))
    out.append("<h1 class=case-subj>%s</h1>" % e(c.get("subject", "")))
    out.append("<div class=letter-body>%s</div>" % e(c.get("body", "")))
    out.append("<hr><h2>Decision</h2>")
    if r["decision"] == "route":
        status = "<span class='dot route'></span><b>Routed</b> to <b>%s</b>" % e(queue_label(r.get("queue")))
        rec_text = (r.get("recommended_action") or "").rstrip(".")
        why = "<p class=status-why>Recommended next step: %s.</p>" % e(rec_text)
        actions = ("<form method=post action='/case/%s/approve'><button class=btn type=submit>Approve recommendation</button></form>"
                   "<form method=post action='/case/%s/reviewed'><button class='btn sec' type=submit>Mark reviewed - no action</button></form>"
                   % (cid, cid))
    else:
        status = "<span class='dot held'></span><b>Held</b> &middot; %s" % e(reason_prose(r.get("reason")))
        why = ("<p class=status-why>The policy checks could not clear this case; "
               "a person decides what happens next.</p>")
        opts = "".join("<option value='%s'>%s</option>" % (e(q), e(queue_label(q))) for q, _a in policy.CATEGORIES.values())
        actions = ("<form method=post action='/case/%s/assign'><select name=queue aria-label='Assign queue'>%s</select>"
                   "<button class=btn type=submit>Assign queue</button></form>"
                   "<form method=post action='/case/%s/reviewed'><button class='btn sec' type=submit>Mark reviewed - no routing</button></form>"
                   % (cid, opts, cid))
    flags = _flags(r)
    flags_html = (" " + flags) if flags else ""
    out.append("<div class=status-line>%s%s</div>%s" % (status, flags_html, why))
    if s:
        out.append("<p class=status-why><span class=qstatus>&#10003; Handled: %s.</span></p>" % e(status_label(s)))
    out.append("<hr><h2>What the system extracted</h2>")
    if raw_fields:
        out.append("<dl class=kv>" + "".join(
            "<dt>%s</dt><dd>%s</dd>" % (e(FIELD_LABELS.get(k, k.replace("_", " "))), e(_fmt_val(k, v)))
            for k, v in raw_fields.items()) + "</dl>")
    else:
        if (r.get("reason") or "").startswith(("escalation:", "conflicting")):
            out.append("<p class='status-why'>Nothing extracted - this case was held at an earlier check "
                       "(escalation triggers run first, on the raw text).</p>")
        else:
            out.append("<p class=status-why>None recorded.</p>")
    raw_json = json.dumps({"decision": r["decision"], "queue": r.get("queue"), "reason": r.get("reason"),
                           "fields": raw_fields,
                           "injection_patterns": r.get("injection_patterns"),
                           "withdrawal_patterns": r.get("withdrawal_patterns")}, indent=1)
    out.append("<details class=tech><summary class='muted small'>Technical details</summary>"
               "<pre>%s</pre></details>" % e(raw_json))
    out.append("<hr><h2>Your action</h2>")
    out.append(actions)
    out.append("<p class='muted small' style='margin:6px 0 0'>Actions are recorded in the audit log. "
               "Approving never sends anything to the customer.</p>")
    out.append("</div>")
    return "".join(out)


def inbox_page(st, view="all", selected=None, note=None):
    if selected and selected in st.results:
        pane = detail_pane(st, selected, note)
    else:
        pane = ("<div class=empty><p><b>Select a case from the queue.</b></p>"
                "<p class=keys>j / k or arrow keys move between cases</p></div>")
    sel_cls = " has-sel" if (selected and selected in st.results) else ""
    body = (_masthead(st, "Every decision below was made by policy checks; a person finishes each one.")
            + "<div class='inbox%s'><div class=queue-col>" % sel_cls + _queue_html(st, view, selected) + "</div>"
            + "<div class=detail-col id=pane>" + pane + "</div></div>")
    return _shell("Complaint review queue", body, with_js=True)


def snapshot_html(cases, results):
    """Static held-queue snapshot written by run.py as review.html. Same design, no server."""

    class _St:
        pass

    st = _St()
    st.results = {r["id"]: r for r in results}
    st.cases = {c["id"]: c for c in cases}
    st.status = {}
    held = [i for i in sorted(st.results) if st.results[i]["decision"] == "hold"]
    groups = _queue_groups(st, held)
    parts = []
    for title, members in groups:
        parts.append(_section(title, len(members)))
        rows = "".join(_qrow(st, i, False) for i in members)
        parts.append("<div class=queue>" + rows.replace("href='/case/", "href='#case-") + "</div>")
    body = (_masthead(st, "Held for human review - snapshot. Approving or assigning happens in the live review app.")
            + "<div class=inbox><div class=queue-col>" + "".join(parts) + "</div>"
            + "<div class=detail-col><div class=empty><p><b>%d cases held.</b> "
              "Open the live review app to work through them.</p></div></div></div>" % len(held))
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
            q = parse_qs(parsed.query)
            if path == "/":
                view = q.get("view", ["all"])[0]
                if view not in ("all", "held", "routed", "flagged"):
                    view = "all"
                selected = None if "queue" in q else _first_pending(st, view)
                return self.send(inbox_page(st, view, selected=selected))
            if path.startswith("/case/") and path[6:] in st.results:
                cid = path[6:]
                if q.get("partial") or self.headers.get("X-Partial"):
                    return self.send(detail_pane(st, cid).encode())
                return self.send(inbox_page(st, "all", selected=cid))
            self.send(_shell("Not found", "<div class=inbox><p>Not found.</p></div>"), 404)

        def do_POST(self):
            path = unquote(urlparse(self.path).path)
            parts = path.strip("/").split("/")
            want_partial = bool(self.headers.get("X-Partial"))

            def answer(cid, note=None):
                body = detail_pane(st, cid, note).encode() if want_partial \
                    else inbox_page(st, "all", selected=cid, note=note)
                return self.send(body)

            if len(parts) != 3 or parts[0] != "case" or parts[1] not in st.results:
                return self.send(_shell("Not found", "<div class=inbox><p>Not found.</p></div>"), 404)
            cid, action = parts[1], parts[2]
            if st.status.get(cid):
                return answer(cid, note="Already %s. No change made." % status_label(st.status[cid]))
            if action == "approve" and st.results[cid]["decision"] == "route":
                st.status[cid] = "approved"
                st.log(id=cid, action="approved", queue=st.results[cid].get("queue"))
                return answer(cid, note="Recommendation approved. Recorded; nothing was sent.")
            if action == "reviewed":
                st.status[cid] = "reviewed"
                st.log(id=cid, action="reviewed")
                return answer(cid, note="Marked reviewed.")
            if action == "assign" and st.results[cid]["decision"] == "hold":
                form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
                queue = form.get("queue", [""])[0]
                if queue not in {q for q, _a in policy.CATEGORIES.values()}:
                    return answer(cid, note="Unknown queue. No change made.")
                st.status[cid] = "assigned:%s" % queue
                st.log(id=cid, action="assigned", queue=queue)
                return answer(cid, note="Assigned to %s by a human." % queue_label(queue))
            self.send(_shell("Not found", "<div class=inbox><p>Not found.</p></div>"), 404)
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
