import os
import pandas as pd
import requests
from datetime import datetime
from dash import Dash, html, dcc, dash_table, Input, Output
import dash_auth
import plotly.express as px

# Credenciais e configurações
TOKEN = os.getenv("RDSTATION_API_TOKEN")
BASE_URL = os.getenv("RDSTATION_BASE_URL", "https://crm.rdstation.com/api/v1")
USERNAME = os.getenv("APP_USER", "admin")
PASSWORD = os.getenv("APP_PASS", "admin123")

# Função para buscar dados da API
def get_data(endpoint):
    url = f"{BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {"Authorization": f"Bearer {TOKEN}", "accept": "application/json"}
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.json()

# Monta dados fictícios (exemplo simplificado)
def load_data():
    deals = pd.DataFrame(get_data("deals"))
