"""One complaint in, one decision out: route + recommend, or hold with the exact reason.

Order of the gates (first one that fires decides):
  1. escalation triggers on the raw text (always human)
  2. the writer contradicting their own complaint (conflicting_instructions)
  3. required fields, in policy order
  4. duplicate of a prior complaint from the same account
  5. LLM/deterministic field disagreement (only when the LLM extractor is enabled)
  6. route to the owning queue with the policy's recommended action for a human to approve

The system never replies to a customer, never resolves a complaint, never touches an
account. It recommends; a human approves.
"""
from . import checks, policy


def process(case, log, extractor=None):
    """case: {"id", "subject", "body"}. log: AuditLog. extractor: LLMExtractor or None."""
    cid = case["id"]
    raw = "%s\n%s" % (case.get("subject", ""), case.get("body", ""))
    toks = sorted(checks.tokenset(raw))
    amounts = checks.find_amounts(raw)
    base = {
        "id": cid,
        "account_reference": checks.find_account_ref(raw),
        "tokens": toks,
        "injection_attempt": bool(checks.injection_flags(raw)),
        "injection_patterns": checks.injection_flags(raw),
        "writer_withdrawal": bool(checks.withdrawal_flags(raw)),
        "withdrawal_patterns": checks.withdrawal_flags(raw),
    }

    def hold(reason, **extra):
        rec = dict(base, decision="hold", reason=reason)
        rec.update(extra)
        return log.append(rec)

    # 1. escalation triggers (raw text, before everything)
    esc = checks.escalation(raw, amounts)
    if esc:
        return hold(esc)

    # 2. writer contradicts their own complaint
    if checks.conflicting_withdrawal(raw):
        return hold("conflicting_instructions")

    # 3. required fields in policy order
    fields, missing = checks.check_fields(raw)
    if missing:
        return hold(missing, fields={k: v for k, v in fields.items() if k != "category_scores"})

    # 4. duplicate of a prior complaint from the same account
    dup, sim = log.find_duplicate(fields["account_reference"], set(toks), checks.DUPLICATE_THRESHOLD)
    if dup:
        return hold("duplicate_of:%s" % dup["id"], duplicate_similarity=round(sim, 3))

    # 5. LLM cross-check: the model's fields must agree with the deterministic parse
    llm_fields = None
    if extractor is not None:
        rec = extractor.extract(case.get("subject", ""), case.get("body", ""))
        llm_fields = rec
        disagree = field_disagreements(fields, rec)
        if disagree:
            return hold("extraction_disagreement:%s" % disagree[0],
                        disagreements=disagree, deterministic_fields=_pub(fields), llm_fields=rec)

    # 6. route + recommend (a human approves the action; nothing is sent or resolved)
    queue, action = policy.CATEGORIES[fields["category"]]
    return log.append(dict(base, decision="route", queue=queue, category=fields["category"],
                           recommended_action=action, fields=_pub(fields), llm_fields=llm_fields))


def _pub(fields):
    return {k: v for k, v in fields.items() if k != "category_scores"}


def field_disagreements(fields, rec):
    """Material fields where the two routes disagree. Names and account refs compared
    normalized; amounts with a small tolerance; dates by exact string only when both
    routes found one."""
    out = []
    dn = (fields.get("customer_name") or "").lower().strip()
    ln = (rec.get("customer_name") or "").lower().strip()
    if dn and ln and dn != ln and dn not in ln and ln not in dn:
        out.append("customer_name")
    da = (fields.get("account_reference") or "")
    la = (rec.get("account_reference") or "")
    da_digits = "".join(ch for ch in da if ch.isdigit())
    la_digits = "".join(ch for ch in la if ch.isdigit())
    if da_digits and la_digits:
        if len(da_digits) == len(la_digits):
            # both routes returned a complete reference: it must match in full
            if da_digits != la_digits:
                out.append("account_reference")
        elif da_digits[-4:] != la_digits[-4:]:
            # one side is a masked/short rendering (e.g. last-4 of a longer ref):
            # only then is suffix matching intended, and it is explicitly last-4
            out.append("account_reference")
    if fields.get("amounts") and rec.get("amount") is not None:
        if abs(fields["amounts"][0] - float(rec["amount"])) > 0.01:
            out.append("amount")
    return out
