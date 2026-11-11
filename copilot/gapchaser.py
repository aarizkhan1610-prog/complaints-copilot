"""Gap chaser: for each missing handover field, the question that fills it and who to ask.

Fixed wording (no AI), so the questions are consistent and approved in advance. The handler sends them;
nothing is sent to a customer automatically.
"""
QUESTIONS = {
    "summary": ("internal", "Write a two-line summary of what the customer is unhappy about."),
    "products_accounts": ("customer", "Which of your accounts or cards does this concern? The last four digits are enough."),
    "desired_outcome": ("customer", "What would you like us to do to put this right?"),
    "timeline": ("customer", "Roughly when did this happen, and when did you first contact us about it?"),
    "actions_taken": ("internal", "Check the case system for any action taken so far and record it."),
    "evidence_held": ("customer", "Do you have anything that shows what happened, such as a letter, screenshot or "
                                  "statement? You can send a photo."),
    "vulnerability_assessment": ("customer", "Is there anything about your circumstances that makes this harder to "
                                             "deal with, or any support that would help us communicate with you?"),
    "contact_preference": ("customer", "How would you prefer us to contact you (phone, email or letter), and are "
                                       "there times or formats that work best?"),
    "open_questions": ("internal", "List what the specialist team will need to decide this case."),
    "third_party_authority": ("customer", "As you're contacting us for someone else, please send a signed "
                                          "authority or Power of Attorney so we can discuss their account with you."),
    "frd_payment_details": ("customer", "For each payment, please tell us the date, the approximate time and the amount."),
    "frd_payee_details": ("customer", "Who did you pay? Please give the name on the account, and the sort code and "
                                      "account number if you have them."),
    "frd_contact_method": ("customer", "How did the person first contact you: phone call, text, email, social media "
                                       "or a website?"),
    "frd_security_details": ("customer", "Did you share any passcodes, PINs or online banking details with them? "
                                         "It's fine to tell us; it helps us protect your account."),
    "account_secured": ("internal", "Confirm the card is blocked and online banking credentials are reset (FRD-4), "
                                    "and record it."),
}


def questions_for(gap_keys):
    return [{"key": k, "who": QUESTIONS[k][0], "question": QUESTIONS[k][1]} for k in gap_keys if k in QUESTIONS]


def customer_message(gap_keys):
    qs = [q["question"] for q in questions_for(gap_keys) if q["who"] == "customer"]
    if not qs:
        return ""
    lines = ["Dear [customer name],", "",
             "Thank you for contacting us. So that the right team can look into your complaint without delay, "
             "could you help us with the following:", ""]
    lines += [f"{i}. {q}" for i, q in enumerate(qs, 1)]
    lines += ["", "You can reply to this message or call us, whichever is easier.", "", "Kind regards,",
              "[handler name], Complaints team"]
    return "\n".join(lines)
