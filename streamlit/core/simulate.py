"""Clearly labelled simulated history for the Live monitor.

Accountability charts need months of data; a new deployment has days. This adds ~90 days of synthetic complaints with
IDs AWZ-LHR-S0001…, reporters 'seed-hist-…', and the 'simulated' flag shown everywhere they appear. One click removes them."""
import random
from datetime import timedelta

from . import db

BBOX = (31.4615, 31.4785, 74.2615, 74.2855)  # Johar Town, Lahore
SECTORS = ["J Block", "H Block", "K Block", "L Block", "G Block", "M Block", "E Block", "R1 Block", "Q Block", "P Block"]
# Per department, so simulated complaints obey the same routing rules as the knowledge base (garbage → LWMC, street lights → MCL, …)
TEMPLATES = {
    "LWMC": ["Garbage not collected for days in {s}", "Overflowing waste container on {s} street {n}", "Garbage being burned near {s} market"],
    "WASA-LHR": ["Sewage overflowing in {s} street {n}", "Blocked drain near {s} mosque", "Missing manhole cover on {s} street {n}"],
    "WASA-LHR:water": ["No tap water in {s} street {n}", "Low water pressure in {s}", "Dirty tap water in {s} street {n}"],
    "LESCO": ["Transformer fault in {s}", "Power out on {s} street {n} since morning", "Sparking wires on a pole in {s}"],
    "MCL-LIGHTS": ["Street lights off on {s} street {n}", "Street lights flickering on {s} main road"],
    "MCL-ROADS": ["Pothole on the main road near {s} market", "Broken road surface on {s} street {n}", "Road dug up and not restored in {s}"],
    "TEPA": ["Traffic signal not working at {s} chowk", "Unmarked speed breaker on {s} main road"],
    "SNGPL": ["Low gas pressure in {s} street {n}", "Smell of gas near {s} park"],
    "MCL-ENC": ["Stalls blocking the footpath at {s} market", "Construction material blocking {s} street {n}"],
    "PHA": ["Fallen tree in {s} park", "Broken swings in {s} park"],
}
# department → (category, share of complaints, chance acknowledged, chance fixed, typical days to fix, chance a fix is resident-verified)
PROFILES = {
    "LWMC": ("sanitation", 0.20, 0.95, 0.9, 2.2, 0.92), "WASA-LHR": ("sanitation", 0.14, 0.8, 0.7, 8.5, 0.82),
    "LESCO": ("electrical", 0.14, 0.92, 0.88, 3.8, 0.9), "MCL-LIGHTS": ("electrical", 0.08, 0.75, 0.7, 8.5, 0.8),
    "MCL-ROADS": ("roads", 0.16, 0.6, 0.5, 21, 0.7), "TEPA": ("roads", 0.05, 0.8, 0.75, 10, 0.85),
    "SNGPL": ("gas", 0.07, 0.95, 0.9, 2.6, 0.93), "MCL-ENC": ("encroachment", 0.07, 0.5, 0.4, 30, 0.6),
    "PHA": ("other", 0.05, 0.85, 0.8, 6.5, 0.88), "WASA-LHR:water": ("water", 0.04, 0.8, 0.7, 7.5, 0.82),
}


# departments whose performance changes over the period (factor applied to fix time: >1 = slower in the past)
TRENDS = {"LWMC": 2.6, "LESCO": 1.5, "MCL-ROADS": 0.85, "WASA-LHR": 1.3}


def add_history(n: int = 650, days: int = 540, seed: int = 7) -> int:
    """~18 months of labelled simulated complaints: adoption grows over time, some departments improve,
    a few fixes are rejected by residents, some places keep breaking, and one area has a spike this week."""
    rnd = random.Random(seed)
    now = db.now()
    bench = {a["authority_id"]: a["benchmark_days"] for a in db.authorities()}
    citizens = [(f"seed-hist-{k:03d}", f"+9299900{k:05d}") for k in range(200)]  # range unused by real or demo residents
    db.executemany("insert into citizens (citizen_hash, phone) values (%s, %s) on conflict do nothing", citizens)
    keys, weights = zip(*[(k, p[1]) for k, p in PROFILES.items()])
    hotspots = [(key, rnd.uniform(BBOX[0], BBOX[1]), rnd.uniform(BBOX[2], BBOX[3]), rnd.choice(SECTORS))
                for key in rnd.choices(keys, weights, k=10)]
    plan = []
    for _ in range(n):
        if rnd.random() < 0.22:  # repeat locations: the same spot keeps breaking
            key, lat, lng, sector = rnd.choice(hotspots)
            lat += rnd.uniform(-0.0003, 0.0003); lng += rnd.uniform(-0.0003, 0.0003)
        else:
            key = rnd.choices(keys, weights)[0]
            lat, lng, sector = rnd.uniform(BBOX[0], BBOX[1]), rnd.uniform(BBOX[2], BBOX[3]), rnd.choice(SECTORS)
        ago = days * (1 - rnd.random() ** 0.55)  # more complaints recently: adoption grows
        plan.append((key, lat, lng, sector, ago))
    for _ in range(9):  # this week's spike: garbage piling up in M Block
        plan.append(("LWMC", rnd.uniform(31.4705, 31.4725), rnd.uniform(74.2780, 74.2800), "M Block", rnd.uniform(0.2, 5.5)))
    issues, reports, events = [], [], []
    for k, (key, lat, lng, sector, ago) in enumerate(plan, 1):
        aid = key.split(":")[0]
        cat, _, p_ack, p_fix, fix_days, p_verify = PROFILES[key]
        drift = 1 + (TRENDS.get(aid, 1.0) - 1) * (ago / days)  # older complaints took longer for improving departments
        t0 = now - timedelta(days=ago, hours=rnd.uniform(0, 10))
        b = bench.get(aid, 7)
        summary = rnd.choice(TEMPLATES[key]).format(s=sector, n=rnd.randint(1, 30))
        sev = "urgent" if any(w in summary for w in ("Sparking", "Smell of gas", "Missing manhole")) else rnd.choices(["low", "medium", "high"], [20, 55, 25])[0]
        iid = f"AWZ-LHR-S{k:04d}"
        backers = rnd.sample(citizens, min(len(citizens), max(1, int(rnd.paretovariate(1.5)))))
        ev = [("filed", t0)]
        tier, status, resolved_at, expected = 0, "open", None, t0 + timedelta(days=b)
        ack_at = t0 + timedelta(hours=rnd.uniform(2, 60) * drift) if rnd.random() < p_ack else None
        if ack_at and ack_at < now:
            ev.append(("acknowledged", ack_at)); status = "acknowledged"
            work = ack_at + timedelta(hours=rnd.uniform(6, 72))
            if work < now and rnd.random() < 0.8:
                ev.append(("in_progress", work)); status = "in_progress"
        fix_at = t0 + timedelta(days=rnd.lognormvariate(0, 0.55) * fix_days * drift)
        fixed = rnd.random() < p_fix and fix_at < now
        if not fixed:  # unresolved past target: residents escalate, roughly weekly
            t = expected
            while tier < 3 and t + timedelta(days=1) < now and rnd.random() < 0.65:
                tier += 1; t += timedelta(days=7)
                ev.append(("escalation_approved", t - timedelta(days=6)))
            if tier:
                status, expected = f"escalated_t{tier}", t
        else:
            ev.append(("authority_marked_fixed", fix_at))
            if rnd.random() < 0.08:  # bounce-back: a resident rejects the fix, the department returns
                ev.append(("fix_disputed", fix_at + timedelta(hours=rnd.uniform(4, 48))))
                fix_at = fix_at + timedelta(days=rnd.uniform(2, 9))
                if fix_at < now:
                    ev.append(("authority_marked_fixed", fix_at))
            if fix_at >= now:
                status = "in_progress"
            elif rnd.random() < p_verify:
                ev.append(("resolved", fix_at + timedelta(hours=rnd.uniform(2, 60)))); status = "resolved"
            else:
                ev.append(("closed_unverified", fix_at + timedelta(days=5))); status = "closed_unverified"
            if status in ("resolved", "closed_unverified"):
                resolved_at = min(ev[-1][1], now)
        issues.append((iid, "Lahore", sector, cat, sev, aid, summary, f"POINT({lng} {lat})", len(backers), rnd.randint(0, 4),
                       backers[0][0], status, tier, t0, expected, resolved_at))
        for j, (h, _) in enumerate(backers):
            reports.append((f"R-{iid}-{j + 1}", iid, h, "text", summary, f"POINT({lng} {lat})", min(now, t0 + timedelta(hours=j * rnd.uniform(1, 30)))))
        for typ, at in ev:
            if at <= now:
                events.append((iid, typ, "seed-hist" if typ in ("filed", "resolved", "escalation_approved", "fix_disputed") else aid,
                               '{"tier": %d}' % tier if typ == "escalation_approved" else "{}", at))
    db.executemany("""insert into issues (issue_id, city, sector, category, severity, authority_id, summary, geo_private, report_count,
                      confirmations, tracker_hash, status, escalation_tier, first_reported_at, expected_by, resolved_at)
                      values (%s,%s,%s,%s,%s,%s,%s,st_geogfromtext(%s),%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing""", issues)
    db.executemany("""insert into reports (report_id, issue_id, citizen_hash, input_type, raw_text, geo_private, created_at)
                      values (%s,%s,%s,%s,%s,st_geogfromtext(%s),%s) on conflict do nothing""", reports)
    db.executemany("insert into events (issue_id, type, actor, payload, created_at) values (%s,%s,%s,%s::jsonb,%s)", events)
    return len(issues)


def remove_history() -> int:
    n = db.simulated_count()
    db.q("delete from issues where tracker_hash like 'seed-hist%%'")
    db.q("delete from citizens where citizen_hash like 'seed-hist%%'")
    return n
