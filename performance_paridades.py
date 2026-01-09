# performance_paridades.py
import re
from datetime import datetime
from typing import List, Dict

import pandas as pd
import streamlit as st

# Regex para mensagens resolvidas
RESOLVED_RE = re.compile(
    r"^(?P<check>[✅❌🃏])(?P<sup>[\u00b9\u00b2\u00b3\d]?)\s*"
    r"(?P<pair>[A-Z0-9\-\_]+(?:-OTC)?)\s*-\s*(?P<time>\d{2}:\d{2}:\d{2})\s*-\s*(?P<tf>\w+)\s*-\s*(?P<dir>\w+)\s*-\s*(?P<result>WIN|LOSS|DOJI)$",
    flags=re.IGNORECASE,
)

SUPERSCRIPT_MAP = {
    "\u00b9": 1,
    "\u00b2": 2,
    "\u00b3": 3,
    "1": 1,
    "2": 2,
    "3": 3,
}

def _sup_to_level(s: str) -> int:
    if not s:
        return 0
    return SUPERSCRIPT_MAP.get(s, 0)

def _get_text_from_msg(msg: dict) -> str:
    for k in ("text", "message.text", "message", "message_text"):
        v = msg.get(k)
        if isinstance(v, str) and v.strip():
            return v
    v = msg.get("text") or msg.get("message")
    return v if isinstance(v, str) else ""

def _extract_records(messages: List[dict]) -> List[dict]:
    records = []
    signals = {}
    
    for msg in messages:
        text = _get_text_from_msg(msg)
        if not isinstance(text, str):
            continue
        if "Ativo:" in text or "Payout:" in text:
            m_pair = re.search(r"Ativo:\s*([A-Z0-9\-\_]+(?:-OTC)?)", text, re.IGNORECASE)
            m_time = re.search(r"Hor[aá]rio:\s*(\d{2}:\d{2}:\d{2})", text, re.IGNORECASE)
            m_pay = re.search(r"Payout:\s*([\d\.]+)\s*%", text, re.IGNORECASE)
            if m_pair and m_time:
                p = m_pair.group(1).strip()
                t = m_time.group(1).strip()
                payout = None
                if m_pay:
                    try:
                        payout = float(m_pay.group(1)) / 100.0
                    except:
                        payout = None
                signals[(p, t)] = payout

    for msg in messages:
        text = _get_text_from_msg(msg)
        if not text:
            continue
        one_line = " ".join(text.splitlines()).strip()
        m = RESOLVED_RE.match(one_line)
        if m:
            try:
                sup = m.group("sup") or ""
                gale_level = _sup_to_level(sup)
                pair = m.group("pair").strip()
                time = m.group("time").strip()
                tf = m.group("tf").strip()
                direction = m.group("dir").strip()
                
                # Tenta pegar o resultado de diferentes formas
                if "r" in m.groupdict():
                    result_raw = m.group("r").strip().upper()
                elif "result" in m.groupdict():
                    result_raw = m.group("result").strip().upper()
                else:
                    # Pega o último grupo
                    result_raw = m.groups()[-1].strip().upper()
                    
                result = "DOJI" if result_raw == "DOJI" else ("WIN" if result_raw == "WIN" else "LOSS")
                payout = signals.get((pair, time))
            except Exception as e:
                # Se der erro, pula esta mensagem
                continue
            
            records.append({
                "pair": pair,
                "time": time,
                "tf": tf,
                "direction": direction,
                "result": result,
                "gale_level": gale_level,
                "payout": payout,
            })
    return records

def _calculate_volatility(wins, losses):
    """
    Calcula volatilidade baseada na dispersão dos resultados.
    Quanto maior a proporção de losses, maior a volatilidade/risco.
    """
    total = wins + losses
    if total == 0:
        return 0.0
    loss_rate = (losses / total) * 100.0
    return loss_rate

def _classify_pair(win_rate_pct, volatility_pct, total_ops):
    """
    Classifica a paridade baseado no win rate, volatilidade e volume.
    """
    if total_ops < 5:
        return "SEM_DADOS", "#9aa0a6"
    
    if win_rate_pct >= 90 and volatility_pct <= 15:
        return "EXCELENTE", "#0b8043"
    elif win_rate_pct >= 85 and volatility_pct <= 18:
        return "BOM", "#1a73e8"
    elif win_rate_pct >= 80 and volatility_pct <= 25:
        return "OK", "#f9ab00"
    elif win_rate_pct >= 75:
        return "REGULAR", "#f29900"
    else:
        return "PERIGOSO", "#d93025"

def render_from_json(json_data: dict):
    """
    Renderiza a página de Performance de Paridades a partir do JSON.
    """
    messages = json_data.get("messages", [])
    records = _extract_records(messages)
    df = pd.DataFrame(records)

    if df.empty:
        st.warning("⚠️ Nenhum dado disponível para análise de paridades.")
        return

    # Agrupar por paridade
    pair_analysis = df.groupby("pair").agg(
        Total_Operacoes=("result", "size"),
        WIN=("result", lambda s: (s == "WIN").sum()),
        LOSS=("result", lambda s: (s == "LOSS").sum()),
        DOJI=("result", lambda s: (s == "DOJI").sum()),
        G0=("gale_level", lambda s: (s == 0).sum()),
        G1=("gale_level", lambda s: (s == 1).sum()),
        G2=("gale_level", lambda s: (s == 2).sum()),
    ).reset_index()

    # Calcular métricas
    pair_analysis["Win_Rate_Pct"] = (
        pair_analysis["WIN"] / (pair_analysis["WIN"] + pair_analysis["LOSS"]) * 100
    ).fillna(0).round(2)
    
    pair_analysis["Pct_Gale1"] = (
        pair_analysis["G1"] / pair_analysis["Total_Operacoes"] * 100
    ).fillna(0).round(2)
    
    pair_analysis["Pct_Gale2"] = (
        pair_analysis["G2"] / pair_analysis["Total_Operacoes"] * 100
    ).fillna(0).round(2)
    
    pair_analysis["Volatilidade_Pct"] = pair_analysis.apply(
        lambda row: _calculate_volatility(row["WIN"], row["LOSS"]), axis=1
    ).round(2)

    # Classificação
    pair_analysis[["Classificacao", "Cor"]] = pair_analysis.apply(
        lambda row: pd.Series(_classify_pair(
            row["Win_Rate_Pct"], 
            row["Volatilidade_Pct"],
            row["Total_Operacoes"]
        )),
        axis=1
    )

    # Ordenar por total de operações (mais operadas primeiro)
    pair_analysis = pair_analysis.sort_values("Total_Operacoes", ascending=False)

    # ===== RENDERIZAÇÃO =====
    st.markdown("<h1 style='text-align:center; color:#1f4068; margin-bottom:30px;'>💱 Performance de Paridades</h1>", unsafe_allow_html=True)

    # Cards resumo por classificação
    excelente_count = (pair_analysis["Classificacao"] == "EXCELENTE").sum()
    bom_count = (pair_analysis["Classificacao"] == "BOM").sum()
    ok_count = (pair_analysis["Classificacao"] == "OK").sum()
    regular_count = (pair_analysis["Classificacao"] == "REGULAR").sum()
    perigoso_count = (pair_analysis["Classificacao"] == "PERIGOSO").sum()
    sem_dados_count = (pair_analysis["Classificacao"] == "SEM_DADOS").sum()

    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #0b8043 0%, #12b35a 100%); 
                    border-radius: 12px; padding: 16px; color: white; text-align: center;">
            <div style="font-size: 12px; opacity: 0.9; margin-bottom: 6px;">EXCELENTES</div>
            <div style="font-size: 28px; font-weight: 700;">{excelente_count}</div>
            <div style="font-size: 11px; opacity: 0.8; margin-top: 6px;">≥90% WR</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #1a73e8 0%, #4285f4 100%); 
                    border-radius: 12px; padding: 16px; color: white; text-align: center;">
            <div style="font-size: 12px; opacity: 0.9; margin-bottom: 6px;">BOAS</div>
            <div style="font-size: 28px; font-weight: 700;">{bom_count}</div>
            <div style="font-size: 11px; opacity: 0.8; margin-top: 6px;">85-89% WR</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #f9ab00 0%, #fbc02d 100%); 
                    border-radius: 12px; padding: 16px; color: white; text-align: center;">
            <div style="font-size: 12px; opacity: 0.9; margin-bottom: 6px;">OK</div>
            <div style="font-size: 28px; font-weight: 700;">{ok_count}</div>
            <div style="font-size: 11px; opacity: 0.8; margin-top: 6px;">80-84% WR</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #f29900 0%, #ff9800 100%); 
                    border-radius: 12px; padding: 16px; color: white; text-align: center;">
            <div style="font-size: 12px; opacity: 0.9; margin-bottom: 6px;">REGULARES</div>
            <div style="font-size: 28px; font-weight: 700;">{regular_count}</div>
            <div style="font-size: 11px; opacity: 0.8; margin-top: 6px;">75-79% WR</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col5:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #d93025 0%, #ea4335 100%); 
                    border-radius: 12px; padding: 16px; color: white; text-align: center;">
            <div style="font-size: 12px; opacity: 0.9; margin-bottom: 6px;">PERIGOSAS</div>
            <div style="font-size: 28px; font-weight: 700;">{perigoso_count}</div>
            <div style="font-size: 11px; opacity: 0.8; margin-top: 6px;"><75% WR</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Top 3 e Bottom 3
    top_pairs = pair_analysis[pair_analysis["Total_Operacoes"] >= 5].nlargest(3, "Win_Rate_Pct")
    bottom_pairs = pair_analysis[pair_analysis["Total_Operacoes"] >= 5].nsmallest(3, "Win_Rate_Pct")

    col_top, col_bottom = st.columns(2)
    
    with col_top:
        st.markdown("### 🏆 Top 3 Melhores Paridades")
        for idx, row in top_pairs.iterrows():
            st.markdown(f"""
            <div style="background: #e8f5e9; border-left: 4px solid #0b8043; 
                        border-radius: 8px; padding: 12px; margin-bottom: 8px;">
                <div style="font-size: 16px; font-weight: 700; color: #1f4068;">
                    {row['pair']}
                </div>
                <div style="font-size: 13px; color: #666; margin-top: 4px;">
                    Win Rate: <strong>{row['Win_Rate_Pct']:.2f}%</strong> | 
                    {int(row['WIN'])} vitórias em {int(row['Total_Operacoes'])} ops
                </div>
            </div>
            """, unsafe_allow_html=True)
    
    with col_bottom:
        st.markdown("### ⚠️ Top 3 Piores Paridades")
        for idx, row in bottom_pairs.iterrows():
            st.markdown(f"""
            <div style="background: #fce4ec; border-left: 4px solid #d93025; 
                        border-radius: 8px; padding: 12px; margin-bottom: 8px;">
                <div style="font-size: 16px; font-weight: 700; color: #1f4068;">
                    {row['pair']}
                </div>
                <div style="font-size: 13px; color: #666; margin-top: 4px;">
                    Win Rate: <strong>{row['Win_Rate_Pct']:.2f}%</strong> | 
                    {int(row['WIN'])} vitórias em {int(row['Total_Operacoes'])} ops
                </div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ===== GRÁFICO DE BARRAS - TOP 10 =====
    st.markdown("### 📊 Top 10 Paridades Mais Operadas")
    
    top10 = pair_analysis.head(10)
    
    # Criar gráfico de barras horizontal simples com HTML/CSS
    max_ops = top10["Total_Operacoes"].max()
    
    for _, row in top10.iterrows():
        pct = (row["Total_Operacoes"] / max_ops) * 100
        color = row["Cor"]
        
        st.markdown(f"""
        <div style="margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                <span style="font-weight: 600; color: #1f4068;">{row['pair']}</span>
                <span style="font-weight: 700; color: {color};">{int(row['Total_Operacoes']):,} ops</span>
            </div>
            <div style="background: #e8eaed; border-radius: 4px; height: 24px; overflow: hidden;">
                <div style="background: {color}; width: {pct}%; height: 100%; border-radius: 4px; 
                            display: flex; align-items: center; padding-left: 8px; color: white; font-size: 12px; font-weight: 600;">
                    {row['Win_Rate_Pct']:.1f}%
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ===== TABELA DETALHADA =====
    st.markdown("### 📋 Análise Completa de Todas as Paridades")

    # Preparar tabela para exibição
    display_df = pair_analysis[[
        "pair", "Total_Operacoes", "WIN", "LOSS",
        "Win_Rate_Pct", "Pct_Gale1", "Pct_Gale2", "Volatilidade_Pct", "Classificacao"
    ]].copy()

    # Formatar colunas
    display_df["Total_Operacoes"] = display_df["Total_Operacoes"].apply(lambda x: f"{int(x):,}" if x > 0 else "—")
    display_df["WIN"] = display_df["WIN"].apply(lambda x: f"{int(x):,}" if x > 0 else "—")
    display_df["LOSS"] = display_df["LOSS"].apply(lambda x: f"{int(x):,}" if x > 0 else "—")
    display_df["Win_Rate_Pct"] = display_df["Win_Rate_Pct"].apply(lambda x: f"{x:.2f}%" if x > 0 else "0%")
    display_df["Pct_Gale1"] = display_df["Pct_Gale1"].apply(lambda x: f"{x:.1f}%")
    display_df["Pct_Gale2"] = display_df["Pct_Gale2"].apply(lambda x: f"{x:.1f}%")
    display_df["Volatilidade_Pct"] = display_df["Volatilidade_Pct"].apply(lambda x: f"{x:.1f}%")

    # Colorir classificação
    def color_classification(row):
        classif = row["Classificacao"]
        if classif == "EXCELENTE":
            return f'<span style="color: #0b8043; font-weight: 700;">★ {classif}</span>'
        elif classif == "BOM":
            return f'<span style="color: #1a73e8; font-weight: 700;">● {classif}</span>'
        elif classif == "OK":
            return f'<span style="color: #f9ab00; font-weight: 600;">◐ {classif}</span>'
        elif classif == "REGULAR":
            return f'<span style="color: #f29900; font-weight: 600;">◔ {classif}</span>'
        elif classif == "PERIGOSO":
            return f'<span style="color: #d93025; font-weight: 600;">✗ {classif}</span>'
        else:
            return f'<span style="color: #9aa0a6; font-weight: 500;">○ {classif}</span>'

    display_df["Classificacao"] = display_df.apply(color_classification, axis=1)

    # Renomear colunas
    display_df.columns = [
        "Paridade", "Total Ops", "Vitórias", "Derrotas",
        "Win Rate", "% Gale 1", "% Gale 2", "Volatilidade", "Classificação"
    ]

    # Renderizar tabela
    st.markdown("""
    <style>
    .pair-table {
        border-collapse: collapse;
        width: 100%;
        font-family: "Inter", "Arial", sans-serif;
    }
    .pair-table th {
        background-color: #f7f9fc;
        color: #333;
        padding: 12px;
        text-align: left;
        font-weight: 600;
        border-bottom: 2px solid #e6eef6;
        position: sticky;
        top: 0;
    }
    .pair-table td {
        padding: 10px 12px;
        border-top: 1px solid #f0f4f8;
        color: #333;
    }
    .pair-table tr:hover {
        background-color: #f8f9fa;
    }
    </style>
    """, unsafe_allow_html=True)
    
    html_table = display_df.to_html(index=False, escape=False, classes="pair-table")
    st.markdown(f'<div style="overflow-x: auto; max-height: 600px; padding: 10px; background: #ffffff; border-radius: 8px; border: 1px solid #eef2f6;">{html_table}</div>', unsafe_allow_html=True)

    # ===== RECOMENDAÇÕES =====
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 💡 Recomendações de Trading")
    
    excelentes = pair_analysis[pair_analysis["Classificacao"] == "EXCELENTE"]["pair"].tolist()
    boas = pair_analysis[pair_analysis["Classificacao"] == "BOM"]["pair"].tolist()
    perigosas = pair_analysis[pair_analysis["Classificacao"] == "PERIGOSO"]["pair"].tolist()

    col_rec1, col_rec2 = st.columns(2)
    
    with col_rec1:
        st.markdown("#### ✅ Paridades Recomendadas")
        if excelentes:
            st.success(f"**EXCELENTES ({len(excelentes)}):** {', '.join(excelentes[:5])}" + 
                      (f" e mais {len(excelentes)-5}" if len(excelentes) > 5 else ""))
        if boas:
            st.info(f"**BOAS ({len(boas)}):** {', '.join(boas[:5])}" +
                   (f" e mais {len(boas)-5}" if len(boas) > 5 else ""))
    
    with col_rec2:
        st.markdown("#### ⚠️ Paridades a Evitar")
        if perigosas:
            st.error(f"**PERIGOSAS ({len(perigosas)}):** {', '.join(perigosas)}")
        else:
            st.success("Nenhuma paridade perigosa identificada! 🎉")