# Komplett användarguide — Auto-Healing AI DevOps Platform

> **För dig som aldrig har programmerat.** Den här guiden tar dig från noll till ett fungerande system, steg för steg. Följ varje steg i ordning.

---

## Vad gör det här systemet?

Systemet övervakar automatiskt dina kodbyggen (builds) och fixar fel utan att du behöver göra något manuellt.

**Så här fungerar det:**
```
Ditt projekt bygger fel
        ↓
Systemet fångar upp felet automatiskt
        ↓
AI analyserar vad som gick fel
        ↓
AI genererar en kodrättning
        ↓
Du får ett meddelande i Slack:
  🟢 GRÖN  → Fixad automatiskt, mergad
  🟡 GUL   → Behöver din granskning
  🔴 RÖD   → Blockerad, du måste agera
```

---

## Vad behöver du?

Innan du börjar, se till att du har:

| Krav | Var får du det? | Kostnad |
|------|-----------------|---------|
| En dator med Windows 10/11, Mac eller Linux | — | Gratis |
| GitHub-konto | [github.com](https://github.com) | Gratis |
| NVIDIA NIM API-nyckel | [build.nvidia.com](https://build.nvidia.com) | Gratis nivå finns |
| Slack-workspace | [slack.com](https://slack.com) | Gratis |
| Docker Desktop | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) | Gratis |

---

## DEL 1 — Installera verktyg på din dator

### Steg 1 — Installera Docker Desktop

Docker är programmet som kör systemet. Utan Docker fungerar ingenting.

1. Gå till [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
2. Klicka på **"Download Docker Desktop"**
3. Välj rätt version för din dator (Windows / Mac / Linux)
4. Öppna filen du laddade ner och följ installationen
5. Starta Docker Desktop
6. Vänta tills du ser en grön ikon nere till vänster — det betyder att Docker är igång

> ⚠️ **Viktigt:** Docker måste vara igång varje gång du använder systemet.

---

### Steg 2 — Ladda ner projektet från GitHub

1. Gå till [github.com/Mouaz7/auto-healing-devops-platform](https://github.com/Mouaz7/auto-healing-devops-platform)
2. Klicka på den gröna knappen **"Code"**
3. Klicka på **"Download ZIP"**
4. Packa upp ZIP-filen till en mapp du kommer ihåg, t.ex. `C:\projekt\` eller `~/projekt/`

**Eller om du har Git installerat**, öppna Terminal (Mac/Linux) eller Command Prompt (Windows) och skriv:
```bash
git clone https://github.com/Mouaz7/auto-healing-devops-platform.git
cd auto-healing-devops-platform
```

---

## DEL 2 — Skaffa API-nycklar

### Steg 3 — NVIDIA NIM API-nyckel

NVIDIA NIM är AI-motorn som analyserar fel och skriver kod.

1. Gå till [build.nvidia.com](https://build.nvidia.com)
2. Klicka på **"Sign In"** → **"Create Account"**
3. Fyll i din e-post och skapa ett konto
4. När du är inloggad, klicka på ditt namn uppe till höger
5. Välj **"API Keys"**
6. Klicka på **"Generate Key"**
7. Kopiera nyckeln (den börjar med `nvapi-...`) — **spara den, du ser den bara en gång!**

---

### Steg 4 — GitHub Personal Access Token

GitHub-token låter systemet skapa pull requests automatiskt.

1. Logga in på [github.com](https://github.com)
2. Klicka på din profilbild uppe till höger → **"Settings"**
3. Scrolla ner till vänstermenyn och klicka på **"Developer settings"**
4. Klicka på **"Personal access tokens"** → **"Tokens (classic)"**
5. Klicka på **"Generate new token (classic)"**
6. Ge token ett namn, t.ex. `auto-healing-platform`
7. Sätt utgångsdatum till **90 days**
8. Kryssa i dessa rättigheter:
   - ✅ `repo` (alla underalternativ)
   - ✅ `workflow`
9. Klicka på **"Generate token"**
10. Kopiera token (börjar med `ghp_...`) — **spara den nu!**

---

## DEL 3 — Sätt upp Slack

### Steg 5 — Skapa en Slack Webhook

Slack-webhook är adressen systemet skickar meddelanden till.

1. Gå till [api.slack.com/apps](https://api.slack.com/apps)
2. Klicka på **"Create New App"** → **"From scratch"**
3. Ge appen ett namn, t.ex. `AI DevOps Bot`
4. Välj ditt Slack-workspace
5. Klicka på **"Create App"**
6. I vänstermenyn, klicka på **"Incoming Webhooks"**
7. Slå på **"Activate Incoming Webhooks"** (klicka på knappen så den blir grön)
8. Klicka på **"Add New Webhook to Workspace"**
9. Välj vilken Slack-kanal systemet ska skicka till (t.ex. `#devops-alerts`)
10. Klicka på **"Allow"**
11. Kopiera **Webhook URL** (ser ut som `https://hooks.slack.com/services/T.../B.../...`)

**Testmeddelande** — verifiera att det fungerar (ersätt URL:en):
```bash
curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"✅ Test från AI DevOps Platform!"}' \
  https://hooks.slack.com/services/DIN-URL-HÄR
```
Om du ser `OK` i terminalen och ett meddelande i Slack — det fungerar!

---

## DEL 4 — Konfigurera systemet

### Steg 6 — Skapa din .env-fil

`.env`-filen är där du lagrar alla dina API-nycklar och inställningar.

1. Öppna projektmappen
2. Hitta filen `.env.example`
3. Kopiera den och döp kopian till `.env` (ta bort `.example`)

**På Windows:** Högerklicka → Kopiera → Klistra in → Döp om till `.env`

**På Mac/Linux i Terminal:**
```bash
cp .env.example .env
```

4. Öppna `.env` med Anteckningar (Windows) eller TextEdit (Mac)

Nu ska du fylla i dina nycklar. Filen ser ut så här — fyll i det som saknas:

```
# NVIDIA NIM — din AI-motor
NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1

# Agent 1: Pipeline Monitor
PIPELINE_MONITOR_PRIMARY_MODEL=meta/llama-3.2-1b-instruct
PIPELINE_MONITOR_PRIMARY_API_KEY=nvapi-DIN-NYCKEL-HÄR

# Agent 5: Code Repairer (viktigast — använd en stark modell)
CODE_REPAIRER_PRIMARY_MODEL=qwen/qwen2.5-coder-32b-instruct
CODE_REPAIRER_PRIMARY_API_KEY=nvapi-DIN-NYCKEL-HÄR

# GitHub
GITHUB_TOKEN=ghp_DIN-TOKEN-HÄR

# Slack
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/DIN-URL-HÄR
```

> ✅ **Tips:** Du kan använda samma NVIDIA API-nyckel för alla agenter om du bara har en.

---

## DEL 5 — Koppla till Jira eller Trello *(valfritt)*

### Alternativ A — Jira

Jira används för att spåra tickets och issues.

1. Logga in på ditt Jira-konto
2. Gå till **Settings** → **Apps** → **Webhooks**
3. Klicka på **"Create a Webhook"**
4. Sätt URL till: `http://DIN-SERVER-IP:8082/webhook/jenkins`
5. Under **"Events"**, välj **"Issue: Created, Updated"**
6. Spara

Nu skickar Jira automatiskt nya issues till systemet som analyserar dem.

### Alternativ B — Trello

1. Gå till [trello.com/power-ups/admin](https://trello.com/power-ups/admin)
2. Skapa ett nytt Power-Up
3. Under **"Capabilities"**, välj **"Webhooks"**
4. Sätt callback URL till: `http://DIN-SERVER-IP:8082/webhook/jenkins`

---

## DEL 6 — Starta systemet

### Steg 7 — Starta alla tjänster

Öppna Terminal (Mac/Linux) eller Command Prompt (Windows):

```bash
# Gå till projektmappen
cd auto-healing-devops-platform

# Starta alla 7 tjänster
docker-compose up --build
```

Första gången tar det **5–15 minuter** — Docker laddar ner allt som behövs.

Du vet att det fungerar när du ser något liknande:
```
log-cleaner-mcp    | service_started service=log-cleaner port=8081
jenkins-mcp        | service_started service=jenkins-mcp port=8082
gerrit-mcp         | service_started service=gerrit-mcp port=8083
knowledge-graph-mcp| service_started service=knowledge-graph port=8084
orchestrator-mcp   | service_started service=orchestrator port=8085
llm-mcp            | service_started service=llm-mcp port=8086
notification-mcp   | service_started service=notification port=8087
```

### Steg 8 — Kontrollera att allt är igång

Öppna en **ny** Terminal och kör:

```bash
python scripts/demo.py
```

Du ska se:
```
=== HEALTH CHECK ===
  Agent 3 - Log Analyst:      ✅ OK
  Agent 1 - Pipeline Monitor: ✅ OK
  Gerrit MCP:                  ✅ OK
  Agent 4 - Error Analyst:    ✅ OK
  Orchestrator:                ✅ OK
  Agent 5 - Code Repairer:    ✅ OK
  Agent 6 - Review & Notify:  ✅ OK
```

Om alla visar ✅ — systemet är igång och redo!

---

## DEL 7 — Använda systemet

### Steg 9 — Skicka ett bygge-fel till systemet

När ett bygge misslyckas i Jenkins eller GitHub Actions skickas det automatiskt om du har konfigurerat webhook (se Del 5).

**Testa manuellt** — öppna Terminal och kör:

```bash
curl -X POST http://localhost:8082/webhook/jenkins \
  -H "Content-Type: application/json" \
  -d '{
    "build_id": "test-001",
    "repo": "ditt-användarnamn/ditt-repo",
    "branch": "main",
    "raw_log": "ImportError: cannot import name Foo from bar"
  }'
```

### Steg 10 — Följ vad som händer

I den terminal där du startade systemet ser du loggar i realtid:

```
orchestrator | pipeline_started build_id=test-001
log-cleaner  | logs_cleaned lines=1543→47
knowledge-gr | error_detected type=IMPORT_ERROR blast=LOW
llm-mcp      | fix_generated confidence=0.91
notification | traffic_light=GREEN auto_merge=true
```

### Steg 11 — Se resultatet i Slack

Inom 30–60 sekunder får du ett meddelande i din Slack-kanal:

**🟢 Grön (AUTO-MERGE):**
> Build `test-001` — AUTO-FIXAD ✅
> Confidence: 91% | Blast radius: LOW
> Fix mergad automatiskt till `main`

**🟡 Gul (GRANSKNING KRÄVS):**
> Build `test-001` — GRANSKNING KRÄVS 👀
> Confidence: 72% | Öppna PR #42 på GitHub

**🔴 Röd (BLOCKERAD):**
> Build `test-001` — BLOCKERAD 🚫
> Manuell åtgärd krävs

---

## DEL 8 — Daglig användning

### Stoppa systemet

```bash
# Tryck Ctrl+C i terminalen där systemet kör
# Eller kör detta i en ny terminal:
docker-compose down
```

### Starta systemet igen

```bash
docker-compose up
```

(Ingen `--build` behövs efter första gången — går mycket snabbare)

### Se loggarna för en specifik tjänst

```bash
docker-compose logs orchestrator-mcp
docker-compose logs llm-mcp
docker-compose logs notification-mcp
```

### Se Prometheus-metrics (avancerat)

Öppna webbläsaren och gå till:
```
http://localhost:8085/metrics
```

Här ser du statistik som antal behandlade byggen, tokenanvändning per agent, m.m.

---

## DEL 9 — Felsökning

### Problem: "Docker is not running"
**Lösning:** Starta Docker Desktop och vänta tills ikonen blir grön.

### Problem: Tjänsterna startar inte
```bash
# Kontrollera om portarna är lediga
docker-compose down
docker-compose up --build
```

### Problem: Slack-meddelanden kommer inte
1. Kontrollera att `SLACK_WEBHOOK_URL` i `.env` är korrekt
2. Testa webhook manuellt (se Steg 5)
3. Kontrollera att Slack-appen är installerad i rätt workspace

### Problem: "API key invalid"
1. Öppna `.env`
2. Kontrollera att nyckeln inte har extra mellanslag
3. Generera en ny nyckel på [build.nvidia.com](https://build.nvidia.com)

### Problem: Bygget blir alltid RÖTT
Det kan bero på:
- Koden som ska fixas är för komplex (>50 rader ändringar)
- Blast radius är HIGH (påverkar för många filer)
- Token-budget slut för timmen — vänta en timme

---

## Snabbreferens

| Kommando | Vad det gör |
|----------|-------------|
| `docker-compose up --build` | Starta systemet (första gången) |
| `docker-compose up` | Starta systemet (vanligt) |
| `docker-compose down` | Stoppa systemet |
| `python scripts/demo.py` | Testa att allt fungerar |
| `docker-compose logs` | Se alla loggar |

| Port | Tjänst |
|------|--------|
| 8081 | Log Analyst (Agent 3) |
| 8082 | Pipeline Monitor (Agent 1) |
| 8083 | Gerrit / Code Fetcher |
| 8084 | Error Analyst (Agent 4) |
| 8085 | Orchestrator (central) |
| 8086 | Code Repairer (Agent 5) |
| 8087 | Review & Notify (Agent 6) |

---

## Kontakt och support

**Skapare:**
- Ahmad Darwich — ahda23@student.bth.se
- Mouaz Naji — moap23@student.bth.se

**Handledare:**
- Ahmad Nauman Ghazi — nauman.ghazi@bth.se

**Källkod:** [github.com/Mouaz7/auto-healing-devops-platform](https://github.com/Mouaz7/auto-healing-devops-platform)
