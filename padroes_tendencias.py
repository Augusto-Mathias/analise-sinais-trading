# padroes_tendencias.py
import re
from datetime import datetime
from typing import List, Dict
from collections import Counter

import pandas as pd
import streamlit as st

# Regex para mensagens resolvidas
RESOLVED_RE = re.compile(
    r"^(?P<check>[✅❌🃏])(?P<sup>[\u00b9\u00b2\u00b3\d]?)\s*"
    r"(?P<pair>[A-Z0-9\-\_]+(?:-OTC)?)\s*-\s*(?P<time>\d{2}:\d{2}:\d{2})\s*-\s*(?P<tf>\w+)\s*-\s*(?P<dir>\w+)\s*-\s*(?P<r>WIN|LOSS|DOJI)$",
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

DIAS_SEMANA_PT = {
    0: "Segunda",
    1: "Terça",
    2: "Quarta",
    3: "Quinta",
    4: "Sexta",
    5: "Sábado",
    6: "Domingo"
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

def _get_date_from_msg(msg: dict):
    for key in ("date", "message.date"):
        if key in msg:
            val = msg[key]
            if isinstance(val, str):
                try:
                    return datetime.fromisoformat(val.replace("Z", ""))
                except:
                    pass
    return None

def _extract_records(messages: List[dict]) -> List[dict]:
    records = []
    
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
                
                if "r" in m.groupdict():
                    result_raw = m.group("r").strip().upper()
                else:
                    result_raw = m.groups()[-1].strip().upper()
                    
                result = "DOJI" if result_raw == "DOJI" else ("WIN" if result_raw == "WIN" else "LOSS")
                
                msg_date = _get_date_from_msg(msg)
                
                records.append({
                    "pair": pair,
                    "time": time,
                    "tf": tf,
                    "direction": direction,
                    "result": result,
                    "gale_level": gale_level,
                    "msg_date": msg_date,
                })
            except:
                continue
                
    return records

def render_from_json(json_data: dict):
    """
    Renderiza a página de Padrões e Tendências a partir do JSON.
    """
    messages = json_data.get("messages", [])
    records = _extract_records(messages)
    df = pd.DataFrame(records)

    if df.empty:
        st.warning("⚠️ Nenhum dado disponível para análise de padrões.")
        return

    # Filtrar apenas registros com data válida
    df = df[df["msg_date"].notnull()].copy()
    
    if df.empty:
        st.warning("⚠️ Nenhum registro com data válida encontrado.")
        return

    # Adicionar colunas de data
    df["weekday"] = df["msg_date"].dt.weekday
    df["day_name"] = df["weekday"].map(DIAS_SEMANA_PT)
    df["day_of_month"] = df["msg_date"].dt.day

    # ===== RENDERIZAÇÃO =====
    st.markdown("<h1 style='text-align:center; color:#1f4068; margin-bottom:30px;'>📊 Padrões e Tendências</h1>", unsafe_allow_html=True)

    # ===== ANÁLISE POR DIA DA SEMANA =====
    st.markdown("### 📅 Performance por Dia da Semana")
    
    weekday_analysis = df.groupby("weekday").agg(
        Total_Operacoes=("result", "size"),
        WIN=("result", lambda s: (s == "WIN").sum()),
        LOSS=("result", lambda s: (s == "LOSS").sum()),
    ).reset_index()
    
    weekday_analysis["Win_Rate_Pct"] = (
        weekday_analysis["WIN"] / (weekday_analysis["WIN"] + weekday_analysis["LOSS"]) * 100
    ).fillna(0).round(2)
    
    weekday_analysis["Dia_Semana"] = weekday_analysis["weekday"].map(DIAS_SEMANA_PT)
    weekday_analysis = weekday_analysis.sort_values("weekday")
    
    # Gráfico de barras por dia da semana
    st.markdown("#### 📊 Win Rate por Dia da Semana")
    
    max_ops_week = weekday_analysis["Total_Operacoes"].max()
    
    for _, row in weekday_analysis.iterrows():
        pct_bar = (row["Total_Operacoes"] / max_ops_week) * 100
        wr = row["Win_Rate_Pct"]
        
        # Cor baseada no win rate
        if wr >= 85:
            color = "#0b8043"
        elif wr >= 80:
            color = "#1a73e8"
        elif wr >= 75:
            color = "#f9ab00"
        else:
            color = "#d93025"
        
        st.markdown(f"""
        <div style="margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                <span style="font-weight: 600; color: #1f4068; font-size: 14px;">{row['Dia_Semana']}</span>
                <span style="font-weight: 600; color: #666; font-size: 13px;">
                    {int(row['Total_Operacoes']):,} ops | WR: <strong style="color: {color};">{wr:.1f}%</strong>
                </span>
            </div>
            <div style="background: #e8eaed; border-radius: 6px; height: 28px; overflow: hidden;">
                <div style="background: {color}; width: {pct_bar}%; height: 100%; border-radius: 6px; 
                            display: flex; align-items: center; justify-content: center; color: white; 
                            font-size: 13px; font-weight: 600;">
                    {int(row['WIN'])} wins / {int(row['LOSS'])} losses
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Cards de destaque - Melhor e Pior dia
    best_day = weekday_analysis.loc[weekday_analysis["Win_Rate_Pct"].idxmax()]
    worst_day = weekday_analysis.loc[weekday_analysis["Win_Rate_Pct"].idxmin()]
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #0b8043 0%, #12b35a 100%); 
                    border-radius: 12px; padding: 20px; color: white;">
            <div style="font-size: 13px; opacity: 0.9; margin-bottom: 8px;">🏆 MELHOR DIA</div>
            <div style="font-size: 28px; font-weight: 700; margin: 8px 0;">{best_day['Dia_Semana']}</div>
            <div style="font-size: 18px; font-weight: 600; margin-bottom: 8px;">{best_day['Win_Rate_Pct']:.2f}%</div>
            <div style="font-size: 13px; opacity: 0.9;">
                {int(best_day['WIN'])} vitórias em {int(best_day['Total_Operacoes'])} ops
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #d93025 0%, #ea4335 100%); 
                    border-radius: 12px; padding: 20px; color: white;">
            <div style="font-size: 13px; opacity: 0.9; margin-bottom: 8px;">⚠️ PIOR DIA</div>
            <div style="font-size: 28px; font-weight: 700; margin: 8px 0;">{worst_day['Dia_Semana']}</div>
            <div style="font-size: 18px; font-weight: 600; margin-bottom: 8px;">{worst_day['Win_Rate_Pct']:.2f}%</div>
            <div style="font-size: 13px; opacity: 0.9;">
                {int(worst_day['WIN'])} vitórias em {int(worst_day['Total_Operacoes'])} ops
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br><br>", unsafe_allow_html=True)

    # ===== ANÁLISE POR PERÍODO DO MÊS =====
    st.markdown("### 📆 Performance por Período do Mês")
    
    def classify_period(day):
        if day <= 10:
            return "Início (1-10)"
        elif day <= 20:
            return "Meio (11-20)"
        else:
            return "Fim (21-31)"
    
    df["periodo_mes"] = df["day_of_month"].apply(classify_period)
    
    period_analysis = df.groupby("periodo_mes").agg(
        Total_Operacoes=("result", "size"),
        WIN=("result", lambda s: (s == "WIN").sum()),
        LOSS=("result", lambda s: (s == "LOSS").sum()),
    ).reset_index()
    
    period_analysis["Win_Rate_Pct"] = (
        period_analysis["WIN"] / (period_analysis["WIN"] + period_analysis["LOSS"]) * 100
    ).fillna(0).round(2)
    
    # Ordenar por período
    period_order = ["Início (1-10)", "Meio (11-20)", "Fim (21-31)"]
    period_analysis["order"] = period_analysis["periodo_mes"].map({p: i for i, p in enumerate(period_order)})
    period_analysis = period_analysis.sort_values("order")
    
    # Cards de períodos
    cols = st.columns(3)
    
    for idx, (_, row) in enumerate(period_analysis.iterrows()):
        with cols[idx]:
            wr = row["Win_Rate_Pct"]
            if wr >= 85:
                color = "#0b8043"
            elif wr >= 80:
                color = "#1a73e8"
            else:
                color = "#f9ab00"
            
            st.markdown(f"""
            <div style="background: white; border-left: 4px solid {color}; 
                        border-radius: 8px; padding: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                <div style="font-size: 12px; color: #666; font-weight: 600; margin-bottom: 8px;">
                    {row['periodo_mes']}
                </div>
                <div style="font-size: 28px; font-weight: 700; color: {color};">
                    {wr:.2f}%
                </div>
                <div style="font-size: 12px; color: #666; margin-top: 8px;">
                    {int(row['Total_Operacoes']):,} operações<br>
                    {int(row['WIN'])} wins / {int(row['LOSS'])} losses
                </div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ===== ANÁLISE DE TIMEFRAMES =====
    st.markdown("### ⏱️ Performance por Timeframe")
    
    tf_analysis = df.groupby("tf").agg(
        Total_Operacoes=("result", "size"),
        WIN=("result", lambda s: (s == "WIN").sum()),
        LOSS=("result", lambda s: (s == "LOSS").sum()),
    ).reset_index()
    
    tf_analysis["Win_Rate_Pct"] = (
        tf_analysis["WIN"] / (tf_analysis["WIN"] + tf_analysis["LOSS"]) * 100
    ).fillna(0).round(2)
    
    tf_analysis = tf_analysis.sort_values("Total_Operacoes", ascending=False)
    
    # Gráfico de timeframes
    if len(tf_analysis) > 0:
        max_ops_tf = tf_analysis["Total_Operacoes"].max()
        
        for _, row in tf_analysis.head(10).iterrows():
            pct_bar = (row["Total_Operacoes"] / max_ops_tf) * 100
            wr = row["Win_Rate_Pct"]
            
            if wr >= 85:
                color = "#0b8043"
            elif wr >= 80:
                color = "#1a73e8"
            else:
                color = "#f9ab00"
            
            st.markdown(f"""
            <div style="margin-bottom: 12px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                    <span style="font-weight: 600; color: #1f4068;">{row['tf']}</span>
                    <span style="font-weight: 600; color: #666; font-size: 13px;">
                        {int(row['Total_Operacoes']):,} ops | <strong style="color: {color};">{wr:.1f}%</strong>
                    </span>
                </div>
                <div style="background: #e8eaed; border-radius: 4px; height: 24px; overflow: hidden;">
                    <div style="background: {color}; width: {pct_bar}%; height: 100%; border-radius: 4px; 
                                display: flex; align-items: center; padding-left: 8px; color: white; 
                                font-size: 12px; font-weight: 600;">
                        {int(row['WIN'])} / {int(row['LOSS'])}
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ===== ANÁLISE DE DIREÇÕES =====
    st.markdown("### 🔄 Performance por Direção")
    
    dir_analysis = df.groupby("direction").agg(
        Total_Operacoes=("result", "size"),
        WIN=("result", lambda s: (s == "WIN").sum()),
        LOSS=("result", lambda s: (s == "LOSS").sum()),
    ).reset_index()
    
    dir_analysis["Win_Rate_Pct"] = (
        dir_analysis["WIN"] / (dir_analysis["WIN"] + dir_analysis["LOSS"]) * 100
    ).fillna(0).round(2)
    
    col1, col2 = st.columns(2)
    
    for idx, row in dir_analysis.iterrows():
        with col1 if idx == 0 else col2:
            wr = row["Win_Rate_Pct"]
            icon = "📈" if row["direction"].upper() in ["CALL", "UP"] else "📉"
            
            if wr >= 85:
                color = "#0b8043"
            elif wr >= 80:
                color = "#1a73e8"
            else:
                color = "#f9ab00"
            
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, {color} 0%, {color}dd 100%); 
                        border-radius: 12px; padding: 20px; color: white;">
                <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">
                    {icon} {row['direction'].upper()}
                </div>
                <div style="font-size: 32px; font-weight: 700; margin: 8px 0;">
                    {wr:.2f}%
                </div>
                <div style="font-size: 13px; opacity: 0.9;">
                    {int(row['Total_Operacoes']):,} operações<br>
                    {int(row['WIN'])} wins / {int(row['LOSS'])} losses
                </div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ===== TABELAS COMPLETAS =====
    st.markdown("### 📋 Tabelas Detalhadas")
    
    tab1, tab2 = st.tabs(["📅 Por Dia da Semana", "📆 Por Período do Mês"])
    
    with tab1:
        display_week = weekday_analysis[["Dia_Semana", "Total_Operacoes", "WIN", "LOSS", "Win_Rate_Pct"]].copy()
        display_week.columns = ["Dia da Semana", "Total Ops", "WIN", "LOSS", "Win Rate"]
        display_week["Total Ops"] = display_week["Total Ops"].apply(lambda x: f"{int(x):,}")
        display_week["WIN"] = display_week["WIN"].apply(lambda x: f"{int(x):,}")
        display_week["LOSS"] = display_week["LOSS"].apply(lambda x: f"{int(x):,}")
        display_week["Win Rate"] = display_week["Win Rate"].apply(lambda x: f"{x:.2f}%")
        
        st.markdown("""
        <style>
        .pattern-table {
            border-collapse: collapse;
            width: 100%;
            font-family: "Inter", "Arial", sans-serif;
        }
        .pattern-table th {
            background-color: #f7f9fc;
            color: #333;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            border-bottom: 2px solid #e6eef6;
        }
        .pattern-table td {
            padding: 10px 12px;
            border-top: 1px solid #f0f4f8;
            color: #333;
        }
        .pattern-table tr:hover {
            background-color: #f8f9fa;
        }
        </style>
        """, unsafe_allow_html=True)
        
        html_week = display_week.to_html(index=False, escape=False, classes="pattern-table")
        st.markdown(f'<div style="overflow-x: auto; padding: 10px; background: #ffffff; border-radius: 8px; border: 1px solid #eef2f6;">{html_week}</div>', unsafe_allow_html=True)
    
    with tab2:
        display_period = period_analysis[["periodo_mes", "Total_Operacoes", "WIN", "LOSS", "Win_Rate_Pct"]].copy()
        display_period.columns = ["Período", "Total Ops", "WIN", "LOSS", "Win Rate"]
        display_period["Total Ops"] = display_period["Total Ops"].apply(lambda x: f"{int(x):,}")
        display_period["WIN"] = display_period["WIN"].apply(lambda x: f"{int(x):,}")
        display_period["LOSS"] = display_period["LOSS"].apply(lambda x: f"{int(x):,}")
        display_period["Win Rate"] = display_period["Win Rate"].apply(lambda x: f"{x:.2f}%")
        
        html_period = display_period.to_html(index=False, escape=False, classes="pattern-table")
        st.markdown(f'<div style="overflow-x: auto; padding: 10px; background: #ffffff; border-radius: 8px; border: 1px solid #eef2f6;">{html_period}</div>', unsafe_allow_html=True)

    # ===== INSIGHTS =====
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 💡 Insights Identificados")
    
    # Insights automáticos
    diff_weekday = weekday_analysis["Win_Rate_Pct"].max() - weekday_analysis["Win_Rate_Pct"].min()
    if diff_weekday > 5:
        st.warning(f"⚠️ **Variação significativa entre dias da semana**: Diferença de {diff_weekday:.1f}% entre melhor e pior dia. Considere focar nos dias com melhor performance.")
    else:
        st.success("✅ **Consistência entre dias**: Performance estável ao longo da semana, com variação de apenas {diff_weekday:.1f}%.")
    
    # Insight de período
    best_period = period_analysis.loc[period_analysis["Win_Rate_Pct"].idxmax()]
    st.info(f"📆 **Melhor período do mês**: {best_period['periodo_mes']} com {best_period['Win_Rate_Pct']:.2f}% de win rate.")