"""Tracker & Escalator (Agent 4) and fix verification for the web channel.
Deterministic state machine: the model only writes escalation text, and nothing is sent without the resident's approval."""
from datetime import timedelta

from . import agents, db, services

STAGE = {"open": 0, "acknowledged": 1, "in_progress": 2, "escalated_t1": 1, "escalated_t2": 1, "escalated_t3": 1, "resolved": 3, "closed_unverified": 3}


def is_closed(i: dict) -> bool:
    return i["status"] in ("resolved", "closed_unverified")


def checkin_due(i: dict) -> bool:
    return not is_closed(i) and db.now() >= i["expected_by"] and not i["pending_escalation"] and not i["verification_requested_at"]


def not_fixed(i: dict, citizen: str, language: str) -> dict | None:
    """Resident says it's still broken: draft the next tier and wait for consent."""
    db.add_event(i["issue_id"], "citizen_no", citizen)
    if i["escalation_tier"] >= 3:
        db.update_issue(i["issue_id"], expected_by=db.now() + timedelta(days=7))
        return None
    auth = db.authority(i["authority_id"])
    draft, mode = agents.escalate(i, auth, i["escalation_tier"] + 1, db.timeline(i["issue_id"]), language)
    draft["mode"] = mode
    db.update_issue(i["issue_id"], pending_escalation=draft)
    db.add_event(i["issue_id"], "escalation_drafted", "system", {"tier": draft["tier"], "mode": mode})
    return draft


def approve(i: dict, citizen: str) -> str:
    d = i["pending_escalation"]
    auth = db.authority(i["authority_id"])
    if d["tier"] == 3:
        how = "handed_to_citizen"  # Awaaz never posts on anyone's behalf
    else:
        cc = (auth.get("escalation_contacts") or {}).get(i["sector"], {}).get("email")
        sent = "@" in (auth["filing_target"] or "") and services.send_email([auth["filing_target"]], d["subject"], d["body"], [cc] if cc and d["tier"] == 2 else None)
        how = "email" if sent else "assisted"
    db.update_issue(i["issue_id"], pending_escalation=None, escalation_tier=d["tier"], status=f"escalated_t{d['tier']}",
                    expected_by=db.now() + timedelta(days=7))
    db.add_event(i["issue_id"], "escalation_approved", citizen, {"tier": d["tier"], "delivery": how})
    return how


def decline(i: dict, citizen: str):
    db.add_event(i["issue_id"], "escalation_declined", citizen, {"tier": (i["pending_escalation"] or {}).get("tier")})
    db.update_issue(i["issue_id"], pending_escalation=None)


def claim_fixed(i: dict, citizen: str) -> str:
    """A resident says it's fixed. A second resident must confirm, unless only one person ever reported it."""
    db.add_event(i["issue_id"], "fix_claimed", citizen)
    if db.reporter_count(i["issue_id"]) <= 1:
        resolve(i, citizen)
        return "resolved"
    db.update_issue(i["issue_id"], verification_requested_at=db.now())
    return "waiting"


def confirm(i: dict, citizen: str, fixed: bool):
    if fixed:
        resolve(i, citizen)
    else:
        db.update_issue(i["issue_id"], verification_requested_at=None,
                        status=f"escalated_t{i['escalation_tier']}" if i["escalation_tier"] else "in_progress")
        db.add_event(i["issue_id"], "fix_disputed", citizen)


def resolve(i: dict, citizen: str):
    db.update_issue(i["issue_id"], status="resolved", resolved_at=db.now(), verification_requested_at=None, pending_escalation=None)
    db.add_event(i["issue_id"], "resolved", citizen)


def authority_action(i: dict, action: str):
    if is_closed(i):
        return
    if action in ("acknowledge", "in_progress"):
        status = "acknowledged" if action == "acknowledge" else "in_progress"
        if not i["escalation_tier"]:
            db.update_issue(i["issue_id"], status=status)
        db.add_event(i["issue_id"], status, i["authority_id"])
    elif action == "fixed":
        db.update_issue(i["issue_id"], verification_requested_at=db.now())
        db.add_event(i["issue_id"], "authority_marked_fixed", i["authority_id"])
