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
    c.execute('''CREATE TABLE IF NOT EXISTS positions (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, symbol TEXT, type TEXT, entry REAL, size REAL, leverage INTEGER, margin REAL, tp REAL, sl REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history (time TEXT, username TEXT, symbol TEXT, action TEXT, price TEXT, size TEXT, pnl TEXT)''')
    conn.commit()
    conn.close()

def make_hashes(p): return hashlib.sha256(str.encode(p)).hexdigest()
def check_hashes(p,h): return make_hashes(p) == h

# === 3. 核心 API ===
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

# === 4. 排行榜核心逻辑 ===
def get_all_users_equity():
    conn = sqlite3.connect(DB_FILE)
    users = pd.read_sql("SELECT username, balance FROM users", conn)
    positions = pd.read_sql("SELECT * FROM positions", conn)
    conn.close()
    
    leaderboard = []
    
    for index, user in users.iterrows():
        name = user['username']
        balance = user['balance']
        unrealized_pnl = 0
        user_pos = positions[positions['username'] == name]
        
        for idx, p in user_pos.iterrows():
            curr = get_ticker_price(p['symbol'])
            if curr > 0:
                if p['type'] == 'LONG': unrealized_pnl += (curr - p['entry']) * p['size']
                else: unrealized_pnl += (p['entry'] - curr) * p['size']
        
        total_equity = balance + unrealized_pnl
        leaderboard.append({"Username": name, "Equity": total_equity, "PNL": unrealized_pnl})
    
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
    # 使用三引号，防止换行报错
    st.markdown("""
    <br><br>
    <h1 class='main-title' style='text-align: center;'>JARVIS OS 4.0</h1>
    <p style='text-align: center; color: #00f3ff; letter-spacing: 3px;'>MULTI-USER NEURAL INTERFACE</p>
    """, unsafe_allow_html=True)
    
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
    
    with st.sidebar:
        st.markdown(f"## 👤 COMMANDER: {user}")
        page = st.radio("NAVIGATION", ["📈 TRADING TERMINAL", "🏆 LEADERBOARD", "📜 AUDIT LOGS"], label_visibility="collapsed")
        st.divider()
        if st.button("LOGOUT", use_container_width=True):
            del st.session_state['user']
            st.rerun()

    if "TRADING" in page:
        # 使用三引号
        st.markdown(f"""<h1 class='main-title'>MARKET UPLINK</h1>""", unsafe_allow_html=True)
        
        cols = st.columns(6)
        coins = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"]
        for i, sym in enumerate(coins):
            p = get_ticker_price(sym)
            cols[i].metric(sym, f"${p:,.2f}")
            
        st.divider()
        
        c_chart, c_ctrl = st.columns([3, 1])
        with c_ctrl:
            st.markdown("### ⚡️ OPERATIONS")
            sym = st.selectbox("TARGET", coins + ["ADA", "PEPE"])
            curr = get_ticker_price(sym)
            st.info(f"PRICE: ${curr:,.2f}")
            lev = st.slider("LEVERAGE", 1, 125, 20)
            mar = st.number_input("MARGIN (USDT)", min_value=10, value=100)
            c1, c2 = st.columns(2)
            if c1.button("🟢 LONG", use_container_width=True):
                ok, msg = place_order(user, sym, "LONG", mar, lev, 0, 0)
                if ok: st.success(msg); st.rerun()
                else: st.error(msg)
            if c2.button("🔴 SHORT", use_container_width=True):
                ok, msg = place_order(user, sym, "SHORT", mar, lev, 0, 0)
                if ok: st.success(msg); st.rerun()
                else: st.error(msg)

        with c_chart:
            df = get_klines(sym, "1h")
            if not df.empty:
                fig = go.Figure(data=[go.Candlestick(x=df['time'], open=df['o'], high=df['h'], low=df['l'], close=df['c'], increasing_line_color='#00f3ff', decreasing_line_color='#ff073a')])
                fig.update_layout(template="plotly_dark", height=500, margin=dict(l=0,r=0,t=0,b=0), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)

        st.markdown("### 📊 ACTIVE POSITIONS")
        conn = sqlite3.connect(DB_FILE)
        pos = pd.read_sql("SELECT * FROM positions WHERE username=?", conn, params=(user,))
        conn.close()
        
        if not pos.empty:
            for i, p in pos.iterrows():
                curr = get_ticker_price(p['symbol'])
                pnl = (curr - p['entry']) * p['size'] if p['type']=='LONG' else (p['entry'] - curr) * p['size']
                color = "#00f3ff" if pnl>=0 else "#ff073a"
                with st.expander(f"{p['symbol']} {p['type']} {p['leverage']}x"):
                    c1, c2 = st.columns([3, 1])
                    c1.markdown(f"PNL: <span style='color:{color};font-size:20px'>${pnl:+.2f}</span>", unsafe_allow_html=True)
                    if c2.button("CLOSE", key=f"cl_{p['id']}"):
                        close_order(p['id'], curr)
                        st.rerun()
        else: st.info("NO ACTIVE SIGNALS")

    elif "LEADERBOARD" in page:
        st.markdown(f"""<h1 class='main-title'>GLOBAL RANKINGS</h1>""", unsafe_allow_html=True)
        if st.button("🔄 REFRESH DATA"): st.rerun()
        
        df_rank = get_all_users_equity()
        top3_cols = st.columns(3)
        if len(df_rank) > 0:
            with top3_cols[1]: 
                r = df_rank.iloc[0]
                # 使用三引号
                st.markdown(f"""
                <div style='text-align:center; padding:20px; border:1px solid #ffd700; border-radius:10px; background:rgba(255,215,0,0.1);'>
                    <h1>👑 1ST</h1>
                    <h2>{r['Username']}</h2>
                    <h3 style='color:#ffd700'>${r['Equity']:,.0f}</h3>
                </div>""", unsafe_allow_html=True)
        if len(df_rank) > 1:
            with top3_cols[0]:
                r = df_rank.iloc[1]
                st.markdown(f"""
                <div style='text-align:center; padding:20px; border:1px solid #c0c0c0; border-radius:10px; background:rgba(192,192,192,0.1);'>
                    <h2>🥈 2ND</h2>
                    <h3>{r['Username']}</h3>
                    <h4>${r['Equity']:,.0f}</h4>
                </div>""", unsafe_allow_html=True)
        if len(df_rank) > 2:
            with top3_cols[2]: 
                r = df_rank.iloc[2]
                st.markdown(f"""
                <div style='text-align:center; padding:20px; border:1px solid #cd7f32; border-radius:10px; background:rgba(205,127,50,0.1);'>
                    <h2>🥉 3RD</h2>
                    <h3>{r['Username']}</h3>
                    <h4>${r['Equity']:,.0f}</h4>
                </div>""", unsafe_allow_html=True)
        
        st.divider()
        for idx, row in df_rank.iterrows():
            badge = get_rank_badge(row['Equity'])
            color = "#00f3ff" if row['PNL'] >= 0 else "#ff073a"
            bg_color = "rgba(0, 243, 255, 0.1)" if row['Username'] == user else "transparent"
            border = "1px solid #00f3ff" if row['Username'] == user else "1px solid rgba(255,255,255,0.1)"
            
            # 使用三引号
            st.markdown(f"""
            <div style="background:{bg_color}; border:{border}; padding:15px; margin-bottom:10px; border-radius:8px; display:flex; justify-content:space-between; align-items:center;">
                <div style="display:flex; align-items:center; gap:20px;">
                    <h2 style="margin:0; width:40px;">#{idx+1}</h2>
                    <div>
                        <h3 style="margin:0;">{row['Username']}</h3>
                        <span style="font-size:14px; color:#888;">{badge}</span>
                    </div>
                </div>
                <div style="text-align:right;">
                    <h3 style="margin:0;">${row['Equity']:,.2f}</h3>
                    <span style="color:{color};">Open PNL: ${row['PNL']:+.2f}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

    elif "AUDIT" in page:
        st.markdown(f"""<h1 class='main-title'>TRANSACTION LOGS</h1>""", unsafe_allow_html=True)
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql("SELECT * FROM history WHERE username=? ORDER BY rowid DESC", conn, params=(user,))
        conn.close()
        st.dataframe(df, use_container_width=True, hide_index=True)

# === 入口 ===
if __name__ == '__main__':
    init_db()
    if 'user' not in st.session_state: login_page()
    else: app_interface()
