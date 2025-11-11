# Email Campaign Docker

Toolbox per spedire newsletter o campagne one-shot tramite Gmail API dentro un container isolato. Di seguito trovi la checklist completa per arrivare all’invio della prima campagna.

---

## Guida rapida (3 step)

1. **Configura gli accessi Gmail**
   - Crea un OAuth Client “Desktop” nel progetto Google Cloud con Gmail API abilitata.
   - Scarica `credentials.json` e salvalo in `creds/default/` (o in `creds/<nome_account>/` se vuoi account multipli).  
   - Al primo `docker compose run --rm emailer send …` partirà il flow OAuth in console: inserisci il codice e verrà generato automaticamente `token.json` nella stessa cartella.

2. **Prepara la campagna**
   - Duplica l’esempio `cp -R data/campaigns/example data/campaigns/<nome_campagna>`.
   - Aggiorna `campaign_config.yaml`: mittente (`from_email`/`send_as_email`), limiti (`daily_send_limit`, `delay_between_emails_seconds`, ecc.), resilienza (retry/backoff/cooldown) e tracking (pixel + unsubscribe).
   - Compila `recipients.csv` con i destinatari e gli eventuali campi personalizzati, modifica `template.html` e carica gli allegati opzionali sotto `data/attachments/...`.

3. **Avvia build, test e invio**
   - `docker compose build` per creare l’immagine, `docker compose run --rm test` per eseguire `pytest` dentro il container.
   - Lancia l’invio con `docker compose run --rm emailer send --campaign <nome_campagna>`.  
   - Monitora lo STDOUT (log JSON strutturati) o consulta `data/logs/<campagna>/` per stato, log degli invii e metriche aggregate.

---

## 1. Prerequisiti

1. **Docker + Docker Compose** installati e funzionanti.
2. **Progetto Google Cloud** con Gmail API abilitata.
   - Crea un OAuth Client **Desktop**.
   - Scarica `credentials.json`.
3. (Opzionale) **Google Sheets + Apps Script** se vuoi tracciare aperture/unsubscribe.
4. Python non è necessario sul host: tutto gira nel container.

---

## 2. Struttura principale

```
app/                # codice Python (manage.py + helper)
data/
  campaigns/        # una cartella per campagna (config, CSV, template)
  logs/             # viene popolata al primo invio
creds/
  default/          # metti qui credentials.json e i token generati
docker-compose.yml  # servizi emailer + test
```

`/data` e `/creds` vengono montati nel container, quindi le modifiche restano persistenti.

---

## 3. Preparazione credenziali Gmail

1. Crea (se serve) `creds/default/`.
2. Copia `credentials.json` dentro `creds/default/`.
3. Al primo avvio, il CLI avvierà il flow OAuth (modalità console) e salverà `token.json` nella stessa cartella.
4. Se usi account multipli, crea sottocartelle (`creds/acme/`, ecc.) e punta a quella giusta in `campaign_config.yaml` (`account_name`).

### 3.1 Come generare `credentials.json` e `token.json`

1. Vai su [console.cloud.google.com](https://console.cloud.google.com/) e seleziona/crea un progetto dedicato alle campagne email.
2. Nel menu “API & Services” abilita **Gmail API** (Enable APIs and Services → cerca “Gmail API” → Enable).
3. Sempre sotto “API & Services”, apri “Credentials” e clicca **Create Credentials → OAuth client ID**:
   - Tipo applicazione: **Desktop**.
   - Scarica il file `credentials.json` e salvalo in `creds/default/`.
4. (Facoltativo ma consigliato) imposta schermata di consenso OAuth con nome applicazione e email di supporto, e aggiungi gli account che useranno lo strumento.
5. Avvia il container per la prima volta, es. `docker compose run --rm emailer send --campaign example`: lo script stamperà un URL.
6. Apri l’URL nel browser, autentica l’account Gmail e copia il codice di verifica nella CLI.
7. Alla fine comparirà `token.json` nella stessa cartella delle credenziali: è il refresh token usato per gli invii futuri. Non committarlo e proteggilo come fosse una password.

---

## 3bis. Gestione segreta (opzionale ma consigliata)

Per evitare di versionare o lasciare in chiaro le credenziali sul filesystem puoi affidarti a un Secret Manager (Google Secret Manager, AWS Secrets Manager, HashiCorp Vault, ecc.). Un flusso tipico con Google Cloud:

1. Carica il file sul Secret Manager:
   ```bash
   gcloud secrets create emailer-credentials --data-file=creds/default/credentials.json
   gcloud secrets create emailer-token --data-file=creds/default/token.json  # dopo il primo login
   ```
2. Concedi al service account/utente che avvia i container il permesso `roles/secretmanager.secretAccessor`.
3. Prima di eseguire `docker compose run ...`, recupera i file e popolali nelle cartelle montate (puoi usare uno script wrapper):
   ```bash
   gcloud secrets versions access latest --secret=emailer-credentials > creds/default/credentials.json
   gcloud secrets versions access latest --secret=emailer-token > creds/default/token.json
   ```
4. Dopo l’esecuzione, puoi cancellare i file temporanei (`shred -u creds/default/*.json`) sapendo che la copia autoritativa resta nel Secret Manager.

Su altre piattaforme il meccanismo è analogo: estrai i segreti al volo prima del comando e non committarli mai. Assicurati che la directory `creds/` sia protetta da ACL/permessi restrittivi sull’host.

---

## 4. (Opzionale) Tracking aperture e unsubscribe

1. Crea un Google Sheet con i fogli:
   - `opens` con intestazione `ts,cid,to,ua,ip`
   - `unsubs` con `ts,email`
2. Apri Apps Script, incolla `apps_script_pixel.gs`, sostituisci `SHEET_ID` e deploya come Web App (accesso “Anyone”).
3. Nel file `campaign_config.yaml` imposta:
   - `tracking_base_url`: URL della Web App con `?mode=pixel`
   - `sheet_id`: ID del foglio
   - `unsubscribe_enabled` + `unsubscribe_base_url` se vuoi il link di disiscrizione (`?mode=unsubscribe`).

---

## 5. Crea la tua prima campagna

1. Copia l’esempio:
   ```bash
   cp -R data/campaigns/example data/campaigns/hello_world
   ```
2. Apri `data/campaigns/hello_world/campaign_config.yaml` e aggiorna:
   - `campaign_name`, `from_email`, `send_as_email` (se usi alias)
   - limiti (`daily_send_limit`, `delay_between_emails_seconds`, ecc.)
   - resilienza (`max_attempts_per_contact`, `max_retry_attempts`, `retry_backoff_initial_seconds`, `retry_backoff_multiplier`, `retry_backoff_max_seconds`)
   - throttling globale (`global_error_threshold_for_cooldown`, `global_error_cooldown_seconds`)
   - parametri tracking/unsubscribe se usati
3. Modifica `recipients.csv` (una riga per destinatario, puoi aggiungere colonne personalizzate usate dal template).
4. Personalizza `template.html` con Jinja2 (puoi usare `{{ first_name }}`, `{{ email }}`, ecc.).
5. Eventuali allegati per-riga vanno salvati sotto `data/attachments/...` e referenziati tramite il campo `attachment_path`.

---

## 6. Build e (opzionale) test

```bash
docker compose build
# opzionale ma consigliato
docker compose run --rm test
```

Il servizio `test` monta `app/`, `tests/`, `data/`, `creds/` e lancia `pytest` per assicurarsi che la toolchain funzioni anche fuori dall’ambiente host.

---

## 7. Invio della campagna

1. Elenca le campagne disponibili:
   ```bash
   docker compose run --rm emailer list
   ```
2. Avvia l’invio:
   ```bash
   docker compose run --rm emailer send --campaign hello_world
   ```
   - Il comando rispetta `daily_send_limit`, `delay_between_emails_seconds`, `batch_size` e `pause_between_batches_seconds`.
   - Ogni invio aggiorna:
     - `data/logs/<campaign>/sent_log.csv`
     - `data/logs/<campaign>/sent_threads.csv`
     - `data/logs/<campaign>/state.json` (stato persistente per riprendere dopo un crash).
   - Gli errori 429/5xx vengono ritentati automaticamente con exponential backoff e jitter; dopo `global_error_threshold_for_cooldown` errori consecutivi il processo attende `global_error_cooldown_seconds` prima di ripartire.
   - Se qualcosa va storto, i contatti rimasti in stato `pending`/`error` verranno ritentati al prossimo `send`, rispettando `max_attempts_per_contact`.
   - Lo STDOUT espone log JSON strutturati, utili per shipping verso Stackdriver/Datadog/etc. Esempio:
     ```json
     {"ts":"2024-05-01T10:11:12.123Z","level":"INFO","event":"send_success","data":{"campaign":"hello_world","email":"mario@example.com","message_id":"abc123"}}
     ```

---

## 8. Monitoraggio e follow-up

| Comando | Descrizione | Output |
|---------|-------------|--------|
| `docker compose run --rm emailer check-bounces --campaign hello_world` | Cerca i messaggi con etichetta bounce (configurata nel YAML) e salva gli indirizzi rimbalzati | `data/logs/.../bounces.csv` |
| `docker compose run --rm emailer check-replies --campaign hello_world` | Analizza i thread salvati per capire chi ha risposto | `replies.csv` |
| `docker compose run --rm emailer fetch-opens --campaign hello_world` | Scarica dal Google Sheet gli open registrati via Apps Script | `opens.csv` |
| `docker compose run --rm emailer stats --campaign hello_world --print` | Unisce `sent`, `bounces`, `replies`, `opens` in un unico CSV e mostra un’anteprima | `stats.csv` |

Tutti i log si trovano in `data/logs/<campaign>/`.

---

## 9. Ripartenza dopo crash o stop volontario

Grazie a `state.json` ogni destinatario ha lo stato (`pending`, `sending`, `sent`, `error`) con timestamp e tentativi. Se il container si ferma a metà:

1. Riavvia il comando `send`.
2. I contatti marcati `sent` vengono saltati.
3. Chi era `sending` viene riportato a `pending`.
4. Gli errori rimangono nel file con il messaggio per poterli ispezionare.

Puoi cancellare `state.json` solo se vuoi ripartire completamente da zero (ricordati di svuotare anche `sent_log.csv`).

---

## 10. Troubleshooting

- **OAuth non parte**: assicurati che `credentials.json` sia nel percorso giusto e che il terminale consenta input (il flow chiede il codice di verifica).
- **Permission denied sul volume**: controlla che `data/` e `creds/` abbiano permessi scrivibili dall’utente Docker.
- **Limiti Gmail**: anche se imposti `daily_send_limit`, resta soggetto alle quote Google (per account consumer max ~500/die, per Workspace 2.000).
- **Test locali**: se vuoi lanciare `pytest` fuori dal container, imposta `PYTHONPATH` sulla root del progetto e replica la struttura `data/`/`creds/`.

BONUS: il workflow GitHub Actions `.github/workflows/tests.yml` lancia automaticamente `pytest` su ogni push/PR usando Python 3.11, così scopri subito eventuali regressioni.

Buon invio! Se aggiungi nuove campagne ricordati di versionare solo i template/config, evitando di committare i log o i token OAuth.***
