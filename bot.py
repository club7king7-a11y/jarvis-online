import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import time
from datetime import datetime
import random
import sqlite3
import hashlib
import requests

# === 1. 系统核心配置 ===
st.set_page_config(page_title="Jarvis OS", page_icon="☢️", layout="wide")

# CSS 样式表 (使用三引号防止断行错误)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;700&family=Share+Tech+Mono&display=swap');
    
    :root { 
        --neon-cyan: #00f3ff; 
        --neon-gold: #ffd700;
        --neon-danger: #ff073a;
        --glass: rgba(10, 10, 20, 0.85);
        --border: 1px solid rgba(0, 243, 255, 0.2);
    }
    
    .stApp { 
        background-color: #050505; 
        background-image: 
            linear-gradient(rgba(0, 243, 255, 0.03) 1px, transparent 1px),
            linear-gradient(90deg, rgba(0, 243, 255, 0.03) 1px, transparent 1px);
        background-size: 30px 30px;
        font-family: 'Rajdhani', sans-serif;
    }
    
    section[data-testid="stSidebar"] { 
        background-color: #0a0a0f; 
        border-right: var(--border);
        box-shadow: 10px 0 30px rgba(0,0,0,0.5);
    }
    
    h1, h2, h3 { 
        font-family: 'Share Tech Mono', monospace; 
        text-transform: uppercase;
        letter-spacing: 2px;
    }
    .main-title {
        background: -webkit-linear-gradient(0deg, var(--neon-cyan), #bd00ff);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 3em;
        font-weight: bold;
        text-shadow: 0 0 20px rgba(0, 243, 255, 0.3);
    }

    .stButton button {
        background: transparent !important;
        border: 1px solid var(--neon-cyan) !important;
        color: var(--neon-cyan) !important;
        font-family: 'Share Tech Mono', monospace;
        text-transform: uppercase;
    }
    .stButton button:hover {
        background: var(--neon-cyan) !important;
        color: black !important;
        box-shadow: 0 0 20px var(--neon-cyan);
    }
</style>
""", unsafe_allow_html=True)

# === 2. 数据库 ===
DB_FILE = "jarvis_cyber_v2.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, balance REAL, bot_active INTEGER)''')
    c.execute('''CREATE TABLE IF NOT
