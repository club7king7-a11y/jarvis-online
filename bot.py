import streamlit as st
import pandas as pd
import time
from datetime import datetime
import random
import sqlite3
import hashlib
import requests
import streamlit.components.v1 as components # 引入组件功能

# === 1. 页面配置 ===
st.set_page_config(page_title="Jarvis Pro", page_icon="☢️", layout="wide")

# CSS 样式
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;700&family=Share+Tech+Mono&display=swap');
    :root { --neon-cyan: #00f3ff; --dark-bg: #0a0a12; }
    .stApp { background-color: var(--dark-bg); color: #fff; font-family: 'Rajdhani', sans-serif; }
    section[data-testid="stSidebar"] { background-color: #05050a; border-right: 1px solid #333; }
    
    /* 隐藏 Streamlit 默认的边距，让图表更大 */
    .block-container { padding-top: 1rem; padding-bottom: 1rem; }
    
    h1, h2, h3 { font-family: 'Share Tech Mono', monospace; text-transform: uppercase; }
    .stButton button {
        background: rgba(0, 243, 255, 0.1) !important;
        border: 1px solid var(--neon-cyan) !important;
        color: var(--neon-cyan) !important;
        font-family: 'Share Tech Mono', monospace;
    }
    .stButton button:hover {
        background: var(--neon-cyan) !important;
        color: #000 !important;
        box-shadow: 0 0 20px var(--neon-cyan);
    }
</style>
""", unsafe_allow_html=True)

# === 2. 数据库 (保持不变) ===
DB_FILE = "jarvis_tv_v4.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, balance REAL, bot_active INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS positions (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, symbol TEXT, type TEXT, entry REAL, size REAL, leverage INTEGER, margin REAL)''')
    conn.commit()
    conn.close()

def make_hashes(p): return hashlib.sha256(str.encode(p)).hexdigest()
def check_hashes(p,h): return make_hashes(p) == h

# === 3. 核心功能 ===
def get_user_data(username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT balance, bot_active FROM users WHERE username=?', (username,))
    res = c.fetchone()
    conn.close()
    return res if res else (0.0, 0)

def place_order(user, sym, side, margin, lev):
    bal, _ = get_user_data(user)
    if bal < margin: return False, "余额不足"
    
    # 获取价格 (如果是云端，尝试用 CoinGecko 替代 Binance API 防止被墙)
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={sym}USDT"
        price = float(requests.get(url, timeout=1).json()['price'])
    except:
        # 备用：CoinGecko API (免费且不屏蔽美国)
        try:
            cg_id = {"BTC":"bitcoin", "ETH":"ethereum", "SOL":"solana", "BNB":"binancecoin", "DOGE":"dogecoin"}.get(sym, "bitcoin")
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd"
            price = float(requests.get(url, timeout=1).json()[cg_id]['usd'])
        except:
            return False, "无法获取价格 (API Blocked)"

    size = (margin * lev) / price
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('UPDATE users SET balance = balance - ? WHERE username=?', (margin, user))
    c.execute('INSERT INTO positions (username, symbol, type, entry, size, leverage, margin) VALUES (?,?,?,?,?,?,?)', 
              (user, sym, side, price, size, lev, margin))
    conn.commit()
    conn.close()
    return True, f"开仓成功 @ ${price:.2f}"

def close_order(id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM positions WHERE id=?", (id,))
    p = c.fetchone()
    if p:
        # 尝试获取现价
        try:
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={p[2]}USDT"
            curr = float(requests.get(url, timeout=1).json()['price'])
        except:
            curr = p[4] # 获取失败则按保本平仓(防止卡死)
            
        if p[3] == 'LONG': pnl = (curr - p[4]) * p[5]
        else: pnl = (p[4] - curr) * p[5]
        
        c.execute('UPDATE users SET balance = balance + ? WHERE username=?', (p[7] + pnl, p[1]))
        c.execute('DELETE FROM positions WHERE id=?', (id,))
        conn.commit()
    conn.close()

# === 4. TradingView 核心组件 (关键!) ===
def render_tradingview_widget(symbol):
    # 这是 TradingView 的原生 HTML 代码
    # 我们把 symbol 动态传进去
    html_code = f"""
    <div class="tradingview-widget-container">
      <div id="tradingview_chart"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget(
      {{
        "width": "100%",
        "height": 500,
        "symbol": "BINANCE:{symbol}USDT",
        "interval": "60",
        "timezone": "Asia/Shanghai",
        "theme": "dark",
        "style": "1",
        "locale": "zh_CN",
        "toolbar_bg": "#f1f3f6",
        "enable_publishing": false,
        "allow_symbol_change": true,
        "container_id": "tradingview_chart"
      }}
      );
      </script>
    </div>
    """
    components.html(html_code, height=500)

# === 5. 主界面 ===
def main():
    if 'user' not in st.session_state:
        st.title("🔐 JARVIS ACCESS")
        u = st.text_input("Username")
        if st.button("Login / Register"):
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, balance REAL, bot_active INTEGER)')
            c.execute('SELECT * FROM users WHERE username=?', (u,))
            if not c.fetchone():
                c.execute('INSERT INTO users VALUES (?,?,?,?)', (u, "123", 10000.0, 0))
                conn.commit()
            st.session_state['user'] = u
            st.rerun()
        return

    user = st.session_state['user']
    bal, _ = get_user_data(user)
    
    # 侧边栏
    with st.sidebar:
        st.markdown(f"## 👤 {user}")
        st.metric("USDT", f"${bal:,.2f}")
        if st.button("EXIT"):
            del st.session_state['user']
            st.rerun()
        
        st.divider()
        st.markdown("### 📊 POSITIONS")
        conn = sqlite3.connect(DB_FILE)
        pos = pd.read_sql("SELECT * FROM positions WHERE username=?", conn, params=(user,))
        conn.close()
        if not pos.empty:
            for i, p in pos.iterrows():
                with st.expander(f"{p['symbol']} {p['type']}"):
                    st.write(f"Entry: ${p['entry']}")
                    if st.button("CLOSE", key=f"c_{p['id']}"):
                        close_order(p['id'])
                        st.rerun()
        else:
            st.caption("No positions")

    # 主区
    st.markdown("## 📈 MARKET UPLINK")
    
    # 1. 币种选择
    c1, c2 = st.columns([1, 4])
    with c1:
        target_coin = st.selectbox("ASSET", ["BTC", "ETH", "SOL", "BNB", "DOGE", "PEPE", "WIF"])
    
    # 2. 渲染 TradingView 图表 (不会被墙！)
    with c2:
        render_tradingview_widget(target_coin)
    
    st.divider()
    
    # 3. 交易面板
    st.markdown("### ⚡️ COMMAND CENTER")
    c_ctrl, c_info = st.columns([2, 1])
    
    with c_ctrl:
        c_lev, c_mar = st.columns(2)
        lev = c_lev.slider("LEVERAGE", 1, 125, 20)
        mar = c_mar.number_input("MARGIN (USDT)", 100)
        
        b1, b2 = st.columns(2)
        if b1.button("🟢 LONG", use_container_width=True):
            ok, msg = place_order(user, target_coin, "LONG", mar, lev)
            if ok: st.success(msg); st.rerun()
            else: st.error(msg)
            
        if b2.button("🔴 SHORT", use_container_width=True):
            ok, msg = place_order(user, target_coin, "SHORT", mar, lev)
            if ok: st.success(msg); st.rerun()
            else: st.error(msg)
            
    with c_info:
        st.info("💡 Pro Tip: TradingView Charts allow you to use technical indicators directly!")

if __name__ == '__main__':
    init_db()
    main()
