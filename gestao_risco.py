# gestao_risco.py
import re
from datetime import datetime
from typing import List, Dict
import math

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
                
                if "r" in m.groupdict():
                    result_raw = m.group("r").strip().upper()
                else:
                    result_raw = m.groups()[-1].strip().upper()
                    
                result = "DOJI" if result_raw == "DOJI" else ("WIN" if result_raw == "WIN" else "LOSS")
                
                records.append({
                    "result": result,
                    "gale_level": gale_level,
                })
            except:
                continue
                
    return records

def calculate_profit(result: str, gale_level: int, stakes: List[float], payout: float = 0.85):
    """Calcula lucro/perda de uma operação"""
    if result == "DOJI":
        return 0.0
    
    level = min(gale_level, len(stakes) - 1)
    
    if result == "WIN":
        if level == 0:
            return stakes[0] * payout
        else:
            lost = sum(stakes[:level])
            win_amount = stakes[level] * payout
            return -lost + win_amount
    else:  # LOSS
        return -sum(stakes[:level + 1])

def simulate_equity_curve(records: List[dict], capital: float, stakes: List[float], payout: float = 0.85):
    """Simula curva de capital ao longo do tempo"""
    equity = [capital]
    current = capital
    
    for rec in records:
        profit = calculate_profit(rec["result"], rec["gale_level"], stakes, payout)
        current += profit
        equity.append(current)
    
    return equity

def render_from_json(json_data: dict):
    """
    Renderiza a página de Gestão de Risco a partir do JSON.
    """
    messages = json_data.get("messages", [])
    records = _extract_records(messages)
    df = pd.DataFrame(records)

    if df.empty:
        st.warning("⚠️ Nenhum dado disponível para análise de risco.")
        return

    # ===== PARÂMETROS PADRÃO =====
    capital_inicial = 500.0
    payout_minimo = 0.85
    
    # Stakes - Ciclo 1
    stake_c1_g0 = 2.0
    stake_c1_g1 = 4.3
    stake_c1_g2 = 9.24
    stakes_c1 = [stake_c1_g0, stake_c1_g1, stake_c1_g2]
    
    # Stakes - Ciclo 2 (2x)
    stake_c2_g0 = 19.86
    stake_c2_g1 = 42.69
    stake_c2_g2 = 91.76
    stakes_c2 = [stake_c2_g0, stake_c2_g1, stake_c2_g2]

    # ===== CÁLCULOS =====
    total_ops = len(df)
    wins = len(df[df["result"] == "WIN"])
    losses = len(df[df["result"] == "LOSS"])
    win_rate = (wins / (wins + losses)) if (wins + losses) > 0 else 0
    loss_rate = 1 - win_rate
    
    # Simular curva de capital
    equity_curve = simulate_equity_curve(records, capital_inicial, stakes_c1, payout_minimo)
    
    # Drawdown
    peak = capital_inicial
    max_dd = 0
    max_dd_pct = 0
    min_balance = capital_inicial
    
    for balance in equity_curve:
        if balance > peak:
            peak = balance
        dd = peak - balance
        dd_pct = (dd / peak * 100) if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct
        if balance < min_balance:
            min_balance = balance
    
    final_balance = equity_curve[-1]
    
    # Probabilidades de sequências de loss
    prob_2_loss = loss_rate ** 2 * 100
    prob_3_loss = loss_rate ** 3 * 100
    prob_4_loss = loss_rate ** 4 * 100
    prob_5_loss = loss_rate ** 5 * 100
    
    # Capital mínimo recomendado (baseado em risco de 3 losses seguidos)
    max_loss_c1 = sum(stakes_c1)  # Perder todo o ciclo 1
    capital_min_recomendado = max_loss_c1 * 5  # 5x o risco máximo
    
    # Status do capital
    if capital_inicial >= capital_min_recomendado:
        status_capital = "ADEQUADO"
        status_color = "#0b8043"
    elif capital_inicial >= capital_min_recomendado * 0.7:
        status_capital = "ACEITÁVEL"
        status_color = "#f9ab00"
    else:
        status_capital = "INSUFICIENTE"
        status_color = "#d93025"
    
    # Lucro médio por operação
    profits = [calculate_profit(r["result"], r["gale_level"], stakes_c1, payout_minimo) for r in records]
    lucro_medio = sum(profits) / len(profits) if profits else 0
    
    # Projeções mensais (assumindo 22 dias úteis)
    ops_por_dia = total_ops / 30 if total_ops > 0 else 10  # estimativa
    
    lucro_diario_atual = sum(profits) / 30 if len(profits) > 0 else 0
    proj_otimista = lucro_diario_atual * 22 * 1.5
    proj_realista = lucro_diario_atual * 22
    proj_pessimista = lucro_diario_atual * 22 * 0.7

    # ===== RENDERIZAÇÃO =====
    st.markdown("<h1 style='text-align:center; color:#1f4068; margin-bottom:30px;'>🛡️ Gestão de Risco</h1>", unsafe_allow_html=True)

    # ===== CARDS PRINCIPAIS =====
    st.markdown("### 💰 Configuração de Capital e Stakes")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                    border-radius: 12px; padding: 20px; color: white; text-align: center;">
            <div style="font-size: 13px; opacity: 0.9; margin-bottom: 8px;">💵 CAPITAL INICIAL</div>
            <div style="font-size: 28px; font-weight: 700; margin: 8px 0;">R$ {capital_inicial:.2f}</div>
            <div style="font-size: 12px; opacity: 0.8;">Banca inicial</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #0b8043 0%, #12b35a 100%); 
                    border-radius: 12px; padding: 20px; color: white; text-align: center;">
            <div style="font-size: 13px; opacity: 0.9; margin-bottom: 8px;">💵 SALDO FINAL</div>
            <div style="font-size: 28px; font-weight: 700; margin: 8px 0;">R$ {final_balance:.2f}</div>
            <div style="font-size: 12px; opacity: 0.8;">Após {total_ops} ops</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #1a73e8 0%, #4285f4 100%); 
                    border-radius: 12px; padding: 20px; color: white; text-align: center;">
            <div style="font-size: 13px; opacity: 0.9; margin-bottom: 8px;">📈 LUCRO TOTAL</div>
            <div style="font-size: 28px; font-weight: 700; margin: 8px 0;">R$ {final_balance - capital_inicial:.2f}</div>
            <div style="font-size: 12px; opacity: 0.8;">{((final_balance/capital_inicial - 1) * 100):.1f}% ROI</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #f9ab00 0%, #fbc02d 100%); 
                    border-radius: 12px; padding: 20px; color: white; text-align: center;">
            <div style="font-size: 13px; opacity: 0.9; margin-bottom: 8px;">💎 PAYOUT</div>
            <div style="font-size: 28px; font-weight: 700; margin: 8px 0;">{payout_minimo * 100:.0f}%</div>
            <div style="font-size: 12px; opacity: 0.8;">Mínimo usado</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ===== STAKES =====
    st.markdown("### 🎯 Estrutura de Stakes")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        <div style="background: white; border: 2px solid #667eea; border-radius: 12px; padding: 20px;">
            <div style="font-size: 16px; font-weight: 700; color: #667eea; margin-bottom: 16px;">
                📊 CICLO 1 (Conservador)
            </div>
        """, unsafe_allow_html=True)
        
        st.markdown(f"""
            <div style="margin-bottom: 12px;">
                <div style="font-size: 13px; color: #666; font-weight: 600;">Entrada Base (G0)</div>
                <div style="font-size: 24px; font-weight: 700; color: #0b8043;">R$ {stake_c1_g0:.2f}</div>
            </div>
            <div style="margin-bottom: 12px;">
                <div style="font-size: 13px; color: #666; font-weight: 600;">Gale 1</div>
                <div style="font-size: 24px; font-weight: 700; color: #1a73e8;">R$ {stake_c1_g1:.2f}</div>
            </div>
            <div style="margin-bottom: 12px;">
                <div style="font-size: 13px; color: #666; font-weight: 600;">Gale 2</div>
                <div style="font-size: 24px; font-weight: 700; color: #f9ab00;">R$ {stake_c1_g2:.2f}</div>
            </div>
            <div style="border-top: 2px solid #eee; padding-top: 12px; margin-top: 12px;">
                <div style="font-size: 13px; color: #666;">Risco Máximo do Ciclo</div>
                <div style="font-size: 20px; font-weight: 700; color: #d93025;">R$ {sum(stakes_c1):.2f}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("""
        <div style="background: white; border: 2px solid #f9ab00; border-radius: 12px; padding: 20px;">
            <div style="font-size: 16px; font-weight: 700; color: #f9ab00; margin-bottom: 16px;">
                🚀 CICLO 2 (Agressivo)
            </div>
        """, unsafe_allow_html=True)
        
        st.markdown(f"""
            <div style="margin-bottom: 12px;">
                <div style="font-size: 13px; color: #666; font-weight: 600;">Entrada Base (G0)</div>
                <div style="font-size: 24px; font-weight: 700; color: #0b8043;">R$ {stake_c2_g0:.2f}</div>
            </div>
            <div style="margin-bottom: 12px;">
                <div style="font-size: 13px; color: #666; font-weight: 600;">Gale 1</div>
                <div style="font-size: 24px; font-weight: 700; color: #1a73e8;">R$ {stake_c2_g1:.2f}</div>
            </div>
            <div style="margin-bottom: 12px;">
                <div style="font-size: 13px; color: #666; font-weight: 600;">Gale 2</div>
                <div style="font-size: 24px; font-weight: 700; color: #f9ab00;">R$ {stake_c2_g2:.2f}</div>
            </div>
            <div style="border-top: 2px solid #eee; padding-top: 12px; margin-top: 12px;">
                <div style="font-size: 13px; color: #666;">Risco Máximo do Ciclo</div>
                <div style="font-size: 20px; font-weight: 700; color: #d93025;">R$ {sum(stakes_c2):.2f}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ===== DRAWDOWN E RISCO =====
    st.markdown("### 📉 Análise de Drawdown")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown(f"""
        <div style="background: #fce4ec; border-left: 4px solid #d93025; 
                    border-radius: 8px; padding: 16px;">
            <div style="font-size: 13px; color: #666; font-weight: 600;">Drawdown Máximo (R$)</div>
            <div style="font-size: 28px; font-weight: 700; color: #d93025; margin: 8px 0;">
                R$ {max_dd:.2f}
            </div>
            <div style="font-size: 12px; color: #666;">Maior perda acumulada</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div style="background: #fce4ec; border-left: 4px solid #d93025; 
                    border-radius: 8px; padding: 16px;">
            <div style="font-size: 13px; color: #666; font-weight: 600;">Drawdown Máximo (%)</div>
            <div style="font-size: 28px; font-weight: 700; color: #d93025; margin: 8px 0;">
                {max_dd_pct:.2f}%
            </div>
            <div style="font-size: 12px; color: #666;">% do capital</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div style="background: #fce4ec; border-left: 4px solid #d93025; 
                    border-radius: 8px; padding: 16px;">
            <div style="font-size: 13px; color: #666; font-weight: 600;">Saldo Mínimo</div>
            <div style="font-size: 28px; font-weight: 700; color: #d93025; margin: 8px 0;">
                R$ {min_balance:.2f}
            </div>
            <div style="font-size: 12px; color: #666;">Menor saldo atingido</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ===== PROBABILIDADES =====
    st.markdown("### 🎲 Probabilidades de Sequências de Loss")
    
    cols = st.columns(4)
    
    probs = [
        ("2 LOSS seguidos", prob_2_loss, "⚠️"),
        ("3 LOSS seguidos", prob_3_loss, "⚠️⚠️"),
        ("4 LOSS seguidos", prob_4_loss, "🚨"),
        ("5 LOSS seguidos", prob_5_loss, "🚨🚨"),
    ]
    
    for idx, (label, prob, icon) in enumerate(probs):
        with cols[idx]:
            color = "#0b8043" if prob < 5 else "#f9ab00" if prob < 10 else "#d93025"
            st.markdown(f"""
            <div style="background: white; border: 2px solid {color}; border-radius: 8px; 
                        padding: 16px; text-align: center;">
                <div style="font-size: 24px; margin-bottom: 8px;">{icon}</div>
                <div style="font-size: 12px; color: #666; font-weight: 600; margin-bottom: 8px;">
                    {label}
                </div>
                <div style="font-size: 24px; font-weight: 700; color: {color};">
                    {prob:.2f}%
                </div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ===== CAPITAL RECOMENDADO =====
    st.markdown("### 💼 Recomendação de Capital")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                    border-radius: 12px; padding: 24px; color: white;">
            <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">💰 CAPITAL MÍNIMO RECOMENDADO</div>
            <div style="font-size: 36px; font-weight: 700; margin: 12px 0;">R$ {capital_min_recomendado:.2f}</div>
            <div style="font-size: 13px; opacity: 0.9;">
                Baseado em 5x o risco máximo do Ciclo 1
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, {status_color} 0%, {status_color}dd 100%); 
                    border-radius: 12px; padding: 24px; color: white;">
            <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">✅ STATUS DO CAPITAL</div>
            <div style="font-size: 36px; font-weight: 700; margin: 12px 0;">{status_capital}</div>
            <div style="font-size: 13px; opacity: 0.9;">
                Capital atual: R$ {capital_inicial:.2f}
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ===== PROJEÇÕES =====
    st.markdown("### 📊 Projeções Mensais")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown(f"""
        <div style="background: white; border-left: 4px solid #0b8043; 
                    border-radius: 8px; padding: 20px;">
            <div style="font-size: 13px; color: #666; font-weight: 600; margin-bottom: 8px;">
                🚀 OTIMISTA (+50%)
            </div>
            <div style="font-size: 32px; font-weight: 700; color: #0b8043;">
                R$ {proj_otimista:.2f}
            </div>
            <div style="font-size: 12px; color: #666; margin-top: 8px;">
                {((proj_otimista/capital_inicial)*100):.1f}% ROI mensal
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div style="background: white; border-left: 4px solid #1a73e8; 
                    border-radius: 8px; padding: 20px;">
            <div style="font-size: 13px; color: #666; font-weight: 600; margin-bottom: 8px;">
                📈 REALISTA (base atual)
            </div>
            <div style="font-size: 32px; font-weight: 700; color: #1a73e8;">
                R$ {proj_realista:.2f}
            </div>
            <div style="font-size: 12px; color: #666; margin-top: 8px;">
                {((proj_realista/capital_inicial)*100):.1f}% ROI mensal
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div style="background: white; border-left: 4px solid #f9ab00; 
                    border-radius: 8px; padding: 20px;">
            <div style="font-size: 13px; color: #666; font-weight: 600; margin-bottom: 8px;">
                ⚠️ PESSIMISTA (-30%)
            </div>
            <div style="font-size: 32px; font-weight: 700; color: #f9ab00;">
                R$ {proj_pessimista:.2f}
            </div>
            <div style="font-size: 12px; color: #666; margin-top: 8px;">
                {((proj_pessimista/capital_inicial)*100):.1f}% ROI mensal
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ===== TABELA DE MÉTRICAS =====
    st.markdown("### 📋 Resumo de Métricas")
    
    metrics_data = [
        ["Capital Inicial", f"R$ {capital_inicial:.2f}"],
        ["Entrada Base Ciclo 1", f"R$ {stake_c1_g0:.2f}"],
        ["Gale 1", f"R$ {stake_c1_g1:.2f}"],
        ["Gale 2", f"R$ {stake_c1_g2:.2f}"],
        ["—", "—"],
        ["Entrada Base Ciclo 2", f"R$ {stake_c2_g0:.2f}"],
        ["Gale 1 (C2)", f"R$ {stake_c2_g1:.2f}"],
        ["Gale 2 (C2)", f"R$ {stake_c2_g2:.2f}"],
        ["—", "—"],
        ["Payout Mínimo", f"{payout_minimo * 100:.0f}%"],
        ["Drawdown Máximo (R$)", f"R$ {max_dd:.2f}"],
        ["Drawdown Máximo (%)", f"{max_dd_pct:.2f}%"],
        ["Saldo Mínimo Atingido", f"R$ {min_balance:.2f}"],
        ["—", "—"],
        ["Prob. 2 LOSS seguidos", f"{prob_2_loss:.2f}%"],
        ["Prob. 3 LOSS seguidos", f"{prob_3_loss:.2f}%"],
        ["Prob. 4 LOSS seguidos", f"{prob_4_loss:.2f}%"],
        ["Prob. 5 LOSS seguidos", f"{prob_5_loss:.2f}%"],
        ["—", "—"],
        ["Capital Mínimo Recomendado", f"R$ {capital_min_recomendado:.2f}"],
        ["Status do Capital", status_capital],
        ["—", "—"],
        ["Lucro Médio por Operação", f"R$ {lucro_medio:.2f}"],
        ["Projeção Mensal OTIMISTA", f"R$ {proj_otimista:.2f}"],
        ["Projeção Mensal REALISTA", f"R$ {proj_realista:.2f}"],
        ["Projeção Mensal PESSIMISTA", f"R$ {proj_pessimista:.2f}"],
    ]
    
    df_metrics = pd.DataFrame(metrics_data, columns=["Métrica", "Valor"])
    
    st.markdown("""
    <style>
    .risk-table {
        border-collapse: collapse;
        width: 100%;
        font-family: "Inter", "Arial", sans-serif;
    }
    .risk-table th {
        background-color: #f7f9fc;
        color: #333;
        padding: 12px;
        text-align: left;
        font-weight: 600;
        border-bottom: 2px solid #e6eef6;
    }
    .risk-table td {
        padding: 10px 12px;
        border-top: 1px solid #f0f4f8;
        color: #333;
    }
    .risk-table tr:hover {
        background-color: #f8f9fa;
    }
    </style>
    """, unsafe_allow_html=True)
    
    html_table = df_metrics.to_html(index=False, escape=False, classes="risk-table")
    st.markdown(f'<div style="overflow-x: auto; padding: 10px; background: #ffffff; border-radius: 8px; border: 1px solid #eef2f6;">{html_table}</div>', unsafe_allow_html=True)

    # ===== RECOMENDAÇÕES =====
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 💡 Recomendações de Gestão")
    
    if status_capital == "ADEQUADO":
        st.success(f"✅ **Capital adequado para operação segura.** Seu capital de R$ {capital_inicial:.2f} está acima do mínimo recomendado.")
    elif status_capital == "ACEITÁVEL":
        st.warning(f"⚠️ **Capital aceitável, mas com margem reduzida.** Considere aumentar para R$ {capital_min_recomendado:.2f} para maior segurança.")
    else:
        st.error(f"🚨 **Capital insuficiente!** Recomendamos fortemente aumentar para pelo menos R$ {capital_min_recomendado:.2f}.")
    
    if max_dd_pct > 20:
        st.warning(f"⚠️ **Drawdown elevado**: {max_dd_pct:.1f}% do capital. Revise a gestão de risco.")
    else:
        st.success(f"✅ **Drawdown controlado**: {max_dd_pct:.1f}% do capital está dentro do esperado.")
    
    if prob_3_loss > 5:
        st.info(f"💡 **Atenção**: Probabilidade de 3 losses seguidos é {prob_3_loss:.2f}%. Mantenha disciplina na gestão.")