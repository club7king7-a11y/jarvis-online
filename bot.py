import streamlit as st
import pandas as pd
import time
from datetime import datetime
import random
import sqlite3
import hashlib
import requests
import streamlit.components.v1 as components

# === 1. 页面配置 & 赛博朋克 UI ===
st.set_page_config(page_title="Jarvis OS 5.0", page_icon="☢️", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;700&family=Share+Tech+Mono&display=swap');
    
    :root { 
        --neon-cyan: #00f3ff; 
        --neon-gold: #ffd700;
        --neon-danger: #ff073a;
        --neon-green: #39ff14;
        --dark-bg: #0a0a12;
    }
    
    .stApp { 
        background-color: var(--dark-bg); 
        color: #fff; 
        font-family: 'Rajdhani', sans-serif;
        background-image: radial-gradient(circle at 50% 50%, rgba(0, 243, 255, 0.05) 0%, transparent 50%);
    }
    
    /* 侧边栏 */
    section[data-testid="stSidebar"] { 
        background-color: #05050a; 
        border-right: 1px solid rgba(0, 243, 255, 0.2); 
    }
    
    /* 标题特效 */
    h1, h2, h3 { font-family: 'Share Tech Mono', monospace; text-transform: uppercase; letter-spacing: 2px; }
    .main-title {
        background: -webkit-linear-gradient(0deg, var(--neon-cyan), #bd00ff);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-shadow: 0 0 20px rgba(0, 243, 255, 0.3);
    }
    
    /* 按钮特效 */
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
        box-shadow: 0 0 15px var(--neon-cyan);
    }

    /* 头像样式 */
    .avatar-circle {
        font-size: 50px;
        text-align: center;
        margin-bottom: 10px;
        text-shadow: 0 0 10px rgba(255,255,255,0.5);
    }
    
    /* 排行榜卡片 */
    .rank-card {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        padding: 10px;
        border-radius: 10px;
        margin-bottom: 5px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
</style>
""", unsafe_allow_html=True)

# === 2. 数据库核心 (自动升级) ===
DB_FILE = "jarvis_v5.db" # 新数据库，防止冲突

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # 用户表：新增 avatar 列
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, balance REAL, bot_active INTEGER, avatar TEXT)''')
    # 持仓表
    c.execute('''CREATE TABLE IF NOT EXISTS positions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, symbol TEXT, type TEXT, entry REAL, size REAL, leverage INTEGER, margin REAL)''')
    # 历史表
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (time TEXT, username TEXT, symbol TEXT, action TEXT, price TEXT, size TEXT, pnl TEXT)''')
    conn.commit()
    conn.close()

# === 3. 安全与用户管理 ===
def make_hashes(p): return hashlib.sha256(str.encode(p)).hexdigest()
def check_hashes(p,h): return make_hashes(p) == h

def register_user(username, password, avatar):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users VALUES (?,?,?,?,?)', (username, make_hashes(password), 10000.0, 0, avatar))
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

def change_password(username, old_pass, new_pass):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT password FROM users WHERE username=?', (username,))
    stored_hash = c.fetchone()[0]
    if check_hashes(old_pass, stored_hash):
        c.execute('UPDATE users SET password=? WHERE username=?', (make_hashes(new_pass), username))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def get_user_info(username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT balance, bot_active, avatar FROM users WHERE username=?', (username,))
    res = c.fetchone()
    conn.close()
    return res if res else (0.0, 0, "👤")

# === 4. 交易核心 (带备用价格源) ===
def get_price_backend(symbol):
    """后台获取价格用于计算盈亏 (防墙版)"""
    try:
        # 优先尝试币安 (如果服务器未被墙)
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"
        return float(requests.get(url, timeout=0.5).json()['price'])
    except:
        try:
            # 备用：CoinGecko
            ids = {"BTC":"bitcoin", "ETH":"ethereum", "SOL":"solana", "BNB":"binancecoin", "DOGE":"dogecoin", "XRP":"ripple", "ADA":"cardano", "PEPE":"pepe"}
            cid = ids.get(symbol, "bitcoin")
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={cid}&vs_currencies=usd"
            return float(requests.get(url, timeout=1).json()[cid]['usd'])
        except:
            # 最后的保底：生成微小波动的随机价格 (防止程序死锁)
            bases = {"BTC":96000, "ETH":3600, "SOL":230, "BNB":650, "XRP":1.4, "DOGE":0.4, "ADA":1.0, "PEPE":0.00002}
            base = bases.get(symbol, 100)
            return base * random.uniform(0.99, 1.01)

def place_order(user, sym, side, margin, lev):
    bal, _, _ = get_user_info(user)
    if bal < margin: return False, "余额不足 / Insufficient Funds"
    
    price = get_price_backend(sym)
    size = (margin * lev) / price
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('UPDATE users SET balance = balance - ? WHERE username=?', (margin, user))
    c.execute('INSERT INTO positions (username, symbol, type, entry, size, leverage, margin) VALUES (?,?,?,?,?,?,?)', 
              (user, sym, side, price, size, lev, margin))
    c.execute('INSERT INTO history VALUES (?,?,?,?,?,?,?)', 
              (datetime.now().strftime("%H:%M"), user, sym, f"OPEN {side}", f"{price:.4f}", f"{size:.4f}", "-"))
    conn.commit()
    conn.close()
    return True, "ORDER EXECUTED"

def close_order(id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM positions WHERE id=?", (id,))
    p = c.fetchone()
    if p:
        curr = get_price_backend(p[2])
        if p[3] == 'LONG': pnl = (curr - p[4]) * p[5]
        else: pnl = (p[4] - curr) * p[5]
        
        c.execute('UPDATE users SET balance = balance + ? WHERE username=?', (p[7] + pnl, p[1]))
        c.execute('DELETE FROM positions WHERE id=?', (id,))
        c.execute('INSERT INTO history VALUES (?,?,?,?,?,?,?)', 
                  (datetime.now().strftime("%H:%M"), p[1], p[2], "CLOSE", f"{curr:.4f}", f"{p[5]:.4f}", f"{pnl:+.2f}"))
        conn.commit()
    conn.close()

# === 5. 机器人与排行榜 ===
def run_auto_bot(username):
    _, active, _ = get_user_info(username)
    if active and random.random() < 0.1: # 10% 概率触发
        coins = ["BTC", "ETH", "SOL", "DOGE"]
        target = random.choice(coins)
        side = random.choice(["LONG", "SHORT"])
        place_order(username, target, side, 100, 20)
        st.toast(f"🤖 BOT ACTION: {target} {side}", icon="⚡️")

def toggle_bot(username, status):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('UPDATE users SET bot_active = ? WHERE username=?', (1 if status else 0, username))
    conn.commit()
    conn.close()

def get_leaderboard():
    conn = sqlite3.connect(DB_FILE)
    users = pd.read_sql("SELECT username, balance, avatar FROM users", conn)
    positions = pd.read_sql("SELECT * FROM positions", conn)
    conn.close()
    
    data = []
    for _, u in users.iterrows():
        name = u['username']
        equity = u['balance']
        user_pos = positions[positions['username'] == name]
        pnl = 0
        for _, p in user_pos.iterrows():
            curr = get_price_backend(p['symbol'])
            if p['type'] == 'LONG': pnl += (curr - p['entry']) * p['size']
            else: pnl += (p['entry'] - curr) * p['size']
        
        data.append({"User": name, "Avatar": u['avatar'], "Equity": equity + pnl, "PNL": pnl})
    
    return pd.DataFrame(data).sort_values(by="Equity", ascending=False)

# === 6. UI 页面 ===
def login_page():
    st.markdown("""<br><h1 style='text-align:center;' class='main-title'>JARVIS OS 5.0</h1>""", unsafe_allow_html=True)
    
    tab1, tab2 = st.tabs(["ACCESS", "NEW IDENTITY"])
    
    with tab1:
        u = st.text_input("USERNAME", key="l_u")
        p = st.text_input("PASSWORD", type='password', key="l_p")
        if st.button("CONNECT", use_container_width=True):
            if login_user(u, p):
                st.session_state['user'] = u
                st.rerun()
            else: st.error("DENIED")
            
    with tab2:
        c1, c2 = st.columns([1, 2])
        with c1:
            st.markdown("### SELECT AVATAR")
            avatars = ["👨‍🚀", "🕵️‍♂️", "👸", "🤖", "👽", "🦊", "🐯", "💀", "👻", "🤡"]
            sel_avatar = st.selectbox("AVATAR", avatars)
            st.markdown(f"<div style='font-size:80px; text-align:center;'>{sel_avatar}</div>", unsafe_allow_html=True)
        with c2:
            nu = st.text_input("NEW USERNAME", key="r_u")
            np = st.text_input("NEW PASSWORD", type='password', key="r_p")
            if st.button("REGISTER IDENTITY", use_container_width=True):
                if register_user(nu, np, sel_avatar): st.success("SUCCESS"); time.sleep(1); st.rerun()
                else: st.error("EXISTS")

def main_app():
    user = st.session_state['user']
    bal, bot_active, avatar = get_user_info(user)
    
    # --- 侧边栏 (个人中心) ---
    with st.sidebar:
        st.markdown(f"<div class='avatar-circle'>{avatar}</div>", unsafe_allow_html=True)
        st.markdown(f"<h2 style='text-align:center;'>{user}</h2>", unsafe_allow_html=True)
        st.metric("NET WORTH", f"${bal:,.2f}")
        
        # 导航
        page = st.radio("MENU", ["📈 TERMINAL", "🏆 LEADERBOARD", "⚙️ SETTINGS"], label_visibility="collapsed")
        
        st.divider()
        # 机器人开关
        st.markdown("### 🤖 AUTO-PILOT")
        bot_on = st.toggle("ACTIVATE", value=bool(bot_active))
        if bot_on != bool(bot_active):
            toggle_bot(user, bot_on)
            st.rerun()
            
        st.divider()
        if st.button("LOGOUT"):
            del st.session_state['user']
            st.rerun()

    # --- 页面 1: 交易终端 (集成 TradingView) ---
    if "TERMINAL" in page:
        st.markdown(f"<h1 class='main-title'>MARKET UPLINK</h1>", unsafe_allow_html=True)
        
        c_chart, c_ctrl = st.columns([3, 1])
        
        with c_ctrl:
            st.markdown("### ⚡️ OPERATIONS")
            sym = st.selectbox("ASSET", ["BTC", "ETH", "SOL", "BNB", "DOGE", "PEPE"])
            
            # 使用 TradingView Widget
            components.html(f"""
            <div class="tradingview-widget-container">
              <div id="tradingview_b7f6c"></div>
              <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
              <script type="text/javascript">
              new TradingView.widget(
              {{ "width": "100%", "height": 300, "symbol": "BINANCE:{sym}USDT", "interval": "60", "timezone": "Etc/UTC", "theme": "dark", "style": "1", "locale": "en", "toolbar_bg": "#f1f3f6", "enable_publishing": false, "hide_top_toolbar": true, "save_image": false, "container_id": "tradingview_b7f6c" }}
              );
              </script>
            </div>
            """, height=300)
            
            lev = st.slider("LEVERAGE", 1, 125, 20)
            mar = st.number_input("MARGIN", 100)
            c1, c2 = st.columns(2)
            if c1.button("🟢 LONG", use_container_width=True):
                ok, msg = place_order(user, sym, "LONG", mar, lev)
                if ok: st.success(msg); st.rerun()
                else: st.error(msg)
            if c2.button("🔴 SHORT", use_container_width=True):
                ok, msg = place_order(user, sym, "SHORT", mar, lev)
                if ok: st.success(msg); st.rerun()
                else: st.error(msg)
        
        with c_chart:
            # 大图 TradingView
            components.html(f"""
            <div class="tradingview-widget-container">
              <div id="tradingview_main"></div>
              <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
              <script type="text/javascript">
              new TradingView.widget(
              {{ "width": "100%", "height": 600, "symbol": "BINANCE:{sym}USDT", "interval": "D", "timezone": "Etc/UTC", "theme": "dark", "style": "1", "locale": "en", "enable_publishing": false, "allow_symbol_change": true, "container_id": "tradingview_main" }}
              );
              </script>
            </div>
            """, height=600)

        # 底部：持仓与日志
        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("📊 POSITIONS")
            conn = sqlite3.connect(DB_FILE)
            pos = pd.read_sql("SELECT * FROM positions WHERE username=?", conn, params=(user,))
            conn.close()
            if not pos.empty:
                for _, p in pos.iterrows():
                    curr = get_price_backend(p['symbol'])
                    pnl = (curr - p['entry']) * p['size'] if p['type']=='LONG' else (p['entry'] - curr) * p['size']
                    color = "#00f3ff" if pnl>=0 else "#ff073a"
                    with st.expander(f"{p['symbol']} {p['type']} ({pnl:+.1f})"):
                        st.markdown(f"**PNL: <span style='color:{color}'>${pnl:+.2f}</span>**", unsafe_allow_html=True)
                        if st.button("CLOSE", key=f"c_{p['id']}"):
                            close_order(p['id'])
                            st.rerun()
            else: st.info("NO ACTIVE SIGNALS")
            
        with c2:
            st.subheader("📜 HISTORY")
            conn = sqlite3.connect(DB_FILE)
            hist = pd.read_sql("SELECT * FROM history WHERE username=? ORDER BY rowid DESC LIMIT 10", conn, params=(user,))
            conn.close()
            st.dataframe(hist, use_container_width=True, hide_index=True)

    # --- 页面 2: 排行榜 (带头像) ---
    elif "LEADERBOARD" in page:
        st.markdown(f"<h1 class='main-title'>GLOBAL RANKINGS</h1>", unsafe_allow_html=True)
        if st.button("🔄 REFRESH"): st.rerun()
        
        df = get_leaderboard()
        for i, row in df.iterrows():
            medal = "🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else f"#{i+1}"
            border = "1px solid #00f3ff" if row['User'] == user else "1px solid #333"
            st.markdown(f"""
            <div class='rank-card' style='border:{border}'>
                <div style='display:flex; align-items:center; gap:15px;'>
                    <span style='font-size:24px;'>{medal}</span>
                    <span style='font-size:30px;'>{row['Avatar']}</span>
                    <div>
                        <div style='font-weight:bold; font-size:18px;'>{row['User']}</div>
                        <div style='color:#888; font-size:12px;'>PNL: ${row['PNL']:.2f}</div>
                    </div>
                </div>
                <div style='font-size:20px; font-weight:bold; color:#00f3ff;'>${row['Equity']:,.0f}</div>
            </div>
            """, unsafe_allow_html=True)

    # --- 页面 3: 设置 (改密码) ---
    elif "SETTINGS" in page:
        st.markdown(f"<h1 class='main-title'>SECURITY SETTINGS</h1>", unsafe_allow_html=True)
        with st.expander("🔐 CHANGE PASSWORD", expanded=True):
            op = st.text_input("CURRENT PASSWORD", type='password')
            np = st.text_input("NEW PASSWORD", type='password')
            if st.button("UPDATE CREDENTIALS"):
                if change_password(user, op, np): st.success("PASSWORD UPDATED")
                else: st.error("INVALID CURRENT PASSWORD")

    # 自动执行机器人
    run_auto_bot(user)

if __name__ == '__main__':
    init_db()
    if 'user' not in st.session_state: login_page()
    else: main_app()
