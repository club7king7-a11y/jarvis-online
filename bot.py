import streamlit as st
import pandas as pd
import time
from datetime import datetime
import random
import sqlite3
import hashlib
import requests
import streamlit.components.v1 as components

# === 1. 页面配置 ===
st.set_page_config(page_title="Jarvis OS 8.0", page_icon="☢️", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;700&family=Share+Tech+Mono&display=swap');
    :root { --neon-cyan: #00f3ff; --neon-green: #39ff14; --neon-red: #ff073a; --dark-bg: #0a0a12; }
    .stApp { background-color: var(--dark-bg); color: #fff; font-family: 'Rajdhani', sans-serif; }
    
    /* 侧边栏 */
    section[data-testid="stSidebar"] { background-color: #080808; border-right: 1px solid #333; }
    
    /* 按钮美化 */
    .stButton button { 
        background: rgba(0, 243, 255, 0.05) !important; 
        border: 1px solid var(--neon-cyan) !important; 
        color: var(--neon-cyan) !important; 
        font-weight: bold;
    }
    .stButton button:hover { 
        background: var(--neon-cyan) !important; 
        color: #000 !important; 
    }
    
    /* 持仓卡片增强版 */
    .pos-card { 
        background: rgba(20, 20, 30, 0.8); 
        border: 1px solid #444; 
        border-left: 4px solid #888; 
        padding: 12px; 
        margin-bottom: 8px; 
        border-radius: 4px;
    }
    .pos-long { border-left-color: var(--neon-green); }
    .pos-short { border-left-color: var(--neon-red); }
    .pos-data { font-family: 'Share Tech Mono'; font-size: 14px; color: #ccc; }
    .pos-pnl { font-weight: bold; font-size: 16px; }
</style>
""", unsafe_allow_html=True)

# === 2. 数据库核心 (智能迁移) ===
DB_FILE = "jarvis_master.db" # 固定文件名，不再更改

def get_conn():
    return sqlite3.connect(DB_FILE, timeout=10, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    
    # 1. 创建基础表
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, balance REAL, active_strategy TEXT, avatar TEXT, bot_enabled INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS positions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, symbol TEXT, type TEXT, 
                  entry REAL, size REAL, leverage INTEGER, margin REAL, tp REAL, sl REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (time TEXT, username TEXT, symbol TEXT, action TEXT, price TEXT, size TEXT, pnl TEXT)''')
    
    # 2. 智能修补列 (防止旧数据库报错)
    # 检查 users 表是否有 avatar 列
    try:
        c.execute("SELECT avatar FROM users LIMIT 1")
    except:
        c.execute("ALTER TABLE users ADD COLUMN avatar TEXT DEFAULT '👤'")
        
    try:
        c.execute("SELECT bot_enabled FROM users LIMIT 1")
    except:
        c.execute("ALTER TABLE users ADD COLUMN bot_enabled INTEGER DEFAULT 0")

    conn.commit()
    conn.close()

# === 3. 用户系统 ===
def make_hashes(p): return hashlib.sha256(str.encode(p)).hexdigest()
def check_hashes(p,h): return make_hashes(p) == h

def register_user(username, password, avatar):
    conn = get_conn()
    try:
        conn.execute('INSERT INTO users VALUES (?,?,?,?,?,?)', (username, make_hashes(password), 10000.0, "None", avatar, 0))
        conn.commit()
        return True
    except: return False
    finally: conn.close()

def login_user(username, password):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username=?', (username,))
    data = c.fetchone()
    conn.close()
    # row[1] is password hash
    if data and check_hashes(password, data[1]): return data
    return None

def get_user_info(username):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT balance, active_strategy, avatar, bot_enabled FROM users WHERE username=?', (username,))
    res = c.fetchone()
    conn.close()
    return res if res else (0.0, "None", "👤", 0)

def update_user_setting(username, col, val):
    conn = get_conn()
    conn.execute(f"UPDATE users SET {col} = ? WHERE username=?", (val, username))
    conn.commit()
    conn.close()

# === 4. 交易引擎 (多源价格聚合) ===
def get_price(symbol):
    # 尝试多个 API 源，解决价格不同步问题
    sources = [
        f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT", # Binance
        f"https://api.huobi.pro/market/detail/merged?symbol={symbol.lower()}usdt", # Huobi
        f"https://api.kraken.com/0/public/Ticker?pair={symbol}USD" # Kraken
    ]
    
    for url in sources:
        try:
            resp = requests.get(url, timeout=1).json()
            if "binance" in url: return float(resp['price'])
            if "huobi" in url: return float(resp['tick']['close'])
            if "kraken" in url: 
                k = list(resp['result'].keys())[0]
                return float(resp['result'][k]['c'][0])
        except:
            continue
            
    # 如果全挂了，使用仿真
    st.toast("⚠️ API 连接受限，使用仿真数据", icon="📡")
    bases = {"BTC":96000, "ETH":3600, "SOL":230, "BNB":650, "XRP":1.4, "DOGE":0.39, "PEPE":0.00002}
    return bases.get(symbol, 100) * random.uniform(0.999, 1.001)

def place_order(user, sym, side, margin, lev, tp, sl):
    bal, _, _, _ = get_user_info(user)
    if bal < margin: return False
    
    price = get_price(sym)
    size = (margin * lev) / price
    
    conn = get_conn()
    try:
        conn.execute('UPDATE users SET balance = balance - ? WHERE username=?', (margin, user))
        conn.execute('INSERT INTO positions (username, symbol, type, entry, size, leverage, margin, tp, sl) VALUES (?,?,?,?,?,?,?,?,?,?)', 
                  (user, sym, side, price, size, lev, margin, tp, sl))
        # 记日志
        conn.execute('INSERT INTO history VALUES (?,?,?,?,?,?,?)', 
                  (datetime.now().strftime("%H:%M:%S"), user, sym, f"OPEN {side}", f"{price:.4f}", f"{size:.4f}", "-"))
        conn.commit()
        return True
    except: return False
    finally: conn.close()

def close_order(id, reason="Manual"):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM positions WHERE id=?", (id,))
        p = c.fetchone()
        if p:
            # p: 0id, 1user, 2sym, 3type, 4entry, 5size, 6lev, 7mar
            curr = get_price(p[2])
            if p[3] == 'LONG': pnl = (curr - p[4]) * p[5]
            else: pnl = (p[4] - curr) * p[5]
            
            conn.execute('UPDATE users SET balance = balance + ? WHERE username=?', (p[7] + pnl, p[1]))
            conn.execute('DELETE FROM positions WHERE id=?', (id,))
            conn.execute('INSERT INTO history VALUES (?,?,?,?,?,?,?)', 
                      (datetime.now().strftime("%H:%M:%S"), p[1], p[2], f"CLOSE ({reason})", f"${curr:.4f}", f"{p[5]:.4f}", f"${pnl:+.2f}"))
            conn.commit()
    finally: conn.close()

# === 5. 机器人逻辑 ===
def bot_run(user):
    _, strategy, _, enabled = get_user_info(user)
    if not enabled or strategy == "None": return

    # 降低触发频率，减少卡顿
    if random.random() < 0.15: # 15% 概率
        coins = ["BTC", "ETH", "SOL", "DOGE"]
        target = random.choice(coins)
        price = get_price(target)
        
        if strategy == "Sniper":
            side = random.choice(["LONG", "SHORT"])
            tp = price * 1.01 if side == 'LONG' else price * 0.99
            sl = price * 0.995 if side == 'LONG' else price * 1.005
            if place_order(user, target, side, 100, 50, tp, sl):
                st.toast(f"🤖 Sniper Open: {target}", icon="🔫")
                
        elif strategy == "Grid":
            side = random.choice(["LONG", "SHORT"])
            if place_order(user, target, side, 50, 20, 0, 0):
                st.toast(f"🤖 Grid Open: {target}", icon="🕸")

def check_monitor(user):
    conn = get_conn()
    positions = pd.read_sql("SELECT * FROM positions WHERE username=?", conn, params=(user,))
    conn.close()
    
    for _, p in positions.iterrows():
        curr = get_price(p['symbol'])
        reason = None
        
        if p['tp'] > 0:
            if (p['type']=='LONG' and curr>=p['tp']) or (p['type']=='SHORT' and curr<=p['tp']): reason = "🎯 TP"
        if p['sl'] > 0:
            if (p['type']=='LONG' and curr<=p['sl']) or (p['type']=='SHORT' and curr>=p['sl']): reason = "🛑 SL"
            
        # 强平
        liq_rate = 1 / p['leverage']
        liq = p['entry'] * (1 - liq_rate + 0.005) if p['type']=='LONG' else p['entry'] * (1 + liq_rate - 0.005)
        if (p['type']=='LONG' and curr<=liq) or (p['type']=='SHORT' and curr>=liq): reason = "💀 LIQ"
            
        if reason: close_order(p['id'], reason)

# === 6. UI ===
def login_page():
    st.markdown("<br><br><h1 style='text-align:center'>JARVIS OS 8.0</h1>", unsafe_allow_html=True)
    t1, t2 = st.tabs(["LOGIN", "REGISTER"])
    with t1:
        u = st.text_input("User", key="l1")
        p = st.text_input("Pass", type="password", key="l2")
        if st.button("Login", use_container_width=True):
            if login_user(u, p): st.session_state['user'] = u; st.rerun()
            else: st.error("Error")
    with t2:
        nu = st.text_input("New User", key="r1")
        np = st.text_input("New Pass", type="password", key="r2")
        av = st.selectbox("Avatar", ["👨‍🚀","🤖","👽","🦊"])
        if st.button("Register", use_container_width=True):
            if register_user(nu, np, av): st.success("OK"); st.rerun()
            else: st.error("Taken")

def main_app():
    user = st.session_state['user']
    bal, strat, ava, bot_on = get_user_info(user)
    
    # 侧边栏
    with st.sidebar:
        st.markdown(f"<h1 style='text-align:center'>{ava}</h1>", unsafe_allow_html=True)
        st.metric("WALLET", f"${bal:,.2f}")
        
        st.divider()
        st.markdown("### 🤖 AI CONFIG")
        new_strat = st.selectbox("STRATEGY", ["None", "Sniper", "Whale", "Grid"], index=["None", "Sniper", "Whale", "Grid"].index(strat))
        if new_strat != strat:
            update_user_setting(user, "active_strategy", new_strat)
            st.rerun()
            
        # 机器人总开关
        toggle = st.toggle("AUTO-TRADING", value=bool(bot_on))
        if toggle != bool(bot_on):
            update_user_setting(user, "bot_enabled", 1 if toggle else 0)
            st.rerun()
            
        if toggle: st.success(f"RUNNING: {new_strat}")
        
        st.divider()
        if st.button("LOGOUT"): del st.session_state['user']; st.rerun()

    # 主界面
    st.markdown(f"<h2 style='color:#00f3ff'>MARKET TERMINAL</h2>", unsafe_allow_html=True)
    
    # K线图配置
    c1, c2 = st.columns([3, 1])
    with c1:
        # 添加周期选择器 (解决问题2)
        col_sym, col_tf = st.columns([2, 1])
        with col_sym:
            sym = st.selectbox("ASSET", ["BTC", "ETH", "SOL", "BNB", "DOGE", "PEPE"])
        with col_tf:
            tf_map = {"1m":"1", "15m":"15", "1h":"60", "4h":"240", "1d":"D"}
            tf_label = st.selectbox("TIMEFRAME", list(tf_map.keys()), index=2)
            tf_val = tf_map[tf_label]

        # 嵌入 TradingView
        components.html(f"""
        <div class="tradingview-widget-container">
          <div id="tv_chart"></div>
          <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
          <script type="text/javascript">
          new TradingView.widget(
          {{ "width": "100%", "height": 500, "symbol": "BINANCE:{sym}USDT", "interval": "{tf_val}", "timezone": "Asia/Shanghai", "theme": "dark", "style": "1", "locale": "en", "toolbar_bg": "#f1f3f6", "enable_publishing": false, "hide_top_toolbar": false, "container_id": "tv_chart" }}
          );
          </script>
        </div>
        """, height=500)

    with c2:
        # 交易面板
        price = get_price(sym)
        st.metric("LIVE PRICE", f"${price:,.4f}") # 解决问题3：这里用了多源API，价格更准
        
        lev = st.slider("LEVERAGE", 1, 125, 20)
        mar = st.number_input("MARGIN", 100)
        tp = st.number_input("TP (Price)", 0.0)
        sl = st.number_input("SL (Price)", 0.0)
        
        if st.button("🟢 LONG", use_container_width=True):
            place_order(user, sym, "LONG", mar, lev, tp, sl)
            st.rerun()
        if st.button("🔴 SHORT", use_container_width=True):
            place_order(user, sym, "SHORT", mar, lev, tp, sl)
            st.rerun()

    # 持仓详情 (解决问题4 & 5)
    st.markdown("### 📊 LIVE POSITIONS")
    conn = get_conn()
    pos = pd.read_sql("SELECT * FROM positions WHERE username=?", conn, params=(user,))
    conn.close()
    
    if not pos.empty:
        for _, p in pos.iterrows():
            curr = get_price(p['symbol'])
            if p['type'] == 'LONG': 
                pnl = (curr - p['entry']) * p['size']
                liq = p['entry'] * (1 - 1/p['leverage'] + 0.005)
            else: 
                pnl = (p['entry'] - curr) * p['size']
                liq = p['entry'] * (1 + 1/p['leverage'] - 0.005)
            
            color = "#39ff14" if pnl >= 0 else "#ff073a"
            border = "pos-long" if p['type'] == 'LONG' else "pos-short"
            
            # 详细数据卡片
            st.markdown(f"""
            <div class='pos-card {border}'>
                <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:5px;'>
                    <div style='font-size:18px; font-weight:bold;'>{p['symbol']} <span style='font-size:14px; color:#888'>{p['type']} {p['leverage']}x</span></div>
                    <div style='font-size:18px; font-weight:bold; color:{color}'>${pnl:+.2f}</div>
                </div>
                <div style='display:flex; justify-content:space-between; font-family:monospace; color:#aaa; font-size:13px;'>
                    <div>ENTRY: {p['entry']:.4f}</div>
                    <div>MARK: {curr:.4f}</div>
                    <div>SIZE: {p['size']:.4f}</div>
                    <div style='color:#ff5555'>LIQ: {liq:.4f}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button(f"CLOSE {p['symbol']}", key=f"c_{p['id']}"):
                close_order(p['id'])
                st.rerun()
    else:
        st.info("NO POSITIONS")

    st.markdown("### 📜 HISTORY")
    conn = get_conn()
    hist = pd.read_sql("SELECT time, symbol, action, price, size, pnl FROM history WHERE username=? ORDER BY rowid DESC LIMIT 10", conn, params=(user,))
    conn.close()
    st.dataframe(hist, use_container_width=True, hide_index=True)

    # 后台执行
    bot_run(user)
    check_monitor(user)
    
    # 解决卡顿：使用更智能的刷新
    # 只有开启机器人时才频繁刷新，否则慢一点
    refresh_rate = 2 if bot_on else 5
    time.sleep(refresh_rate)
    st.rerun()

if __name__ == '__main__':
    init_db()
    if 'user' not in st.session_state: login_page()
    else: main_app()
