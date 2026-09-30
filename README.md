# Awaaz web app (Streamlit)

The live, working web channel of Awaaz. It uses the same Postgres database design and the same five agents as the WhatsApp app in the root of this repository. The agents run on **Claude, Google Gemini or Groq**, whichever key you provide; Gemini and Groq have free tiers.

- **Report a problem:** text, photo or voice note, located on a map, by current location or a named place. Claude classifies it, the Jurisdiction Router picks the department from the knowledge base (RAG) and cites its sources, the Matcher merges duplicates, and the Drafter writes the complaint.
- **Track an issue:** status, due date, check-ins, consent-gated escalation (Tier 1 → 2 → 3) and fix verification by residents.
- **Authority dashboard:** ranked, de-duplicated queue, map, department actions (password) and scorecards.
- **Neighborhood reports** (Pattern Analyst) and **Knowledge base** search.
- **About & status:** shows which services are live.

If the AI provider is unreachable or rate-limited, each agent falls back to deterministic rules and the result is labelled "fallback rules".

## Deploy (browser only, about 20 minutes)

1. **Database (Supabase, free):** create a project at supabase.com. Open **SQL Editor → New query** and run these four files from the repository, one at a time and in this order:
   `supabase/migrations/0001_init.sql`, `supabase/seed.sql`, `supabase/migrations/0002_rag.sql`, `supabase/seed_rag.sql`.
   Then click **Connect**, copy the **Session pooler** connection string, and put your database password into it.
2. **AI key (pick one):** a free **Gemini** key from aistudio.google.com (no card needed, recommended), a free **Groq** key from console.groq.com, or a paid **Claude** key from console.anthropic.com. Note: on Gemini's free tier, prompts may be used to improve Google's models, which is fine for a hackathon but worth revisiting before a real pilot with residents' data.
3. **Streamlit Cloud:** share.streamlit.io → Create app → repository `talhanust/awaaz`, branch `main`, main file `streamlit/streamlit_app.py`. Under **Advanced settings** choose Python 3.12 and paste your secrets (template: `secrets.toml.example`). Deploy.
4. Open the app. On first load it reads the knowledge base from `kb/` into the database automatically.

## Try it

- **Duplicate merge:** Report a problem → "Trying it out? Load an example" → *Pothole (Roman Urdu)* → submit. Twelve neighbors already reported it; add your voice and watch its queue position change.
- **RAG routing:** load *Street lights (Roman Urdu)*. By category it looks like LESCO; the router files it with MCL Street Lighting and shows the rule it used.
- **Escalation:** load *Sparking wires (English)* and add your voice to the existing, overdue issue. On **Track**, answer "No, still not fixed" to see a Tier 1 draft that waits for your approval.
- **Verification:** on the **Authority dashboard**, log in and press **Mark fixed**; then on **Track** (same mobile number) confirm it.

## Run locally

```
pip install -r streamlit/requirements.txt
cd streamlit && DATABASE_URL=postgresql://... GEMINI_API_KEY=... DASHBOARD_PASSWORD=... streamlit run streamlit_app.py
```
