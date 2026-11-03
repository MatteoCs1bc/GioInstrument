import pandas as pd
import numpy as np
import itertools
import warnings
warnings.filterwarnings('ignore')

# ==========================================
# 1. PARAMETRI DI MERCATO E IMPIANTI
# ==========================================
COSTO_DISPACCIAMENTO = 10.0
ONERI_BASE_FISSI = 35.0  # Oneri strutturali inalterabili (reti, ecc.)
ALIQUOTA_IVA = 0.10

# Parametri CfD (Contratti per Differenza) - "Realtà Ziopeppino"
STRIKE_EOLICO = 80.0
STRIKE_FV = 60.0

COSTO_SOVRAPPRODUZIONE = 40.0
COSTO_PROD_FV = 60.0
COSTO_PROD_EOLICO = 80.0
COSTO_PROD_AUTO = 120.0
COSTO_INTEGRAZIONE_MW = 10.0 

# Parametri Accumulo (BESS)
CAPACITA_BESS_MWH = 50000.0   
POTENZA_BESS_MW = 10000.0     
EFFICIENZA_BESS = 0.85
COSTO_LCOE_BESS = 120.0       

# ==========================================
# 2. PREPARAZIONE DATI
# ==========================================
df_volumi = pd.read_excel('20251101_20261101_MGP_Fabbisogno_Totale Italia.xlsx')
df_prezzi = pd.read_excel('20251101_20261101_PUN.xlsx')
df_gen = pd.read_csv('Generazione_Totale_20251101_20261101.csv')

df_volumi['Volumi MWh'] = df_volumi['Volumi MWh'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False).astype(float)
df_prezzi['€/MWh'] = df_prezzi['€/MWh'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False).astype(float)

df_mercato = pd.merge(df_volumi, df_prezzi, on=['Data', 'Ora'], how='inner')
df_mercato.rename(columns={'€/MWh': 'PUN'}, inplace=True)
df_mercato = df_mercato[df_mercato['Ora'] != 25].reset_index(drop=True)

df_mercato['Data e Ora'] = pd.date_range(start='2025-11-01 00:00:00', periods=len(df_mercato), freq='H')
df_gen['Data e Ora'] = pd.to_datetime(df_gen['Date'])
df = pd.merge(df_mercato, df_gen, on='Data e Ora', how='inner')

# Vettori numpy per calcolo vettoriale
PUN = df['PUN'].values
volumi_base = df['Volumi MWh'].values
fv_base = df['Photovoltaic'].values
eolico_base = df['Wind'].values
auto_base = df['Self-consumption'].values

# ==========================================
# 3. SCENARIO BASE (ORIGINALE)
# ==========================================
# Il costo dei CfD nello scenario base si applica ai volumi storici di rinnovabili prodotti
cfd_eolico_base = np.maximum(0, STRIKE_EOLICO - PUN) * eolico_base
cfd_fv_base = np.maximum(0, STRIKE_FV - PUN) * fv_base
oneri_totali_base_orari = (volumi_base * ONERI_BASE_FISSI) + cfd_eolico_base + cfd_fv_base

spesa_energia_base = (volumi_base * (PUN + COSTO_DISPACCIAMENTO)).sum()
spesa_oneri_base = oneri_totali_base_orari.sum()
iva_base = (spesa_energia_base + spesa_oneri_base) * ALIQUOTA_IVA
spesa_totale_base = spesa_energia_base + spesa_oneri_base + iva_base

def simula_bess(eccesso, deficit, capacita, potenza, efficienza):
    n = len(eccesso)
    scaricata = np.zeros(n)
    caricata = np.zeros(n)
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
    return caricata, scaricata

# ==========================================
# 4. OTTIMIZZAZIONE
# ==========================================
fattori = np.arange(1.0, 5, 0.3)
combinazioni = list(itertools.product(fattori, fattori, fattori))

miglior_risparmio = -np.inf
miglior_comb = None
report = {}

for f_fv, f_eol, f_auto in combinazioni:
    # Nuova generazione rinnovabile totale
    fv_totale = fv_base * f_fv
    eolico_totale = eolico_base * f_eol
    auto_totale = auto_base * f_auto
    
    delta_fv = fv_totale - fv_base
    delta_eol = eolico_totale - eolico_base
    delta_auto = auto_totale - auto_base
    delta_energia = delta_fv + delta_eol + delta_auto
    
    eccesso_grezzo = np.maximum(0, delta_energia - volumi_base)
    deficit_grezzo = np.maximum(0, volumi_base - delta_energia)
    
    bess_caricata, bess_scaricata = simula_bess(eccesso_grezzo, deficit_grezzo, CAPACITA_BESS_MWH, POTENZA_BESS_MW, EFFICIENZA_BESS)
    
    eccesso_finale = eccesso_grezzo - bess_caricata
    fabbisogno_residuo = deficit_grezzo - bess_scaricata
    
    # 1. SPESA RETE RESIDUA (Solo sul volume prelevato)
    spesa_mercato = (fabbisogno_residuo * (PUN + COSTO_DISPACCIAMENTO)).sum()
    
    # 2. NUOVI ONERI CfD (Calcolati sull'INTERA generazione rinnovabile dello scenario)
    cfd_eolico_nuovo = np.maximum(0, STRIKE_EOLICO - PUN) * eolico_totale
    cfd_fv_nuovo = np.maximum(0, STRIKE_FV - PUN) * fv_totale
    
    spesa_oneri_nuova = (volumi_base * ONERI_BASE_FISSI).sum() + cfd_eolico_nuovo.sum() + cfd_fv_nuovo.sum()
    
    # 3. IVA
    iva_nuova = (spesa_mercato + spesa_oneri_nuova) * ALIQUOTA_IVA
    spesa_rete_ivata = spesa_mercato + spesa_oneri_nuova + iva_nuova
    
    # 4. ALTRI COSTI
    spesa_sovrapproduzione = (eccesso_finale * COSTO_SOVRAPPRODUZIONE).sum()
    costo_nuovi_impianti = (delta_fv * COSTO_PROD_FV).sum() + (delta_eol * COSTO_PROD_EOLICO).sum() + (delta_auto * COSTO_PROD_AUTO).sum()
    costo_integrazione = (delta_fv.max() + delta_eol.max() + delta_auto.max()) * COSTO_INTEGRAZIONE_MW
    costo_uso_bess = (bess_scaricata * COSTO_LCOE_BESS).sum()
    
    # SPESA TOTALE
    nuova_spesa_totale = spesa_rete_ivata + spesa_sovrapproduzione + costo_nuovi_impianti + costo_uso_bess + costo_integrazione
    risparmio_euro = spesa_totale_base - nuova_spesa_totale
    
    if risparmio_euro > miglior_risparmio:
        miglior_risparmio = risparmio_euro
        miglior_comb = (f_fv, f_eol, f_auto)
        
        report = {
            "Spesa Mercato": spesa_mercato,
            "Oneri Fissi Base": (volumi_base * ONERI_BASE_FISSI).sum(),
            "Oneri CfD Rinnovabili": cfd_eolico_nuovo.sum() + cfd_fv_nuovo.sum(),
            "IVA Nuova": iva_nuova,
            "Costo Impianti": costo_nuovi_impianti,
            "Costo BESS": costo_uso_bess,
            "Costo Integrazione": costo_integrazione,
            "Spesa Penali": spesa_sovrapproduzione,
            "Spesa Totale": nuova_spesa_totale
        }

# ==========================================
# 5. REPORT FINALE
# ==========================================
oneri_totali_ivati = (report['Oneri Fissi Base'] + report['Oneri CfD Rinnovabili']) * (1 + ALIQUOTA_IVA)
spesa_totale_senza_oneri = report['Spesa Totale'] - oneri_totali_ivati

print(f"\n--- OTTIMIZZAZIONE REALE: CONTRATTI PER DIFFERENZA (CfD) ---")
print(f"Miglior Combinazione: FV {miglior_comb[0]:.1f}x | Eolico {miglior_comb[1]:.1f}x | Auto {miglior_comb[2]:.1f}x")
print("-" * 65)
print(f"Spesa Energia Originale (PUN+PD):    € {spesa_energia_base:,.2f}")
print(f"Spesa Oneri Fissi Rete:              € {(volumi_base * ONERI_BASE_FISSI).sum():,.2f}")
print(f"Spesa Oneri CfD (Sussidi Storici):   € {(cfd_eolico_base.sum() + cfd_fv_base.sum()):,.2f}")
print(f"IVA Originale Pagata:                € {iva_base:,.2f}")
print(f"Spesa Totale Iniziale (A):           € {spesa_totale_base:,.2f}")
print("-" * 65)
print(f"Nuova Spesa Energia Rete (PUN+PD):   € {report['Spesa Mercato']:,.2f}")
print(f"Nuovi Oneri Fissi Rete:              € {report['Oneri Fissi Base']:,.2f}")
print(f"Nuovi Oneri CfD (Sussidi Maggiorati):€ {report['Oneri CfD Rinnovabili']:,.2f}")
print(f"Nuova IVA Pagata:                    € {report['IVA Nuova']:,.2f}")
print(f"Nuovi Impianti + BESS + Integraz.:   € {(report['Costo Impianti'] + report['Costo BESS'] + report['Costo Integrazione']):,.2f}")
print(f"Penali Sovrapproduzione (Spreco):    € {report['Spesa Penali']:,.2f}")
print("-" * 65)
print(f"NUOVA SPESA TOTALE SISTEMA (B):      € {report['Spesa Totale']:,.2f}")
print(f"Risparmio Netto Attuale (A - B):     € {miglior_risparmio:,.2f}")