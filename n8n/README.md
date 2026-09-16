# n8n setup

Import **workflows/23e-inbound-sms-intake.json** into n8n. The workflow contains
no credentials or customer message samples.

## Local Docker instance

The development instance is bound only to the local computer at
**http://localhost:5678**. Its data is stored in the named Docker volume
**gestao23e_n8n_data**, so workflows and credentials survive container restarts.
The image is pinned to n8n **2.18.5** by digest.

Start it from the repository root:

```powershell
docker compose -f n8n/docker-compose.yml up -d
```

Check it:

```powershell
docker compose -f n8n/docker-compose.yml ps
docker compose -f n8n/docker-compose.yml logs --tail 100 n8n
```

Stop it without deleting data:

```powershell
docker compose -f n8n/docker-compose.yml stop
```

The Flask backend runs on the Windows host. From an n8n container, its local
address is **http://host.docker.internal:5000**, not 127.0.0.1.

Twilio cannot call a localhost webhook. A temporary public HTTPS tunnel will be
added for the end-to-end trial; the production workflow must later move to an
always-on cloud host.

## Required configuration

1. In the backend, generate one long random value for **N8N_SHARED_SECRET**.
2. In n8n, create a **Header Auth** credential:
   - Name: **Authorization**
   - Value: **Bearer followed by the same N8N_SHARED_SECRET**
3. Assign that credential to:
   - Immediate Event
   - Process Immediate Event
   - Get Pending Events
   - Process Recovered Event
   - Qualify and Draft Reply
   - Send AI Reply
4. Create the n8n variable **BACKEND_BASE_URL** with the public HTTPS origin of
   the Flask backend, without a trailing slash.
5. Copy the production URL shown by **Immediate Event** into the backend
   **N8N_INBOUND_WEBHOOK_URL** variable.
6. Publish the workflow.

The direct webhook handles new events immediately. The schedule trigger checks
every minute for events left in **received** or **failed**, so a temporary n8n
failure does not lose an inbound message or delivery update. Both paths call the
same idempotent backend endpoint.

After processing, **Inbound Message?** sends only inbound messages to
qualification. Delivery callbacks end at **Delivery Status Stored**. The
qualification endpoint returns **completed** only when an automated reply is
allowed; skipped, opted-out, disabled, or human-controlled conversations end at
**No Automated Reply**.

**Send AI Reply** submits only the stored inbound message ID. The backend reads
the previously stored structured decision and sends the reply at most once, so
n8n never supplies or edits customer-facing text. Company settings, conversation
context, lead updates, human escalation, Twilio sender selection, and outbound
idempotency remain enforced by the backend.
