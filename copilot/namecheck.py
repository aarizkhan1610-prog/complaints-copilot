"""Second line of defence for redaction: flag words that might be names the rules missed.

Runs on the already-redacted text, before any AI call. It flags a capitalised word in the middle of a sentence
when the word is not ordinary vocabulary (it never appears in lower case in the case set or the policies) and is
not a known term. The handler confirms or masks each flag; nothing is sent while flags are open on a live run.
"""
import re
from functools import lru_cache

from .data import load_complaints, policy_corpus_text

CAP_RE = re.compile(r"(?<![\[\w'’])([A-Z][a-z]{1,}(?:[A-Z][a-z]+)?(?:[-'][A-Z]?[a-z]+)*)\b")
KNOWN = {
    # calendar
    "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
    "November", "December", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    # banking and UK terms that appear capitalised
    "Faster", "Payment", "Payments", "Direct", "Debit", "Standing", "Order", "Visa", "Mastercard", "ISA",
    "Ombudsman", "Financial", "Conduct", "Authority", "Final", "Response", "Summary", "Resolution",
    "Fraud", "Scams", "Vulnerable", "Customer", "Support", "Lending", "Specialists", "Senior", "Complaints",
    "Review", "Digital", "Operations", "Handler", "Team", "Bank", "Harbourline", "Easy", "Access", "Saver",
    "Spain", "France", "England", "Scotland", "Wales", "UK", "WhatsApp", "Facebook", "Google", "Apple",
    "Amazon", "HMRC", "DWP", "Universal", "Credit", "Power", "Attorney", "Lasting", "Court", "Probate",
    "Christmas", "Easter", "Dear", "Regards", "Thanks", "Kind", "Yours", "Sincerely", "Sir", "Madam",
    "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Sept", "Oct", "Nov", "Dec",
    "Mr", "Mrs", "Ms", "Miss", "Dr", "Mum", "Dad", "Ops", "Travel", "Everyday", "Road", "Street", "Lane", "Avenue",
    "Ack", "Cust", "Pref", "Chased", "Called", "Logged", "Told", "Sent", "Spoke", "Asked", "Checked",
}


@lru_cache
def _vocabulary():
    """Words seen in lower case anywhere in the cases or policies: ordinary vocabulary, not names."""
    text = policy_corpus_text() + " " + " ".join(
        c["complaint"] + " " + " ".join(n["text"] for n in c["case_notes"]) for c in load_complaints())
    return {w for w in re.findall(r"\b[a-z][a-z'-]+\b", text)}


def _sentence_start(text, i):
    j = i - 1
    while j >= 0 and text[j] in " \t\"'‘“(":
        j -= 1
    return j < 0 or text[j] in ".!?:\n"


def suspect_names(text_by_part):
    """Return [{"part", "word"}] for words that may be unmasked names."""
    vocab = _vocabulary()
    out, seen = [], set()
    for part, text in text_by_part.items():
        for m in CAP_RE.finditer(text):
            w = m.group(1)
            parts = w.split("-")
            if all(p in KNOWN for p in parts) or w.lower() in vocab or len(w) < 3 or _sentence_start(text, m.start()):
                continue
            if (part, w) not in seen:
                seen.add((part, w))
                out.append({"part": part, "word": w})
    return out
