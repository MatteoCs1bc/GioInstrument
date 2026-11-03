"""Modello di costo del sistema elettrico: scenario base vs scenario con più rinnovabili.

Logica (identica allo script originale, salvo le opzioni in `Parametri`):

1. Scenario base: tutto il fabbisogno MGP è comprato a PUN + dispacciamento; si aggiungono
   oneri fissi (€/MWh x volumi) e i CfD sulla produzione storica di FV ed eolico; poi IVA.
2. Scenario: FV, eolico e "autoconsumo" vengono moltiplicati per un fattore. Solo la parte
   AGGIUNTIVA (delta) riduce gli acquisti dalla rete, ora per ora.
   - se delta > fabbisogno: l'eccesso carica la batteria, il resto paga una penale;
   - se delta < fabbisogno: la batteria scarica, il resto si compra a PUN + dispacciamento.
3. Costi dello scenario: rete residua + oneri fissi + CfD + IVA, più costo di produzione della
   nuova energia (€/MWh x delta), costo BESS (€/MWh scaricato), integrazione (€/MW di picco),
   penale sovrapproduzione.
4. Risparmio = spesa base - spesa scenario.

Il PUN orario resta quello storico in tutti gli scenari (nessun effetto merit-order).
"""
from __future__ import annotations

import itertools
from typing import Callable

import numpy as np
import pandas as pd

from .parametri import Parametri

try:  # numba accelera la simulazione batteria di ~100x; se manca si usa Python puro
    from numba import njit
except ImportError:  # pragma: no cover
    def njit(*args, **kwargs):
        def deco(f):
            return f
        return deco if not (args and callable(args[0])) else args[0]


@njit(cache=True)
def simula_bess(eccesso, deficit, capacita, potenza, efficienza):
    """Batteria 'greedy': carica appena c'è eccesso, scarica appena c'è deficit.

    L'efficienza è applicata tutta in scarica (come nell'originale).
    Ritorna (energia caricata, energia scaricata, stato di carica) per ogni ora.
    """
    n = len(eccesso)
    caricata = np.zeros(n)
    scaricata = np.zeros(n)
    soc_ora = np.zeros(n)
    soc = 0.0
    for i in range(n):
        if eccesso[i] > 0:
            carica = min(eccesso[i], potenza, capacita - soc)
            soc += carica
            caricata[i] = carica
        elif deficit[i] > 0:
            disp = soc * efficienza
            scarica = min(deficit[i], potenza, disp)
            soc -= scarica / efficienza
            scaricata[i] = scarica
        soc_ora[i] = soc
    return caricata, scaricata, soc_ora


def _cfd(strike: float, pun: np.ndarray, gen: np.ndarray, bidirezionale: bool) -> np.ndarray:
    diff = strike - pun
    if not bidirezionale:
        diff = np.maximum(0.0, diff)
    return diff * gen


def scenario_base(v: dict, p: Parametri) -> dict:
    pun, vol = v["pun"], v["volumi"]
    energia = float((vol * (pun + p.costo_dispacciamento)).sum())
    oneri_fissi = float((vol * p.oneri_base_fissi).sum())
    cfd = float(_cfd(p.strike_eolico, pun, v["eolico"], p.cfd_bidirezionale).sum()
                + _cfd(p.strike_fv, pun, v["fv"], p.cfd_bidirezionale).sum())
    iva = (energia + oneri_fissi + cfd) * p.aliquota_iva
    return {
        "Spesa energia rete": energia,
        "Oneri fissi": oneri_fissi,
        "Oneri CfD": cfd,
        "IVA": iva,
        "Nuovi impianti": 0.0,
        "BESS": 0.0,
        "Integrazione": 0.0,
        "Penali sovrapproduzione": 0.0,
        "Spesa totale": energia + oneri_fissi + cfd + iva,
    }


def valuta_scenario(v: dict, p: Parametri, f_fv: float, f_eol: float, f_auto: float,
                    base: dict | None = None, orario: bool = False) -> dict:
    pun, vol = v["pun"], v["volumi"]
    fv_tot, eol_tot, auto_tot = v["fv"] * f_fv, v["eolico"] * f_eol, v["auto"] * f_auto
    d_fv, d_eol, d_auto = fv_tot - v["fv"], eol_tot - v["eolico"], auto_tot - v["auto"]
    delta = d_fv + d_eol + d_auto

    eccesso = np.maximum(0.0, delta - vol)
    deficit = np.maximum(0.0, vol - delta)
    car, scar, soc = simula_bess(eccesso, deficit, p.capacita_bess_mwh, p.potenza_bess_mw, p.efficienza_bess)
    eccesso_finale = eccesso - car
    residuo = deficit - scar

    energia = float((residuo * (pun + p.costo_dispacciamento)).sum())
    oneri_fissi = float((vol * p.oneri_base_fissi).sum())
    gen_cfd_eol = eol_tot if p.cfd_su_nuova_generazione else v["eolico"]
    gen_cfd_fv = fv_tot if p.cfd_su_nuova_generazione else v["fv"]
    cfd = float(_cfd(p.strike_eolico, pun, gen_cfd_eol, p.cfd_bidirezionale).sum()
                + _cfd(p.strike_fv, pun, gen_cfd_fv, p.cfd_bidirezionale).sum())
    iva = (energia + oneri_fissi + cfd) * p.aliquota_iva

    impianti = float((d_fv * p.costo_prod_fv).sum() + (d_eol * p.costo_prod_eolico).sum()
                     + (d_auto * p.costo_prod_auto).sum())
    integrazione = float((d_fv.max() + d_eol.max() + d_auto.max()) * p.costo_integrazione_mw)
    bess = float((scar * p.costo_lcoe_bess).sum())
    penali = float((eccesso_finale * p.costo_sovrapproduzione).sum())
    totale = energia + oneri_fissi + cfd + iva + impianti + integrazione + bess + penali

    if base is None:
        base = scenario_base(v, p)
    ris = {
        "f_fv": f_fv, "f_eol": f_eol, "f_auto": f_auto,
        "Spesa energia rete": energia,
        "Oneri fissi": oneri_fissi,
        "Oneri CfD": cfd,
        "IVA": iva,
        "Nuovi impianti": impianti,
        "BESS": bess,
        "Integrazione": integrazione,
        "Penali sovrapproduzione": penali,
        "Spesa totale": totale,
        "Risparmio": base["Spesa totale"] - totale,
        "Nuova energia TWh": float(delta.sum()) / 1e6,
        "Eccesso sprecato TWh": float(eccesso_finale.sum()) / 1e6,
        "Scaricato BESS TWh": float(scar.sum()) / 1e6,
        "Ore con eccesso": int((eccesso > 0).sum()),
    }
    if orario:
        ris["orario"] = pd.DataFrame({
            "Fabbisogno": vol, "Nuova FV": d_fv, "Nuovo eolico": d_eol, "Nuovo autoconsumo": d_auto,
            "Carica BESS": car, "Scarica BESS": scar, "SoC BESS": soc,
            "Eccesso sprecato": eccesso_finale, "Prelievo rete": residuo, "PUN": pun,
        })
    return ris


def griglia(minimo: float, massimo: float, passo: float) -> np.ndarray:
    """Come np.arange ma include il massimo se ci cade sopra (a meno di arrotondamenti)."""
    n = int(np.floor((massimo - minimo) / passo + 1e-9)) + 1
    return np.round(minimo + passo * np.arange(n), 6)


def ottimizza(v: dict, p: Parametri, fattori_fv, fattori_eol, fattori_auto,
              progresso: Callable[[float], None] | None = None) -> pd.DataFrame:
    """Valuta tutte le combinazioni e ritorna una tabella ordinata per risparmio decrescente."""
    base = scenario_base(v, p)
    comb = list(itertools.product(fattori_fv, fattori_eol, fattori_auto))
    righe = []
    for i, (a, b, c) in enumerate(comb):
        righe.append(valuta_scenario(v, p, float(a), float(b), float(c), base=base))
        if progresso and (i % 50 == 0 or i == len(comb) - 1):
            progresso((i + 1) / len(comb))
    return pd.DataFrame(righe).sort_values("Risparmio", ascending=False).reset_index(drop=True)
