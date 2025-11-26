import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import time
from datetime import datetime, timedelta
import random
import sqlite3
import hashlib
import requests
import numpy as np

# === 1. 系统核心配置 ===
st.set_page_config(page_title="Jarvis OS", page_icon="☢️", layout="wide")

# CSS 样式 (三引号防断行)
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
    
    /* 机器人状态灯 */
    .bot-status {
        padding: 10px;
        border-radius: 5px;
        text-align: center;
        margin-bottom: 10px;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# === 2. 数据库 ===
DB_FILE = "jarvis_cyber_v3.db"

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

# === 3. 核心 API (双模引擎：真实+仿真) ===

# 模拟基础价格，防止每次刷新价格乱跳
MOCK_PRICES = {
    "BTC": 96000.0, "ETH": 3500.0, "SOL": 190.0, "BNB": 620.0,
    "XRP": 1.10, "DOGE": 0.38, "ADA": 0.95, "PEPE": 0.00001
}

def get_ticker_price(symbol):
    """获取价格：优先API，失败则使用仿真数据"""
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"
        return float(requests.get(url, timeout=0.5).json()['price'])
    except:
        # 仿真模式：生成随机波动
        base = MOCK_PRICES.get(symbol, 100)
        # 加上时间因子产生波动
        noise = np.sin(time.time() / 10) * (base * 0.005) + random.uniform(-base*0.001, base*0.001)
        return base + noise

@st.cache_data(ttl=60)
def get_klines(symbol, interval):
    """获取K线：优先API，失败则生成仿真K线"""
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit=50"
        data = requests.get(url, timeout=1).json()
        df = pd.DataFrame(data, columns=['time','o','h','l','c','v','x','y','z','a','b','c'])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        for c in ['o','h','l','c']: df[c] = df[c].astype(float)
        return df
    except:
        # 仿真模式：生成逼真的随机漫步K线
        dates = pd.date_range(end=datetime.now(), periods=50, freq='1H')
        base = MOCK_PRICES.get(symbol, 100)
        
        closes = []
        curr = base
        for _ in range(50):
            change = np.random.normal(0, base*0.01)
            curr += change
            closes.append(curr)
            
        df = pd.DataFrame(index=dates)
        df['time'] = df.index
        df['c'] = closes
        df['o'] = [c + random.uniform(-base*0.005, base*0.005) for c in closes]
        df['h'] = [max(c, o) + random.uniform(0, base*0.005) for c, o in zip(df['c'], df['o'])]
        df['l'] = [min(c, o) - random.uniform(0, base*0.005) for c, o in zip(df['c'], df['o'])]
        return df

# === 4. 排行榜逻辑 ===
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
    if equity > 100000: return "👑 LEGEND"
    if equity > 50000: return "💎 DIAMOND"
    if equity > 20000: return "🥇 GOLD"
    if equity > 10000: return "🥈 SILVER"
    return "🥉 BRONZE"

# === 5. 交易 & 机器人 ===
def get_user_bot_status(username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT bot_active FROM users WHERE username=?', (username,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else 0

def toggle_bot(username, status):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('UPDATE users SET bot_active = ? WHERE username=?', (1 if status else 0, username))
    conn.commit()
    conn.close()

def place_order(user, sym, side, margin, lev, tp, sl):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT balance FROM users WHERE username=?', (user,))
    bal = c.fetchone()[0]
    
    if bal < margin: return False, "INSUFFICIENT FUNDS"
    price = get_ticker_price(sym)
    
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

def auto_bot_engine(username):
    is_active = get_user_bot_status(username)
    if not is_active: return

    # 10% 概率触发交易
    if random.random() < 0.1:
        coins = ["BTC", "ETH", "SOL", "DOGE", "PEPE"]
        target = random.choice(coins)
        price = get_ticker_price(target)
        
        side = random.choice(["LONG", "SHORT"])
        lev = random.randint(20, 50)
        margin = random.randint(50, 200)
        
        place_order(username, target, side, margin, lev, 0, 0)
        st.toast(f"🤖 AI-BOT: {target} {side}", icon="⚡️")

# === 6. UI 页面 ===

def login_page():
    st.markdown("""
    <br><br>
    <h1 class='main-title' style='text-align: center;'>JARVIS OS</h1>
    <p style='text-align: center; color: #00f3ff; letter-spacing: 3px;'>SECURE QUANTITATIVE INTERFACE</p>
    """, unsafe_allow_html=True)
    
    c1,c2,c3 = st.columns([1,2,1])
    with c2:
        tab1, tab2 = st.tabs(["LOGIN", "REGISTER"])
        with tab1:
            u = st.text_input("USERNAME", key="l_u")
            p = st.text_input("PASSWORD", type='password', key="l_p")
            if st.button("CONNECT SYSTEM", use_container_width=True):
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
            if st.button("CREATE IDENTITY", use_container_width=True):
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
        st.markdown("### 🤖 AI-PILOT STATUS")
        
        # 机器人开关 (侧边栏显眼位置)
        bot_status = get_user_bot_status(user)
        if bot_status:
            st.markdown(f"<div class='bot-status' style='background:rgba(57, 255, 20, 0.2); color:#39ff14; border:1px solid #39ff14;'>ONLINE</div>", unsafe_allow_html=True)
            if st.button("DEACTIVATE BOT", use_container_width=True):
                toggle_bot(user, False)
                st.rerun()
        else:
            st.markdown(f"<div class='bot-status' style='background:rgba(255, 255, 255, 0.1); color:#888; border:1px solid #555;'>OFFLINE</div>", unsafe_allow_html=True)
            if st.button("ACTIVATE BOT", use_container_width=True):
                toggle_bot(user, True)
                st.rerun()

        st.divider()
        if st.button("LOGOUT", use_container_width=True):
            del st.session_state['user']
            st.rerun()

    if "TRADING" in page:
        st.markdown(f"""<h1 class='main-title'>MARKET UPLINK</h1>""", unsafe_allow_html=True)
        
        # 顶部行情
        cols = st.columns(6)
        coins = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"]
        for i, sym in enumerate(coins):
            p = get_ticker_price(sym)
            cols[i].metric(sym, f"${p:,.2f}")
            
        st.divider()
        
        # 交易区
        c_chart, c_ctrl = st.columns([3, 1])
        with c_ctrl:
            st.markdown("### ⚡️ OPERATIONS")
            sym = st.selectbox("TARGET", coins + ["ADA", "PEPE"])
            curr = get_ticker_price(sym)
            
            # 价格颜色跳动
            price_color = "#00f3ff"
            st.markdown(f"<h2 style='color:{price_color}'>${curr:,.2f}</h2>", unsafe_allow_html=True)
            
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
            # 自动使用仿真数据如果 API 失败
            df = get_klines(sym, "1h")
            if not df.empty:
                fig = go.Figure(data=[go.Candlestick(x=df['time'], open=df['o'], high=df['h'], low=df['l'], close=df['c'], increasing_line_color='#00f3ff', decreasing_line_color='#ff073a')])
                
                # 画持仓线
                conn = sqlite3.connect(DB_FILE)
                pos = pd.read_sql("SELECT * FROM positions WHERE username=?", conn, params=(user,))
                conn.close()
                for i, p in pos.iterrows():
                    if p['symbol'] == sym:
                        color = "#00f3ff" if p['type']=='LONG' else "#ff073a"
                        fig.add_hline(y=p['entry'], line_dash="dash", line_color=color, annotation_text=f"ENTRY {p['type']}")

                fig.update_layout(template="plotly_dark", height=500, margin=dict(l=0,r=0,t=0,b=0), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)

        st.markdown("### 📊 ACTIVE POSITIONS")
        # 重新读取持仓显示
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
                st.markdown(f"""<div style='text-align:center; padding:20px; border:1px solid #ffd700; border-radius:10px; background:rgba(255,215,0,0.1);'><h1>👑 1ST</h1><h2>{r['Username']}</h2><h3 style='color:#ffd700'>${r['Equity']:,.0f}</h3></div>""", unsafe_allow_html=True)
        
        st.divider()
        for idx, row in df_rank.iterrows():
            badge = get_rank_badge(row['Equity'])
            color = "#00f3ff" if row['PNL'] >= 0 else "#ff073a"
            bg_color = "rgba(0, 243, 255, 0.1)" if row['Username'] == user else "transparent"
            border = "1px solid #00f3ff" if row['Username'] == user else "1px solid rgba(255,255,255,0.1)"
            
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
    
    # 自动执行
    auto_bot_engine(user)

# === 入口 ===
if __name__ == '__main__':
    init_db()
    if 'user' not in st.session_state: login_page()
    else: 
        app_interface()
        # 自动刷新以更新数据
        if st.checkbox("SYNC DATA STREAM", value=True):
            time.sleep(3)
            st.rerun()
