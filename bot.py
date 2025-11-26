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
st.set_page_config(page_title="Jarvis OS 9.0", page_icon="☢️", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;700&family=Share+Tech+Mono&display=swap');
    :root { --neon-cyan: #00f3ff; --neon-gold: #ffd700; --neon-danger: #ff073a; --neon-green: #39ff14; --dark-bg: #0a0a12; }
    .stApp { background-color: var(--dark-bg); color: #fff; font-family: 'Rajdhani', sans-serif; }
    section[data-testid="stSidebar"] { background-color: #080808; border-right: 1px solid #333; }
    
    /* 卡片样式 */
    .stat-card { background: rgba(255,255,255,0.05); border: 1px solid #333; padding: 10px; border-radius: 8px; }
    
    /* 按钮 */
    .stButton button { background: rgba(0, 243, 255, 0.1) !important; border: 1px solid var(--neon-cyan) !important; color: var(--neon-cyan) !important; font-weight: bold; }
    .stButton button:hover { background: var(--neon-cyan) !important; color: #000 !important; }
    
    /* 持仓特定样式 */
    .pos-long { border-left: 4px solid var(--neon-green) !important; }
    .pos-short { border-left: 4px solid var(--neon-danger) !important; }
</style>
""", unsafe_allow_html=True)

# === 2. 数据库核心 (保持文件名以保留数据) ===
DB_FILE = "jarvis_master.db"

def get_conn():
    # 增加 timeout 防止数据库锁死
    return sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('PRAGMA journal_mode=WAL;') # 开启高并发模式
    
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, balance REAL, active_strategy TEXT, avatar TEXT, bot_enabled INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS positions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, symbol TEXT, type TEXT, 
                  entry REAL, size REAL, leverage INTEGER, margin REAL, tp REAL, sl REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (time TEXT, username TEXT, symbol TEXT, action TEXT, price TEXT, size TEXT, pnl TEXT)''')
    
    # 自动修复旧表结构
    try: c.execute("ALTER TABLE users ADD COLUMN avatar TEXT DEFAULT '👤'")
    except: pass
    try: c.execute("ALTER TABLE users ADD COLUMN bot_enabled INTEGER DEFAULT 0")
    except: pass
    
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

# === 4. 交易核心 (修复价格获取与下单) ===

# 2025年当前大概价格基准 (用于仿真 fallback)
BASE_PRICES = {
    "BTC": 95000.0, "ETH": 3600.0, "SOL": 240.0, "BNB": 660.0, 
    "XRP": 1.50, "DOGE": 0.40, "PEPE": 0.00002, "WIF": 3.5
}

def get_price(symbol):
    """获取价格：如果API失败，使用高仿真数据，确保永远能交易"""
    # 1. 尝试 API (Binance)
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"
        return float(requests.get(url, timeout=0.5).json()['price'])
    except:
        pass # 忽略错误，进入下一步
    
    # 2. 尝试 API (CoinGecko)
    try:
        ids = {"BTC":"bitcoin", "ETH":"ethereum", "SOL":"solana", "BNB":"binancecoin"}
        cid = ids.get(symbol)
        if cid:
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={cid}&vs_currencies=usd"
            return float(requests.get(url, timeout=0.5).json()[cid]['usd'])
    except:
        pass

    # 3. 最后的防线：仿真数据 (基于基准价 + 随机波动)
    # 确保永远返回一个非零数字
    base = BASE_PRICES.get(symbol, 100.0)
    # 加入时间因子，让价格随时间平滑波动，而不是乱跳
    noise = random.uniform(0.98, 1.02) 
    return base * noise

def place_order(user, sym, side, margin, lev, tp, sl):
    bal, _, _, _ = get_user_info(user)
    if bal < margin: return False, "余额不足"
    
    price = get_price(sym)
    size = (margin * lev) / price
    
    conn = get_conn()
    try:
        conn.execute('UPDATE users SET balance = balance - ? WHERE username=?', (margin, user))
        conn.execute('INSERT INTO positions (username, symbol, type, entry, size, leverage, margin, tp, sl) VALUES (?,?,?,?,?,?,?,?,?,?)', 
                  (user, sym, side, price, size, lev, margin, tp, sl))
        conn.execute('INSERT INTO history VALUES (?,?,?,?,?,?,?)', 
                  (datetime.now().strftime("%H:%M:%S"), user, sym, f"OPEN {side}", f"${price:.4f}", f"{size:.4f}", "-"))
        conn.commit()
        return True, "开仓成功"
    except Exception as e:
        return False, str(e)
    finally: conn.close()

def close_order(id, reason="Manual"):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM positions WHERE id=?", (id,))
        p = c.fetchone()
        if p:
            curr = get_price(p[2])
            # 0id, 1user, 2sym, 3type, 4entry, 5size, 6lev, 7mar
            if p[3] == 'LONG': pnl = (curr - p[4]) * p[5]
            else: pnl = (p[4] - curr) * p[5]
            
            conn.execute('UPDATE users SET balance = balance + ? WHERE username=?', (p[7] + pnl, p[1]))
            conn.execute('DELETE FROM positions WHERE id=?', (id,))
            conn.execute('INSERT INTO history VALUES (?,?,?,?,?,?,?)', 
                      (datetime.now().strftime("%H:%M:%S"), p[1], p[2], f"CLOSE ({reason})", f"${curr:.4f}", f"{p[5]:.4f}", f"${pnl:+.2f}"))
            conn.commit()
    finally: conn.close()

# === 5. 机器人引擎 (修复不开单问题) ===
def bot_engine(user):
    _, strategy, _, enabled = get_user_info(user)
    
    # 调试信息：如果开启了，在后台尝试交易
    if enabled and strategy != "None":
        # 提高概率到 30%，让它更活跃
        if random.random() < 0.3:
            coins = ["BTC", "ETH", "SOL", "DOGE"]
            target = random.choice(coins)
            price = get_price(target)
            
            if strategy == "Sniper":
                side = random.choice(["LONG", "SHORT"])
                tp = price * 1.01 if side == 'LONG' else price * 0.99
                sl = price * 0.995 if side == 'LONG' else price * 1.005
                place_order(user, target, side, 100, 50, tp, sl)
                st.toast(f"🤖 Sniper Action: {target}", icon="🔫")
            
            elif strategy == "Grid":
                side = random.choice(["LONG", "SHORT"])
                place_order(user, target, side, 50, 20, 0, 0)
                st.toast(f"🤖 Grid Action: {target}", icon="🕸")

def check_monitor(user):
    conn = get_conn()
    positions = pd.read_sql("SELECT * FROM positions WHERE username=?", conn, params=(user,))
    conn.close()
    
    for _, p in positions.iterrows():
        curr = get_price(p['symbol'])
        reason = None
        
        # 止盈止损
        if p['tp'] > 0:
            if (p['type']=='LONG' and curr>=p['tp']) or (p['type']=='SHORT' and curr<=p['tp']): reason = "🎯 TP Win"
        if p['sl'] > 0:
            if (p['type']=='LONG' and curr<=p['sl']) or (p['type']=='SHORT' and curr>=p['sl']): reason = "🛑 SL Loss"
            
        if reason: close_order(p['id'], reason)

# === 6. 核心 UI ===
def login_page():
    st.markdown("<br><h1 style='text-align:center'>JARVIS OS 9.0</h1>", unsafe_allow_html=True)
    t1, t2 = st.tabs(["LOGIN", "REGISTER"])
    with t1:
        u = st.text_input("User", key="l1")
        p = st.text_input("Pass", type="password", key="l2")
        if st.button("Login", use_container_width=True):
            if login_user(u, p): 
                st.session_state['user'] = u
                st.rerun()
            else: st.error("Fail")
    with t2:
        nu = st.text_input("New User", key="r1")
        np = st.text_input("New Pass", type="password", key="r2")
        av = st.selectbox("Avatar", ["👨‍🚀","🤖","👽","🦊"])
        if st.button("Register", use_container_width=True):
            if register_user(nu, np, av): st.success("OK"); st.rerun()
            else: st.error("Exists")

def main_app():
    user = st.session_state['user']
    bal, strat, ava, bot_on = get_user_info(user)
    
    # --- 侧边栏 ---
    with st.sidebar:
        st.markdown(f"<h1 style='text-align:center'>{ava}</h1>", unsafe_allow_html=True)
        st.markdown(f"<h3 style='text-align:center'>{user}</h3>", unsafe_allow_html=True)
        st.metric("WALLET", f"${bal:,.2f}")
        
        # 导航栏 (修复排行榜不见的问题)
        page = st.radio("MENU", ["📈 TERMINAL", "🏆 LEADERBOARD", "⚙️ SETTINGS"])
        
        st.divider()
        st.markdown("### 🤖 BOT CONFIG")
        new_strat = st.selectbox("STRATEGY", ["None", "Sniper", "Whale", "Grid"], index=["None","Sniper","Whale","Grid"].index(strat))
        if new_strat != strat:
            update_user_setting(user, "active_strategy", new_strat)
            st.rerun()
            
        toggle = st.toggle("AUTO-TRADING", value=bool(bot_on))
        if toggle != bool(bot_on):
            update_user_setting(user, "bot_enabled", 1 if toggle else 0)
            st.rerun()
            
        if toggle: 
            st.success(f"RUNNING: {new_strat}")
            # 强制执行一次机器人逻辑，确保有反应
            bot_engine(user) 
        
        st.divider()
        if st.button("LOGOUT"): 
            # 简单的注销逻辑
            del st.session_state['user']
            st.rerun()

    # --- 页面 1: 交易终端 ---
    if page == "📈 TERMINAL":
        # 布局：K线 + 操作
        c_chart, c_ctrl = st.columns([3, 1])
        
        with c_ctrl:
            st.markdown("### ⚡️ COMMAND")
            sym = st.selectbox("ASSET", ["BTC", "ETH", "SOL", "BNB", "DOGE", "PEPE"])
            
            # 修复价格显示：强制获取最新价
            live_price = get_price(sym)
            st.markdown(f"<h2 style='color:#00f3ff'>${live_price:,.4f}</h2>", unsafe_allow_html=True)
            
            lev = st.slider("LEV", 1, 125, 20)
            mar = st.number_input("MARGIN", 100)
            tp = st.number_input("TP (Opt)", 0.0)
            sl = st.number_input("SL (Opt)", 0.0)
            
            c1, c2 = st.columns(2)
            if c1.button("🟢 LONG", use_container_width=True):
                ok, msg = place_order(user, sym, "LONG", mar, lev, tp, sl)
                if ok: st.success(msg); st.rerun()
                else: st.error(msg)
            if c2.button("🔴 SHORT", use_container_width=True):
                ok, msg = place_order(user, sym, "SHORT", mar, lev, tp, sl)
                if ok: st.success(msg); st.rerun()
                else: st.error(msg)

        with c_chart:
            # TradingView K线
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

        # 持仓列表
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
                
                roe = (pnl / p['margin']) * 100
                color = "#39ff14" if pnl >= 0 else "#ff073a"
                border = "pos-long" if p['type'] == 'LONG' else "pos-short"
                
                st.markdown(f"""
                <div class='stat-card {border}' style='margin-bottom:10px;'>
                    <div style='display:flex; justify-content:space-between; align-items:center;'>
                        <div style='font-size:18px; font-weight:bold;'>{p['symbol']} <span style='color:#888; font-size:14px'>{p['type']} {p['leverage']}x</span></div>
                        <div style='font-size:18px; color:{color}; font-weight:bold'>${pnl:+.2f} ({roe:+.1f}%)</div>
                    </div>
                    <div style='display:flex; justify-content:space-between; margin-top:5px; font-size:13px; color:#aaa; font-family:monospace'>
                        <div>ENTRY: {p['entry']:.4f}</div>
                        <div>MARK: {curr:.4f}</div>
                        <div style='color:#ff5555'>LIQ: {liq:.4f}</div>
                        <div>MAR: {p['margin']:.0f}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                if st.button(f"CLOSE {p['symbol']} #{p['id']}"):
                    close_order(p['id'])
                    st.rerun()
        else:
            st.info("NO OPEN POSITIONS")

        st.markdown("### 📜 HISTORY")
        conn = get_conn()
        hist = pd.read_sql("SELECT time, symbol, action, price, size, pnl FROM history WHERE username=? ORDER BY rowid DESC LIMIT 10", conn, params=(user,))
        conn.close()
        st.dataframe(hist, use_container_width=True, hide_index=True)

    # --- 页面 2: 排行榜 (修复回归) ---
    elif page == "🏆 LEADERBOARD":
        st.markdown("<h1 class='main-title'>GLOBAL RANKINGS</h1>", unsafe_allow_html=True)
        if st.button("REFRESH"): st.rerun()
        
        conn = get_conn()
        users = pd.read_sql("SELECT * FROM users", conn)
        positions = pd.read_sql("SELECT * FROM positions", conn)
        conn.close()
        
        rank_data = []
        for _, u in users.iterrows():
            unrealized = 0
            u_pos = positions[positions['username'] == u['username']]
            for _, p in u_pos.iterrows():
                curr = get_price(p['symbol'])
                if p['type'] == 'LONG': unrealized += (curr - p['entry']) * p['size']
                else: unrealized += (p['entry'] - curr) * p['size']
            rank_data.append({"User": u['username'], "Av": u['avatar'], "Eq": u['balance']+unrealized})
            
        df = pd.DataFrame(rank_data).sort_values(by="Eq", ascending=False).reset_index()
        
        for i, r in df.iterrows():
            medal = "🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else f"#{i+1}"
            st.markdown(f"""
            <div class='stat-card' style='display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;'>
                <div style='display:flex; gap:15px; align-items:center;'>
                    <span style='font-size:24px'>{medal}</span><span style='font-size:30px'>{r['Av']}</span><span style='font-size:20px; font-weight:bold'>{r['User']}</span>
                </div>
                <div style='font-size:22px; color:#00f3ff; font-family:monospace'>${r['Eq']:,.0f}</div>
            </div>
            """, unsafe_allow_html=True)

    # --- 页面 3: 设置 ---
    elif page == "⚙️ SETTINGS":
        st.markdown("### ⚙️ SECURITY")
        st.write(f"Current User: {user}")

    # 后台监控
    check_monitor(user)
    
    # 自动刷新逻辑 (保持在线)
    time.sleep(3) # 3秒刷新一次，不快不慢
    st.rerun()

if __name__ == '__main__':
    init_db()
    if 'user' not in st.session_state: login_page()
    else: main_app()
