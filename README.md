# ⚡ Simulatore rinnovabili e costo del sistema elettrico

Quanto costerebbe un anno di elettricità in Italia se avessimo **N volte più fotovoltaico, eolico e
autoconsumo** (più una batteria nazionale), usando prezzi e profili orari reali?

Il modello prende un anno di dati orari (nov 2025 – ott 2026) e confronta:

- **A, scenario base**: tutto il fabbisogno MGP comprato a *PUN + dispacciamento*, più oneri di rete, CfD e IVA;
- **B, scenario**: la produzione rinnovabile aggiuntiva copre parte del fabbisogno ora per ora, la batteria
  sposta l'eccesso, il resto si compra in rete; in più si pagano i nuovi impianti, l'accumulo e le penali per l'energia sprecata.

Risparmio = A − B. Un'ottimizzazione a griglia cerca la combinazione di moltiplicatori col risparmio massimo.

## Avvio rapido

```bash
git clone https://github.com/<utente>/simulatore-bolletta-rinnovabili.git
cd simulatore-bolletta-rinnovabili
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

streamlit run app.py                                   # app interattiva
python scripts/run_ottimizzazione.py                   # versione a riga di comando
python scripts/run_ottimizzazione.py --max 10 --cfd-bidirezionale --no-cfd-nuova-gen
pytest                                                 # test
```

## Pubblicare su Streamlit Community Cloud

1. Carica il repository su GitHub (anche privato).
2. Vai su [share.streamlit.io](https://share.streamlit.io) → **Create app** → scegli repo e branch, *Main file path* = `app.py`.
3. Deploy. Le dipendenze vengono lette da `requirements.txt`, i dati sono già in `data/`.

## Struttura

```
app.py                       # interfaccia Streamlit (scenario manuale, ottimizzazione, dati e ipotesi)
simulatore/
  parametri.py               # tutti i parametri in un dataclass (default = script originale)
  dati.py                    # lettura e pulizia dei file GME/Terna
  modello.py                 # scenario base, valutazione scenario, batteria, ottimizzazione
scripts/
  run_ottimizzazione.py      # CLI equivalente al vecchio script
  dimezzare_originale.py     # script originale, conservato per riferimento
data/                        # PUN e fabbisogno MGP (GME), generazione oraria per fonte (Terna)
tests/
```

## Dati

| File | Fonte | Contenuto |
|---|---|---|
| `MGP_Fabbisogno_Italia_*.xlsx` | GME | fabbisogno orario MGP (MWh), formato numerico italiano |
| `PUN_*.xlsx` | GME | Prezzo Unico Nazionale orario (€/MWh) |
| `Generazione_Totale_*.csv` | Terna | generazione oraria per fonte (MW medi) |

Per usare un altro periodo puoi sostituire i file in `data/` (stessi nomi di colonna) oppure caricarli dalla barra laterale dell'app.

**Pulizia applicata** (differenze rispetto allo script originale):
- i timestamp del mercato sono costruiti rispettando l'ora legale; prima venivano generati come sequenza
  continua e, dal 29 marzo in poi, prezzi e volumi risultavano sfasati di un'ora rispetto alla generazione;
- se Excel restituisce già colonne numeriche non vengono riconvertite (la vecchia conversione le avrebbe corrotte);
- 49 ore in cui Terna riporta zero su tutte le fonti (14–15 gennaio 2026 e le 02:00 del 29 marzo) vengono riempite con la stessa ora della settimana precedente;
- `freq='H'` → `'h'` (con pandas ≥ 3 il vecchio script si fermava con un errore).

A parità di dati il modello dà gli stessi numeri dell'originale al centesimo; con la pulizia il risparmio ottimo passa da 13,76 a 13,67 mld €.

## Ipotesi forti (leggere prima di citare i risultati)

- **PUN invariato**: le rinnovabili aggiuntive non abbassano il prezzo (niente effetto merit-order). Ogni MWh in più
  evita ~120 €/MWh e ne costa 60–80, quindi l'ottimo tende al bordo della griglia. I risparmi sono un **limite superiore**.
- **Nessun costo di adeguatezza/backup** né di nuove reti: gli oneri di rete restano un €/MWh fisso.
- **"Self-consumption" Terna** non è solo FV sui tetti: ha ~1,8 GW di carico notturno; moltiplicarlo moltiplica anche quello.
- **Costo di integrazione** 10 €/MW di picco: trascurabile (< 1 M€), probabilmente l'unità voluta era un'altra.
- **Batteria**: taglia fissa, strategia "carica appena c'è eccesso / scarica appena serve", costo solo per MWh scaricato.
- **CfD**: di default unidirezionale e applicato anche alla nuova generazione, già pagata a costo di produzione
  (doppio conteggio parziale). Le opzioni `cfd_bidirezionale` e `cfd_su_nuova_generazione` permettono di cambiarlo.
- **IVA** solo sulla spesa di rete, non sui nuovi impianti.
