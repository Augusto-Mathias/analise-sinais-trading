# app.py
import json
import re
from datetime import datetime, timedelta, date
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st

from resumo_executivo import build_all_sheets
import qualidade_sala  # qualidade_sala.py (tem render_from_json)
import validacao_horarios  # validacao_horarios.py (análise de horários)
import performance_paridades  # performance_paridades.py (análise de paridades)
import analise_gales  # analise_gales.py (análise de gales)
import padroes_tendencias  # padroes_tendencias.py (padrões e tendências)
import gestao_risco  # integração solicitada

# ----- PARSER / EXTRAÇÃO ----------------------------------------------------

SUPERSCRIPT_MAP = {
    "\u00b9": 1,  # ¹
    "\u00b2": 2,  # ²
    "\u00b3": 3,  # ³
    "1": 1,
    "2": 2,
    "3": 3,
}

def sup_to_level(s: str) -> int:
    if not s:
        return 0
    return SUPERSCRIPT_MAP.get(s, 0)

def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def try_parse_iso_date(s):
    """Tenta converter várias formas comuns de data para datetime.date.
       Retorna None se não conseguir parsear."""
    if not s:
        return None
    # já é date (mas não datetime)
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if isinstance(s, datetime):
        return s.date()

    s2 = str(s).strip()

    # unix timestamp numérico (segundos ou milissegundos)
    # tenta extrair somente dígitos contíguos (remove possíveis espaços)
    digits = re.sub(r"\D", "", s2)
    if digits and digits == s2:
        try:
            n = int(s2)
            # detectar ms vs s (se maior que ~1e12 provavelmente ms)
            if n > 1_000_000_000_000:
                return datetime.fromtimestamp(n / 1000.0).date()
            else:
                return datetime.fromtimestamp(n).date()
        except:
            pass

    # remover Z final e tentar ISO/formatos comuns
    if s2.endswith("Z"):
        s2 = s2[:-1]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s2, fmt).date()
        except:
            pass
    try:
        # tentativa final com fromisoformat
        return datetime.fromisoformat(s2).date()
    except:
        return None

def parse_signal_block(text: str) -> dict:
    res = {}
    m = re.search(r"Ativo:\s*([A-Z0-9\-\_]+(?:-OTC)?)", text, re.IGNORECASE)
    if m:
        res["pair"] = m.group(1).strip()
    m = re.search(r"Hor[aá]rio:\s*(\d{2}:\d{2}:\d{2})", text, re.IGNORECASE)
    if m:
        res["time"] = m.group(1)
    m = re.search(r"Payout:\s*([\d\.]+)\s*%", text, re.IGNORECASE)
    if m:
        try:
            res["payout"] = float(m.group(1)) / 100.0
        except:
            pass
    return res

RESOLVED_RE = re.compile(
    r"^(?P<check>[✅❌🃏])(?P<sup>[\u00b9\u00b2\u00b3\d]?)\s*"
    r"(?P<pair>[A-Z0-9\-\_]+(?:-OTC)?)\s*-\s*(?P<time>\d{2}:\d{2}:\d{2})\s*-\s*(?P<tf>\w+)\s*-\s*(?P<dir>\w+)\s*-\s*(?P<result>WIN|LOSS|DOJI|Doji|Doji)$",
    flags=re.IGNORECASE,
)

def extract_records(messages: List[dict]) -> Tuple[List[dict], Dict[Tuple[str,str], float]]:
    signals = {}
    resolved = []
    for msg in messages:
        text = msg.get("text", "")
        if isinstance(text, list):
            text = "".join([t.get("text", "") if isinstance(t, dict) else str(t) for t in text])

        if "Ativo:" in text or "Payout:" in text:
            blk = parse_signal_block(text)
            if "pair" in blk and "time" in blk and "payout" in blk:
                signals[(blk["pair"], blk["time"])] = blk["payout"]

        one_line = " ".join(str(text).splitlines()).strip()
        m = RESOLVED_RE.match(one_line)
        if m:
            sup = m.group("sup") or ""
            gale_level = sup_to_level(sup)
            pair = m.group("pair").strip()
            time = m.group("time").strip()
            tf = m.group("tf").strip()
            direction = m.group("dir").strip()
            result_raw = m.group("result").strip().upper()
            result = "DOJI" if result_raw == "DOJI" else ("WIN" if result_raw == "WIN" else ("LOSS" if result_raw == "LOSS" else result_raw))
            payout = signals.get((pair, time), None)

            msg_date = None
            # tenta várias chaves para achar a data no próprio registro
            for key in ("date", "message.date", "message.date_unixtime", "message.date_unixtime_str"):
                if key in msg and msg.get(key) is not None:
                    msg_date = try_parse_iso_date(msg.get(key))
                    break
            if msg_date is None:
                # tenta extrair do texto se possível
                msg_date = try_parse_iso_date(msg.get("text") or msg.get("message") or "")

            resolved.append({
                "pair": pair,
                "time": time,
                "hour": int(time.split(":")[0]) if time else None,
                "tf": tf,
                "direction": direction,
                "result": result,
                "gale_level": gale_level,
                "payout": payout,
                "msg_date": msg_date
            })
    return resolved, signals

# ----- METRICAS / ESTIMATIVAS -----------------------------------------------

def compute_profit_for_record(rec: dict, stakes: List[float], default_payout: float = 0.85) -> float:
    payout = rec.get("payout") or default_payout
    level = rec.get("gale_level", 0)
    result = rec.get("result", "").upper()
    level = min(level, len(stakes)-1)

    if result == "DOJI":
        return 0.0
    if result == "WIN":
        if level == 0:
            return stakes[0] * payout
        else:
            lost = sum(stakes[:level])
            win_amount = stakes[level] * payout
            return -lost + win_amount
    if result == "LOSS":
        lost = sum(stakes[:level+1])
        return -lost
    return 0.0

def summarize_resolved(resolved: List[dict], stakes: List[float], default_payout: float = 0.85):
    df = pd.DataFrame(resolved)
    if df.empty:
        return {}

    total_ops = len(df)
    counts = df["result"].value_counts().to_dict()
    wins = counts.get("WIN", 0)
    losses = counts.get("LOSS", 0)
    dojis = counts.get("DOJI", 0) or counts.get("Doji", 0) or 0
    resolved_count = total_ops - dojis
    win_rate = 100.0 * wins / resolved_count if resolved_count > 0 else 0.0

    g_counts = df["gale_level"].value_counts().to_dict()
    g0 = g_counts.get(0, 0)
    g1 = g_counts.get(1, 0)
    g2 = g_counts.get(2, 0)

    pair_counts = df["pair"].value_counts()
    top_pairs = pair_counts.index.tolist()[:12]

    hourly = df.groupby("hour").agg(
        total=("result", "size"),
        wins=("result", lambda s: (s == "WIN").sum())
    ).reset_index()
    hourly["win_rate"] = 100.0 * hourly["wins"] / hourly["total"]
    min_sample = max(10, int(0.005 * total_ops))
    good_hours = hourly[hourly["total"] >= min_sample].sort_values(
        ["win_rate", "total"], ascending=[False, False]
    )
    # Pega os top 7 horários e ordena por hora (ordem crescente)
    top_hours = good_hours.head(7).sort_values("hour")
    horarios_list = [f"{int(r['hour']):02d}:00-{int(r['hour'])+1:02d}:00" for _, r in top_hours.iterrows()]

    profits = df.apply(lambda r: compute_profit_for_record(r.to_dict(), stakes, default_payout), axis=1)
    total_profit = profits.sum()

    summary = {
        "total_ops": total_ops,
        "wins": wins,
        "losses": losses,
        "dojis": dojis,
        "win_rate": round(win_rate, 2),
        "g0": int(g0),
        "g1": int(g1),
        "g2": int(g2),
        "top_pairs": top_pairs,
        "horarios": horarios_list,
        "total_profit": float(total_profit),
        "hourly_table": hourly.sort_values("hour").reset_index(drop=True),
        "pair_counts": pair_counts
    }
    return summary

def build_resumo_params_from_json(json_data: dict, stakes: List[float] = [2.0, 4.3, 9.24], default_payout: float = 0.85, capital_default: float = 500.0) -> Tuple[Dict, dict]:
    messages = json_data.get("messages", [])
    resolved, signals = extract_records(messages)
    summary = summarize_resolved(resolved, stakes, default_payout)

    if not summary:
        resumo_empty = {
            "mes": "Sem dados",
            "win_rate": None,
            "horarios": [],
            "pares": [],
            "g0": 0, "g1": 0, "g2": 0,
            "capital": capital_default,
            "proj_min": None, "proj_max": None, "meta_dia": None
        }
        return resumo_empty, summary

    # coletar datas como objetos date e contar dias (para projeção)
    dates = set()
    for m in messages:
        # tenta chaves alternativas
        candidate = None
        for key in ("date", "message.date", "message.date_unixtime", "message.date_unixtime_str"):
            if key in m and m.get(key) is not None:
                candidate = try_parse_iso_date(m.get(key))
                break
        if candidate is None:
            candidate = try_parse_iso_date(m.get("text") or m.get("message") or "")
        if candidate:
            dates.add(candidate)

    n_days = max(1, len(dates))

    # cálculo de projeções (mantido)
    daily_profit = summary["total_profit"] / n_days if n_days > 0 else 0.0
    proj_min = daily_profit * 22
    proj_max = proj_min * 1.7
    meta_dia = round(daily_profit) if abs(daily_profit) >= 1 else 15

    # formata o mês/última data como dd/mm/yyyy
    mes_display = max(dates).strftime("%d/%m/%Y") if dates else "Periodo"

    resumo_params = {
        "mes": mes_display,
        "win_rate": summary["win_rate"],
        "horarios": summary["horarios"],
        "pares": summary["top_pairs"],
        "g0": summary["g0"],
        "g1": summary["g1"],
        "g2": summary["g2"],
        "capital": capital_default,
        "proj_min": round(max(0, proj_min), 0),
        "proj_max": round(max(0, proj_max), 0),
        "meta_dia": int(meta_dia)
    }
    return resumo_params, summary

# --------------------------
# Styling helpers & CSS (injetado uma vez)
# --------------------------

GLOBAL_CSS = """
<style>
/* Fonte e título */
h1, h2, h3 { font-family: "Inter", "Arial", sans-serif; color: #1f4068; }

/* Container para tabelas com scroll horizontal */
.table-container{
  overflow-x: auto;
  padding: 10px;
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #eef2f6;
}

/* Tabela estilizada: usa max-content para permitir largura conforme conteúdo.
   O container acima exibirá o scroll horizontal quando necessário. */
table.styled-table {
  border-collapse: collapse;
  width: max-content;
  min-width: 100%;
  font-family: "Inter", "Arial", sans-serif;
}
table.styled-table th {
  background-color: #f7f9fc;
  color: #333;
  padding: 10px;
  text-align: left;
  font-weight: 600;
  border-bottom: 1px solid #e6eef6;
}
table.styled-table td {
  padding: 10px;
  border-top: 1px solid #f0f4f8;
  color: #333;
  white-space: nowrap; /* mantém cada célula em uma linha para facilitar scroll */
}

/* Destaques de status */
span.status-good { color: #0b8043; font-weight: 700; }   /* verde */
span.status-info { color: #0b63c4; font-weight: 700; }   /* azul */

/* Container de métricas com scroll horizontal */
.metrics-scroll {
  display: flex;
  gap: 18px;
  overflow-x: auto;
  padding: 8px 4px;
  margin-bottom: 8px;
}
.metric-box {
  min-width: 220px;
  background: #ffffff;
  border-radius: 8px;
  padding: 12px;
  border: 1px solid #eef2f6;
  flex: 0 0 auto;
}
.metric-title { color: #666; font-weight: 600; margin-bottom: 6px; }
.metric-value { font-size: 22px; font-weight: 700; color: #1f4068; }

/* Pequena responsividade */
@media (max-width: 700px) {
  table.styled-table th, table.styled-table td { padding: 8px; font-size: 13px; }
  .metric-box { min-width: 180px; padding: 10px; }
  .metric-value { font-size: 18px; }
}
</style>
"""

def render_df_with_scroll(df: pd.DataFrame, index: bool = False):
    html = df.to_html(index=index, classes="styled-table", escape=False)
    st.markdown(f"<div class='table-container' style='width:100%'>{html}</div>", unsafe_allow_html=True)

# ----- STREAMLIT UI ---------------------------------------------------------

st.set_page_config(page_title="Dashboard de Análise", layout="wide")
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

st.markdown("<h1 style='text-align:center; margin-bottom: 6px;'>Dashboard de Análise — extração automática do result.json</h1>", unsafe_allow_html=True)

# Carregamento de arquivo (mantém igual)
uploaded = st.file_uploader("Faça upload do result.json (ou deixe em branco para usar o result.json local)", type=["json"])
if uploaded:
    data = json.load(uploaded)
else:
    try:
        data = load_json("result.json")
    except FileNotFoundError:
        st.error("Arquivo 'result.json' não encontrado no diretório e nenhum upload fornecido.")
        st.stop()

# --- FILTRO DE DATA GLOBAL (Dois date_inputs: Início / Fim) ---
all_messages = data.get("messages", [])
all_dates = []
for m in all_messages:
    # tenta várias chaves possíveis onde a data pode estar
    for key in ("date", "message.date", "message.date_unixtime", "message.date_unixtime_str"):
        if key in m and m.get(key) is not None:
            d = try_parse_iso_date(m.get(key))
            if d:
                all_dates.append(d)
            break
    else:
        # tenta extrair de texto livre (caso haja data embutida)
        text_field = m.get("text") or m.get("message") or ""
        d = try_parse_iso_date(text_field)
        if d:
            all_dates.append(d)

if all_dates:
    min_date, max_date = min(all_dates), max(all_dates)
else:
    min_date = max_date = datetime.now().date()
    all_dates = []

# Filtragem de mensagens por data (se houver datas válidas)
if all_dates:
    # Valores já definidos dentro a sidebar (serão definidos lá)
    start_f = st.session_state.get("start_date", min_date)
    end_f = st.session_state.get("end_date", max_date)
    
    if isinstance(start_f, datetime):
        start_f = start_f.date()
    if isinstance(end_f, datetime):
        end_f = end_f.date()
    
    # filtra mensagens de forma robusta usando try_parse_iso_date
    filtered_messages = []
    for m in all_messages:
        # tenta várias chaves onde a data pode estar
        candidate = None
        for key in ("date", "message.date", "message.date_unixtime", "message.date_unixtime_str"):
            if key in m and m.get(key) is not None:
                candidate = try_parse_iso_date(m.get(key))
                break
        if candidate is None:
            # fallback: tenta extrair do texto
            candidate = try_parse_iso_date(m.get("text") or m.get("message") or "")
        if candidate is None:
            # ignora mensagens sem data válida
            continue
        if start_f <= candidate <= end_f:
            filtered_messages.append(m)
    data_filtrada = {"messages": filtered_messages}
else:
    data_filtrada = data

# Build resumo (USANDO dados filtrados)
resumo_params, summary = build_resumo_params_from_json(data_filtrada)

# ---------------------------
# Funções de renderização por seção
# ---------------------------

def render_resumo_executivo(resumo_params: dict, summary: dict):
    win_rate_value = resumo_params.get("win_rate")
    win_rate_display = f"{win_rate_value:.2f}%" if isinstance(win_rate_value, (int, float)) else "—"

    g0 = int(resumo_params.get("g0", 0))
    g1 = int(resumo_params.get("g1", 0))
    g2 = int(resumo_params.get("g2", 0))

    proj_min = resumo_params.get("proj_min")
    proj_max = resumo_params.get("proj_max")
    if proj_min is not None and proj_max is not None:
        proj_min_fmt = f"{proj_min:,.0f}"
        proj_max_fmt = f"{proj_max:,.0f}"
        proj_display_short = f"R$ {proj_min_fmt} — R$ {proj_max_fmt}"
    else:
        proj_display_short = "—"

    metrics_html = f"""
    <div class="metrics-scroll">
      <div class="metric-box">
        <div class="metric-title">Total operações</div>
        <div class="metric-value">{summary.get('total_ops', 0):,}</div>
      </div>
      <div class="metric-box">
        <div class="metric-title">Win Rate</div>
        <div class="metric-value">{win_rate_display}</div>
      </div>
      <div class="metric-box">
        <div class="metric-title">G0 / G1 / G2</div>
        <div class="metric-value">{g0:,} / {g1:,} / {g2:,}</div>
      </div>
      <div class="metric-box">
        <div class="metric-title">Projeção mensal (min-max)</div>
        <div class="metric-value">{proj_display_short}</div>
      </div>
    </div>
    """
    st.markdown(metrics_html, unsafe_allow_html=True)

    if proj_min is not None and proj_max is not None:
        st.markdown(f"**Projeção mensal (min-max) — completo:** R$ {proj_min_fmt} — R$ {proj_max_fmt}")

    st.markdown("#### Horários recomendados (top por win rate com amostra mínima)")
    for h in resumo_params.get("horarios", []):
        st.write(f"- {h}")

    st.markdown("#### Pares mais frequentes")
    pares = resumo_params.get("pares", [])
    if pares:
        st.code(", ".join(pares), language=None)
    else:
        st.write("—")

    # integrar com resumo_executivo.py
    sheets = build_all_sheets(resumo_params)
    tab_names = list(sheets.keys())
    tabs = st.tabs(tab_names)
    for tab, name in zip(tabs, tab_names):
        with tab:
            st.header(name)
            df_tab = sheets[name].copy()
            
            # Tratamento especial para a aba "Resumo Executivo"
            if "resumo" in name.lower() and "executivo" in name.lower():
                # Usando containers nativos do Streamlit para garantir renderização
                num_cols = min(2, len(df_tab))  # Máximo 2 colunas
                
                for idx in range(0, len(df_tab), num_cols):
                    cols = st.columns(num_cols)
                    for col_idx, col in enumerate(cols):
                        row_idx = idx + col_idx
                        if row_idx < len(df_tab):
                            row = df_tab.iloc[row_idx]
                            with col:
                                categoria = str(row.get('Categoria', ''))
                                status = str(row.get('Status', ''))
                                detalhes = str(row.get('Detalhes (com base no JSON real)', ''))
                                
                                # Criar card com container do Streamlit
                                with st.container():
                                    st.markdown(f"""
                                    <div style="
                                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                                        border-radius: 12px;
                                        padding: 24px;
                                        margin-bottom: 16px;
                                        color: white;
                                        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                                    ">
                                        <div style="
                                            font-size: 14px;
                                            font-weight: 600;
                                            text-transform: uppercase;
                                            letter-spacing: 1px;
                                            opacity: 0.9;
                                            margin-bottom: 8px;
                                        ">{categoria}</div>
                                        <div style="
                                            display: inline-block;
                                            background: rgba(255,255,255,0.25);
                                            padding: 6px 16px;
                                            border-radius: 20px;
                                            font-weight: 700;
                                            font-size: 15px;
                                            margin-bottom: 12px;
                                            backdrop-filter: blur(10px);
                                        ">{status}</div>
                                        <div style="
                                            font-size: 15px;
                                            line-height: 1.6;
                                            opacity: 0.95;
                                            white-space: pre-wrap;
                                        ">{detalhes}</div>
                                    </div>
                                    """, unsafe_allow_html=True)
            else:
                # Para outras abas, mantém o estilo de tabela normal
                if "Status" in df_tab.columns:
                    def decorate_status(s):
                        s_upper = str(s).upper()
                        if s_upper in ["BOM", "SAUDÁVEL", "ADEQUADA"]:
                            return f"<span class='status-good'>{s}</span>"
                        if s_upper in ["VALIDADOS", "IDENTIFICADOS"]:
                            return f"<span class='status-info'>{s}</span>"
                        return s
                    df_tab["Status"] = df_tab["Status"].apply(decorate_status)
                render_df_with_scroll(df_tab, index=False)

    st.markdown("---")
    st.subheader("📊 Detalhes adicionais")

    if "hourly_table" in summary and not summary["hourly_table"].empty:
        st.markdown("### ⏰ Performance por Horário")
        df_hourly = summary["hourly_table"].copy()
        
        # Renomear e formatar colunas
        df_hourly["Horário"] = df_hourly["hour"].apply(lambda x: f"{int(x):02d}:00 - {int(x)+1:02d}:00")
        df_hourly["Total de Operações"] = df_hourly["total"]
        df_hourly["Vitórias"] = df_hourly["wins"]
        df_hourly["Taxa de Acerto"] = pd.to_numeric(df_hourly["win_rate"], errors="coerce").fillna(0.0).map(lambda x: f"{x:.2f}%")
        
        # Adicionar cor baseada na taxa de acerto
        def color_win_rate(val):
            try:
                rate = float(val.replace('%', ''))
                if rate >= 85:
                    return f'<span style="color: #0b8043; font-weight: 700;">{val}</span>'
                elif rate >= 75:
                    return f'<span style="color: #f9ab00; font-weight: 600;">{val}</span>'
                else:
                    return f'<span style="color: #d93025; font-weight: 600;">{val}</span>'
            except:
                return val
        
        df_hourly_display = df_hourly[["Horário", "Total de Operações", "Vitórias", "Taxa de Acerto"]].copy()
        df_hourly_display["Taxa de Acerto"] = df_hourly_display["Taxa de Acerto"].apply(color_win_rate)
        
        render_df_with_scroll(df_hourly_display, index=False)

    if "pair_counts" in summary:
        st.markdown("### 💱 Ranking de Paridades")
        df_pairs = summary["pair_counts"].reset_index()
        df_pairs.columns = ["Paridade", "Operações"]
        
        # Adicionar coluna de porcentagem
        total = df_pairs["Operações"].sum()
        df_pairs["Participação %"] = df_pairs["Operações"].apply(lambda x: f"{(x/total*100):.1f}%")
        
        # Formatação de números
        df_pairs["Operações"] = df_pairs["Operações"].apply(lambda x: f"{x:,}")
        
        # Adicionar posição/rank
        df_pairs.insert(0, "Rank", range(1, len(df_pairs) + 1))
        
        # Destacar top 3
        def highlight_rank(row):
            rank = row["Rank"]
            paridade = row["Paridade"]
            if rank == 1:
                return f'<span style="color: #f9ab00; font-weight: 700;">🥇 {paridade}</span>'
            elif rank == 2:
                return f'<span style="color: #9aa0a6; font-weight: 700;">🥈 {paridade}</span>'
            elif rank == 3:
                return f'<span style="color: #cd7f32; font-weight: 700;">🥉 {paridade}</span>'
            return paridade
        
        df_pairs_display = df_pairs.head(30).copy()
        df_pairs_display["Paridade"] = df_pairs_display.apply(highlight_rank, axis=1)
        df_pairs_display = df_pairs_display[["Rank", "Paridade", "Operações", "Participação %"]]
        
        render_df_with_scroll(df_pairs_display, index=False)

# Simple placeholders for other sections
def render_gestao_risco(resumo_params: dict, summary: dict):
    st.header("Gestao_Risco")
    st.info("Em desenvolvimento — simulações de risco e gestão.")

# ---------------------------
# Sidebar menu e roteamento
# ---------------------------

with st.sidebar:
    # Logo/Título estilizado
    st.markdown("""
    <div style="text-align: center; padding: 20px 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                border-radius: 12px; margin-bottom: 20px;">
        <h1 style="color: white; margin: 0; font-size: 24px; font-weight: 700;">
            📊 Dashboard
        </h1>
        <p style="color: rgba(255,255,255,0.8); margin: 5px 0 0 0; font-size: 12px;">
            Análise de Trading
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("### 🧭 Navegação")
    
    # CSS para esconder as bolinhas do radio
    st.markdown("""
    <style>
    /* Esconde as bolinhas do radio button */
    div[role="radiogroup"] label {
        background: transparent;
        padding: 12px 16px;
        border-radius: 8px;
        cursor: pointer;
        transition: all 0.2s;
        margin-bottom: 4px;
        display: block;
    }
    
    div[role="radiogroup"] label:hover {
        background: rgba(102, 126, 234, 0.1);
    }
    
    /* Item selecionado */
    div[role="radiogroup"] label:has(input:checked) {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white !important;
        font-weight: 600;
    }
    
    div[role="radiogroup"] label:has(input:checked) span {
        color: white !important;
    }
    
    /* Esconde completamente o radio button */
    div[role="radiogroup"] input[type="radio"] {
        display: none !important;
    }
    
    /* Remove o espaço do radio button */
    div[role="radiogroup"] label > div:first-child {
        display: none !important;
    }
    
    /* Ajusta o texto */
    div[role="radiogroup"] label > div {
        padding: 0 !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Menu estilizado com emojis
    menu_items = {
        "Resumo Executivo": "📈",
        "Qualidade_Sala": "✅",
        "Validacao_Horarios": "⏰",
        "Performance_Paridades": "💱",
        "Analise_Gales": "🎯",
        "Padroes_Tendencias": "📊",
        "Gestao_Risco": "🛡️",
    }
    
    pagina = st.radio(
        "Selecione a seção:",
        list(menu_items.keys()),
        format_func=lambda x: f"{menu_items[x]} {x.replace('_', ' ')}",
        label_visibility="collapsed"
    )
    
    # Filtro de data movido para depois do menu
    st.markdown("---")
    st.markdown("### 📅 Filtro de Período")
    
    if all_dates:
        # Botões de atalho
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📅 7 dias", use_container_width=True):
                st.session_state.start_date = max_date - timedelta(days=6)
                st.session_state.end_date = max_date
        with col2:
            if st.button("📅 15 dias", use_container_width=True):
                st.session_state.start_date = max_date - timedelta(days=14)
                st.session_state.end_date = max_date

        # Date inputs
        initial_start = st.session_state.get("start_date", min_date)
        initial_end = st.session_state.get("end_date", max_date)

        start_f = st.date_input(
            "Data início",
            value=initial_start,
            min_value=min_date,
            max_value=max_date,
            key="start_date",
            format="DD/MM/YYYY"
        )
        end_f = st.date_input(
            "Data fim",
            value=initial_end,
            min_value=min_date,
            max_value=max_date,
            key="end_date",
            format="DD/MM/YYYY"
        )

        if isinstance(start_f, datetime):
            start_f = start_f.date()
        if isinstance(end_f, datetime):
            end_f = end_f.date()

        if start_f > end_f:
            start_f, end_f = end_f, start_f

        st.markdown(f"""
        <div style="background: #f0f2f6; border-radius: 8px; padding: 10px; margin-top: 10px; text-align: center;">
            <div style="font-size: 11px; color: #666; margin-bottom: 4px;">Período selecionado</div>
            <div style="font-size: 13px; font-weight: 600; color: #1f4068;">
                {start_f.strftime('%d/%m/%Y')} — {end_f.strftime('%d/%m/%Y')}
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    # Info box estilizado
    st.markdown("---")
    st.markdown(f"""
    <div style="background: #f0f2f6; border-radius: 8px; padding: 12px;">
        <div style="font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">
            📁 Dados carregados
        </div>
        <div style="font-size: 18px; font-weight: 700; color: #1f4068;">
            {len(data_filtrada.get('messages', [])):,}
        </div>
        <div style="font-size: 11px; color: #666; margin-top: 2px;">
            mensagens analisadas
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Rodapé
    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; padding: 10px; color: #666; font-size: 11px;">
        <strong>Dashboard v2.0</strong><br>
        Powered by Streamlit
    </div>
    """, unsafe_allow_html=True)

# ---------------------------
# Filtragem de mensagens pelo período selecionado (robusta)
# ---------------------------
start = st.session_state.get("start_date", min_date)
end = st.session_state.get("end_date", max_date)
if isinstance(start, datetime):
    start = start.date()
if isinstance(end, datetime):
    end = end.date()
if start > end:
    start, end = end, start

filtered_messages = []
for m in all_messages:
    candidate = None
    for key in ("date", "message.date", "message.date_unixtime", "message.date_unixtime_str"):
        if key in m and m.get(key) is not None:
            candidate = try_parse_iso_date(m.get(key))
            break
    if candidate is None:
        candidate = try_parse_iso_date(m.get("text") or m.get("message") or "")
    if candidate is None:
        continue
    if start <= candidate <= end:
        filtered_messages.append(m)

data_filtrada = {"messages": filtered_messages}

# Renderiza a página selecionada
if pagina == "Resumo Executivo":
    render_resumo_executivo(resumo_params, summary)

elif pagina == "Qualidade_Sala":
    # chama o módulo dedicado (usa os dados filtrados)
    try:
        qualidade_sala.render_from_json(data_filtrada)
    except AttributeError:
        try:
            qualidade_sala.render(resumo_params, summary)
        except Exception as e:
            st.error("Erro ao executar qualidade_sala. Verifique o arquivo qualidade_sala.py")
            st.exception(e)

elif pagina == "Validacao_Horarios":
    # chama o módulo dedicado (usa os dados filtrados)
    try:
        validacao_horarios.render_from_json(data_filtrada)
    except Exception as e:
        st.error("Erro ao executar validacao_horarios. Verifique o arquivo validacao_horarios.py")
        st.exception(e)
elif pagina == "Performance_Paridades":
    # chama o módulo dedicado (usa os dados filtrados)
    try:
        performance_paridades.render_from_json(data_filtrada)
    except Exception as e:
        st.error("Erro ao executar performance_paridades. Verifique o arquivo performance_paridades.py")
        st.exception(e)
elif pagina == "Analise_Gales":
    # chama o módulo dedicado (usa os dados filtrados)
    try:
        analise_gales.render_from_json(data_filtrada)
    except Exception as e:
        st.error("Erro ao executar analise_gales. Verifique o arquivo analise_gales.py")
        st.exception(e)
elif pagina == "Padroes_Tendencias":
    # chama o módulo dedicado (usa os dados filtrados)
    try:
        padroes_tendencias.render_from_json(data_filtrada)
    except Exception as e:
        st.error("Erro ao executar padroes_tendencias. Verifique o arquivo padroes_tendencias.py")
        st.exception(e)
elif pagina == "Gestao_Risco":
    # chama o módulo gestao_risco integrado (usa os dados filtrados)
    try:
        gestao_risco.render_from_json(data_filtrada)
    except AttributeError:
        # fallback para a implementação local se existir
        try:
            render_gestao_risco(resumo_params, summary)
        except Exception as e:
            st.error("Erro ao executar gestao_risco. Verifique o arquivo gestao_risco.py")
            st.exception(e)
    except Exception as e:
        st.error("Erro ao executar gestao_risco. Verifique o arquivo gestao_risco.py")
        st.exception(e)
else:
    st.write("Selecione uma seção no menu lateral.")