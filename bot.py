import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import time
from datetime import datetime
import random
import sqlite3
import hashlib
import requests

# === 1. 系统核心配置 & HUD 界面风格 ===
st.set_page_config(page_title="Jarvis OS", page_icon="☢️", layout="wide")

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
    
    /* 侧边导航 */
    section[data-testid="stSidebar"] { 
        background-color: #0a0a0f; 
        border-right: var(--border);
        box-shadow: 10px 0 30px rgba(0,0,0,0.5);
    }
    
    /* 标题特效 */
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

    /* 排行榜卡片 */
    .rank-card {
        background: linear-gradient(135deg, rgba(255,255,255,0.05), rgba(255,255,255,0.01));
        border: var(--border);
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 10px;
        display: flex;
        align-items: center;
        transition: 0.3s;
    }
    .rank-card:hover { transform: scale(1.02); border-color: var(--neon-cyan); }
    .rank-1 { border: 1px solid var(--neon-gold); box-shadow: 0 0 15px rgba(255, 215, 0, 0.2); }
    
    /* 按钮 */
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

# === 2. 数据库 (保持不变) ===
DB_FILE = "jarvis_cyber_v2.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, balance REAL, bot_active INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS positions (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, symbol TEXT, type TEXT, entry REAL, size REAL, leverage INTEGER, margin REAL, tp REAL, sl REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history (time TEXT, username TEXT, symbol TEXT, action TEXT, price TEXT, size TEXT, pnl TEXT)''')
    conn.commit()
    conn.close()

def make_hashes(p): return hashlib.sha256(str.encode(p)).hexdigest()
def check_hashes(p,h): return make_hashes(p) == h

# === 3. 核心 API (缓存加速) ===
@st.cache_data(ttl=3)
def get_ticker_price(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"
        return float(requests.get(url, timeout=1).json()['price'])
    except: return 0.0

@st.cache_data(ttl=60)
def get_klines(symbol, interval):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit=100"
        data = requests.get(url, timeout=2).json()
        df = pd.DataFrame(data, columns=['time','o','h','l','c','v','x','y','z','a','b','c'])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        for c in ['o','h','l','c']: df[c] = df[c].astype(float)
        return df
    except: return pd.DataFrame()

# === 4. 排行榜核心逻辑 (新功能) ===
def get_all_users_equity():
    """计算所有用户的真实身价 (余额 + 未实现盈亏)"""
    conn = sqlite3.connect(DB_FILE)
    users = pd.read_sql("SELECT username, balance FROM users", conn)
    positions = pd.read_sql("SELECT * FROM positions", conn)
    conn.close()
    
    leaderboard = []
    
    for index, user in users.iterrows():
        name = user['username']
        balance = user['balance']
        
        # 计算该用户的未实现盈亏
        unrealized_pnl = 0
        user_pos = positions[positions['username'] == name]
        
        for idx, p in user_pos.iterrows():
            curr = get_ticker_price(p['symbol'])
            if curr > 0:
                if p['type'] == 'LONG': unrealized_pnl += (curr - p['entry']) * p['size']
                else: unrealized_pnl += (p['entry'] - curr) * p['size']
        
        total_equity = balance + unrealized_pnl
        leaderboard.append({"Username": name, "Equity": total_equity, "PNL": unrealized_pnl})
    
    # 按身价排序
    df = pd.DataFrame(leaderboard).sort_values(by="Equity", ascending=False).reset_index(drop=True)
    return df

def get_rank_badge(equity):
    if equity > 100000: return "👑 王者"
    if equity > 50000: return "💎 钻石"
    if equity > 20000: return "🥇 黄金"
    if equity > 10000: return "🥈 白银"
    return "🥉 青铜"

# === 5. 交易功能 ===
def place_order(user, sym, side, margin, lev, tp, sl):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT balance FROM users WHERE username=?', (user,))
    bal = c.fetchone()[0]
    
    if bal < margin: return False, "INSUFFICIENT FUNDS"
    price = get_ticker_price(sym)
    if price == 0: return False, "MARKET OFFLINE"
    
    size = (margin * lev) / price
    c.execute('UPDATE users SET balance = balance - ? WHERE username=?', (margin, user))
    c.execute('INSERT INTO positions (username, symbol, type, entry, size, leverage, margin, tp, sl) VALUES (?,?,?,?,?,?,?,?,?)', 
              (user, sym, side, price, size, lev, margin, tp, sl))
    conn.commit()
    conn.close()
    return True, "ORDER EXECUTED"

def close_order(id, price):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT * FROM positions WHERE id=?', (id,))
    p = c.fetchone()
    if p:
        # id0, user1, sym2, type3, entry4, size5, lev6, mar7
        if p[3] == 'LONG': pnl = (price - p[4]) * p[5]
        else: pnl = (p[4] - price) * p[5]
        c.execute('UPDATE users SET balance = balance + ? WHERE username=?', (p[7] + pnl, p[1]))
        c.execute('DELETE FROM positions WHERE id=?', (id,))
        c.execute('INSERT INTO history VALUES (?,?,?,?,?,?,?)', 
                  (datetime.now().strftime("%H:%M"), p[1], p[2], "CLOSE", str(price), str(p[5]), str(pnl)))
        conn.commit()
    conn.close()

# === 6. UI 页面 ===

def login_page():
    st.markdown("<br><br><h1 class='main-title' style='text-align: center;'>JARVIS OS 4.0</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #00f3ff; letter-spacing: 3px;'>MULTI-USER NEURAL INTERFACE</p>", unsafe_allow_html=True)
    
    c1,c2,c3 = st.columns([1,2,1])
    with c2:
        tab1, tab2 = st.tabs(["LOGIN", "REGISTER"])
        with tab1:
            u = st.text_input("USERNAME", key="l_u")
            p = st.text_input("PASSWORD", type='password', key="l_p")
            if st.button("CONNECT", use_container_width=True):
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute('SELECT * FROM users WHERE username=?', (u,))
                data = c.fetchone()
                conn.close()
                if data and check_hashes(p, data[1]):
                    st.session_state['user'] = u
                    st.rerun()
                else: st.error("ACCESS DENIED")
        with tab2:
            nu = st.text_input("NEW USERNAME", key="r_u")
            np = st.text_input("NEW PASSWORD", type='password', key="r_p")
            if st.button("CREATE ID", use_container_width=True):
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                try:
                    c.execute('INSERT INTO users VALUES (?,?,?,?)', (nu, make_hashes(np), 10000.0, 0))
                    conn.commit()
                    st.success("ID CREATED")
                except: st.error("USER EXISTS")
                finally: conn.close()

def app_interface():
    user = st.session_state['user']
    
    # --- 侧边导航栏 ---
    with st.sidebar:
        st.markdown(f"## 👤 COMMANDER: {user}")
        
        # 导航菜单
        page = st.radio("NAVIGATION", ["📈 TRADING TERMINAL", "🏆 LEADERBOARD", "📜 AUDIT LOGS"], label_visibility="collapsed")
        
        st.divider()
        st.markdown("### SYSTEM STATUS")
        st.caption("🟢 SERVER: ONLINE")
        st.caption("🟢 LATENCY: 24ms")
        
        if st.button("LOGOUT", use_container_width=True):
            del st.session_state['user']
            st.rerun()

    # --- 页面 1: 交易终端 ---
    if "TRADING" in page:
        st.markdown(f"<h1 class='main-
