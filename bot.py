import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import time
from datetime import datetime
import random
import sqlite3
import hashlib

# === 1. 页面配置 ===
st.set_page_config(page_title="Jarvis Online", page_icon="🌐", layout="wide")

# === 2. 数据库核心 (SQLite) ===
DB_FILE = "jarvis_data.db"

def init_db():
    """初始化数据库：创建用户表、持仓表、历史表"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # 用户表
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, balance REAL)''')
    # 持仓表
    c.execute('''CREATE TABLE IF NOT EXISTS positions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, symbol TEXT, type TEXT, 
                  entry REAL, size REAL, leverage INTEGER, margin REAL, tp REAL, sl REAL)''')
    # 历史表
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (time TEXT, username TEXT, symbol TEXT, action TEXT, 
                  price TEXT, size TEXT, pnl TEXT)''')
    conn.commit()
    conn.close()

# 密码加密函数
def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password, hashed_text):
    if make_hashes(password) == hashed_text: return True
    return False

def add_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username =?', (username,))
    if c.fetchone(): return False # 用户已存在
    c.execute('INSERT INTO users VALUES (?,?,?)', (username, make_hashes(password), 10000.0)) # 初始送1万U
    conn.commit()
    conn.close()
    return True

def login_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username =?', (username,))
    data = c.fetchone()
    conn.close()
    if data and check_hashes(password, data[1]): return data
    return None

# === 3. 交易功能函数 (读写数据库) ===
def get_user_balance(username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT balance FROM users WHERE username=?', (username,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else 0.0

def update_balance(username, amount):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('UPDATE users SET balance = balance + ? WHERE username=?', (amount, username))
    conn.commit()
    conn.close()

def get_positions(username):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM positions WHERE username = ?", conn, params=(username,))
    conn.close()
    return df.to_dict('records')

def place_order_db(username, symbol, side, margin, leverage):
    current_bal = get_user_balance(username)
    if current_bal < margin: return False, "余额不足"
    
    price = get_ticker_data(symbol)['price']
    size = (margin * leverage) / price
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # 1. 扣钱
    c.execute('UPDATE users SET balance = balance - ? WHERE username=?', (margin, username))
    # 2. 加仓
    c.execute('''INSERT INTO positions (username, symbol, type, entry, size, leverage, margin, tp, sl)
                 VALUES (?,?,?,?,?,?,?,0,0)''', (username, symbol, side, price, size, leverage, margin))
    # 3. 记日志
    c.execute('''INSERT INTO history VALUES (?,?,?,?,?,?,?)''', 
              (datetime.now().strftime("%H:%M:%S"), username, symbol, f"OPEN {side}", 
               f"${price:.2f}", f"{size:.4f}", "-"))
    conn.commit()
    conn.close()
    return True, "开仓成功"

def close_position_db(pos_id, current_price):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM positions WHERE id=?", (pos_id,))
    pos = c.fetchone() # (id, user, sym, type, entry, size, lev, mar, ...)
    
    if pos:
        username, symbol, side, entry, size, margin = pos[1], pos[2], pos[3], pos[4], pos[5], pos[7]
        
        # 计算盈亏
        if side == 'LONG': pnl = (current_price - entry) * size
        else: pnl = (entry - current_price) * size
        
        # 退钱 (本金+盈亏)
        c.execute('UPDATE users SET balance = balance + ? WHERE username=?', (margin + pnl, username))
        # 删仓位
        c.execute('DELETE FROM positions WHERE id=?', (pos_id,))
        # 记日志
        c.execute('''INSERT INTO history VALUES (?,?,?,?,?,?,?)''', 
              (datetime.now().strftime("%H:%M:%S"), username, symbol, "CLOSE", 
               f"${current_price:.2f}", f"{size:.4f}", f"${pnl:+.2f}"))
        conn.commit()
    conn.close()

def get_history(username):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM history WHERE username = ? ORDER BY rowid DESC LIMIT 50", conn, params=(username,))
    conn.close()
    return df

# === 4. API 与 机器人逻辑 (简化版) ===
def get_ticker_data(symbol):
    try:
        # 为了速度，这里用个随机模拟，真实部署时解开下面的 requests
        # url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}USDT"
        # data = requests.get(url, timeout=1).json()
        # return {'price': float(data['lastPrice']), 'change': float(data['priceChangePercent'])}
        base = 80000 if 'BTC' in symbol else 3000
        mock_price = base + random.randint(-50, 50)
        return {'price': mock_price, 'change': random.uniform(-5, 5)}
    except: return {'price': 0, 'change': 0}

def get_klines(symbol):
    # 模拟 K 线数据，避免多人请求被币安封 IP
    dates = pd.date_range(end=datetime.now(), periods=50, freq='1H')
    df = pd.DataFrame(index=dates)
    df['close'] = [get_ticker_data(symbol)['price'] for _ in range(50)]
    df['open'] = df['close'] + 50
    df['high'] = df['close'] + 100
    df['low'] = df['close'] - 100
    df['time'] = df.index
    return df

# === 5. 登录/注册页面 ===
def login_page():
    st.markdown("## 🔐 Jarvis Online 登录")
    
    tab1, tab2 = st.tabs(["登录", "注册新账号"])
    
    with tab1:
        user = st.text_input("用户名", key="l_user")
        pwd = st.text_input("密码", type='password', key="l_pwd")
        if st.button("登录"):
            account = login_user(user, pwd)
            if account:
                st.session_state['logged_in'] = True
                st.session_state['username'] = user
                st.success(f"欢迎回来, {user}!")
                st.rerun()
            else:
                st.error("用户名或密码错误")

    with tab2:
        new_user = st.text_input("设置用户名", key="r_user")
        new_pwd = st.text_input("设置密码", type='password', key="r_pwd")
        if st.button("立即注册"):
            if add_user(new_user, new_pwd):
                st.success("注册成功！请去登录页面登录。")
            else:
                st.error("该用户名已被占用")

# === 6. 交易主界面 ===
def main_app():
    user = st.session_state['username']
    balance = get_user_balance(user)
    
    # 侧边栏
    with st.sidebar:
        st.title(f"👤 {user}")
        st.metric("钱包余额", f"${balance:,.2f}")
        if st.button("退出登录"):
            st.session_state['logged_in'] = False
            st.rerun()
        
        st.divider()
        st.subheader("我的持仓")
        positions = get_positions(user)
        if positions:
            for p in positions:
                curr = get_ticker_data(p['symbol'])['price']
                if p['type'] == 'LONG': pnl = (curr - p['entry']) * p['size']
                else: pnl = (p['entry'] - curr) * p['size']
                
                color = "green" if pnl>=0 else "red"
                with st.expander(f"{p['symbol']} {p['type']} ${pnl:.1f}"):
                    st.write(f"Entry: {p['entry']}")
                    st.markdown(f"**PNL: :{color}[${pnl:.2f}]**")
                    if st.button("平仓", key=f"c_{p['id']}"):
                        close_position_db(p['id'], curr)
                        st.rerun()
        else:
            st.info("空仓")

    # 主区
    st.markdown("### 🌐 全球市场 (多人联机版)")
    
    # 简单的行情
    cols = st.columns(4)
    coins = ["BTC", "ETH", "SOL", "BNB"]
    for i, c in enumerate(coins):
        d = get_ticker_data(c)
        cols[i].metric(c, f"${d['price']}", f"{d['change']:.2f}%")
        
    st.divider()
    
    # 交易操作
    sel_coin = st.selectbox("选择币种", coins)
    
    # 画图
    df = get_klines(sel_coin)
    fig = go.Figure(data=[go.Candlestick(x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'])])
    fig.update_layout(height=400, template="plotly_dark", margin=dict(l=0,r=0,t=0,b=0))
    st.plotly_chart(fig, use_container_width=True)
    
    c1, c2, c3 = st.columns([1,1,2])
    lev = c1.slider("杠杆", 1, 100, 20)
    margin = c2.number_input("保证金", 100)
    
    with c3:
        st.write("")
        st.write("")
        b1, b2 = st.columns(2)
        if b1.button("🟢 做多", use_container_width=True):
            ok, msg = place_order_db(user, sel_coin, "LONG", margin, lev)
            if ok: st.success(msg); st.rerun()
            else: st.error(msg)
        if b2.button("🔴 做空", use_container_width=True):
            ok, msg = place_order_db(user, sel_coin, "SHORT", margin, lev)
            if ok: st.success(msg); st.rerun()
            else: st.error(msg)

    # 历史
    st.subheader("📜 交易记录")
    hist = get_history(user)
    if not hist.empty:
        st.dataframe(hist, use_container_width=True, hide_index=True)

    if st.checkbox("刷新数据", value=True):
        time.sleep(3)
        st.rerun()

# === 程序入口 ===
if __name__ == '__main__':
    init_db() # 确保数据库存在
    
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
        
    if not st.session_state['logged_in']:
        login_page()
    else:
        main_app()