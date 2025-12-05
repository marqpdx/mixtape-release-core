
# Create your views here.

* Agent part

a curator-centric, semi-agentic knowledge flow.

** Steps

* Curator browses suggested books → selects N to approve → submits
↓
* Backend receives approved list
↓
* Spawns background jobs (agents) to:
    1. Download each book to ./ai/ebooks/
    2. (Optionally) mark as retrieved in DB
↓
* Watchdog or manual trigger picks it up for ingestion
