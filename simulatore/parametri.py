"""Parametri di mercato, impianti e accumulo.

I valori di default sono quelli dello script originale `dimezzare.py`.
Unità: €/MWh salvo diversa indicazione.
"""
from dataclasses import dataclass, asdict, fields


@dataclass
class Parametri:
    # --- Mercato / bolletta ---
    costo_dispacciamento: float = 10.0      # €/MWh sommato al PUN
    oneri_base_fissi: float = 35.0          # €/MWh, oneri strutturali (reti, ecc.) inalterabili
    aliquota_iva: float = 0.10

    # --- Contratti per Differenza (CfD) ---
    strike_eolico: float = 80.0
    strike_fv: float = 60.0
    cfd_bidirezionale: bool = False         # False = paga solo se PUN < strike (come l'originale)
    cfd_su_nuova_generazione: bool = True   # True = CfD anche sulla generazione aggiuntiva (come l'originale)

    # --- Costi di produzione della generazione AGGIUNTIVA ---
    costo_prod_fv: float = 60.0
    costo_prod_eolico: float = 80.0
    costo_prod_auto: float = 120.0
    costo_sovrapproduzione: float = 40.0    # €/MWh di energia in eccesso non assorbita
    costo_integrazione_mw: float = 10.0     # € per MW di picco aggiuntivo (una tantum nell'anno)

    # --- Accumulo (BESS) ---
    capacita_bess_mwh: float = 50_000.0
    potenza_bess_mw: float = 10_000.0
    efficienza_bess: float = 0.85
    costo_lcoe_bess: float = 120.0          # €/MWh scaricato

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Parametri":
        nomi = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in nomi})
