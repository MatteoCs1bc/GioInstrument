"""Versione a riga di comando (equivalente al vecchio dimezzare.py).

Uso:
    python scripts/run_ottimizzazione.py
    python scripts/run_ottimizzazione.py --max 8 --passo 0.5 --cfd-bidirezionale
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulatore import Parametri, carica_dati, griglia, ottimizza, scenario_base  # noqa: E402


def eur(x: float) -> str:
    return f"€ {x / 1e9:,.2f} mld"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min", type=float, default=1.0)
    ap.add_argument("--max", type=float, default=4.9)
    ap.add_argument("--passo", type=float, default=0.3)
    ap.add_argument("--cfd-bidirezionale", action="store_true")
    ap.add_argument("--no-cfd-nuova-gen", action="store_true",
                    help="non applicare il CfD alla generazione aggiuntiva (già pagata a costo di produzione)")
    ap.add_argument("--csv", help="salva tutte le combinazioni in questo CSV")
    a = ap.parse_args()

    p = Parametri(cfd_bidirezionale=a.cfd_bidirezionale, cfd_su_nuova_generazione=not a.no_cfd_nuova_gen)
    dati = carica_dati()
    for n in dati.note:
        print("·", n)
    v = dati.vettori
    f = griglia(a.min, a.max, a.passo)
    print(f"\nValuto {len(f) ** 3} combinazioni...")
    tab = ottimizza(v, p, f, f, f)
    base, best = scenario_base(v, p), tab.iloc[0]

    print(f"\nMiglior combinazione: FV {best.f_fv:.1f}x | Eolico {best.f_eol:.1f}x | Autoconsumo {best.f_auto:.1f}x")
    bordo = [n for n, x in (("FV", best.f_fv), ("Eolico", best.f_eol), ("Autoconsumo", best.f_auto)) if x >= f.max()]
    if bordo:
        print(f"ATTENZIONE: {', '.join(bordo)} al massimo della griglia -> l'ottimo vero è oltre, allarga --max")
    print("-" * 60)
    voci = ["Spesa energia rete", "Oneri fissi", "Oneri CfD", "IVA", "Nuovi impianti", "BESS",
            "Integrazione", "Penali sovrapproduzione", "Spesa totale"]
    print(f"{'':28s}{'Base (A)':>16s}{'Scenario (B)':>16s}")
    for k in voci:
        print(f"{k:28s}{eur(base[k]):>16s}{eur(best[k]):>16s}")
    print("-" * 60)
    print(f"Risparmio netto (A - B): {eur(best.Risparmio)}  ({best.Risparmio / base['Spesa totale']:.1%})")
    if a.csv:
        tab.to_csv(a.csv, index=False)
        print(f"Tabella salvata in {a.csv}")


if __name__ == "__main__":
    main()
