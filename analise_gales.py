# analise_gales.py
import re
from datetime import datetime
from typing import List, Dict

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
                pair = m.group("pair").strip()
                time = m.group("time").strip()
                tf = m.group("tf").strip()
                direction = m.group("dir").strip()
                
                if "r" in m.groupdict():
                    result_raw = m.group("r").strip().upper()
                else:
                    result_raw = m.groups()[-1].strip().upper()
                    
                result = "DOJI" if result_raw == "DOJI" else ("WIN" if result_raw == "WIN" else "LOSS")
                
                records.append({
                    "pair": pair,
                    "time": time,
                    "tf": tf,
                    "direction": direction,
                    "result": result,
                    "gale_level": gale_level,
                })
            except:
                continue
                
    return records

def render_from_json(json_data: dict):
    """
    Renderiza a página de Análise de Gales a partir do JSON.
    """
    messages = json_data.get("messages", [])
    records = _extract_records(messages)
    df = pd.DataFrame(records)

    if df.empty:
        st.warning("⚠️ Nenhum dado disponível para análise de gales.")
        return

    # ===== CÁLCULOS DE MÉTRICAS =====
    total_ops = len(df)
    
    # Operações por nível de gale
    g0_ops = df[df["gale_level"] == 0]
    g1_ops = df[df["gale_level"] == 1]
    g2_ops = df[df["gale_level"] == 2]
    
    total_g0 = len(g0_ops)
    total_g1 = len(g1_ops)
    total_g2 = len(g2_ops)
    
    pct_g0 = (total_g0 / total_ops * 100) if total_ops > 0 else 0
    pct_g1 = (total_g1 / total_ops * 100) if total_ops > 0 else 0
    pct_g2 = (total_g2 / total_ops * 100) if total_ops > 0 else 0
    
    # Win rates por nível
    wins_g0 = len(g0_ops[g0_ops["result"] == "WIN"])
    wins_g1 = len(g1_ops[g1_ops["result"] == "WIN"])
    wins_g2 = len(g2_ops[g2_ops["result"] == "WIN"])
    
    losses_g0 = len(g0_ops[g0_ops["result"] == "LOSS"])
    losses_g1 = len(g1_ops[g1_ops["result"] == "LOSS"])
    losses_g2 = len(g2_ops[g2_ops["result"] == "LOSS"])
    
    wr_g0 = (wins_g0 / (wins_g0 + losses_g0) * 100) if (wins_g0 + losses_g0) > 0 else 0
    wr_g1 = (wins_g1 / (wins_g1 + losses_g1) * 100) if (wins_g1 + losses_g1) > 0 else 0
    wr_g2 = (wins_g2 / (wins_g2 + losses_g2) * 100) if (wins_g2 + losses_g2) > 0 else 0
    
    # Win rate combinado (com gale 1)
    ops_ate_g1 = df[df["gale_level"] <= 1]
    wins_ate_g1 = len(ops_ate_g1[ops_ate_g1["result"] == "WIN"])
    losses_ate_g1 = len(ops_ate_g1[ops_ate_g1["result"] == "LOSS"])
    wr_com_g1 = (wins_ate_g1 / (wins_ate_g1 + losses_ate_g1) * 100) if (wins_ate_g1 + losses_ate_g1) > 0 else 0
    
    # Win rate combinado (com gale 1+2)
    wins_total = len(df[df["result"] == "WIN"])
    losses_total = len(df[df["result"] == "LOSS"])
    wr_com_g1_g2 = (wins_total / (wins_total + losses_total) * 100) if (wins_total + losses_total) > 0 else 0
    
    # Taxa de recuperação (% de wins após ir para gale)
    taxa_recup_g1 = (wins_g1 / total_g1 * 100) if total_g1 > 0 else 0
    taxa_recup_g2 = (wins_g2 / total_g2 * 100) if total_g2 > 0 else 0
    
    # Falhas mesmo com gales
    falhas_g1 = losses_g1  # Perdeu no G1
    falhas_g2 = losses_g2  # Perdeu no G2

    # ===== RENDERIZAÇÃO =====
    st.markdown("<h1 style='text-align:center; color:#1f4068; margin-bottom:30px;'>🎯 Análise de Gales</h1>", unsafe_allow_html=True)

    # Cards principais - Distribuição de Gales
    st.markdown("### 📊 Distribuição de Operações por Nível")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #0b8043 0%, #12b35a 100%); 
                    border-radius: 12px; padding: 24px; color: white; text-align: center;">
            <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">SEM GALE (G0)</div>
            <div style="font-size: 36px; font-weight: 700; margin: 8px 0;">{total_g0:,}</div>
            <div style="font-size: 18px; font-weight: 600; margin-bottom: 8px;">{pct_g0:.2f}%</div>
            <div style="font-size: 12px; opacity: 0.8;">do total de operações</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #1a73e8 0%, #4285f4 100%); 
                    border-radius: 12px; padding: 24px; color: white; text-align: center;">
            <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">GALE 1 (G1)</div>
            <div style="font-size: 36px; font-weight: 700; margin: 8px 0;">{total_g1:,}</div>
            <div style="font-size: 18px; font-weight: 600; margin-bottom: 8px;">{pct_g1:.2f}%</div>
            <div style="font-size: 12px; opacity: 0.8;">precisaram de gale 1</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #f9ab00 0%, #fbc02d 100%); 
                    border-radius: 12px; padding: 24px; color: white; text-align: center;">
            <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">GALE 2 (G2)</div>
            <div style="font-size: 36px; font-weight: 700; margin: 8px 0;">{total_g2:,}</div>
            <div style="font-size: 18px; font-weight: 600; margin-bottom: 8px;">{pct_g2:.2f}%</div>
            <div style="font-size: 12px; opacity: 0.8;">precisaram de gale 2</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Win Rates por cenário
    st.markdown("### 📈 Win Rate por Cenário")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        color_g0 = "#0b8043" if wr_g0 >= 80 else "#f9ab00" if wr_g0 >= 70 else "#d93025"
        st.markdown(f"""
        <div style="background: white; border-left: 4px solid {color_g0}; 
                    border-radius: 8px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <div style="font-size: 13px; color: #666; font-weight: 600; margin-bottom: 8px;">
                🎯 SEM GALES
            </div>
            <div style="font-size: 32px; font-weight: 700; color: {color_g0};">
                {wr_g0:.2f}%
            </div>
            <div style="font-size: 13px; color: #666; margin-top: 8px;">
                {wins_g0:,} wins / {losses_g0:,} losses
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        color_g1 = "#0b8043" if wr_com_g1 >= 90 else "#1a73e8" if wr_com_g1 >= 85 else "#f9ab00"
        st.markdown(f"""
        <div style="background: white; border-left: 4px solid {color_g1}; 
                    border-radius: 8px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <div style="font-size: 13px; color: #666; font-weight: 600; margin-bottom: 8px;">
                🔄 COM GALE 1
            </div>
            <div style="font-size: 32px; font-weight: 700; color: {color_g1};">
                {wr_com_g1:.2f}%
            </div>
            <div style="font-size: 13px; color: #666; margin-top: 8px;">
                Incluindo recuperação
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        color_g2 = "#0b8043" if wr_com_g1_g2 >= 90 else "#1a73e8" if wr_com_g1_g2 >= 85 else "#f9ab00"
        st.markdown(f"""
        <div style="background: white; border-left: 4px solid {color_g2}; 
                    border-radius: 8px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <div style="font-size: 13px; color: #666; font-weight: 600; margin-bottom: 8px;">
                🔄🔄 COM GALE 1+2
            </div>
            <div style="font-size: 32px; font-weight: 700; color: {color_g2};">
                {wr_com_g1_g2:.2f}%
            </div>
            <div style="font-size: 13px; color: #666; margin-top: 8px;">
                Recuperação completa
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Taxa de Recuperação
    st.markdown("### 🔄 Taxa de Recuperação dos Gales")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                    border-radius: 12px; padding: 24px; color: white;">
            <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">RECUPERAÇÃO GALE 1</div>
            <div style="font-size: 42px; font-weight: 700; margin: 12px 0;">{taxa_recup_g1:.1f}%</div>
            <div style="font-size: 14px; opacity: 0.9;">
                {wins_g1:,} vitórias de {total_g1:,} tentativas
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                    border-radius: 12px; padding: 24px; color: white;">
            <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">RECUPERAÇÃO GALE 2</div>
            <div style="font-size: 42px; font-weight: 700; margin: 12px 0;">{taxa_recup_g2:.1f}%</div>
            <div style="font-size: 14px; opacity: 0.9;">
                {wins_g2:,} vitórias de {total_g2:,} tentativas
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Falhas
    st.markdown("### ⚠️ Falhas Mesmo com Gales")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown(f"""
        <div style="background: #fce4ec; border-left: 4px solid #d93025; 
                    border-radius: 8px; padding: 16px;">
            <div style="font-size: 13px; color: #666; font-weight: 600;">Falhas no G1</div>
            <div style="font-size: 28px; font-weight: 700; color: #d93025; margin: 8px 0;">
                {falhas_g1:,}
            </div>
            <div style="font-size: 12px; color: #666;">operações perdidas</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div style="background: #fce4ec; border-left: 4px solid #d93025; 
                    border-radius: 8px; padding: 16px;">
            <div style="font-size: 13px; color: #666; font-weight: 600;">Falhas no G2</div>
            <div style="font-size: 28px; font-weight: 700; color: #d93025; margin: 8px 0;">
                {falhas_g2:,}
            </div>
            <div style="font-size: 12px; color: #666;">operações perdidas</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        total_falhas = falhas_g1 + falhas_g2
        pct_falhas = (total_falhas / total_ops * 100) if total_ops > 0 else 0
        st.markdown(f"""
        <div style="background: #fce4ec; border-left: 4px solid #d93025; 
                    border-radius: 8px; padding: 16px;">
            <div style="font-size: 13px; color: #666; font-weight: 600;">Total de Falhas</div>
            <div style="font-size: 28px; font-weight: 700; color: #d93025; margin: 8px 0;">
                {total_falhas:,}
            </div>
            <div style="font-size: 12px; color: #666;">{pct_falhas:.2f}% do total</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Tabela de Métricas Detalhadas
    st.markdown("### 📋 Tabela de Métricas Completas")
    
    metrics_data = [
        ["Total de Operações", f"{total_ops:,}", "—"],
        ["Resolvidas na ENTRADA (qtd)", f"{total_g0:,}", "—"],
        ["Resolvidas na ENTRADA (%)", f"{pct_g0:.2f}%", "—"],
        ["Precisaram de GALE 1 (qtd)", f"{total_g1:,}", "—"],
        ["Precisaram de GALE 1 (%)", f"{pct_g1:.2f}%", "—"],
        ["Precisaram de GALE 2 (qtd)", f"{total_g2:,}", "—"],
        ["Precisaram de GALE 2 (%)", f"{pct_g2:.2f}%", "—"],
        ["—", "—", "—"],
        ["Win Rate SEM Gales", f"{wr_g0:.2f}%", "🎯"],
        ["Win Rate COM Gale 1", f"{wr_com_g1:.2f}%", "🔄"],
        ["Win Rate COM Gale 1+2", f"{wr_com_g1_g2:.2f}%", "🔄🔄"],
        ["—", "—", "—"],
        ["Taxa de Recuperação Gale 1", f"{taxa_recup_g1:.1f}%", "✅"],
        ["Taxa de Recuperação Gale 2", f"{taxa_recup_g2:.1f}%", "✅"],
        ["—", "—", "—"],
        ["Falhas mesmo com Gale 1", f"{falhas_g1:,}", "❌"],
        ["Falhas mesmo com Gale 2", f"{falhas_g2:,}", "❌"],
    ]
    
    df_metrics = pd.DataFrame(metrics_data, columns=["Métrica", "Valor", "Indicador"])
    
    st.markdown("""
    <style>
    .metrics-table {
        border-collapse: collapse;
        width: 100%;
        font-family: "Inter", "Arial", sans-serif;
    }
    .metrics-table th {
        background-color: #f7f9fc;
        color: #333;
        padding: 12px;
        text-align: left;
        font-weight: 600;
        border-bottom: 2px solid #e6eef6;
    }
    .metrics-table td {
        padding: 10px 12px;
        border-top: 1px solid #f0f4f8;
        color: #333;
    }
    .metrics-table tr:hover {
        background-color: #f8f9fa;
    }
    </style>
    """, unsafe_allow_html=True)
    
    html_table = df_metrics.to_html(index=False, escape=False, classes="metrics-table")
    st.markdown(f'<div style="overflow-x: auto; padding: 10px; background: #ffffff; border-radius: 8px; border: 1px solid #eef2f6;">{html_table}</div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Tabela de Cenários
    st.markdown("### 📊 Comparação de Cenários")
    
    cenarios_data = [
        ["A - Sem Gales", f"{total_g0:,}", f"{wins_g0:,}", f"{losses_g0:,}", f"{wr_g0:.2f}%"],
        ["B - Com Gale 1", f"{total_g1:,}", f"{wins_g1:,}", f"{losses_g1:,}", f"{wr_g1:.2f}%"],
        ["C - Com Gale 2", f"{total_g2:,}", f"{wins_g2:,}", f"{losses_g2:,}", f"{wr_g2:.2f}%"],
    ]
    
    df_cenarios = pd.DataFrame(cenarios_data, columns=["Cenário", "Total Ops", "WIN", "LOSS", "Win Rate"])
    
    html_cenarios = df_cenarios.to_html(index=False, escape=False, classes="metrics-table")
    st.markdown(f'<div style="overflow-x: auto; padding: 10px; background: #ffffff; border-radius: 8px; border: 1px solid #eef2f6;">{html_cenarios}</div>', unsafe_allow_html=True)

    # Insights
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 💡 Insights e Recomendações")
    
    if wr_g0 >= 80:
        st.success(f"✅ **Excelente assertividade sem gales!** Com {wr_g0:.2f}% de win rate na entrada, a estratégia está muito sólida.")
    elif wr_g0 >= 70:
        st.info(f"ℹ️ **Boa assertividade na entrada.** Win rate de {wr_g0:.2f}% permite operação sustentável com gestão adequada.")
    else:
        st.warning(f"⚠️ **Atenção à assertividade.** Win rate de {wr_g0:.2f}% na entrada exige gales para recuperação.")
    
    if taxa_recup_g1 >= 95:
        st.success(f"✅ **Gale 1 extremamente eficiente!** Taxa de recuperação de {taxa_recup_g1:.1f}% é excelente.")
    elif taxa_recup_g1 >= 85:
        st.info(f"ℹ️ **Gale 1 funcionando bem.** Taxa de {taxa_recup_g1:.1f}% é saudável para a estratégia.")
    
    if pct_g2 > 15:
        st.warning(f"⚠️ **Alto uso de Gale 2.** {pct_g2:.1f}% das operações chegam ao G2. Considere revisar sinais.")
    elif pct_g2 < 10:
        st.success(f"✅ **Baixo uso de Gale 2.** Apenas {pct_g2:.1f}% precisam de G2, indicando boa assertividade.")