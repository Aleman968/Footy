# Footy App

## Nuova funzione
- pulsante **Salva tutte su Sheets** nella pagina OVER
- pulsante **Salva tutte su Sheets** nella pagina MG

Ogni riga salvata contiene:
- Data
- Campionato
- Partita
- Giocata
- Quota
- xG totale
- % Over 2.5
- % MG 2-4
- % Over 1.5
- % Under 4.5

## Secrets Streamlit richiesti
```toml
FOOTYSTATS_API_KEY = "LA_TUA_CHIAVE"
GSHEETS_SPREADSHEET_ID = "ID_DEL_TUO_FOGLIO"

[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "..."
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
universe_domain = "googleapis.com"
```
