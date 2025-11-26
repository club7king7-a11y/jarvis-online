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
st.set_page_config(page_title="Jarvis OS X", page_icon="☢️", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;700&family=Share+Tech+Mono&display=swap');
    :root { --neon-cyan: #00f3ff; --neon-green: #39ff14; --neon-red: #ff073a; --dark-bg: #0a0a12; }
    .stApp { background-color: var(--dark-bg); color: #fff; font-family: 'Rajdhani', sans-serif; }
    section[data-testid="stSidebar"] { background-color: #050505; border-right: 1px solid #333; }
    
    .stat-box { border: 1px solid #333; padding: 10px; border-radius: 5px; background: rgba(255,255,255,0.05); text-align: center; }
    .stat-value { font-size: 16px; font-weight: bold; color: var(--neon-cyan); font-family: 'Share Tech Mono'; }
    
    .stButton button { background: rgba(0, 243, 255, 0.1) !important; border: 1px solid var(--neon-cyan) !important; color: var(--neon-cyan) !important; font-weight: bold; }
    .stButton button:hover { background: var(--neon-cyan) !important; color: #000 !important; }
    
    .pos-card { background: rgba(20, 20, 30, 0.9); border: 1px solid #444; border-left: 4px solid #888; padding: 15px; margin-bottom: 10px; border-radius: 4px; }
    .pos-long { border-left-color: var(--neon-green); }
    .pos-short { border-left-color: var(--neon-red); }
</style>
""", unsafe_allow_html=True)

# === 2. 数据库核心 (关键修复：更换新文件名) ===
DB_FILE = "jarvis_production_v10.db" 

def get_conn():
    return sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('PRAGMA journal_mode=WAL;')
    
    # 强制创建完整表结构
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

# === 4. 交易引擎 (带错误反馈) ===
def get_price(symbol):
    # 多源价格获取，确保不断网
    urls = [
        f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT",
        f"https://api.huobi.pro/market/detail/merged?symbol={symbol.lower()}usdt",
    ]
    for url in urls:
        try:
            res = requests.get(url, timeout=1).json()
            if 'price' in res: return float(res['price'])
            if 'tick' in res: return float(res['tick']['close'])
        except: continue
    
    # 仿真保底
    bases = {"BTC":96000, "ETH":3600, "SOL":230, "BNB":650, "DOGE":0.4, "PEPE":0.00002}
    return bases.get(symbol, 100) * random.uniform(0.99, 1.01)

def place_order(user, sym, side, margin, lev, tp, sl):
    # 1. 余额检查
    bal, _, _, _ = get_user_info(user)
    if bal < margin: return False, "Insufficient Balance"
    
    price = get_price(sym)
    size = (margin * lev) / price
    
    conn = get_conn()
    try:
        # 2. 事务写入
        conn.execute('UPDATE users SET balance = balance - ? WHERE username=?', (margin, user))
        conn.execute('''INSERT INTO positions (username, symbol, type, entry, size, leverage, margin, tp, sl) 
                        VALUES (?,?,?,?,?,?,?,?,?)''', (user, sym, side, price, size, lev, margin, tp, sl))
        conn.execute('INSERT INTO history VALUES (?,?,?,?,?,?,?)', 
                     (datetime.now().strftime("%H:%M:%S"), user, sym, f"OPEN {side}", f"${price:.4f}", f"{size:.4f}", "-"))
        conn.commit()
        return True, f"Opened @ ${price:.2f}"
    except Exception as e:
        return False, str(e) # 返回具体错误信息
    finally: conn.close()

def close_order(id, reason="Manual"):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM positions WHERE id=?", (id,))
        p = c.fetchone()
        if p:
            curr = get_price(p[2])
            if p[3] == 'LONG': pnl = (curr - p[4]) * p[5]
            else: pnl = (p[4] - curr) * p[5]
            
            conn.execute('UPDATE users SET balance = balance + ? WHERE username=?', (p[7] + pnl, p[1]))
            conn.execute('DELETE FROM positions WHERE id=?', (id,))
            conn.execute('INSERT INTO history VALUES (?,?,?,?,?,?,?)', 
                      (datetime.now().strftime("%H:%M:%S"), p[1], p[2], f"CLOSE ({reason})", f"${curr:.4f}", f"{p[5]:.4f}", f"${pnl:+.2f}"))
            conn.commit()
    finally: conn.close()

# === 5. 机器人引擎 (修复：只有成功才弹窗) ===
def bot_engine(user):
    _, strategy, _, enabled = get_user_info(user)
    if not enabled or strategy == "None": return

    # 提高触发概率到 20%
    if random.random() < 0.2:
        coins = ["BTC", "ETH", "SOL", "DOGE", "PEPE"]
        target = random.choice(coins)
        price = get_price(target)
        
        if strategy == "Sniper":
            side = random.choice(["LONG", "SHORT"])
            tp = price * 1.01 if side == 'LONG' else price * 0.99
            sl = price * 0.995 if side == 'LONG' else price * 1.005
            # 关键修改：获取返回值
            success, msg = place_order(user, target, side, 100, 50, tp, sl)
            if success: st.toast(f"🔫 Sniper: {target} {side}", icon="💥")
            
        elif strategy == "Grid":
            side = random.choice(["LONG", "SHORT"])
            success, msg = place_order(user, target, side, 50, 20, 0, 0)
            if success: st.toast(f"🕸 Grid: {target} {side}", icon="🕷️")

def check_monitor(user):
    conn = get_conn()
    positions = pd.read_sql("SELECT * FROM positions WHERE username=?", conn, params=(user,))
    conn.close()
    
    for _, p in positions.iterrows():
        curr = get_price(p['symbol'])
        reason = None
        
        if p['tp'] > 0:
            if (p['type']=='LONG' and curr>=p['tp']) or (p['type']=='SHORT' and curr<=p['tp']): reason = "TP Hit"
        if p['sl'] > 0:
            if (p['type']=='LONG' and curr<=p['sl']) or (p['type']=='SHORT' and curr>=p['sl']): reason = "SL Hit"
            
        liq_rate = 1 / p['leverage']
        liq = p['entry'] * (1 - liq_rate + 0.005) if p['type']=='LONG' else p['entry'] * (1 + liq_rate - 0.005)
        if (p['type']=='LONG' and curr<=liq) or (p['type']=='SHORT' and curr>=liq): reason = "LIQUIDATED"
            
        if reason: close_order(p['id'], reason)

# === 6. UI 界面 ===
def login_page():
    st.markdown("<br><br><h1 style='text-align:center'>JARVIS OS 10.0</h1>", unsafe_allow_html=True)
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
        av = st.selectbox("Avatar", ["👨‍🚀","🤖","👽","🦊","💀"])
        if st.button("Register", use_container_width=True):
            if register_user(nu, np, av): st.success("OK"); st.rerun()
            else: st.error("Taken")

def main_app():
    user = st.session_state['user']
    bal, strat, ava, bot_on = get_user_info(user)
    
    with st.sidebar:
        st.markdown(f"<h1 style='text-align:center'>{ava}</h1><h3 style='text-align:center'>{user}</h3>", unsafe_allow_html=True)
        st.metric("WALLET", f"${bal:,.2f}")
        page = st.radio("MENU", ["TERMINAL", "LEADERBOARD"], label_visibility="collapsed")
        
        st.divider()
        st.markdown("### 🤖 BOT CONTROL")
        new_strat = st.selectbox("STRATEGY", ["None", "Sniper", "Grid"], index=["None","Sniper","Grid"].index(strat))
        if new_strat != strat:
            update_user_setting(user, "active_strategy", new_strat)
            st.rerun()
            
        toggle = st.toggle("AUTO-TRADING", value=bool(bot_on))
        if toggle != bool(bot_on):
            update_user_setting(user, "bot_enabled", 1 if toggle else 0)
            st.rerun()
            
        if toggle: 
            st.success(f"ACTIVE: {new_strat}")
            bot_engine(user) # 尝试执行一次
        
        st.divider()
        if st.button("LOGOUT"): del st.session_state['user']; st.rerun()

    if page == "TERMINAL":
        c_chart, c_ctrl = st.columns([3, 1])
        with c_ctrl:
            st.markdown("### ⚡️ COMMAND")
            sym = st.selectbox("ASSET", ["BTC", "ETH", "SOL", "DOGE", "PEPE"])
            price = get_price(sym)
            st.markdown(f"<h2 style='color:#00f3ff'>${price:,.4f}</h2>", unsafe_allow_html=True)
            lev = st.slider("LEV", 1, 125, 20)
            mar = st.number_input("MARGIN", 100)
            tp = st.number_input("TP", 0.0)
            sl = st.number_input("SL", 0.0)
            
            c1, c2 = st.columns(2)
            if c1.button("🟢 LONG", use_container_width=True):
                res, msg = place_order(user, sym, "LONG", mar, lev, tp, sl)
                if res: st.success(msg); st.rerun()
                else: st.error(msg)
            if c2.button("🔴 SHORT", use_container_width=True):
                res, msg = place_order(user, sym, "SHORT", mar, lev, tp, sl)
                if res: st.success(msg); st.rerun()
                else: st.error(msg)

        with c_chart:
            components.html(f"""
            <div class="tradingview-widget-container">
              <div id="tv_chart"></div>
              <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
              <script type="text/javascript">
              new TradingView.widget(
              {{ "width": "100%", "height": 500, "symbol": "BINANCE:{sym}USDT", "interval": "15", "timezone": "Asia/Shanghai", "theme": "dark", "style": "1", "locale": "en", "enable_publishing": false, "hide_top_toolbar": false, "container_id": "tv_chart" }}
              );
              </script>
            </div>
            """, height=500)

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
                
                st.markdown(f"""
                <div class='pos-card {border}'>
                    <div style='display:flex; justify-content:space-between; align-items:center;'>
                        <div style='font-size:18px; font-weight:bold;'>{p['symbol']} <span style='color:#888; font-size:14px'>{p['type']} {p['leverage']}x</span></div>
                        <div style='font-size:18px; color:{color}; font-weight:bold'>${pnl:+.2f}</div>
                    </div>
                    <div style='display:flex; justify-content:space-between; margin-top:5px; font-size:13px; color:#aaa; font-family:monospace'>
                        <div>ENT: {p['entry']:.4f}</div>
                        <div>MK: {curr:.4f}</div>
                        <div>LIQ: <span style='color:#ff5555'>{liq:.4f}</span></div>
                        <div>TP/SL: {p['tp']}/{p['sl']}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                if st.button(f"CLOSE {p['symbol']} #{p['id']}"):
                    close_order(p['id'])
                    st.rerun()
        else: st.info("NO OPEN POSITIONS")

        st.markdown("### 📜 HISTORY")
        conn = get_conn()
        hist = pd.read_sql("SELECT time, symbol, action, price, size, pnl FROM history WHERE username=? ORDER BY rowid DESC LIMIT 10", conn, params=(user,))
        conn.close()
        st.dataframe(hist, use_container_width=True, hide_index=True)

    elif page == "LEADERBOARD":
        st.markdown("### 🏆 RANKING")
        if st.button("REFRESH"): st.rerun()
        conn = get_conn()
        users = pd.read_sql("SELECT * FROM users", conn)
        pos = pd.read_sql("SELECT * FROM positions", conn)
        conn.close()
        
        data = []
        for _, u in users.iterrows():
            unrealized = 0
            u_pos = pos[pos['username'] == u['username']]
            for _, p in u_pos.iterrows():
                curr = get_price(p['symbol'])
                if p['type'] == 'LONG': unrealized += (curr - p['entry']) * p['size']
                else: unrealized += (p['entry'] - curr) * p['size']
            data.append({"User": u['username'], "Av": u['avatar'], "Eq": u['balance']+unrealized})
            
        df = pd.DataFrame(data).sort_values(by="Eq", ascending=False).reset_index()
        for i, r in df.iterrows():
            st.markdown(f"""<div style='padding:10px; margin-bottom:5px; border:1px solid #333; border-radius:5px;'>#{i+1} {r['Av']} <b>{r['User']}</b> - <span style='color:#00f3ff'>${r['Eq']:,.0f}</span></div>""", unsafe_allow_html=True)

    check_monitor(user)
    time.sleep(2)
    st.rerun()

if __name__ == '__main__':
    init_db()
    if 'user' not in st.session_state: login_page()
    else: main_app()

