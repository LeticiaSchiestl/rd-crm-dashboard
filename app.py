import os
import pandas as pd
import requests
from urllib.parse import quote
from datetime import datetime
from dash import Dash, html, dcc, dash_table
from dash.dependencies import Input, Output
import dash_auth
import plotly.express as px

# ========= Config =========
TOKEN = os.getenv("RDSTATION_API_TOKEN")
BASE_URL = os.getenv("RDSTATION_BASE_URL", "https://crm.rdstation.com/api/v1").rstrip("/")
USERNAME = os.getenv("APP_USER", "admin")
PASSWORD = os.getenv("APP_PASS", "admin123")

if not TOKEN:
    raise RuntimeError("RDSTATION_API_TOKEN não definido nas variáveis de ambiente.")

# ========= HTTP =========
def _get(url: str) -> dict:
    headers = {"Authorization": f"Bearer {TOKEN}", "accept": "application/json"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_all_deals() -> list:
    """Busca todas as páginas de /deals (esperando chaves deals/has_more/next_page)."""
    items = []
    next_page = None
    while True:
        url = f"{BASE_URL}/deals"
        if next_page:
            url += f"?next_page={quote(next_page)}"
        data = _get(url)

        deals_page = data.get("deals") or data.get("items") or data
        if isinstance(deals_page, dict):
            # caso a API retorne um objeto, tente achar uma lista dentro
            for v in deals_page.values():
                if isinstance(v, list):
                    deals_page = v
                    break

        if not isinstance(deals_page, list):
            deals_page = []

        items.extend(deals_page)

        has_more = bool(data.get("has_more"))
        next_page = data.get("next_page")
        if not has_more or not next_page:
            break
    return items

def load_data() -> pd.DataFrame:
    deals = fetch_all_deals()
    if not deals:
        return pd.DataFrame()

    # Normaliza campos comuns
    df = pd.json_normalize(deals, sep="__")

    # Tenta inferir algumas colunas padrão
    # Ajuste os nomes se sua API usar outras chaves.
    rename_map = {
        "id": "id",
        "name": "nome",
        "status": "status",
        "stage": "etapa",
        "amount": "valor",
        "value": "valor",                       # fallback
        "closed_at": "closed_at",
        "prediction_date": "prediction_date",
        "created_at": "created_at",
    }
    for k, v in list(rename_map.items()):
        if k not in df.columns:
            # procura por variações (ex: deal.amount, deal.value etc)
            alt = [c for c in df.columns if c.endswith(k) or c.split("__")[-1] == k]
            if alt:
                rename_map[alt[0]] = v
                rename_map.pop(k, None)

    df = df.rename(columns=rename_map)

    # Conversões de data (se existirem)
    for col in ["closed_at", "prediction_date", "created_at"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.tz_localize(None)

    # Valor numérico
    if "valor" in df.columns:
        df["valor"] = pd.to_numeric(df["valor"], errors="coerce")

    # Colunas amigáveis pro frontend
    keep_cols = [c for c in ["id", "nome", "status", "etapa", "valor", "closed_at", "prediction_date", "created_at"] if c in df.columns]
    if keep_cols:
        df_display = df[keep_cols].copy()
    else:
        df_display = df.copy()

    return df_display

# ========= App =========
app = Dash(__name__)
server = app.server  # para Render/Heroku

auth = dash_auth.BasicAuth(app, {USERNAME: PASSWORD})

def build_layout(df: pd.DataFrame):
    # Opções de filtros
    etapas = sorted(df["etapa"].dropna().unique()) if "etapa" in df.columns else []
    status_opts = sorted(df["status"].dropna().unique()) if "status" in df.columns else []

    return html.Div(
        style={"padding": "24px", "fontFamily": "Arial, sans-serif"},
        children=[
            html.H2("Painel de Deals (RD Station)"),
            html.Div(
                style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "12px"},
                children=[
                    dcc.Dropdown(
                        id="filtro-etapa",
                        options=[{"label": e, "value": e} for e in etapas],
                        placeholder="Filtrar por etapa",
                        multi=True,
                        style={"minWidth": "260px"},
                    ),
                    dcc.Dropdown(
                        id="filtro-status",
                        options=[{"label": s, "value": s} for s in status_opts],
                        placeholder="Filtrar por status",
                        multi=True,
                        style={"minWidth": "260px"},
                    ),
                    html.Button("Recarregar dados", id="btn-reload"),
                ],
            ),
            html.Div(id="kpis", style={"display": "flex", "gap": "24px", "marginBottom": "12px"}),
            dcc.Graph(id="grafico-etapas"),
            dcc.Graph(id="grafico-mensal"),
            dash_table.DataTable(
                id="tabela",
                columns=[{"name": c, "id": c} for c in df.columns],
                data=df.to_dict("records"),
                page_size=15,
                sort_action="native",
                filter_action="native",
                style_table={"overflowX": "auto"},
                style_cell={"fontSize": 12, "padding": "6px"},
            ),
            dcc.Store(id="store-data", data=df.to_dict("records")),
        ],
    )

# Carrega uma vez no start
_df = load_data()
app.layout = build_layout(_df)

# ========= Callbacks =========
@app.callback(
    Output("store-data", "data"),
    [Input("btn-reload", "n_clicks")],
    prevent_initial_call=True,
)
def reload_data(n):
    df = load_data()
    return df.to_dict("records")

@app.callback(
    [Output("tabela", "data"), Output("grafico-etapas", "figure"), Output("grafico-mensal", "figure"), Output("kpis", "children")],
    [Input("store-data", "data"), Input("filtro-etapa", "value"), Input("filtro-status", "value")],
)
def update_views(data, etapas_sel, status_sel):
    df = pd.DataFrame(data or [])

    # Filtros
    if etapas_sel and "etapa" in df.columns:
        df = df[df["etapa"].isin(etapas_sel)]
    if status_sel and "status" in df.columns:
        df = df[df["status"].isin(status_sel)]

    # KPIs
    kpi_children = []
    total_deals = len(df)
    kpi_children.append(html.Div([html.H4("Deals"), html.H3(f"{total_deals}")]))
    if "valor" in df.columns and not df["valor"].isna().all():
        kpi_children.append(html.Div([html.H4("Soma Valor"), html.H3(f"{df['valor'].sum():,.2f}")]))

    # Gráfico por etapas
    if "etapa" in df.columns:
        fig1 = px.bar(df.groupby("etapa").size().reset_index(name="qtde"), x="etapa", y="qtde", title="Deals por Etapa")
    else:
        fig1 = px.bar(title="Deals por Etapa (coluna 'etapa' não encontrada)")

    # Gráfico mensal (por created_at ou closed_at)
    date_col = "created_at" if "created_at" in df.columns else ("closed_at" if "closed_at" in df.columns else None)
    if date_col:
        dff = df.dropna(subset=[date_col]).copy()
        if not dff.empty:
            dff["mes"] = dff[date_col].dt.to_period("M").astype(str)
            fig2 = px.bar(dff.groupby("mes").size().reset_index(name="qtde"), x="mes", y="qtde", title=f"Deals por Mês ({date_col})")
        else:
            fig2 = px.bar(title=f"Deals por Mês ({date_col})")
    else:
        fig2 = px.bar(title="Deals por Mês (sem colunas de data)")

    return df.to_dict("records"), fig1, fig2, kpi_children

# ========= Main =========
if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.getenv("PORT", "8050")), debug=False)

