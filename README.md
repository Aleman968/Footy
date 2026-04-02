# Footy Bet App

## Avvio locale
```bash
py -m pip install -r requirements.txt
py -m streamlit run app.py
```

## Deploy su Streamlit Community Cloud
1. Carica questi file su GitHub
2. Su Streamlit Cloud scegli il repository
3. Come file principale usa `app.py`
4. Nei Secrets inserisci:

```toml
FOOTYSTATS_API_KEY = "LA_TUA_CHIAVE"
```

## Filtri gol integrati
- **MULTIGOL 2-5** passa solo se:
  - Over 1.5 > 75
  - MG 2-4 > 60
  - Under 4.5 > 78
  - **media gol ponderata MG tra 2.20 e 3.60**

- **OVER 2.5** passa solo se:
  - Over 2.5 > 60
  - quota Over 2.5 tra 1.45 e 1.70
  - quota Gol < quota Over 2.5
  - Over 0.5 PT > 70
  - **media gol ponderata Over >= 2.40**
