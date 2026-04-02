# Footy Bet App

## Avvio locale
```bash
py -m pip install -r requirements.txt
py -m streamlit run app.py
```

## Deploy su Streamlit Community Cloud
1. Carica questi file su GitHub
2. Su Streamlit Cloud scegli il repo
3. Come file principale usa `app.py`
4. Nei Secrets inserisci:

```toml
FOOTYSTATS_API_KEY = "LA_TUA_CHIAVE"
```
