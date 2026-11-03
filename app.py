"""Simulatore costo sistema elettrico con più rinnovabili — app Streamlit.

Avvio locale:  streamlit run app.py
"""
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from simulatore import Parametri, carica_dati, griglia, ottimizza, scenario_base, valuta_scenario

st.set_page_config(page_title="Simulatore rinnovabili e bolletta", page_icon="⚡", layout="wide")

# Palette categoriale (ordine fisso)
C = {"blu": "#2a78d6", "arancio": "#eb6834", "acqua": "#1baf7a", "giallo": "#eda100",
     "magenta": "#e87ba4", "viola": "#6250d6", "rosso": "#e34948", "grigio": "#8c8b86"}
VOCI = ["Spesa energia rete", "Oneri fissi", "Oneri CfD", "IVA", "Nuovi impianti", "BESS",
        "Integrazione", "Penali sovrapproduzione"]
COLORI_VOCI = dict(zip(VOCI, [C["blu"], C["grigio"], C["arancio"], C["giallo"], C["acqua"],
                              C["viola"], C["magenta"], C["rosso"]]))


def mld(x: float) -> str:
    return f"€ {x / 1e9:,.2f} mld".replace(",", "X").replace(".", ",").replace("X", ".")


# ------------------------------------------------------------------ dati
@st.cache_data(show_spinner="Carico i dati...")
def _carica(upload_vol=None, upload_pun=None, upload_gen=None):
    kw = {}
    if upload_vol is not None:
        kw["src_volumi"] = upload_vol
    if upload_pun is not None:
        kw["src_pun"] = upload_pun
    if upload_gen is not None:
        kw["src_gen"] = upload_gen
    d = carica_dati(**kw)
    return d.df, d.note


@st.cache_data(show_spinner=False)
def _ottimizza(_v, chiave_dati, par: dict, ffv, feol, fauto):
    barra = st.progress(0.0, text="Ottimizzazione in corso...")
    tab = ottimizza(_v, Parametri.from_dict(par), ffv, feol, fauto,
                    progresso=lambda x: barra.progress(x, text=f"Ottimizzazione in corso... {x:.0%}"))
    barra.empty()
    return tab


# ------------------------------------------------------------------ sidebar
st.sidebar.title("⚙️ Parametri")
with st.sidebar.expander("📂 Dati (opzionale: carica i tuoi)"):
    st.caption("Senza upload si usano i file in `data/` (nov 2025 – ott 2026).")
    up_vol = st.file_uploader("Fabbisogno MGP (GME, xlsx)", type=["xlsx", "csv"])
    up_pun = st.file_uploader("PUN (GME, xlsx)", type=["xlsx", "csv"])
    up_gen = st.file_uploader("Generazione (Terna, csv)", type=["csv", "xlsx"])

d = Parametri()
with st.sidebar.expander("💶 Mercato e bolletta", expanded=True):
    disp = st.number_input("Dispacciamento (€/MWh)", value=d.costo_dispacciamento, step=1.0)
    oneri = st.number_input("Oneri fissi di rete (€/MWh)", value=d.oneri_base_fissi, step=1.0)
    iva = st.number_input("IVA (%)", value=d.aliquota_iva * 100, step=1.0) / 100
with st.sidebar.expander("📜 Contratti per Differenza"):
    k_eol = st.number_input("Strike eolico (€/MWh)", value=d.strike_eolico, step=5.0)
    k_fv = st.number_input("Strike FV (€/MWh)", value=d.strike_fv, step=5.0)
    cfd_bi = st.toggle("CfD bidirezionale", value=d.cfd_bidirezionale,
                       help="Se attivo, quando il PUN supera lo strike il produttore restituisce la differenza.")
    cfd_new = st.toggle("CfD anche sulla generazione aggiuntiva", value=d.cfd_su_nuova_generazione,
                        help="Default dell'originale. Nota: la nuova energia è già pagata a costo di produzione, "
                             "quindi attivo = possibile doppio conteggio.")
with st.sidebar.expander("🏭 Costi nuova generazione"):
    c_fv = st.number_input("FV (€/MWh)", value=d.costo_prod_fv, step=5.0)
    c_eol = st.number_input("Eolico (€/MWh)", value=d.costo_prod_eolico, step=5.0)
    c_auto = st.number_input("Autoconsumo (€/MWh)", value=d.costo_prod_auto, step=5.0)
    c_sovr = st.number_input("Penale sovrapproduzione (€/MWh)", value=d.costo_sovrapproduzione, step=5.0)
    c_int = st.number_input("Integrazione (€ per MW di picco)", value=d.costo_integrazione_mw, step=1.0)
with st.sidebar.expander("🔋 Accumulo"):
    cap = st.number_input("Capacità (MWh)", value=d.capacita_bess_mwh, step=5000.0)
    pot = st.number_input("Potenza (MW)", value=d.potenza_bess_mw, step=1000.0)
    eff = st.slider("Efficienza round-trip", 0.5, 1.0, d.efficienza_bess, 0.01)
    c_bess = st.number_input("LCOE accumulo (€/MWh scaricato)", value=d.costo_lcoe_bess, step=5.0)

par = Parametri(disp, oneri, iva, k_eol, k_fv, cfd_bi, cfd_new, c_fv, c_eol, c_auto,
                c_sovr, c_int, cap, pot, eff, c_bess)

# ------------------------------------------------------------------ calcolo base
try:
    df, note = _carica(up_vol, up_pun, up_gen)
except Exception as e:  # file caricati non validi
    st.error(f"Errore nel caricamento dei dati: {e}")
    st.stop()

v = {"pun": df["PUN"].to_numpy(float), "volumi": df["Volumi MWh"].to_numpy(float),
     "fv": df["Photovoltaic"].to_numpy(float), "eolico": df["Wind"].to_numpy(float),
     "auto": df["Self-consumption"].to_numpy(float)}
chiave_dati = (len(df), float(v["volumi"].sum()), float(v["pun"].sum()), float(v["fv"].sum()))
base = scenario_base(v, par)

st.title("⚡ Rinnovabili e costo del sistema elettrico")
st.caption("Quanto costerebbe un anno di elettricità in Italia con più fotovoltaico, eolico e autoconsumo "
           "(e una batteria nazionale), a prezzi orari storici. Modello semplificato: vedi tab *Ipotesi*.")

tab_sim, tab_opt, tab_dati = st.tabs(["🎚️ Scenario", "🔎 Ottimizzazione", "📋 Dati e ipotesi"])


def grafico_confronto(base: dict, scen: dict, nome_scen: str = "Scenario") -> go.Figure:
    fig = go.Figure()
    for voce in VOCI:
        fig.add_bar(name=voce, x=["Base", nome_scen], y=[base[voce] / 1e9, scen[voce] / 1e9],
                    marker_color=COLORI_VOCI[voce],
                    hovertemplate=f"{voce}: €%{{y:.2f}} mld<extra></extra>")
    fig.update_layout(barmode="stack", height=420, yaxis_title="miliardi di €/anno",
                      legend=dict(orientation="h", y=-0.15), margin=dict(t=20, b=10), bargap=0.45)
    return fig


# ------------------------------------------------------------------ tab scenario
with tab_sim:
    c1, c2, c3 = st.columns(3)
    f_fv = c1.slider("Moltiplicatore fotovoltaico", 1.0, 10.0, 3.4, 0.1)
    f_eol = c2.slider("Moltiplicatore eolico", 1.0, 10.0, 4.9, 0.1)
    f_auto = c3.slider("Moltiplicatore autoconsumo", 1.0, 10.0, 1.0, 0.1)
    r = valuta_scenario(v, par, f_fv, f_eol, f_auto, base=base, orario=True)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Spesa base (A)", mld(base["Spesa totale"]))
    k2.metric("Spesa scenario (B)", mld(r["Spesa totale"]))
    k3.metric("Risparmio (A − B)", mld(r["Risparmio"]), f"{r['Risparmio'] / base['Spesa totale']:+.1%}")
    k4.metric("Energia sprecata", f"{r['Eccesso sprecato TWh']:.1f} TWh".replace(".", ","),
              f"{r['Ore con eccesso']} ore con eccesso", delta_color="off")

    g1, g2 = st.columns([2, 3])
    with g1:
        st.subheader("Composizione della spesa")
        st.plotly_chart(grafico_confronto(base, r), width="stretch")
    with g2:
        st.subheader("Profilo orario")
        o = r["orario"].copy()
        o.index = df["Data e Ora"]
        settimane = pd.date_range(o.index.min().normalize(), o.index.max(), freq="7D")
        inizio = st.select_slider("Settimana dal", options=list(settimane),
                                  value=settimane[len(settimane) // 2],
                                  format_func=lambda t: t.strftime("%d %b %Y"))
        w = o.loc[inizio: inizio + pd.Timedelta(days=7)]
        fig = go.Figure()
        for col, colore in [("Nuova FV", C["giallo"]), ("Nuovo eolico", C["blu"]),
                            ("Nuovo autoconsumo", C["acqua"]), ("Scarica BESS", C["viola"])]:
            fig.add_scatter(x=w.index, y=w[col] / 1e3, name=col, stackgroup="g", mode="none",
                            fillcolor=colore, hovertemplate="%{y:.1f} GW")
        fig.add_scatter(x=w.index, y=w["Fabbisogno"] / 1e3, name="Fabbisogno MGP",
                        line=dict(color="#0b0b0b", width=2), hovertemplate="%{y:.1f} GW")
        fig.update_layout(height=420, yaxis_title="GW medi orari", hovermode="x unified",
                          legend=dict(orientation="h", y=-0.15), margin=dict(t=20, b=10))
        st.plotly_chart(fig, width="stretch")

    with st.expander("Dettaglio voci (€)"):
        t = pd.DataFrame({"Base (A)": {k: base[k] for k in VOCI + ["Spesa totale"]},
                          "Scenario (B)": {k: r[k] for k in VOCI + ["Spesa totale"]}})
        t["Differenza (B − A)"] = t["Scenario (B)"] - t["Base (A)"]
        st.dataframe(t.style.format("{:,.0f}"), width="stretch")
        st.download_button("Scarica profilo orario (CSV)", o.to_csv().encode(), "profilo_orario.csv")

# ------------------------------------------------------------------ tab ottimizzazione
with tab_opt:
    st.markdown("Prova tutte le combinazioni dei tre moltiplicatori e trova quella col risparmio massimo.")
    c1, c2, c3, c4 = st.columns(4)
    g_min = c1.number_input("Fattore minimo", value=1.0, step=0.1, min_value=0.0)
    g_max = c2.number_input("Fattore massimo", value=4.9, step=0.1)
    g_passo = c3.number_input("Passo", value=0.3, step=0.1, min_value=0.05)
    blocca_auto = c4.checkbox("Autoconsumo fisso a 1×", value=False,
                              help="Riduce le combinazioni di un fattore N e velocizza molto.")
    fattori = griglia(g_min, g_max, g_passo)
    f_auto_g = np.array([1.0]) if blocca_auto else fattori
    n_comb = len(fattori) ** 2 * len(f_auto_g)
    st.caption(f"{n_comb:,} combinazioni".replace(",", "."))

    if n_comb > 50_000:
        st.warning("Troppe combinazioni: aumenta il passo o restringi l'intervallo.")
    elif st.button("▶️ Avvia ottimizzazione", type="primary"):
        st.session_state["opt"] = _ottimizza(v, chiave_dati, par.to_dict(),
                                             tuple(fattori), tuple(fattori), tuple(f_auto_g))
        st.session_state["opt_griglia"] = (fattori.min(), fattori.max())

    if "opt" in st.session_state:
        tab = st.session_state["opt"]
        gmin, gmax = st.session_state["opt_griglia"]
        best = tab.iloc[0]
        st.success(f"**Ottimo:** FV {best.f_fv:.1f}× · Eolico {best.f_eol:.1f}× · Autoconsumo {best.f_auto:.1f}× "
                   f"→ risparmio **{mld(best.Risparmio)}** ({best.Risparmio / base['Spesa totale']:.1%})")
        bordo = [n for n, x in (("FV", best.f_fv), ("Eolico", best.f_eol), ("Autoconsumo", best.f_auto))
                 if np.isclose(x, gmax) and not (n == "Autoconsumo" and blocca_auto)]
        if bordo:
            st.warning(f"{', '.join(bordo)} è al **massimo della griglia**: l'ottimo vero sta oltre. "
                       "Alza il fattore massimo.")

        h1, h2 = st.columns([3, 2])
        with h1:
            st.subheader("Risparmio per FV × eolico")
            sub = tab[np.isclose(tab.f_auto, best.f_auto)]
            piv = sub.pivot(index="f_eol", columns="f_fv", values="Risparmio") / 1e9
            fig = px.imshow(piv, origin="lower", aspect="auto", color_continuous_scale="Blues",
                            labels=dict(x="Moltiplicatore FV", y="Moltiplicatore eolico", color="mld €"))
            fig.add_scatter(x=[best.f_fv], y=[best.f_eol], mode="markers", name="Ottimo",
                            marker=dict(symbol="x", size=14, color=C["arancio"], line=dict(width=2)))
            fig.update_layout(height=460, margin=dict(t=10), showlegend=False)
            fig.update_traces(hovertemplate="FV %{x}× · Eolico %{y}×<br>Risparmio €%{z:.2f} mld<extra></extra>",
                              selector=dict(type="heatmap"))
            st.caption(f"Autoconsumo fissato a {best.f_auto:.1f}×")
            st.plotly_chart(fig, width="stretch")
        with h2:
            st.subheader("Base vs ottimo")
            st.plotly_chart(grafico_confronto(base, best.to_dict(), "Ottimo"), width="stretch")

        st.subheader("Migliori 20 combinazioni")
        cols = ["f_fv", "f_eol", "f_auto", "Risparmio", "Spesa totale", "Nuova energia TWh",
                "Eccesso sprecato TWh", "Scaricato BESS TWh"]
        st.dataframe(tab[cols].head(20).style.format({"Risparmio": "{:,.0f}", "Spesa totale": "{:,.0f}",
                                                      "f_fv": "{:.1f}", "f_eol": "{:.1f}", "f_auto": "{:.1f}",
                                                      "Nuova energia TWh": "{:.1f}",
                                                      "Eccesso sprecato TWh": "{:.2f}",
                                                      "Scaricato BESS TWh": "{:.2f}"}),
                     width="stretch")
        st.download_button("Scarica tutte le combinazioni (CSV)", tab.to_csv(index=False).encode(),
                           "ottimizzazione.csv")

# ------------------------------------------------------------------ tab dati
with tab_dati:
    st.subheader("Qualità dei dati")
    for n in note:
        st.markdown(f"- {n}")

    st.subheader("Totali annui nel periodo")
    tot = pd.DataFrame({
        "TWh": [v["volumi"].sum() / 1e6, v["fv"].sum() / 1e6, v["eolico"].sum() / 1e6, v["auto"].sum() / 1e6],
    }, index=["Fabbisogno MGP", "Fotovoltaico", "Eolico", "Autoconsumo (Terna 'Self-consumption')"])
    c1, c2 = st.columns(2)
    c1.dataframe(tot.style.format("{:.1f}"), width="stretch")
    c2.metric("PUN medio semplice", f"{v['pun'].mean():.1f} €/MWh")
    c2.metric("PUN medio ponderato sui volumi", f"{np.average(v['pun'], weights=v['volumi']):.1f} €/MWh")

    st.subheader("Come funziona il modello")
    st.markdown("""
1. **Scenario base** — tutto il fabbisogno MGP è pagato a *PUN + dispacciamento*; si aggiungono
   gli oneri fissi (€/MWh × volumi), i CfD sulla produzione storica di FV ed eolico e l'IVA.
2. **Scenario** — FV, eolico e autoconsumo orari vengono moltiplicati. Solo l'energia **aggiuntiva**
   riduce gli acquisti dalla rete, ora per ora. Se supera il fabbisogno, l'eccesso carica la batteria
   e il resto paga una penale; se non basta, la batteria scarica e il resto si compra a PUN.
3. **Costi dello scenario** — rete residua + oneri + CfD + IVA, più: costo di produzione della nuova energia
   (€/MWh), accumulo (€/MWh scaricato), integrazione (€/MW di picco), penali.
4. **Risparmio** = spesa base − spesa scenario. L'ottimizzazione prova tutte le combinazioni della griglia.
""")
    st.subheader("Ipotesi forti da tenere a mente")
    st.markdown("""
- **Il PUN resta quello storico.** Ogni MWh rinnovabile in più evita ~PUN+dispacciamento (≈120 €/MWh)
  e costa 60–80 €/MWh, quindi “più è sempre meglio” finché non si spreca. Nella realtà, con molte rinnovabili
  il prezzo nelle ore di sole/vento crolla (effetto merit-order): i risparmi qui sono un **limite superiore**.
- **Nessun costo di adeguatezza**: il parco termico di backup, le reti di trasmissione e i servizi di
  rete restano fuori (gli oneri di rete sono fissi a €/MWh).
- **“Self-consumption” di Terna non è solo FV sui tetti**: ha un carico notturno di ~1,8 GW
  (autoconsumi di centrale/industriali) più una componente solare. Moltiplicarlo moltiplica anche la parte notturna.
- **Costo di integrazione**: 10 € per MW di picco aggiuntivo vale poche centinaia di migliaia di euro
  su un totale di decine di miliardi — probabilmente l'unità voluta era diversa (k€/MW o €/kW·anno).
- **Batteria**: dimensione fissa, carica solo dall'eccesso sopra il fabbisogno *nazionale* totale,
  costo solo per MWh scaricato (nessun costo di capacità).
- **CfD**: di default unidirezionale e applicato anche alla nuova generazione, che però è già pagata
  a costo di produzione → doppio conteggio parziale. Le due opzioni nella barra laterale lo correggono.
- **IVA** applicata solo alla spesa di rete, non ai costi dei nuovi impianti.
""")
