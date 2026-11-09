"""Deterministic checks on the raw complaint text.

These are the only gate for automatic routing. Model output never decides anything:
it supplies extracted fields that must AGREE with what these checks find, and any
material disagreement sends the complaint to a human. Escalation, injection and
duplicate scans always run on the raw text so an extraction error cannot bypass them.
"""
import re
from . import policy

_WORD = re.compile(r"[a-z0-9']+")
_AMOUNT = re.compile(r"\$\s*([\d,]+(?:\.\d{1,2})?)")
_ACCT = re.compile(
    r"(?:account|acct|card|loan|mortgage|cd)\s+(?:account\s+)?(?:number\s+|no\.?\s+|#)?"
    r"(?:ending\s+(?:in\s+)?)?(\d{4,6})\b", re.IGNORECASE)
_CASE_ID = re.compile(r"\bcase\s+(?:id\s+|number\s+|no\.?\s+|#)?([A-Za-z0-9-]{4,})\b", re.IGNORECASE)
_NAME_PATTERNS = [
    re.compile(r"\bmy name is\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})", re.IGNORECASE),
    re.compile(r"\bi'm\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*[,.]", re.IGNORECASE),
    re.compile(r"\bi am\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*[,.]", re.IGNORECASE),
    re.compile(r"\bthis is\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*[,.]", re.IGNORECASE),
    re.compile(r"\bname[:\s]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*[,.]"),
    re.compile(r"^\s*(?:(?i:hi|hello|hey),?\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s*(?:\s+(?i:again|here|writing))?\s*,\s*(?i:account|acct|card|loan|mortgage)\b", re.MULTILINE),
    re.compile(r"[\u2013\u2014-]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*$"),
]
_PRODUCT_DOMAINS = {
    "loan": ["loan", "mortgage", "escrow"],
    "card": ["card", "checking", "savings", "account", " cd", "wire", "debit", "atm"],
    "digital": ["app", "website", "online banking", "login", "log in", "password", "mobile"],
    "branch": ["branch", "teller", "atm"],
}

# A complaint must say something is wrong. Compliments and pure notes have no marker.
PROBLEM_MARKERS = [
    "wrong", "error", "n't", " not ", "never", " no ", "refus", "missing", "late",
    "fee", "charg", "denied", "reject", "crash", "locked", "can't", "cannot",
    "won't", "wont", "problem", "issue", "stopped", "stuck", "twice", "disconnect",
    "out-of-service", "out of service", "downhill", "terrible", "glitch", "past due",
    "stolen", "dispute", "complaint", "short by", "ate my card",
]


def words(text):
    return _WORD.findall(text.lower())


def tokenset(text):
    return {w for w in words(text) if len(w) > 2}


def find_amounts(text):
    out = []
    for m in _AMOUNT.finditer(text):
        try:
            out.append(float(m.group(1).replace(",", "")))
        except ValueError:
            pass
    return out


def find_account_ref(text):
    m = _ACCT.search(text)
    if m:
        return "acct:" + m.group(1)
    m = _CASE_ID.search(text)
    if m:
        return "case:" + m.group(1)
    return None


def find_name(text):
    for pat in _NAME_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1)
    # signature: last non-empty line of 1-3 capitalized words whose first word appears earlier
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) > 1:
        last = lines[-1].rstrip(".")
        if re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}", last):
            first = last.split()[0].lower()
            if first not in ("hi", "hello", "thanks", "thank", "please", "my", "re", "subject") \
                    and first in " ".join(lines[:-1]).lower():
                return last
    return None


def find_product_domains(text):
    t = " " + text.lower() + " "
    return {d for d, kws in _PRODUCT_DOMAINS.items() if any(_contains(t, k) for k in kws)}


def has_date(text):
    t = text.lower()
    if any(m in t for m in policy.MONTHS):
        return True
    if any(v in t for v in policy.DATE_VAGUE_OK):
        return True
    return bool(re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", t))


# Phrase matching. Short single words must match on letter boundaries or they fire
# inside unrelated words (the frozen holdout caught exactly this: "sue" inside
# "issued"/"issue", "app" inside "unhappiness", "late" inside "lately"). Multiword
# phrases and phrases with punctuation match as substrings. Words in PREFIX_WORDS are
# intended prefixes ("charg" matches charge/charged/charging) and get a left boundary only.
PREFIX_WORDS = {"charg", "refus", "reject", "crash", "disconnect", "glitch", "discriminat"}


def _contains(t, phrase):
    if not phrase.isalpha():
        return phrase in t
    if phrase in PREFIX_WORDS:
        return re.search(r"(?<![a-z])" + re.escape(phrase), t) is not None
    return re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", t) is not None


def _count_phrases(text, phrases):
    t = " " + text.lower() + " "
    return sum(1 for p in phrases if _contains(t, p))


def category_scores(text):
    return {c: _count_phrases(text, ph) for c, ph in policy.CATEGORY_PHRASES.items()}


def has_problem_marker(text):
    t = " " + text.lower() + " "
    return any(_contains(t, m) for m in PROBLEM_MARKERS)


def resolve_category(text, product_domains):
    """The owning category, or None when the complaint is not clearly about one thing.

    Rules: a complaint needs a problem marker (compliments are not complaints); a loan
    customer's loan-related complaint goes to loan servicing; otherwise the category
    with the most matched phrases wins only when it is decisive (no competitor, or more
    than twice the runner-up). Anything else is unclear -> human triage.
    """
    if not has_problem_marker(text):
        return None, category_scores(text)
    t = " " + text.lower() + " "
    if any(_contains(t, p) for p in policy.ROUTING_UNCERTAINTY_PHRASES):
        # the customer themselves doesn't know where this belongs: human triage
        return None, category_scores(text)
    scores = category_scores(text)
    if "loan" in product_domains and scores["loan_servicing"] > 0:
        return "loan_servicing", scores
    best = max(scores.values()) if scores else 0
    if best == 0:
        return None, scores
    second = sorted(scores.values(), reverse=True)[1]
    if second == 0 or best > 2 * second:
        return [c for c, s in scores.items() if s == best][0], scores
    return None, scores


def escalation(text, amounts):
    t = " " + text.lower() + " "
    for reason, phrases in policy.ESCALATION_PHRASES:
        if any(_contains(t, p) for p in phrases):
            return reason
    if amounts and max(amounts) > policy.ESCALATION_AMOUNT:
        return "escalation:amount"
    return None


def injection_flags(text):
    t = " " + text.lower() + " "
    return [p for p in policy.INJECTION_PHRASES if _contains(t, p)]


def withdrawal_flags(text):
    """Writer retracting or demanding deletion of their own complaint: human handles it."""
    t = " " + text.lower() + " "
    return [p for p in policy.WITHDRAWAL_PHRASES if _contains(t, p)]


def conflicting_withdrawal(text):
    t = " " + text.lower() + " "
    return any(_contains(t, p) for p in policy.CONFLICT_PHRASES)


def amount_material(text):
    """The complaint turns on a dollar amount unless the customer asks for a full
    reversal of a known fee (the record already has the fee; no amount needed)."""
    t = " " + text.lower() + " "
    triggers = ("fee", "charge", "charged", "overcharged", "penalty", "refund",
                "payment", "withdrew", "withdrawal", "short by", "difference")
    if not any(_contains(t, k) for k in triggers):
        return False
    if any(p in t for p in policy.FULL_REVERSAL_PHRASES):
        return False
    return True


def date_material(text):
    t = " " + text.lower() + " "
    triggers = ("fee", "charge", "charged", "payment", "late", "statement", "deposit",
                "withdrawal", "wire", "denied", "increase", "went up", "glitch")
    return any(_contains(t, k) for k in triggers)


def check_fields(text):
    """Required fields in policy order. Returns (fields, first_missing_reason or None).

    Order: name, account reference, clear category, identified product, amount when
    material, date when material. When neither product nor category can be identified
    the reason is category_clear: the complaint cannot be understood well enough to
    route at all.
    """
    fields = {
        "customer_name": find_name(text),
        "account_reference": find_account_ref(text),
        "product_domains": sorted(find_product_domains(text)),
        "amounts": find_amounts(text),
        "has_date": has_date(text),
    }
    category, scores = resolve_category(text, set(fields["product_domains"]))
    fields["category"] = category
    fields["category_scores"] = scores
    if not fields["customer_name"]:
        return fields, "missing_field:customer_name"
    if not fields["account_reference"]:
        return fields, "missing_field:account_reference"
    if not category:
        return fields, "missing_field:category_clear"
    if not fields["product_domains"]:
        return fields, "missing_field:product_identified"
    if amount_material(text) and not fields["amounts"]:
        return fields, "missing_field:amount_present_when_material"
    if date_material(text) and not fields["has_date"]:
        return fields, "missing_field:date_present_when_material"
    return fields, None


def similarity(a_tokens, b_tokens):
    if not a_tokens or not b_tokens:
        return 0.0
    inter = len(a_tokens & b_tokens)
    return inter / float(len(a_tokens | b_tokens))


def containment(a_tokens, b_tokens):
    """Share of the shorter complaint's tokens present in the longer one. Short
    follow-ups ('still waiting on the fee') must match their long original."""
    if not a_tokens or not b_tokens:
        return 0.0
    inter = len(a_tokens & b_tokens)
    return inter / float(min(len(a_tokens), len(b_tokens)))


DUPLICATE_THRESHOLD = 0.5
