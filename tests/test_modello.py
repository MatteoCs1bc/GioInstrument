import numpy as np
import pytest

from simulatore import Parametri, carica_dati, scenario_base, simula_bess, valuta_scenario


@pytest.fixture(scope="module")
def v():
    return carica_dati().vettori


def test_dati_allineati():
    d = carica_dati()
    assert len(d.df) == 8759                       # 8760 ore meno l'ora inesistente del 29/03 alle 02:00
    assert not d.df["Data e Ora"].duplicated().any()
    assert (d.df[["Photovoltaic", "Wind", "Self-consumption"]].sum(axis=1) > 0).all()


def test_scenario_1x_uguale_al_base(v):
    p = Parametri()
    r = valuta_scenario(v, p, 1.0, 1.0, 1.0)
    assert r["Risparmio"] == pytest.approx(0.0, abs=1.0)
    assert r["Spesa totale"] == pytest.approx(scenario_base(v, p)["Spesa totale"])


def test_bess_conserva_energia():
    ecc = np.array([5.0, 5.0, 0.0, 0.0, 0.0])
    defi = np.array([0.0, 0.0, 3.0, 3.0, 3.0])
    car, scar, soc = simula_bess(ecc, defi, 8.0, 4.0, 0.5)
    assert car.sum() == pytest.approx(8.0)          # limitato dalla capacità
    assert scar.sum() == pytest.approx(4.0)         # 8 MWh × 50% di efficienza
    assert soc[-1] == pytest.approx(0.0)


def test_cfd_bidirezionale_riduce_oneri(v):
    uni = scenario_base(v, Parametri(cfd_bidirezionale=False))["Oneri CfD"]
    bi = scenario_base(v, Parametri(cfd_bidirezionale=True))["Oneri CfD"]
    assert bi < uni
