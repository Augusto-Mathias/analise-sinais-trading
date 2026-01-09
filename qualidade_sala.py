# qualidade_sala.py
import re
from datetime import datetime, timedelta
from typing import List, Dict

import pandas as pd
import streamlit as st

# Regex para mensagens resolvidas no formato:
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

def _get_date_from_msg(msg: dict):
    for key in ("date", "message.date", "message.date_unixtime", "message.date_unixtime_ms"):
        if key in msg:
            val = msg[key]
            if isinstance(val, (int, float)):
                if val > 1e12:
                    return datetime.fromtimestamp(val / 1000.0)
                return datetime.fromtimestamp(val)
            if isinstance(val, str):
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(val, fmt)
                    except:
                        pass
    return None

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
            sup = m.group("sup") or ""
            gale_level = _sup_to_level(sup)
            pair = m.group("pair").strip()
            time = m.group("time").strip()
            tf = m.group("tf").strip()
            direction = m.group("dir").strip()
            result_raw = m.group("result").strip().upper()
            result = "DOJI" if result_raw == "DOJI" else ("WIN" if result_raw == "WIN" else "LOSS")
            payout = signals.get((pair, time))
            dt = _get_date_from_msg(msg)
            records.append({
                "pair": pair,
                "time": time,
                "hour": int(time.split(":")[0]) if time else None,
                "tf": tf,
                "direction": direction,
                "result": result,
                "gale_level": gale_level,
                "payout": payout,
                "msg_date": dt
            })
    return records

def _safe_div(a, b):
    return (a / b) if (b and b != 0) else 0.0

def render_from_json(json_data: dict):
    """
    Renderiza a página Qualidade da Sala a partir do JSON.
    """
    messages = json_data.get("messages", [])
    records = _extract_records(messages)
    df = pd.DataFrame(records)

    dates = [r["msg_date"].date() for r in records if r.get("msg_date") is not None]
    if dates:
        start = min(dates)
        end = max(dates)
        total_days = (end - start).days + 1
    else:
        start = end = None
        total_days = 0

    total_operations = len(df)
    wins = int((df["result"] == "WIN").sum()) if not df.empty else 0
    losses = int((df["result"] == "LOSS").sum()) if not df.empty else 0
    dojis = int((df["result"] == "DOJI").sum()) if not df.empty else 0

    total_g0 = int((df["gale_level"] == 0).sum()) if not df.empty else 0
    total_g1 = int((df["gale_level"] == 1).sum()) if not df.empty else 0
    total_g2 = int((df["gale_level"] == 2).sum()) if not df.empty else 0

    wins_g0 = int(df[(df["gale_level"] == 0) & (df["result"] == "WIN")].shape[0]) if not df.empty else 0
    wins_g1 = int(df[(df["gale_level"] == 1) & (df["result"] == "WIN")].shape[0]) if not df.empty else 0
    wins_g2 = int(df[(df["gale_level"] == 2) & (df["result"] == "WIN")].shape[0]) if not df.empty else 0

    resolved_ops = wins + losses
    win_rate_bruto_pct = round(_safe_div(wins, resolved_ops) * 100.0, 2) if resolved_ops > 0 else 0.0

    win_rate_g0_pct = round(_safe_div(wins_g0, total_g0) * 100.0, 2) if total_g0 > 0 else 0.0
    win_rate_g1_pct = round(_safe_div(wins_g1, total_g1) * 100.0, 2) if total_g1 > 0 else 0.0
    win_rate_g2_pct = round(_safe_div(wins_g2, total_g2) * 100.0, 2) if total_g2 > 0 else 0.0

    ops_resolved_at_entry_pct = round(_safe_div(total_g0, total_operations) * 100.0, 2) if total_operations > 0 else 0.0
    ops_needed_g1_pct = round(_safe_div(total_g1, total_operations) * 100.0, 2) if total_operations > 0 else 0.0
    ops_needed_g2_pct = round(_safe_div(total_g2, total_operations) * 100.0, 2) if total_operations > 0 else 0.0

    # Tendência
    tendencia = "N/A"
    tendencia_color = "#666"
    if win_rate_bruto_pct >= 85:
        tendencia = "EXCELENTE"
        tendencia_color = "#0b8043"
    elif win_rate_bruto_pct >= 75:
        tendencia = "BOM"
        tendencia_color = "#1a73e8"
    elif win_rate_bruto_pct >= 65:
        tendencia = "REGULAR"
        tendencia_color = "#f9ab00"
    else:
        tendencia = "ALERTA"
        tendencia_color = "#d93025"

    # ===== RENDERIZAÇÃO =====
    st.markdown("<h1 style='text-align:center; color:#1f4068; margin-bottom:30px;'>📊 Qualidade da Sala — Análise Completa</h1>", unsafe_allow_html=True)

    # Cards de métricas principais
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                    border-radius: 12px; padding: 20px; color: white; text-align: center;">
            <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">PERÍODO ANALISADO</div>
            <div style="font-size: 20px; font-weight: 700;">{total_days} dias</div>
            <div style="font-size: 12px; opacity: 0.8; margin-top: 8px;">
                {start.strftime("%d/%m/%Y") if start else "—"} a {end.strftime("%d/%m/%Y") if end else "—"}
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                    border-radius: 12px; padding: 20px; color: white; text-align: center;">
            <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">TOTAL DE OPERAÇÕES</div>
            <div style="font-size: 28px; font-weight: 700;">{total_operations:,}</div>
            <div style="font-size: 12px; opacity: 0.8; margin-top: 8px;">Ciclos completos</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                    border-radius: 12px; padding: 20px; color: white; text-align: center;">
            <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">WIN RATE BRUTO</div>
            <div style="font-size: 28px; font-weight: 700;">{win_rate_bruto_pct:.2f}%</div>
            <div style="font-size: 12px; opacity: 0.8; margin-top: 8px;">{wins:,} WIN / {losses:,} LOSS</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                    border-radius: 12px; padding: 20px; color: white; text-align: center;">
            <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">TENDÊNCIA</div>
            <div style="font-size: 24px; font-weight: 700;">{tendencia}</div>
            <div style="font-size: 12px; opacity: 0.8; margin-top: 8px;">Classificação geral</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ===== ANÁLISE DE GALES =====
    st.markdown("### 🎯 Análise de Gales")
    
    col_g1, col_g2, col_g3 = st.columns(3)
    
    with col_g1:
        st.markdown(f"""
        <div style="background: #f8f9fa; border-left: 4px solid #0b8043; 
                    border-radius: 8px; padding: 16px;">
            <div style="font-size: 13px; color: #666; font-weight: 600;">SEM GALE (G0)</div>
            <div style="font-size: 24px; font-weight: 700; color: #1f4068; margin: 8px 0;">
                {win_rate_g0_pct:.2f}%
            </div>
            <div style="font-size: 13px; color: #666;">
                {wins_g0:,} vitórias em {total_g0:,} ops ({ops_resolved_at_entry_pct:.1f}%)
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col_g2:
        st.markdown(f"""
        <div style="background: #f8f9fa; border-left: 4px solid #1a73e8; 
                    border-radius: 8px; padding: 16px;">
            <div style="font-size: 13px; color: #666; font-weight: 600;">GALE 1</div>
            <div style="font-size: 24px; font-weight: 700; color: #1f4068; margin: 8px 0;">
                {win_rate_g1_pct:.2f}%
            </div>
            <div style="font-size: 13px; color: #666;">
                {wins_g1:,} vitórias em {total_g1:,} ops ({ops_needed_g1_pct:.1f}%)
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col_g3:
        st.markdown(f"""
        <div style="background: #f8f9fa; border-left: 4px solid #f9ab00; 
                    border-radius: 8px; padding: 16px;">
            <div style="font-size: 13px; color: #666; font-weight: 600;">GALE 2</div>
            <div style="font-size: 24px; font-weight: 700; color: #1f4068; margin: 8px 0;">
                {win_rate_g2_pct:.2f}%
            </div>
            <div style="font-size: 13px; color: #666;">
                {wins_g2:,} vitórias em {total_g2:,} ops ({ops_needed_g2_pct:.1f}%)
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ===== TABELA SEMANAL =====
    st.markdown("### 📅 Desempenho Semanal")
    
    df_dates = df.copy()
    df_dates = df_dates[df_dates["msg_date"].notnull()].copy()
    
    if df_dates.empty:
        st.warning("⚠️ Sem dados com timestamp válido para montar a tabela semanal.")
        return

    df_dates["iso_year"] = df_dates["msg_date"].dt.isocalendar().year
    df_dates["iso_week"] = df_dates["msg_date"].dt.isocalendar().week
    df_dates["date_only"] = df_dates["msg_date"].dt.date

    weekly = df_dates.groupby(["iso_year", "iso_week"]).agg(
        Data_Inicio=("date_only", "min"),
        Data_Fim=("date_only", "max"),
        Total_Operacoes=("result", "size"),
        WIN=("result", lambda s: (s == "WIN").sum()),
        LOSS=("result", lambda s: (s == "LOSS").sum())
    ).reset_index()

    weekly["Win_Rate"] = weekly.apply(
        lambda r: _safe_div(r['WIN'], (r['WIN'] + r['LOSS'])) * 100, axis=1
    )
    
    # Formatar datas
    weekly["Data_Inicio"] = weekly["Data_Inicio"].apply(lambda d: d.strftime("%d/%m/%Y"))
    weekly["Data_Fim"] = weekly["Data_Fim"].apply(lambda d: d.strftime("%d/%m/%Y"))
    
    # Colorir Win Rate
    def color_win_rate(val):
        if val >= 85:
            return f'<span style="color: #0b8043; font-weight: 700;">{val:.2f}%</span>'
        elif val >= 75:
            return f'<span style="color: #1a73e8; font-weight: 600;">{val:.2f}%</span>'
        elif val >= 65:
            return f'<span style="color: #f9ab00; font-weight: 600;">{val:.2f}%</span>'
        else:
            return f'<span style="color: #d93025; font-weight: 600;">{val:.2f}%</span>'
    
    weekly["Win Rate (%)"] = weekly["Win_Rate"].apply(color_win_rate)
    
    # Renomear colunas
    weekly_display = weekly[[
        "iso_year", "iso_week", "Data_Inicio", "Data_Fim", 
        "Total_Operacoes", "WIN", "LOSS", "Win Rate (%)"
    ]].copy()
    
    weekly_display.columns = [
        "Ano", "Semana", "Início", "Fim", 
        "Total Ops", "Vitórias", "Derrotas", "Win Rate"
    ]
    
    # Renderizar com estilo
    html_table = weekly_display.to_html(index=False, escape=False, classes="styled-table")
    st.markdown(f"""
    <div style="overflow-x: auto; padding: 10px; background: #ffffff; 
                border-radius: 8px; border: 1px solid #eef2f6;">
        {html_table}
    </div>
    """, unsafe_allow_html=True)