"""Caricamento e pulizia dei dati orari (GME + Terna).

Fonti attese:
- Fabbisogno MGP (GME): colonne `Data` (gg/mm/aaaa), `Ora` (1..25), `Volumi MWh`
- PUN (GME):            colonne `Data`, `Ora`, `€/MWh`
- Generazione (Terna):  colonna `Date` (ora locale, griglia oraria continua) + una colonna per fonte
                        (`Photovoltaic`, `Wind`, `Self-consumption`, ...)

Rispetto allo script originale:
- i timestamp di mercato sono ricostruiti rispettando l'ora legale (Ora 1..23 a marzo, 1..25 a ottobre)
  invece di essere generati come sequenza continua, che spostava di un'ora tutti i dati da fine marzo;
- i numeri in formato italiano vengono convertiti solo se letti come testo (se Excel li fornisce
  già numerici, la vecchia conversione li avrebbe moltiplicati per 10^n);
- le ore in cui Terna riporta generazione nulla su tutte le fonti (buchi nei dati) vengono
  riempite con la stessa ora della settimana precedente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FILE_VOLUMI = DATA_DIR / "MGP_Fabbisogno_Italia_20251101_20261101.xlsx"
FILE_PUN = DATA_DIR / "PUN_20251101_20261101.xlsx"
FILE_GEN = DATA_DIR / "Generazione_Totale_20251101_20261101.csv"

COLONNE_GEN = ["Photovoltaic", "Wind", "Self-consumption"]


@dataclass
class Dati:
    df: pd.DataFrame                      # tabella oraria allineata
    note: list[str] = field(default_factory=list)

    @property
    def vettori(self) -> dict[str, np.ndarray]:
        return {
            "pun": self.df["PUN"].to_numpy(float),
            "volumi": self.df["Volumi MWh"].to_numpy(float),
            "fv": self.df["Photovoltaic"].to_numpy(float),
            "eolico": self.df["Wind"].to_numpy(float),
            "auto": self.df["Self-consumption"].to_numpy(float),
        }


def _numero_it(s: pd.Series) -> pd.Series:
    """Converte '24.220,5' -> 24220.5; lascia invariati i valori già numerici."""
    if pd.api.types.is_numeric_dtype(s):
        return s.astype(float)
    return (
        s.astype(str).str.strip()
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
        .astype(float)
    )


def _timestamp_mercato(df: pd.DataFrame) -> pd.Series:
    """Data + Ora (1..25, ora locale italiana) -> timestamp locale naive di inizio ora."""
    giorno = pd.to_datetime(df["Data"].astype(str), format="%d/%m/%Y")
    mezzanotte_utc = giorno.dt.tz_localize("Europe/Rome").dt.tz_convert("UTC")
    ts = mezzanotte_utc + pd.to_timedelta(df["Ora"].astype(int) - 1, unit="h")
    return ts.dt.tz_convert("Europe/Rome").dt.tz_localize(None)


def _leggi_tabella(src) -> pd.DataFrame:
    nome = getattr(src, "name", str(src)).lower()
    if nome.endswith((".xlsx", ".xls")):
        return pd.read_excel(src)
    return pd.read_csv(src)


def carica_dati(src_volumi=FILE_VOLUMI, src_pun=FILE_PUN, src_gen=FILE_GEN) -> Dati:
    """Accetta percorsi o file-like (es. upload di Streamlit)."""
    note: list[str] = []

    vol = _leggi_tabella(src_volumi)
    pun = _leggi_tabella(src_pun)
    vol["Volumi MWh"] = _numero_it(vol["Volumi MWh"])
    pun["PUN"] = _numero_it(pun["€/MWh"])

    mercato = pd.merge(vol[["Data", "Ora", "Volumi MWh"]], pun[["Data", "Ora", "PUN"]],
                       on=["Data", "Ora"], how="inner")
    mercato["Data e Ora"] = _timestamp_mercato(mercato)
    dup = mercato["Data e Ora"].duplicated(keep="first")
    if dup.any():
        note.append(f"Cambio ora (ottobre): scartata {dup.sum()} ora duplicata (02:00 ripetuta).")
    mercato = mercato[~dup]

    gen = _leggi_tabella(src_gen)
    gen["Data e Ora"] = pd.to_datetime(gen["Date"])
    mancanti = [c for c in COLONNE_GEN if c not in gen.columns]
    if mancanti:
        raise ValueError(f"Colonne mancanti nel file di generazione: {mancanti}")

    fonti = [c for c in gen.columns if c not in ("Date", "Data e Ora")]
    vuote = gen[fonti].sum(axis=1) == 0
    if vuote.any():
        gen = gen.set_index("Data e Ora").sort_index()
        settimana_prima = gen[fonti].shift(freq=pd.Timedelta(hours=168))
        idx = gen.index[vuote.to_numpy()]
        riempibili = idx.intersection(settimana_prima.index)
        gen.loc[riempibili, fonti] = settimana_prima.loc[riempibili, fonti].to_numpy()
        giorni = sorted({d.strftime("%d/%m/%Y") for d in idx})
        note.append(
            f"Generazione Terna nulla su tutte le fonti per {len(idx)} ore "
            f"({', '.join(giorni)}): sostituite con la stessa ora di 7 giorni prima."
        )
        gen = gen.reset_index()

    df = pd.merge(mercato, gen, on="Data e Ora", how="inner").sort_values("Data e Ora").reset_index(drop=True)
    note.insert(0, f"Ore allineate: {len(df)} (dal {df['Data e Ora'].min():%d/%m/%Y %H:%M} "
                   f"al {df['Data e Ora'].max():%d/%m/%Y %H:%M}).")
    return Dati(df=df, note=note)
