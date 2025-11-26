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
st.set_page_config(page_title="Jarvis OS 7.1", page_icon="☢️", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;700&family=Share+Tech+Mono&display=swap');
    :root { --neon-cyan: #00f3ff; --neon-gold: #ffd700; --neon-danger: #ff073a; --neon-green: #39ff14; --dark-bg: #0a0a12; }
    .stApp { background-color: var(--dark-bg); color: #fff; font-family: 'Rajdhani', sans-serif; }
    section[data-testid="stSidebar"] { background-color: #080808; border-right: 1px solid #333; }
    .stat-box { border: 1px solid #333; padding: 10px; border-radius: 5px; background: rgba(255,255,255,0.05); text-align: center; }
    .stat-label { font-size: 12px; color: #888; }
    .stat-value { font-size: 16px; font-weight: bold; color: var(--neon-cyan); font-family: 'Share Tech Mono'; }
    .stButton button { background: rgba(0, 243, 255, 0.05) !important; border: 1px solid var(--neon-cyan) !important; color: var(--neon-cyan) !important; }
    .stButton button:hover { background: var(--neon-cyan) !important; color: #000 !important; box-shadow: 0 0 20px var(--neon-cyan); }
    .pos-card { background: rgba(255,255,255,0.03); border-left: 3px solid #555; padding: 10px; margin-bottom: 10px; border-radius: 0 10px 10px 0; }
    .pos-long { border-left-color: var(--neon-green); }
    .pos-short { border-left-color: var(--neon-danger); }
</style>
""", unsafe_allow_html=True)

# === 2. 数据库核心 (高并发优化) ===
DB_FILE = "jarvis_stable_v8.db"

def get_db_connection():
    """获取数据库连接，带超时处理"""
    conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row # 允许通过列名访问
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    # 开启 WAL 模式 (关键修复：允许并发读写)
    c.execute('PRAGMA journal_mode=WAL;')
    
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, balance REAL, active_strategy TEXT, avatar TEXT, bot_enabled INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS positions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, symbol TEXT, type TEXT, 
                  entry REAL, size REAL, leverage INTEGER, margin REAL, tp REAL, sl REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (time TEXT, username TEXT, symbol TEXT, action TEXT, price TEXT, size TEXT, pnl TEXT)''')
    conn.commit()
    conn.close()

# === 3. 用户系统 ===
def make_hashes(p): return hashlib.sha256(str.encode(p)).hexdigest()
def check_hashes(p,h): return make_hashes(p) == h

def register_user(username, password, avatar):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users VALUES (?,?,?,?,?,?)', (username, make_hashes(password), 10000.0, "None", avatar, 0))
        conn.commit()
        return True
    except: return False
    finally: conn.close()

def login_user(username, password):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username=?', (username,))
    data = c.fetchone()
    conn.close()
    if data and check_hashes(password, data['password']): return data
    return None

def get_user_info(username):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT balance, active_strategy, avatar, bot_enabled FROM users WHERE username=?', (username,))
    res = c.fetchone()
    conn.close()
    return res if res else (0.0, "None", "👤", 0)

def update_user_setting(username, column, value):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(f"UPDATE users SET {column} = ? WHERE username=?", (value, username))
    conn.commit()
    conn.close()

def change_password(username, np):
    update_user_setting(username, "password", make_hashes(np))

# === 4. 交易引擎 ===
def get_price(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"
        return float(requests.get(url, timeout=0.5).json()['price'])
    except:
        bases = {"BTC":96000, "ETH":3600, "SOL":230, "BNB":650, "XRP":1.4, "DOGE":0.4, "PEPE":0.00002, "WIF":3.0}
        return bases.get(symbol, 100) * random.uniform(0.999, 1.001)

def place_order(user, sym, side, margin, lev, tp=0.0, sl=0.0):
    bal, _, _, _ = get_user_info(user)
    if bal < margin: return False, "余额不足"
    
    price = get_price(sym)
    size = (margin * lev) / price
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute('UPDATE users SET balance = balance - ? WHERE username=?', (margin, user))
        c.execute('INSERT INTO positions (username, symbol, type, entry, size, leverage, margin, tp, sl) VALUES (?,?,?,?,?,?,?,?,?,?)', 
                  (user, sym, side, price, size, lev, margin, tp, sl))
        c.execute('INSERT INTO history VALUES (?,?,?,?,?,?,?)', 
                  (datetime.now().strftime("%H:%M:%S"), user, sym, f"OPEN {side} {lev}x", f"${price:.4f}", f"{size:.4f}", "-"))
        conn.commit()
        return True, "ORDER EXECUTED"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def close_order(id, reason="Manual"):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT * FROM positions WHERE id=?", (id,))
        p = c.fetchone()
        if p:
            curr = get_price(p['symbol'])
            if p['type'] == 'LONG': pnl = (curr - p['entry']) * p['size']
            else: pnl = (p['entry'] - curr) * p['size']
            
            c.execute('UPDATE users SET balance = balance + ? WHERE username=?', (p['margin'] + pnl, p['username']))
            c.execute('DELETE FROM positions WHERE id=?', (id,))
            c.execute('INSERT INTO history VALUES (?,?,?,?,?,?,?)', 
                      (datetime.now().strftime("%H:%M:%S"), p['username'], p['symbol'], f"CLOSE ({reason})", f"${curr:.4f}", f"{p['size']:.4f}", f"${pnl:+.2f}"))
            conn.commit()
    finally:
        conn.close()

# === 5. 机器人与监控 ===
def bot_logic(username):
    _, strategy, _, enabled = get_user_info(username)
    if not enabled or strategy == "None": return

    if random.random() < 0.1:
        coins = ["BTC", "ETH", "SOL", "DOGE", "PEPE"]
        target = random.choice(coins)
        price = get_price(target)
        
        if strategy == "Sniper":
            side = random.choice(["LONG", "SHORT"])
            lev = 50
            tp = price * 1.01 if side == 'LONG' else price * 0.99
            sl = price * 0.995 if side == 'LONG' else price * 1.005
            place_order(username, target, side, 100, lev, tp, sl)
            st.toast(f"🔫 Sniper: {target} {side}", icon="💥")
            
        elif strategy == "Whale":
            side = random.choice(["LONG", "SHORT"])
            lev = 5
            tp = price * 1.10 if side == 'LONG' else price * 0.90
            sl = price * 0.95 if side == 'LONG' else price * 1.05
            place_order(username, target, side, 500, lev, tp, sl)
            st.toast(f"🐋 Whale: {target} {side}", icon="🌊")
            
        elif strategy == "Grid":
            side = random.choice(["LONG", "SHORT"])
            lev = 20
            tp = price * 1.02 if side == 'LONG' else price * 0.98
            sl = price * 0.98 if side == 'LONG' else price * 1.02
            place_order(username, target, side, 50, lev, tp, sl)
            st.toast(f"🕸 Grid: {target} {side}", icon="🕷️")

def auto_sl_tp_check(username):
    conn = get_db_connection()
    positions = pd.read_sql("SELECT * FROM positions WHERE username=?", conn, params=(username,))
    conn.close()
    
    for _, p in positions.iterrows():
        curr = get_price(p['symbol'])
        reason = None
        
        if p['tp'] > 0:
            if (p['type'] == 'LONG' and curr >= p['tp']) or (p['type'] == 'SHORT' and curr <= p['tp']): reason = "🎯 TP Win"
        if p['sl'] > 0:
            if (p['type'] == 'LONG' and curr <= p['sl']) or (p['type'] == 'SHORT' and curr >= p['sl']): reason = "🛑 SL Loss"
            
        liq_rate = 1 / p['leverage']
        liq_price = p['entry'] * (1 - liq_rate + 0.005) if p['type']=='LONG' else p['entry'] * (1 + liq_rate - 0.005)
        
        if (p['type']=='LONG' and curr <= liq_price) or (p['type']=='SHORT' and curr >= liq_price): reason = "💀 LIQUIDATED"
            
        if reason: close_order(p['id'], reason)

# === 6. UI ===
def login_page():
    st.markdown("<br><br><h1 style='text-align:center;'>JARVIS OS 7.1</h1>", unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["LOGIN", "REGISTER"])
    with tab1:
        u = st.text_input("USERNAME", key="l_u")
        p = st.text_input("PASSWORD", type='password', key="l_p")
        if st.button("CONNECT", use_container_width=True):
            if login_user(u, p):
                st.session_state['user'] = u
                st.rerun()
            else: st.error("Failed")
    with tab2:
        c1, c2 = st.columns([1,2])
        with c1:
            ava = st.selectbox("AVATAR", ["👨‍🚀","🤖","👽","🦊","🐯","💀","👻","🤡"])
            st.markdown(f"<h1 style='text-align:center'>{ava}</h1>", unsafe_allow_html=True)
        with c2:
            nu = st.text_input("NEW USER", key="r_u")
            np = st.text_input("NEW PASS", type='password', key="r_p")
            if st.button("CREATE ID", use_container_width=True):
                if register_user(nu, np, ava): st.success("Done"); time.sleep(1); st.rerun()
                else: st.error("Exists")

def main_app():
    user = st.session_state['user']
    bal, strategy, avatar, bot_enabled = get_user_info(user)
    
    with st.sidebar:
        st.markdown(f"<h1 style='text-align:center'>{avatar}</h1>", unsafe_allow_html=True)
        st.markdown(f"<h3 style='text-align:center'>{user}</h3>", unsafe_allow_html=True)
        st.metric("WALLET BALANCE", f"${bal:,.2f}")
        page = st.radio("NAVIGATION", ["📈 TERMINAL", "🏆 LEADERBOARD", "⚙️ SETTINGS"], label_visibility="collapsed")
        
        st.divider()
        st.markdown("### 🤖 BOT CONFIG")
        options = ["None", "Sniper", "Whale", "Grid"]
        idx = options.index(strategy) if strategy in options else 0
        new_strat = st.selectbox("STRATEGY MODEL", options, index=idx)
        if new_strat != strategy:
            update_user_setting(user, "active_strategy", new_strat)
            st.rerun()
            
        is_on = st.toggle("AUTO-TRADING", value=bool(bot_enabled))
        if is_on != bool(bot_enabled):
            update_user_setting(user, "bot_enabled", 1 if is_on else 0)
            st.rerun()
            
        if is_on and new_strat != "None": st.success(f"RUNNING: {new_strat}")
        elif is_on: st.warning("SELECT STRATEGY")
        else: st.caption("STANDBY")
        
        st.divider()
        if st.button("LOGOUT"): del st.session_state['user']; st.rerun()

    if "TERMINAL" in page:
        c_tv, c_panel = st.columns([3, 1])
        with c_panel:
            st.markdown("### ⚡️ COMMAND")
            sym = st.selectbox("ASSET", ["BTC", "ETH", "SOL", "BNB", "DOGE", "PEPE", "WIF"])
            price = get_price(sym)
            st.markdown(f"<h2 style='color:#00f3ff'>${price:,.4f}</h2>", unsafe_allow_html=True)
            lev = st.slider("LEVERAGE", 1, 125, 20)
            mar = st.number_input("MARGIN", 100)
            tp = st.number_input("TP (Price)", 0.0)
            sl = st.number_input("SL (Price)", 0.0)
            
            c1, c2 = st.columns(2)
            if c1.button("🟢 LONG", use_container_width=True):
                ok, msg = place_order(user, sym, "LONG", mar, lev, tp, sl)
                if ok: st.success(msg); st.rerun()
                else: st.error(msg)
            if c2.button("🔴 SHORT", use_container_width=True):
                ok, msg = place_order(user, sym, "SHORT", mar, lev, tp, sl)
                if ok: st.success(msg); st.rerun()
                else: st.error(msg)

        with c_tv:
            components.html(f"""
            <div class="tradingview-widget-container">
              <div id="tradingview_main"></div>
              <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
              <script type="text/javascript">
              new TradingView.widget(
              {{ "width": "100%", "height": 550, "symbol": "BINANCE:{sym}USDT", "interval": "15", "timezone": "Asia/Shanghai", "theme": "dark", "style": "1", "locale": "en", "enable_publishing": false, "hide_top_toolbar": true, "container_id": "tradingview_main" }}
              );
              </script>
            </div>
            """, height=500)

        st.markdown("### 📊 LIVE POSITIONS")
        conn = get_db_connection()
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
                
                roe = (pnl / p['margin']) * 100
                color = "#39ff14" if pnl >= 0 else "#ff073a"
                border = "pos-long" if p['type'] == 'LONG' else "pos-short"
                
                st.markdown(f"""
                <div class='pos-card {border}'>
                    <div style='display:flex; justify-content:space-between; align-items:center;'>
                        <h3 style='margin:0'>{p['symbol']} <span style='font-size:14px; color:#888'>{p['type']} {p['leverage']}x</span></h3>
                        <h3 style='margin:0; color:{color}'>${pnl:+.2f} ({roe:+.1f}%)</h3>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                c1, c2, c3, c4, c5, c6 = st.columns(6)
                c1.markdown(f"<div class='stat-box'><div class='stat-label'>ENTRY</div><div class='stat-value'>${p['entry']:.4f}</div></div>", unsafe_allow_html=True)
                c2.markdown(f"<div class='stat-box'><div class='stat-label'>MARK</div><div class='stat-value'>${curr:.4f}</div></div>", unsafe_allow_html=True)
                c3.markdown(f"<div class='stat-box'><div class='stat-label'>SIZE</div><div class='stat-value'>{p['size']:.3f}</div></div>", unsafe_allow_html=True)
                c4.markdown(f"<div class='stat-box'><div class='stat-label'>LIQ</div><div class='stat-value' style='color:red'>${liq:.4f}</div></div>", unsafe_allow_html=True)
                c5.markdown(f"<div class='stat-box'><div class='stat-label'>MARGIN</div><div class='stat-value'>${p['margin']:.0f}</div></div>", unsafe_allow_html=True)
                if c6.button("CLOSE", key=f"btn_{p['id']}", use_container_width=True):
                    close_order(p['id'])
                    st.rerun()
                st.write("")
        else: st.info("NO OPEN POSITIONS")

        st.markdown("### 📜 TRADE HISTORY")
        conn = get_db_connection()
        hist = pd.read_sql("SELECT time, symbol, action, price, size, pnl FROM history WHERE username=? ORDER BY rowid DESC LIMIT 20", conn, params=(user,))
        conn.close()
        st.dataframe(hist, use_container_width=True, hide_index=True)

    elif "LEADERBOARD" in page:
        st.markdown("<h1 class='main-title'>GLOBAL RANKINGS</h1>", unsafe_allow_html=True)
        if st.button("REFRESH"): st.rerun()
        conn = get_db_connection()
        users = pd.read_sql("SELECT * FROM users", conn)
        all_pos = pd.read_sql("SELECT * FROM positions", conn)
        conn.close()
        
        rank_data = []
        for _, u in users.iterrows():
            unrealized = 0
            u_pos = all_pos[all_pos['username'] == u['username']]
            for _, p in u_pos.iterrows():
                curr = get_price(p['symbol'])
                if p['type'] == 'LONG': unrealized += (curr - p['entry']) * p['size']
                else: unrealized += (p['entry'] - curr) * p['size']
            rank_data.append({"User": u['username'], "Av": u['avatar'], "Eq": u['balance']+unrealized})
            
        df = pd.DataFrame(rank_data).sort_values(by="Eq", ascending=False).reset_index()
        for i, r in df.iterrows():
            medal = "🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else f"#{i+1}"
            st.markdown(f"""
            <div style='padding:15px; margin-bottom:10px; border-radius:10px; background:rgba(255,255,255,0.05); display:flex; justify-content:space-between; align-items:center; border:1px solid #333'>
                <div style='display:flex; gap:15px; align-items:center;'>
                    <span style='font-size:24px'>{medal}</span><span style='font-size:30px'>{r['Av']}</span><span style='font-size:20px; font-weight:bold'>{r['User']}</span>
                </div>
                <div style='font-size:22px; color:#00f3ff; font-family:monospace'>${r['Eq']:,.0f}</div>
            </div>
            """, unsafe_allow_html=True)

    elif "SETTINGS" in page:
        st.markdown("### ⚙️ SETTINGS")
        np = st.text_input("NEW PASSWORD", type='password')
        if st.button("UPDATE"): change_password(user, np); st.success("SAVED")

    bot_logic(user)
    auto_sl_tp_check(user)
    time.sleep(2)
    st.rerun()

if __name__ == '__main__':
    init_db()
    if 'user' not in st.session_state: login_page()
    else: main_app()
