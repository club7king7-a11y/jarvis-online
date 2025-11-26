import streamlit as st
import pandas as pd
import time
from datetime import datetime
import random
import sqlite3
import hashlib
import requests
import streamlit.components.v1 as components

# === 1. 页面配置 & 赛博朋克 CSS ===
st.set_page_config(page_title="Jarvis OS 6.0", page_icon="☢️", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;700&family=Share+Tech+Mono&display=swap');
    
    :root { --neon-cyan: #00f3ff; --neon-gold: #ffd700; --neon-danger: #ff073a; --neon-green: #39ff14; --dark-bg: #0a0a12; }
    
    .stApp { background-color: var(--dark-bg); color: #fff; font-family: 'Rajdhani', sans-serif; }
    
    /* 侧边栏 */
    section[data-testid="stSidebar"] { background-color: #080808; border-right: 1px solid #333; }
    
    /* 标题与文字 */
    h1, h2, h3 { font-family: 'Share Tech Mono', monospace; text-transform: uppercase; letter-spacing: 2px; }
    .highlight { color: var(--neon-cyan); font-weight: bold; }
    
    /* 按钮 */
    .stButton button {
        background: rgba(0, 243, 255, 0.05) !important;
        border: 1px solid var(--neon-cyan) !important;
        color: var(--neon-cyan) !important;
        font-family: 'Share Tech Mono', monospace;
        transition: 0.3s;
    }
    .stButton button:hover {
        background: var(--neon-cyan) !important;
        color: #000 !important;
        box-shadow: 0 0 20px var(--neon-cyan);
    }
    
    /* 持仓卡片 */
    .pos-card {
        background: rgba(255,255,255,0.03);
        border-left: 3px solid #555;
        padding: 10px;
        margin-bottom: 10px;
        border-radius: 0 10px 10px 0;
    }
    .pos-long { border-left-color: var(--neon-green); }
    .pos-short { border-left-color: var(--neon-danger); }
    
    /* 机器人状态 */
    .bot-tag {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: bold;
        margin-left: 5px;
    }
</style>
""", unsafe_allow_html=True)

# === 2. 数据库核心 ===
DB_FILE = "jarvis_v6.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # 用户表：新增 active_strategy (机器人策略)
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, balance REAL, active_strategy TEXT, avatar TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS positions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, symbol TEXT, type TEXT, 
                  entry REAL, size REAL, leverage INTEGER, margin REAL, tp REAL, sl REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (time TEXT, username TEXT, symbol TEXT, action TEXT, price TEXT, size TEXT, pnl TEXT)''')
    conn.commit()
    conn.close()

# === 3. 用户与鉴权 ===
def make_hashes(p): return hashlib.sha256(str.encode(p)).hexdigest()
def check_hashes(p,h): return make_hashes(p) == h

def register_user(username, password, avatar):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        # 默认策略 "None"
        c.execute('INSERT INTO users VALUES (?,?,?,?,?)', (username, make_hashes(password), 10000.0, "None", avatar))
        conn.commit()
        return True
    except: return False
    finally: conn.close()

def login_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username=?', (username,))
    data = c.fetchone()
    conn.close()
    if data and check_hashes(password, data[1]): return data
    return None

def get_user_info(username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT balance, active_strategy, avatar FROM users WHERE username=?', (username,))
    res = c.fetchone()
    conn.close()
    return res if res else (0.0, "None", "👤")

def update_strategy(username, strategy):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('UPDATE users SET active_strategy = ? WHERE username=?', (strategy, username))
    conn.commit()
    conn.close()

def change_password(username, np):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('UPDATE users SET password=? WHERE username=?', (make_hashes(np), username))
    conn.commit()
    conn.close()

# === 4. 核心交易引擎 ===
# 获取价格 (防墙版)
def get_price(symbol):
    try:
        # 优先尝试币安
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"
        return float(requests.get(url, timeout=0.5).json()['price'])
    except:
        # 备用：CoinGecko
        try:
            ids = {"BTC":"bitcoin", "ETH":"ethereum", "SOL":"solana", "BNB":"binancecoin", "DOGE":"dogecoin", "XRP":"ripple", "ADA":"cardano", "PEPE":"pepe"}
            cid = ids.get(symbol, "bitcoin")
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={cid}&vs_currencies=usd"
            return float(requests.get(url, timeout=1).json()[cid]['usd'])
        except:
            # 最后的保底：仿真波动
            bases = {"BTC":96000, "ETH":3600, "SOL":230, "BNB":650, "XRP":1.4, "DOGE":0.4, "ADA":1.0, "PEPE":0.00002}
            return bases.get(symbol, 100) * random.uniform(0.995, 1.005)

def place_order(user, sym, side, margin, lev, tp=0.0, sl=0.0):
    bal, _, _ = get_user_info(user)
    if bal < margin: return False, "余额不足"
    
    price = get_price(sym)
    size = (margin * lev) / price
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('UPDATE users SET balance = balance - ? WHERE username=?', (margin, user))
    c.execute('INSERT INTO positions (username, symbol, type, entry, size, leverage, margin, tp, sl) VALUES (?,?,?,?,?,?,?,?,?,?)', 
              (user, sym, side, price, size, lev, margin, tp, sl))
    # 记录日志
    c.execute('INSERT INTO history VALUES (?,?,?,?,?,?,?)', 
              (datetime.now().strftime("%H:%M:%S"), user, sym, f"OPEN {side} {lev}x", f"${price:.4f}", f"{size:.4f}", "-"))
    conn.commit()
    conn.close()
    return True, "ORDER EXECUTED"

def close_order(id, reason="Manual"):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM positions WHERE id=?", (id,))
    p = c.fetchone()
    if p:
        # p: 0id, 1user, 2sym, 3type, 4entry, 5size, 6lev, 7mar, 8tp, 9sl
        curr = get_price(p[2])
        if p[3] == 'LONG': pnl = (curr - p[4]) * p[5]
        else: pnl = (p[4] - curr) * p[5]
        
        c.execute('UPDATE users SET balance = balance + ? WHERE username=?', (p[7] + pnl, p[1]))
        c.execute('DELETE FROM positions WHERE id=?', (id,))
        c.execute('INSERT INTO history VALUES (?,?,?,?,?,?,?)', 
                  (datetime.now().strftime("%H:%M:%S"), p[1], p[2], f"CLOSE ({reason})", f"${curr:.4f}", f"{p[5]:.4f}", f"${pnl:+.2f}"))
        conn.commit()
    conn.close()

# === 5. 机器人与后台监控 (三大核心) ===

def run_bot_engine(username):
    _, strategy, _ = get_user_info(username)
    if strategy == "None": return

    coins = ["BTC", "ETH", "SOL", "DOGE", "PEPE"]
    
    # 1. 🔫 狙击手 (Sniper): 高频、高杠杆
    if strategy == "Sniper" and random.random() < 0.2:
        target = random.choice(coins)
        price = get_price(target)
        side = random.choice(["LONG", "SHORT"])
        lev = 50
        margin = 100
        tp = price * 1.01 if side == 'LONG' else price * 0.99
        sl = price * 0.995 if side == 'LONG' else price * 1.005
        place_order(username, target, side, margin, lev, tp, sl)
        st.toast(f"🔫 Sniper Bot: {target} {side}", icon="💥")

    # 2. 🐋 巨鲸 (Whale): 低频、大仓位
    elif strategy == "Whale" and random.random() < 0.05:
        target = random.choice(["BTC", "ETH"])
        price = get_price(target)
        side = random.choice(["LONG", "SHORT"])
        lev = 5
        margin = 1000
        place_order(username, target, side, margin, lev, 0, 0) # 不设止损
        st.toast(f"🐋 Whale Bot: {target} {side}", icon="🌊")

    # 3. 🕸 网格 (Grid): 随机开单
    elif strategy == "Grid" and random.random() < 0.15:
        target = random.choice(coins)
        price = get_price(target)
        side = random.choice(["LONG", "SHORT"])
        place_order(username, target, side, 50, 20, price*1.02, price*0.98)
        st.toast(f"🕸 Grid Bot: {target} {side}", icon="🕷️")

def check_tp_sl_liq(username):
    conn = sqlite3.connect(DB_FILE)
    positions = pd.read_sql("SELECT * FROM positions WHERE username=?", conn, params=(username,))
    conn.close()
    
    for _, p in positions.iterrows():
        curr = get_price(p['symbol'])
        reason = None
        
        # 止盈止损
        if p['tp'] > 0:
            if (p['type'] == 'LONG' and curr >= p['tp']) or (p['type'] == 'SHORT' and curr <= p['tp']): reason = "🎯 TP"
        if p['sl'] > 0:
            if (p['type'] == 'LONG' and curr <= p['sl']) or (p['type'] == 'SHORT' and curr >= p['sl']): reason = "🛑 SL"
            
        # 强平
        liq_rate = 1 / p['leverage']
        liq_price = p['entry'] * (1 - liq_rate + 0.005) if p['type']=='LONG' else p['entry'] * (1 + liq_rate - 0.005)
        
        if (p['type']=='LONG' and curr <= liq_price) or (p['type']=='SHORT' and curr >= liq_price):
            reason = "💀 LIQUIDATED"
            
        if reason:
            close_order(p['id'], reason)

# === 6. UI 页面 ===
def login_page():
    st.markdown("<br><br><h1 style='text-align:center;'>JARVIS OS 6.0</h1>", unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["LOGIN", "REGISTER"])
    with tab1:
        u = st.text_input("USERNAME", key="l_u")
        p = st.text_input("PASSWORD", type='password', key="l_p")
        if st.button("CONNECT", use_container_width=True):
            if login_user(u, p):
                st.session_state['user'] = u
                st.rerun()
            else: st.error("DENIED")
    with tab2:
        c1, c2 = st.columns([1,2])
        with c1:
            ava = st.selectbox("AVATAR", ["👨‍🚀","🤖","👽","🦊","🐯","💀","👻","🤡","🦄","🐉"])
            st.markdown(f"<h1 style='text-align:center'>{ava}</h1>", unsafe_allow_html=True)
        with c2:
            nu = st.text_input("NEW USER", key="r_u")
            np = st.text_input("NEW PASS", type='password', key="r_p")
            if st.button("CREATE ID", use_container_width=True):
                if register_user(nu, np, ava): st.success("CREATED"); time.sleep(1); st.rerun()
                else: st.error("EXISTS")

def main_app():
    user = st.session_state['user']
    bal, strategy, avatar = get_user_info(user)
    
    # --- 侧边栏 ---
    with st.sidebar:
        st.markdown(f"<h1 style='text-align:center'>{avatar}</h1>", unsafe_allow_html=True)
        st.markdown(f"<h3 style='text-align:center'>{user}</h3>", unsafe_allow_html=True)
        st.metric("WALLET", f"${bal:,.2f}")
        
        page = st.radio("MENU", ["📈 TERMINAL", "🏆 LEADERBOARD", "⚙️ SETTINGS"], label_visibility="collapsed")
        
        st.divider()
        st.markdown("### 🤖 BOT STRATEGY")
        
        # 机器人选择器
        options = ["None", "Sniper", "Whale", "Grid"]
        idx = options.index(strategy) if strategy in options else 0
        new_strat = st.selectbox("Select AI Model:", options, index=idx)
        
        if new_strat != strategy:
            update_strategy(user, new_strat)
            st.rerun()
            
        if new_strat != "None":
            st.info(f"Running: {new_strat} AI")
        
        st.divider()
        if st.button("LOGOUT"):
            del st.session_state['user']
            st.rerun()

    # --- 页面 1: 交易终端 ---
    if "TERMINAL" in page:
        # TradingView
        c_tv, c_panel = st.columns([3, 1])
        with c_panel:
            st.markdown("### ⚡️ COMMAND")
            sym = st.selectbox("ASSET", ["BTC", "ETH", "SOL", "BNB", "DOGE", "PEPE", "WIF"])
            
            # 显示实时价格
            price = get_price(sym)
            st.markdown(f"<h2 style='color:#00f3ff'>${price:,.4f}</h2>", unsafe_allow_html=True)
            
            lev = st.slider("LEV (x)", 1, 125, 20)
            mar = st.number_input("MARGIN", 100)
            tp = st.number_input("TP (Optional)", 0.0)
            sl = st.number_input("SL (Optional)", 0.0)
            
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
            # 嵌入 TradingView
            components.html(f"""
            <div class="tradingview-widget-container">
              <div id="tradingview_main"></div>
              <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
              <script type="text/javascript">
              new TradingView.widget(
              {{ "width": "100%", "height": 550, "symbol": "BINANCE:{sym}USDT", "interval": "15", "timezone": "Asia/Shanghai", "theme": "dark", "style": "1", "locale": "en", "enable_publishing": false, "allow_symbol_change": true, "container_id": "tradingview_main" }}
              );
              </script>
            </div>
            """, height=550)

        # 详细持仓列表
        st.markdown("### 📊 LIVE POSITIONS")
        conn = sqlite3.connect(DB_FILE)
        pos = pd.read_sql("SELECT * FROM positions WHERE username=?", conn, params=(user,))
        conn.close()
        
        if not pos.empty:
            # 表头
            c1, c2, c3, c4, c5, c6 = st.columns([1,1,1,1,1,1])
            c1.markdown("SYMBOL")
            c2.markdown("SIDE/LEV")
            c3.markdown("ENTRY/MARK")
            c4.markdown("LIQ PRICE")
            c5.markdown("ROE / PNL")
            c6.markdown("ACTION")
            
            st.markdown("---")
            
            for _, p in pos.iterrows():
                curr = get_price(p['symbol'])
                # 计算指标
                if p['type'] == 'LONG': 
                    pnl = (curr - p['entry']) * p['size']
                    liq = p['entry'] * (1 - 1/p['leverage'] + 0.005)
                else: 
                    pnl = (p['entry'] - curr) * p['size']
                    liq = p['entry'] * (1 + 1/p['leverage'] - 0.005)
                
                roe = (pnl / p['margin']) * 100
                color = "#39ff14" if pnl >= 0 else "#ff073a"
                type_color = "var(--neon-green)" if p['type'] == 'LONG' else "var(--neon-danger)"
                
                # 渲染单行
                cc1, cc2, cc3, cc4, cc5, cc6 = st.columns([1,1,1,1,1,1])
                cc1.write(f"**{p['symbol']}**")
                cc2.markdown(f"<span style='color:{type_color}'>{p['type']} {p['leverage']}x</span>", unsafe_allow_html=True)
                cc3.write(f"${p['entry']:.4f} / ${curr:.4f}")
                cc4.markdown(f"<span style='color:red'>${liq:.4f}</span>", unsafe_allow_html=True)
                cc5.markdown(f"<span style='color:{color}'>{roe:.1f}% (${pnl:.1f})</span>", unsafe_allow_html=True)
                if cc6.button("CLOSE", key=f"cl_{p['id']}"):
                    close_order(p['id'])
                    st.rerun()
                st.markdown("<hr style='margin:5px 0; opacity:0.1'>", unsafe_allow_html=True)
        else:
            st.info("NO POSITIONS")

    # --- 页面 2: 排行榜 ---
    elif "LEADERBOARD" in page:
        st.markdown("<h1 class='main-title'>GLOBAL RANKINGS</h1>", unsafe_allow_html=True)
        if st.button("REFRESH"): st.rerun()
        
        conn = sqlite3.connect(DB_FILE)
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
            border = "1px solid #00f3ff" if r['User'] == user else "1px solid #333"
            st.markdown(f"""
            <div style='border:{border}; padding:15px; margin-bottom:10px; border-radius:10px; background:rgba(255,255,255,0.05); display:flex; justify-content:space-between; align-items:center;'>
                <div style='display:flex; gap:15px; align-items:center;'>
                    <span style='font-size:24px'>{medal}</span>
                    <span style='font-size:30px'>{r['Av']}</span>
                    <span style='font-size:20px; font-weight:bold'>{r['User']}</span>
                </div>
                <div style='font-size:22px; color:#00f3ff; font-family:monospace'>${r['Eq']:,.0f}</div>
            </div>
            """, unsafe_allow_html=True)

    # --- 页面 3: 设置 ---
    elif "SETTINGS" in page:
        st.markdown("### ⚙️ SECURITY")
        np = st.text_input("NEW PASSWORD", type='password')
        if st.button("UPDATE PASSWORD"):
            change_password(user, np)
            st.success("UPDATED")

    # === 后台循环 (实时更新的核心) ===
    # 1. 运行机器人
    run_bot_engine(user)
    # 2. 检查止盈止损
    check_tp_sl_liq(user)
    
    # 3. 自动刷新 (每2秒重载页面，实现实时跳动)
    time.sleep(2)
    st.rerun()

if __name__ == '__main__':
    init_db()
    if 'user' not in st.session_state: login_page()
    else: main_app()
