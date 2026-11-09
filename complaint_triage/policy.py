"""Synthetic complaint-handling policy for the fictional 'Meridian Mutual Bank'.

Everything here is invented for a demo. It is not based on any real bank's policies
and makes no regulatory claim. Mirrors briefs/policy-pack.md; that document is the
human-readable source, this module is the executable one.
"""

# category -> (queue, recommended next action a human approves)
CATEGORIES = {
    "card_fee_dispute": (
        "card_services",
        "Check the fee against the account's fee schedule; if misapplied, prepare a reversal for agent approval.",
    ),
    "unauthorized_transaction": (
        "priority_review",
        "Always human-led. Restrict the card if the customer asked; never auto-decide fraud.",
    ),
    "loan_servicing": (
        "loan_servicing",
        "Pull the loan ledger, confirm payment application dates, draft a correction or explanation for agent approval.",
    ),
    "digital_access": (
        "digital_support",
        "Verify identity through the existing bank process; reset access; confirm with the customer.",
    ),
    "service_quality": (
        "branch_ops",
        "Log against the branch/staff record; branch manager follows up within 3 business days.",
    ),
}

# Phrase lists for scoring the complaint's SUBJECT. The category with the most matched
# phrases wins only if it is the unique winner; a tie or no match means the category is
# not clear and the complaint is held (missing_field:category_clear).
# unauthorized_transaction is deliberately NOT scored here: it is detected only by the
# escalation scan, which always holds for a human.
CATEGORY_PHRASES = {
    "card_fee_dispute": [
        "overdraft", "fee", "fees", "late fee", "apr", "interest rate", "penalty", "service charge",
        "foreign transaction", "charged twice", "double charge", "charged me",
        "was charged", "been charged", "refund", "reverse", "reversal", "reimburse",
        "wire fee", "monthly charge",
    ],
    "loan_servicing": [
        "loan", "mortgage", "escrow", "autopay", "payment applied", "payment posted",
        "payment date", "payment was", "my payment", "past due", "late mark",
        "loan ledger", "principal",
    ],
    "digital_access": [
        "app", "log in", "login", "locked out", "password", "website", "online banking",
        "mobile", "can't access", "cannot access", "crashes", "error at login",
        "unexpected error", "won't load", "wont load", "rejected my", "deposit limit",
        "wrong balance", "shows the wrong", "display",
    ],
    "service_quality": [
        "teller", "branch", "rude", "dismissive", "manager", "waited", "on hold",
        "hold time", "disconnected", "paper statement", "atm kept",
        "ate my card", "follow up", "customer service",
    ],
}

# Escalation triggers: scanned on the raw email text, always hold, checked before
# anything else. Ordered: the first matching group supplies the hold reason.
ESCALATION_PHRASES = [
    ("escalation:legal", [
        "attorney", "lawyer", "lawsuit", "sue", "small claims", "legal action",
        "i will be contacting my",
    ]),
    ("escalation:discrimination", [
        "discriminat", "fair lending", "fair-lending", "my ethnicity", "my race",
        "my religion", "my national origin", "because of my age", "because of my gender",
        "my disability", "ethnicity was a factor",
    ]),
    ("escalation:regulator", [
        "cfpb", "consumer financial protection", " occ", "fdic", "ncua",
        "filing a complaint with", "filed a complaint with", "regulator",
        "better business bureau",
    ]),
    ("escalation:safety", [
        "hurt myself", "harm myself", "kill myself", "end it all", "end my life",
        "what i'll do to myself", "do to myself", "threat", "i'll come down",
        "shoot", "bomb",
    ]),
    ("escalation:unauthorized_txn", [
        "didn't make", "did not make", "wasn't me", "was not me", "never been to",
        "never made that", "don't recognize", "do not recognize", "unauthorized",
        "stolen", "i replied no", "replied no", "fraud", "identity theft",
        "i still have my card",
    ]),
]

# Disputed dollar amount strictly above this always holds for a human.
ESCALATION_AMOUNT = 25000.0

# Text aimed at the system rather than the bank. Never obeyed; the case is flagged
# injection_attempt:true and processed on its real content.
INJECTION_PHRASES = [
    "system note", "system:", "ignore your", "ignore previous", "ignore all",
    "ignore the rules", "skip all checks", "skip your checks", "do not hold this",
    "mark this resolved", "mark as resolved", "pre-approved", "forward this customer",
    "email my", "send my statements", "send the customer", "attacker@",
    "disregard",
]

# The customer says they don't know WHERE THIS BELONGS: human triage, no guessing.
# Deliberately routing-specific - "I'm not sure why I was charged" is an ordinary
# complaint about a clear product and must NOT trigger this gate.
ROUTING_UNCERTAINTY_PHRASES = [
    "not sure which", "unsure which", "not sure where", "unsure where",
    "don't know which", "do not know which", "don't know where to",
    "which department", "which team", "who handles", "who deals with",
]

# The writer withdrawing or contradicting their own complaint: a human decides.
CONFLICT_PHRASES = [
    "delete this complaint", "pretend i never wrote", "withdraw this complaint",
    "ignore this complaint", "don't refund anything", "do not refund anything",
]

# The customer retracting or demanding deletion of their own complaint. This is NOT
# adversarial prompt injection - it is an ordinary (if awkward) customer request that a
# human must handle, because the demo never deletes records. Flagged separately as
# writer_withdrawal so the two meanings stay distinct.
WITHDRAWAL_PHRASES = [
    "delete this complaint", "pretend i never wrote", "withdraw this complaint",
    "ignore this complaint", "never mind my complaint", "ignore my complaint",
    "cancel my complaint",
]

# Full-reversal wording: when present, a missing dollar amount is NOT a gap
# (the customer wants the whole fee gone, whatever it was - the record has the fee).
FULL_REVERSAL_PHRASES = ["remove the fee", "reverse the fee", "refund the fee", "remove it", "reverse it"]

# Date wording that satisfies date_present_when_material.
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december",
          "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec")
DATE_VAGUE_OK = ["last week", "yesterday", "today", "tonight", "this week", "last month"]
