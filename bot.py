import streamlit as st
import pandas as pd
import time
from datetime import datetime
import random
import sqlite3
import hashlib
import requests
import streamlit.components.v1 as components

# === 1. 页面配置与 Logo ===
st.set_page_config(page_title="Henry AI Bot", page_icon="🤖", layout="wide")

# 赛博朋克 LOGO (SVG)
HENRY_LOGO = """
<svg width="100%" height="120" viewBox="0 0 400 120" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="neon-grad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" style="stop-color:#00f3ff;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#bd00ff;stop-opacity:1" />
    </linearGradient>
    <filter id="glow">
      <feGaussianBlur stdDeviation="2.5" result="coloredBlur"/>
      <feMerge>
        <feMergeNode in="coloredBlur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
  </defs>
  <rect x="10" y="10" width="380" height="100" rx="15" fill="none" stroke="url(#neon-grad)" stroke-width="3" filter="url(#glow)"/>
  <path d="M50 60 L80 30 M50 60 L80 90 M350 60 L320 30 M350 60 L320 90" stroke="#39ff14" stroke-width="2" filter="url(#glow)"/>
  <circle cx="200" cy="60" r="30" fill="none" stroke="url(#neon-grad)" stroke-width="2"/>
  <text x="200" y="65" font-family="'Share Tech Mono', monospace" font-size="35" fill="url(#neon-grad)" text-anchor="middle" font-weight="bold" filter="url(#glow)">HENRY AI BOT</text>
  <text x="200" y="95" font-family="sans-serif" font-size="12" fill="#00f3ff" text-anchor="middle" letter-spacing="2">QUANTUM TRADING SYSTEM</text>
</svg>
"""

st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;700&family=Share+Tech+Mono&display=swap');
    :root {{ --neon-cyan: #00f3ff; --neon-green: #39ff14; --neon-red: #ff073a; --dark-bg: #0a0a12; }}
    .stApp {{ background-color: var(--dark-bg); color: #fff; font-family: 'Rajdhani', sans-serif; }}
    section[data-testid="stSidebar"] {{ background-color: #050505; border-right: 1px solid #333; }}
    
    .stButton button {{ background: rgba(0, 243, 255, 0.1) !important; border: 1px solid var(--neon-cyan) !important; color: var(--neon-cyan) !important; font-weight: bold; }}
    .stButton button:hover {{ background: var(--neon-cyan) !important; color: #000 !important; }}
    /* 红色按钮特化 */
    .stButton button[kind="primary"] {{ background: rgba(255, 7, 58, 0.2) !important; border: 1px solid var(--neon-red) !important; color: var(--neon-red) !important; }}
    .stButton button[kind="primary"]:hover {{ background: var(--neon-red) !important; color: #fff !important; }}

    .pos-card {{ background: rgba(20, 20, 30, 0.9); border: 1px solid #444; border-left: 4px solid #888; padding: 15px; margin-bottom: 10px; border-radius: 4px; }}
    .pos-long {{ border-left-color: var(--neon-green); }}
    .pos-short {{ border-left-color: var(--neon-red); }}
</style>
<div style='text-align:center; margin-bottom: 20px;'>{HENRY_LOGO}</div>
""", unsafe_allow_html=True)

# === 2. 数据库核心 (保留数据) ===
DB_FILE = "jarvis_production_v10.db" 

def get_conn():
    return sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
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

# === 4. 交易引擎 (修复历史价格 bug) ===
def get_price(symbol):
    # 优先使用仿真基准价，结合随机波动，确保价格稳定且永远存在
    bases = {"BTC":95000.0, "ETH":3650.0, "SOL":235.0, "BNB":655.0, "DOGE":0.41, "PEPE":0.000021}
    base = bases.get(symbol, 100.0)
    # 加上时间因子产生平滑波动
    noise = 1.0 + (time.time() % 100 / 1000.0 - 0.05)
    return base * noise

def place_order(user, sym, side, margin, lev, tp, sl):
    bal, _, _, _ = get_user_info(user)
    if bal < margin: return False, "Insufficient Balance"
    
    price = get_price(sym)
    size = (margin * lev) / price
    
    conn = get_conn()
    try:
        conn.execute('UPDATE users SET balance = balance - ? WHERE username=?', (margin, user))
        conn.execute('''INSERT INTO positions (username, symbol, type, entry, size, leverage, margin, tp, sl) 
                        VALUES (?,?,?,?,?,?,?,?,?)''', (user, sym, side, price, size, lev, margin, tp, sl))
        conn.execute('INSERT INTO history VALUES (?,?,?,?,?,?,?)', 
                     (datetime.now().strftime("%H:%M:%S"), user, sym, f"OPEN {side}", f"${price:.4f}", f"{size:.4f}", "-"))
        conn.commit()
        return True, f"Opened @ ${price:.2f}"
    except Exception as e:
        return False, str(e)
    finally: conn.close()

# 关键修复：增加 forced_price 参数用于准确记录触发价
def close_order(id, reason="Manual", forced_price=None):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM positions WHERE id=?", (id,))
        p = c.fetchone()
        if p:
            # 如果有强制触发价（TP/SL），就用它；否则获取现价
            curr = forced_price if forced_price is not None else get_price(p[2])
            
            if p[3] == 'LONG': pnl = (curr - p[4]) * p[5]
            else: pnl = (p[4] - curr) * p[5]
            
            conn.execute('UPDATE users SET balance = balance + ? WHERE username=?', (p[7] + pnl, p[1]))
            conn.execute('DELETE FROM positions WHERE id=?', (id,))
            conn.execute('INSERT INTO history VALUES (?,?,?,?,?,?,?)', 
                      (datetime.now().strftime("%H:%M:%S"), p[1], p[2], f"CLOSE ({reason})", f"${curr:.4f}", f"{p[5]:.4f}", f"${pnl:+.2f}"))
            conn.commit()
    finally: conn.close()

# === 5. 机器人引擎 (优化卡顿) ===
def bot_engine(user):
    _, strategy, _, enabled = get_user_info(user)
    if not enabled or strategy == "None": return

    # 优化：检查持仓数，超过5个就不开了，防止卡顿
    conn = get_conn()
    pos_count = conn.execute("SELECT COUNT(*) FROM positions WHERE username=?", (user,)).fetchone()[0]
    conn.close()
    if pos_count >= 5: return

    # 降低触发频率到 10%
    if random.random() < 0.1:
        coins = ["BTC", "ETH", "SOL", "DOGE", "PEPE"]
        target = random.choice(coins)
        price = get_price(target)
        
        if strategy == "Sniper":
            side = random.choice(["LONG", "SHORT"])
            tp = price * 1.015 if side == 'LONG' else price * 0.985
            sl = price * 0.99 if side == 'LONG' else price * 1.01
            success, _ = place_order(user, target, side, 100, 50, tp, sl)
            if success: st.toast(f"🔫 Sniper: {target} {side}", icon="💥")
            
        elif strategy == "Grid":
            side = random.choice(["LONG", "SHORT"])
            success, _ = place_order(user, target, side, 50, 20, 0, 0)
            if success: st.toast(f"🕸 Grid: {target} {side}", icon="🕷️")

# 关键修复：传递触发价格给 close_order
def check_monitor(user):
    conn = get_conn()
    positions = pd.read_sql("SELECT * FROM positions WHERE username=?", conn, params=(user,))
    conn.close()
    
    for _, p in positions.iterrows():
        curr = get_price(p['symbol'])
        reason = None
        trigger_price = None # 记录触发时的价格
        
        # 止盈
        if p['tp'] > 0:
            if (p['type']=='LONG' and curr>=p['tp']):
                reason, trigger_price = "TP Hit", p['tp']
            elif (p['type']=='SHORT' and curr<=p['tp']):
                reason, trigger_price = "TP Hit", p['tp']
        
        # 止损 (如果没触发止盈)
        if not reason and p['sl'] > 0:
            if (p['type']=='LONG' and curr<=p['sl']):
                reason, trigger_price = "SL Hit", p['sl']
            elif (p['type']=='SHORT' and curr>=p['sl']):
                reason, trigger_price = "SL Hit", p['sl']
            
        # 强平
        if not reason:
            liq_rate = 1 / p['leverage']
            liq = p['entry'] * (1 - liq_rate + 0.005) if p['type']=='LONG' else p['entry'] * (1 + liq_rate - 0.005)
            if (p['type']=='LONG' and curr<=liq) or (p['type']=='SHORT' and curr>=liq):
                 reason, trigger_price = "LIQUIDATED", liq
            
        if reason:
            # 将准确的触发价格传给平仓函数
            close_order(p['id'], reason, forced_price=trigger_price)

# === 6. UI 界面 ===
def login_page():
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
        av = st.selectbox("Avatar", ["👨‍🚀","🤖","👽","🦊","💀","🐲"])
        if st.button("Register", use_container_width=True):
            if register_user(nu, np, av): st.success("OK"); st.rerun()
            else: st.error("Taken")

def main_app():
    user = st.session_state['user']
    bal, strat, ava, bot_on = get_user_info(user)
    
    with st.sidebar:
        st.markdown(f"<h1 style='text-align:center; margin-bottom:0'>{ava}</h1><h3 style='text-align:center; margin-top:0'>{user}</h3>", unsafe_allow_html=True)
        st.metric("WALLET", f"${bal:,.2f}")
        page = st.radio("MENU", ["TERMINAL", "LEADERBOARD"], label_visibility="collapsed")
        
        st.divider()
        st.markdown("### 🤖 AI CONTROL")
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
            bot_engine(user)
        
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
            components.html(f"""<div class="tradingview-widget-container"><div id="tv_chart"></div><script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script><script type="text/javascript">new TradingView.widget({{ "width": "100%", "height": 500, "symbol": "BINANCE:{sym}USDT", "interval": "15", "timezone": "Asia/Shanghai", "theme": "dark", "style": "1", "locale": "en", "enable_publishing": false, "hide_top_toolbar": false, "container_id": "tv_chart" }});</script></div>""", height=500)

        st.markdown("### 📊 LIVE POSITIONS")
        conn = get_conn()
        pos = pd.read_sql("SELECT * FROM positions WHERE username=?", conn, params=(user,))
        conn.close()
        
        if not pos.empty:
            # 新增：一键全平按钮
            if st.button("🔥 CLOSE ALL POSITIONS 🔥", use_container_width=True, type="primary"):
                conn = get_conn()
                user_pos = pd.read_sql("SELECT id FROM positions WHERE username=?", conn, params=(user,))
                conn.close()
                for _, p_row in user_pos.iterrows():
                    close_order(p_row['id'], "Close All")
                st.rerun()

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
                if st.button(f"CLOSE {p['symbol']} #{p['id']}"): close_order(p['id']); st.rerun()
        else: st.info("NO OPEN POSITIONS")

        st.markdown("### 📜 HISTORY")
        conn = get_conn()
        hist = pd.read_sql("SELECT time, symbol, action, price, size, pnl FROM history WHERE username=? ORDER BY rowid DESC LIMIT 15", conn, params=(user,))
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
    time.sleep(3)
    st.rerun()

if __name__ == '__main__':
    init_db()
    if 'user' not in st.session_state: login_page()
    else: main_app()

