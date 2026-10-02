<img src="brand/awaaz-logo-color-transparent.png" alt="Awaaz" width="320">

# Awaaz — civic accountability layer (production starter)

*Your complaint doesn't end when you file it. It ends when it's fixed.*

**Live demo:** https://YOUR-USERNAME.github.io/awaaz/ (runs in the browser, no sign-up; open it on a phone to try "Current location")

![CI](https://github.com/YOUR-USERNAME/awaaz/actions/workflows/ci.yml/badge.svg)

This is the real, deployable version of the Awaaz MVP: citizens report problems on **WhatsApp** (voice note, photo or text plus a location), five Claude-powered agents classify, de-duplicate, file, track and escalate them, and authorities work from a ranked, de-duplicated **dashboard**.

```
WhatsApp ──► /api/whatsapp (Twilio webhook, answers in <1 s, works in the background)
               │
               ▼
        lib/flow.ts  ── conversation state per citizen (sessions table)
               │
   ┌───────────┼──────────────────────────────┐
   ▼           ▼                  ▼                            ▼
Agent 1     Agent 1b (RAG)     Agent 2                      Agent 3
Classifier  Jurisdiction       Matcher: PostGIS radius +    Drafter & Filer (Sonnet)
(Haiku)     Router: hybrid KB  semantic duplicates (RAG) +  + department guidance (RAG)
            search, cites      Claude same-object check     → email / assisted filing
            sources
                                                    │
Vercel Cron ─► /api/cron/tick ─► lib/lifecycle.ts ◄─┘   Agent 4: check-ins, reminders,
                                     │                  consent-gated Tier 1-3, verification
                                     ▼
            Supabase (Postgres + PostGIS): issues, reports, events, views
                                     │
        /dashboard (queue, map, scorecards) · /reports (Agent 5) · /i/[id] (public page)
```

The single-page demo for judges is `docs/index.html` (published with GitHub Pages; the same file is in `demo/`). It runs in scripted mode: the agents follow the same rules offline, so the demo never depends on Wi-Fi or API keys. The "Live AI" switch only works when the page is opened inside claude.ai.

## RAG: where retrieval is used

| Where | What is retrieved | Why |
|---|---|---|
| **Jurisdiction Router** (`lib/agents/router.ts`) | Knowledge-base passages about which department handles what (street lights vs. LESCO, cantonments, housing societies, drains vs. garbage) | Routing by category alone is often wrong. The router picks the department from retrieved passages, cites them, and can ask one question when the area type decides it. It can't override the default without a cited passage. |
| **Matcher** (`lib/agents/matcher.ts`) | Open Issues within 300 m with similar *meaning*, in any category (`semantic_candidates`) | Catches duplicates filed under a different category or described differently, in any language. |
| **Drafter** | Department guidance (e.g. LESCO asks for the consumer reference number) | Drafts include the fields each department actually asks for. |
| **Escalator** | Escalation channels (councilors, Pakistan Citizen Portal, right to information) | Gives the resident a grounded next step instead of an invented one. |

Retrieval is **hybrid**: vector similarity (Voyage `voyage-4` embeddings, 1024 dimensions, multilingual) and Postgres full-text search, fused with reciprocal rank fusion inside `match_kb()`. Without `VOYAGE_API_KEY` everything still works with keyword search, and semantic duplicate matching is skipped. The routing decision and its sources are stored in `issues.routing_basis` and shown on the public Issue page ("Why this department").

The knowledge base lives in `kb/<city>/*.md`: front matter (title, city, departments, source, verified) and `## ` sections, which become chunks. **Every passage in `kb/lahore` is a demo document written for this prototype and marked `verified: false`.** Replace them with passages checked against official sources, set `verified: true`, and re-run the ingestion. Unverified passages are labeled as such to the model and to residents.

## What each piece does

| Path | Role |
|---|---|
| `lib/agents/classifier.ts` | Agent 1. Language detection (Urdu, Roman Urdu, Punjabi, English), category, severity, authority. Asks a clarifying question when confidence < 0.6. |
| `lib/agents/matcher.ts` | Agent 2. `match_candidates()` finds open Issues within 50–250 m (by category); Claude decides whether it's the same physical problem; the citizen confirms before any merge. |
| `lib/agents/drafter.ts` | Agent 3. Writes the complaint in each department's format. |
| `lib/agents/escalator.ts` | Agent 4 text. Tier 1 re-complaint, Tier 2 CC to the councilor/UC chairman, Tier 3 fact-only public post. |
| `lib/agents/analyst.ts` | Agent 5. Neighborhood Report (English + Urdu) from the `clusters_30d` view. |
| `lib/lifecycle.ts` | Deterministic state machine: check-in at the due date, one reminder after 3 days, never escalates without a "No" and explicit consent, fixes confirmed by another resident, unverified closures after 5 days. |
| `lib/flow.ts` | WhatsApp conversation routing: location handling, voice/photo normalization, replies (1/2, haan/nahi, ہاں/نہیں). |
| `lib/outbound.ts` | Filing. Email via Resend where a department takes email; otherwise **assisted filing**: the citizen receives the ready-to-submit text. Tier 3 is always handed to the citizen; Awaaz never posts. |
| `supabase/migrations/0001_init.sql` | Schema, PostGIS indexes, `create_issue` / `add_voice` / `match_candidates` RPCs, queue/scorecard/cluster views, RLS. |
| `supabase/seed.sql` | Lahore departments and demo Issues in Johar Town. |

## Publish on GitHub

1. Create an empty repository on github.com (no README), then from this folder:
   ```
   git init
   git add .
   git commit -m "Awaaz v3"
   git branch -M main
   git remote add origin https://github.com/YOUR-USERNAME/awaaz.git
   git push -u origin main
   ```
   `.gitignore` keeps `.env` and `.env.local` out of the repo. Never commit API keys.
2. **Demo:** Settings → Pages → Deploy from a branch → `main`, folder `/docs`. It appears at `https://YOUR-USERNAME.github.io/awaaz/` within a minute or two. Replace `YOUR-USERNAME` in this README.
3. **CI:** `.github/workflows/ci.yml` type-checks and builds on every push; the badge above turns green once it passes.
4. **App:** import the repo into Vercel and follow the setup below. Every push to `main` redeploys.

## Set up (about 30 minutes)

1. **Supabase.** Create a project. In the SQL editor run `supabase/migrations/0001_init.sql`, then `supabase/seed.sql`. Copy the project URL and **service role** key.
2. **Claude.** Create an API key in the Anthropic Console.
3. **Twilio WhatsApp.** For the hackathon use the WhatsApp Sandbox. Set its "When a message comes in" webhook to `https://<your-app>/api/whatsapp` (POST).
4. **Voice notes (optional).** Add an OpenAI key for Whisper speech-to-text. Without it, Awaaz asks voice-note senders to type one line.
5. **RAG.** Run `supabase/migrations/0002_rag.sql` and `supabase/seed_rag.sql`. Add a Voyage AI key (optional but recommended), then load the knowledge base with `npm run kb:ingest` (re-run whenever you edit `kb/`).
6. **Environment.** Copy `.env.example` to `.env.local` and fill it in. `TWILIO_WEBHOOK_URL` must match the webhook URL exactly or signature checks fail.
7. **Run.** `npm install && npm run dev`. To receive WhatsApp messages locally, expose port 3000 with a tunnel (for example `ngrok http 3000`) and point the sandbox webhook and `TWILIO_WEBHOOK_URL` at it.
8. **Deploy.** Push to GitHub, import into Vercel, add the same env vars. `vercel.json` schedules `/api/cron/tick` daily at 04:00 UTC (9 AM Pakistan time). Set `CRON_SECRET`; Vercel sends it automatically.

The dashboard (`/dashboard`, `/reports`) is behind basic auth using `DASHBOARD_USER` / `DASHBOARD_PASSWORD`.

## Try it

1. In WhatsApp, share a location near J Block market in Johar Town (📎 → Location), then send: *"J Block market ke saamne bohat bara gaddha hai"*.
2. Awaaz replies that 12 neighbors already reported it. Reply **1**. The Issue becomes 13 residents and moves to the top of `/dashboard`.
3. To test escalation without waiting, set the Issue's `expected_by` to the past in Supabase and call the cron route:
   `curl -H "Authorization: Bearer $CRON_SECRET" https://<your-app>/api/cron/tick`
   Reply **2** to the check-in, then **1** to approve Tier 1.
4. On `/dashboard`, press **Mark fixed**: the resident is asked to confirm before the Issue closes.
5. On `/reports`, press **Write report** on the J Block roads cluster.
6. RAG routing: share a location in Johar Town and send *"street lights 2 hafte se band hain"*. Category alone says LESCO; the router files it with MCL Street Lighting and the reply explains why. The Issue page shows the cited passage.

## Verified vs. not yet verified

Verified while building: TypeScript strict type-check and `next build` pass; both migrations, seeds, RPCs and views were run on Postgres 16 + PostGIS 3.4 + pgvector (duplicate matching at 4 m, `add_voice` counting 12 → 13 and rejecting a second voice from the same citizen, queue ranking, clusters and scorecards). The knowledge base was ingested with the real parser: keyword retrieval returned the right passage first for street lights, a cantonment pothole and garbage in a drain; vector search returned the exact chunk first; hybrid fusion combined both; and `semantic_candidates` found a same-meaning duplicate 4 m away and ignored a far-away one.

Not yet run against live services: Twilio, Claude, Voyage, Whisper, Resend and Nominatim calls were written against their documented APIs but not exercised here. Do one end-to-end run on the sandbox before demo day.

## Known limits (be upfront with judges)

- **WhatsApp 24-hour rule.** Free-form messages only reach a citizen within 24 h of their last message. Check-ins and reminders arrive days later, so production needs **approved message templates** (`TWILIO_TEMPLATE_CHECKIN_SID`, `TWILIO_TEMPLATE_REMINDER_SID`). The sandbox is fine for demos where you've messaged recently.
- **Filing.** Most departments have no public API. Email filing works via Resend; everything else is assisted filing. Add real portal integrations in `lib/outbound.ts` as they become available.
- **One conversation at a time.** A citizen's session tracks one pending question. If two Issues need a check-in the same day, the second waits until the next day's tick.
- **Department data.** Every channel, email, helpline and councilor contact in `seed.sql` and `seed_rag.sql`, and every knowledge-base passage, is a placeholder to verify before a pilot.
- **Similarity threshold.** `semantic_candidates` uses a 0.75 similarity cutoff as a starting point. Tune it on real reports; too low merges different problems (the citizen still confirms every merge).
- **Free map and geocoding services.** OpenStreetMap tiles and Nominatim have fair-use limits (Nominatim: 1 request/second). Move to a paid or self-hosted provider before a public launch.
- **Phone numbers.** Stored so Awaaz can message citizens back; only the service role can read them. Consider column encryption (pgsodium) for production.
