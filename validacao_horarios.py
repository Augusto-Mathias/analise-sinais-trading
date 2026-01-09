# validacao_horarios.py
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
    
    # Primeira passagem: coletar payouts
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

    # Segunda passagem: extrair operações resolvidas
    for msg in messages:
        text = _get_text_from_msg(msg)
        if not text:
            continue
        one_line = " ".join(text.splitlines()).strip()
        m = RESOLVED_RE.match(one_line)
        if m:
            sup = m.group("sup") or ""
            gale_level = _sup_to_level(sup)
            pair = m.group("pair").strip()
            time = m.group("time").strip()
            tf = m.group("tf").strip()
            direction = m.group("dir").strip()
            result_raw = m.group("result").strip().upper()
            result = "DOJI" if result_raw == "DOJI" else ("WIN" if result_raw == "WIN" else "LOSS")
            payout = signals.get((pair, time))
            
            # Extrair hora
            hour = int(time.split(":")[0]) if time else None
            
            records.append({
                "pair": pair,
                "time": time,
                "hour": hour,
                "tf": tf,
                "direction": direction,
                "result": result,
                "gale_level": gale_level,
                "payout": payout,
            })
    return records

def _calculate_volatility(wins, total_ops):
    """
    Calcula volatilidade como a consistência das vitórias.
    Quanto mais próximo de 100%, mais estável é o horário.
    """
    if total_ops == 0:
        return 0.0
    win_rate = wins / total_ops
    # Volatilidade baseada na taxa de acerto
    # Win rate alto = alta volatilidade (mais vitórias)
    volatility = win_rate * 100.0
    return volatility

def _classify_hour(win_rate_pct, volatility_pct):
    """
    Classifica o horário baseado no win rate e volatilidade.
    """
    if win_rate_pct >= 88 and volatility_pct >= 78:
        return "EXCELENTE", "#0b8043"
    elif win_rate_pct >= 85 and volatility_pct >= 74:
        return "BOM", "#1a73e8"
    elif win_rate_pct >= 82 and volatility_pct >= 68:
        return "OK", "#f9ab00"
    else:
        return "RUIM", "#d93025"

def render_from_json(json_data: dict):
    """
    Renderiza a página de Validação de Horários a partir do JSON.
    """
    messages = json_data.get("messages", [])
    records = _extract_records(messages)
    df = pd.DataFrame(records)

    if df.empty:
        st.warning("⚠️ Nenhum dado disponível para análise de horários.")
        return

    # Agrupar por hora
    hourly_analysis = df.groupby("hour").agg(
        Total_Operacoes=("result", "size"),
        WIN=("result", lambda s: (s == "WIN").sum()),
        LOSS=("result", lambda s: (s == "LOSS").sum()),
        DOJI=("result", lambda s: (s == "DOJI").sum()),
    ).reset_index()

    # Calcular métricas
    hourly_analysis["Win_Rate_Pct"] = (
        hourly_analysis["WIN"] / (hourly_analysis["WIN"] + hourly_analysis["LOSS"]) * 100
    ).fillna(0).round(2)
    
    hourly_analysis["Volatilidade_Pct"] = hourly_analysis.apply(
        lambda row: _calculate_volatility(row["WIN"], row["Total_Operacoes"]), axis=1
    ).round(2)

    # Classificação
    hourly_analysis[["Classificacao", "Cor"]] = hourly_analysis.apply(
        lambda row: pd.Series(_classify_hour(row["Win_Rate_Pct"], row["Volatilidade_Pct"])),
        axis=1
    )

    # Criar faixa horária formatada
    hourly_analysis["Faixa_Horaria"] = hourly_analysis["hour"].apply(
        lambda h: f"{int(h):02d}:00-{int(h)+1:02d}:00"
    )

    # Ordenar por hora
    hourly_analysis = hourly_analysis.sort_values("hour")

    # ===== RENDERIZAÇÃO =====
    st.markdown("<h1 style='text-align:center; color:#1f4068; margin-bottom:30px;'>⏰ Validação de Horários</h1>", unsafe_allow_html=True)

    # Cards resumo
    total_hours = len(hourly_analysis)
    excelente_count = (hourly_analysis["Classificacao"] == "EXCELENTE").sum()
    bom_count = (hourly_analysis["Classificacao"] == "BOM").sum()
    ok_count = (hourly_analysis["Classificacao"] == "OK").sum()
    ruim_count = (hourly_analysis["Classificacao"] == "RUIM").sum()
    
    best_hour = hourly_analysis.loc[hourly_analysis["Win_Rate_Pct"].idxmax()]
    worst_hour = hourly_analysis.loc[hourly_analysis["Win_Rate_Pct"].idxmin()]

    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #0b8043 0%, #12b35a 100%); 
                    border-radius: 12px; padding: 20px; color: white; text-align: center;">
            <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">HORÁRIOS EXCELENTES</div>
            <div style="font-size: 32px; font-weight: 700;">{excelente_count}</div>
            <div style="font-size: 12px; opacity: 0.8; margin-top: 8px;">≥88% Win Rate</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #1a73e8 0%, #4285f4 100%); 
                    border-radius: 12px; padding: 20px; color: white; text-align: center;">
            <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">HORÁRIOS BONS</div>
            <div style="font-size: 32px; font-weight: 700;">{bom_count}</div>
            <div style="font-size: 12px; opacity: 0.8; margin-top: 8px;">85-87% Win Rate</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #f9ab00 0%, #fbc02d 100%); 
                    border-radius: 12px; padding: 20px; color: white; text-align: center;">
            <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">HORÁRIOS OK</div>
            <div style="font-size: 32px; font-weight: 700;">{ok_count}</div>
            <div style="font-size: 12px; opacity: 0.8; margin-top: 8px;">82-84% Win Rate</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #d93025 0%, #ea4335 100%); 
                    border-radius: 12px; padding: 20px; color: white; text-align: center;">
            <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">HORÁRIOS RUINS</div>
            <div style="font-size: 32px; font-weight: 700;">{ruim_count}</div>
            <div style="font-size: 12px; opacity: 0.8; margin-top: 8px;"><82% Win Rate</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Destaques
    col_best, col_worst = st.columns(2)
    
    with col_best:
        st.markdown(f"""
        <div style="background: #e8f5e9; border-left: 4px solid #0b8043; 
                    border-radius: 8px; padding: 20px;">
            <div style="font-size: 14px; color: #0b8043; font-weight: 700; margin-bottom: 8px;">
                🏆 MELHOR HORÁRIO
            </div>
            <div style="font-size: 24px; font-weight: 700; color: #1f4068;">
                {best_hour['Faixa_Horaria']}
            </div>
            <div style="font-size: 14px; color: #666; margin-top: 8px;">
                Win Rate: <strong>{best_hour['Win_Rate_Pct']:.2f}%</strong> | 
                {int(best_hour['WIN'])} vitórias em {int(best_hour['Total_Operacoes'])} ops
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col_worst:
        st.markdown(f"""
        <div style="background: #fce4ec; border-left: 4px solid #d93025; 
                    border-radius: 8px; padding: 20px;">
            <div style="font-size: 14px; color: #d93025; font-weight: 700; margin-bottom: 8px;">
                ⚠️ PIOR HORÁRIO
            </div>
            <div style="font-size: 24px; font-weight: 700; color: #1f4068;">
                {worst_hour['Faixa_Horaria']}
            </div>
            <div style="font-size: 14px; color: #666; margin-top: 8px;">
                Win Rate: <strong>{worst_hour['Win_Rate_Pct']:.2f}%</strong> | 
                {int(worst_hour['WIN'])} vitórias em {int(worst_hour['Total_Operacoes'])} ops
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ===== TABELA DETALHADA =====
    st.markdown("### 📊 Análise Detalhada por Horário")

    # Preparar tabela para exibição
    display_df = hourly_analysis[[
        "Faixa_Horaria", "Total_Operacoes", "WIN", "LOSS", 
        "Win_Rate_Pct", "Volatilidade_Pct", "Classificacao"
    ]].copy()

    # Formatar colunas
    display_df["Total_Operacoes"] = display_df["Total_Operacoes"].apply(lambda x: f"{int(x):,}")
    display_df["WIN"] = display_df["WIN"].apply(lambda x: f"{int(x):,}")
    display_df["LOSS"] = display_df["LOSS"].apply(lambda x: f"{int(x):,}")
    display_df["Win_Rate_Pct"] = display_df["Win_Rate_Pct"].apply(lambda x: f"{x:.2f}%")
    display_df["Volatilidade_Pct"] = display_df["Volatilidade_Pct"].apply(lambda x: f"{x:.2f}%")

    # Colorir classificação
    def color_classification(row):
        classif = row["Classificacao"]
        if classif == "EXCELENTE":
            return f'<span style="color: #0b8043; font-weight: 700;">✓ {classif}</span>'
        elif classif == "BOM":
            return f'<span style="color: #1a73e8; font-weight: 700;">● {classif}</span>'
        elif classif == "OK":
            return f'<span style="color: #f9ab00; font-weight: 600;">◐ {classif}</span>'
        else:
            return f'<span style="color: #d93025; font-weight: 600;">✗ {classif}</span>'

    display_df["Classificacao"] = display_df.apply(color_classification, axis=1)

    # Renomear colunas
    display_df.columns = [
        "Faixa Horária", "Total Ops", "Vitórias", "Derrotas",
        "Win Rate", "Volatilidade", "Classificação"
    ]

    # Renderizar tabela com estilo usando função helper
    st.markdown("""
    <style>
    .styled-table {
        border-collapse: collapse;
        width: 100%;
        font-family: "Inter", "Arial", sans-serif;
    }
    .styled-table th {
        background-color: #f7f9fc;
        color: #333;
        padding: 12px;
        text-align: left;
        font-weight: 600;
        border-bottom: 2px solid #e6eef6;
    }
    .styled-table td {
        padding: 10px 12px;
        border-top: 1px solid #f0f4f8;
        color: #333;
    }
    .styled-table tr:hover {
        background-color: #f8f9fa;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Converter para HTML e renderizar
    html_table = display_df.to_html(index=False, escape=False, classes="styled-table")
    st.markdown(f'<div style="overflow-x: auto; padding: 10px; background: #ffffff; border-radius: 8px; border: 1px solid #eef2f6;">{html_table}</div>', unsafe_allow_html=True)

    # ===== RECOMENDAÇÕES =====
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 💡 Recomendações")
    
    excelentes = hourly_analysis[hourly_analysis["Classificacao"] == "EXCELENTE"]["Faixa_Horaria"].tolist()
    bons = hourly_analysis[hourly_analysis["Classificacao"] == "BOM"]["Faixa_Horaria"].tolist()
    ruins = hourly_analysis[hourly_analysis["Classificacao"] == "RUIM"]["Faixa_Horaria"].tolist()

    col_rec1, col_rec2 = st.columns(2)
    
    with col_rec1:
        st.markdown("#### ✅ Horários Recomendados")
        if excelentes:
            st.success(f"**EXCELENTES:** {', '.join(excelentes)}")
        if bons:
            st.info(f"**BONS:** {', '.join(bons)}")
    
    with col_rec2:
        st.markdown("#### ⚠️ Horários a Evitar")
        if ruins:
            st.error(f"**RUINS:** {', '.join(ruins)}")
        else:
            st.success("Nenhum horário ruim identificado! 🎉")