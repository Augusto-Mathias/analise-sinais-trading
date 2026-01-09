# resumo_executivo.py
import pandas as pd
from typing import List, Optional, Dict, Any

def build_resumo_executivo(
    mes: str = "Dezembro 2025",
    win_rate: Optional[float] = None,            # 85.28 -> informe como 85.28
    horarios: Optional[List[str]] = None,        # lista de faixas, ex: ["09:00-10:00", ...]
    pares: Optional[List[str]] = None,           # lista de pares, ex: ["AUDCAD", "AUS200", ...]
    g0: Optional[int] = None, g1: Optional[int] = None, g2: Optional[int] = None,
    capital: Optional[float] = None,             # ex: 500.0
    proj_min: Optional[float] = None,            # ex: 330.0
    proj_max: Optional[float] = None,            # ex: 559.0
    meta_dia: Optional[float] = None,            # ex: 15.0
    observacoes: Optional[str] = None            # texto livre, se necessário
) -> pd.DataFrame:
    """
    Retorna um DataFrame com a estrutura da aba 'Resumo Executivo'.
    Use os argumentos para preencher dinamicamente os campos.
    """
    # Formata campos opcionais em strings amigáveis
    win_str = f"Win Rate {win_rate:.2f}%{', consistência alta' if win_rate is not None else ''}" if win_rate is not None else ""
    horarios_str = " ".join(horarios) if horarios else ""
    pares_str = ", ".join(pares) if pares else ""
    gales_str = (
        f"G1 + G2 com boa recuperação ({g0 if g0 is not None else '?'} G0 / "
        f"{g1 if g1 is not None else '?'} G1 / {g2 if g2 is not None else '?'} G2)"
        if any(x is not None for x in (g0, g1, g2)) else ""
    )
    gestao_str = f"Capital R${capital:.0f} OK, risco controlado" if capital is not None else ""
    proj_str = f"R$ {int(proj_min) if proj_min is not None else '?'}–{int(proj_max) if proj_max is not None else '?'}"
    meta_str = f"Meta R$ {meta_dia:.0f}/dia realista" if meta_dia is not None else ""

    detalhes = [
        win_str or "—",
        horarios_str or "—",
        pares_str or "—",
        gales_str or "—",
        gestao_str or "—",
        f"{proj_str}  {meta_str}".strip() or "—"
    ]

    categorias = [
        "QUALIDADE DA SALA",
        "HORÁRIOS",
        "PARES",
        "GALES",
        "GESTÃO DE RISCO",
        "PROJEÇÃO MENSAL"
    ]

    status = [
        "BOM" if win_rate and win_rate >= 80 else ("ACEITÁVEL" if win_rate and win_rate >= 60 else "A AVALIAR"),
        "VALIDADOS" if horarios else "A VALIDAR",
        "IDENTIFICADOS" if pares else "A IDENTIFICAR",
        "SAUDÁVEL" if (g1 is not None and g2 is not None) else "A AVALIAR",
        "ADEQUADA" if capital and capital >= 500 else "A REVER",
        proj_str
    ]

    df = pd.DataFrame({
        "Categoria": categorias,
        "Status": status,
        "Detalhes (com base no JSON real)": detalhes
    })

    # Opcional: adicionar metadados/linha de cabeçalho com mês
    df.attrs["mes_analise"] = mes

    return df


# Exemplo de função auxiliar para retornar múltiplas abas (DataFrames) pronto para o dashboard
def build_all_sheets(resumo_params: Dict[str, Any], outras_abas: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, pd.DataFrame]:
    """
    Retorna um dicionário {sheet_name: DataFrame} contendo 'Resumo Executivo' + outras abas fornecidas.
    Útil para dashboards que iteram sobre abas.
    """
    sheets = {}
    sheets["Resumo Executivo"] = build_resumo_executivo(**resumo_params)
    if outras_abas:
        sheets.update(outras_abas)
    return sheets