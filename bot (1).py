import requests
import hmac
import hashlib
import time
import pandas as pd
import schedule
import os
import threading
import json
import numpy as np

# ============================================================
# CONFIG
# ============================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")
API_KEY        = os.environ.get("API_KEY", "")
SECRET_KEY     = os.environ.get("SECRET_KEY", "")

BASE_URL       = "https://testnet.binance.vision"
KUCOIN_URL     = "https://api.kucoin.com"
BINANCE_SYMBOL = "DOGEUSDT"
KUCOIN_SYMBOL  = "DOGE-USDT"
ACCOUNT_SIZE   = 5000
MAX_RISK       = 100
TRADES_FILE    = "trades.json"

# ============================================================
# TELEGRAM — SEND
# ============================================================
def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram not configured")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        print("Telegram send error: " + str(e))

# ============================================================
# TELEGRAM — LISTEN
# ============================================================
last_update_id = 0

def poll_telegram():
    global last_update_id
    while True:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                params={"offset": last_update_id + 1, "timeout": 30},
                timeout=35
            )
            data = r.json()
            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    last_update_id = update["update_id"]
                    msg     = update.get("message", {})
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    text    = msg.get("text", "").strip().lower()

                    if chat_id != str(CHAT_ID):
                        continue

                    print("Command received: " + text)

                    if text in ["/start", "/help"]:
                        handle_help()
                    elif text == "/status":
                        handle_status()
                    elif text == "/check":
                        handle_check()
                    elif text == "/trades":
                        handle_trades()
                    elif text == "/summary":
                        handle_summary()
                    elif text == "/pause":
                        handle_pause()
                    elif text == "/resume":
                        handle_resume()
                    elif text == "/balance":
                        handle_balance()
                    else:
                        send_telegram("Unknown command. Type /help to see all commands.")
        except Exception as e:
            print("Telegram poll error: " + str(e))
        time.sleep(1)

# ============================================================
# COMMAND HANDLERS
# ============================================================
def handle_help():
    send_telegram(
        "*DOGE Mean Reversion Bot — Commands*\n\n" +
        "/status — Bot status and last check\n" +
        "/check — Run market check right now\n" +
        "/trades — All open trades with PnL\n" +
        "/summary — Win/loss summary and total PnL\n" +
        "/balance — Testnet USDT balance\n" +
        "/pause — Pause the bot\n" +
        "/resume — Resume the bot\n" +
        "/help — Show this menu"
    )

def handle_status():
    price   = get_current_price()
    now     = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    summary = get_summary()
    status  = "PAUSED" if time.time() < paused_until else "RUNNING"

    send_telegram(
        "*BOT STATUS*\n\n" +
        "Status: " + status + "\n" +
        "Time: " + now + "\n" +
        "DOGE Price: $" + str(price if price else "unavailable") + "\n\n" +
        "*Today*\n" +
        "Daily trades: " + str(daily_trades) + "/10\n" +
        "Daily losses: " + str(round(daily_losses, 2)) + " USDT\n" +
        "Consecutive losses: " + str(consecutive_losses) + "\n\n" +
        "*Overall*\n" +
        "Total trades: " + str(summary["total"]) + "\n" +
        "Open trades: "  + str(summary["open"])  + "\n" +
        "Total PnL: "    + str(summary["total_pnl"]) + " USDT"
    )

def handle_check():
    send_telegram("Running market check now...")
    try:
        run_bot()
    except Exception as e:
        send_telegram("Check failed: " + str(e))

def handle_trades():
    trades = load_trades()
    open_t = [t for t in trades if t["status"] == "open"]

    if not open_t:
        send_telegram("No open trades right now.")
        return

    price = get_current_price()
    msg   = "*OPEN TRADES*\n\n"

    for t in open_t:
        entry    = t["entry_price"]
        current  = price if price else entry
        pnl_pct  = round(((current - entry) / entry) * 100, 2)
        pnl_usdt = round((pnl_pct / 100) * t["size_usdt"], 2)
        sign     = "+" if pnl_usdt >= 0 else ""

        msg += (
            "ID: " + str(t["order_id"]) + "\n" +
            "Tier: " + t["tier"] + " | Size: " + str(t["size_usdt"]) + " USDT\n" +
            "Entry: $" + str(entry) + "\n" +
            "Current: $" + str(round(current, 6)) + "\n" +
            "PnL: " + sign + str(pnl_usdt) + " USDT (" + sign + str(pnl_pct) + "%)\n" +
            "Stop: $" + str(t["stop_price"]) + "\n" +
            "TP1: $" + str(t["tp1_price"]) + " | TP2: $" + str(t["tp2_price"]) + "\n" +
            "Opened: " + t["time"] + "\n\n"
        )

    send_telegram(msg)

def handle_summary():
    summary = get_summary()
    trades  = load_trades()
    closed  = [t for t in trades if t["status"] != "open"]

    tp1_count  = len([t for t in closed if t["status"] == "closed_tp1"])
    tp2_count  = len([t for t in closed if t["status"] == "closed_tp2"])
    sl_count   = len([t for t in closed if t["status"] == "closed_sl"])
    time_count = len([t for t in closed if t["status"] == "closed_time"])
    sign       = "+" if summary["total_pnl"] >= 0 else ""

    send_telegram(
        "*TRADE SUMMARY*\n\n" +
        "Total trades: " + str(summary["total"]) + "\n" +
        "Open: "   + str(summary["open"])   + "\n" +
        "Closed: " + str(summary["closed"]) + "\n\n" +
        "*Results*\n" +
        "Wins: "     + str(summary["wins"])     + "\n" +
        "Losses: "   + str(summary["losses"])   + "\n" +
        "Win rate: " + str(summary["win_rate"]) + "%\n\n" +
        "*Exit Breakdown*\n" +
        "TP1 hits: "    + str(tp1_count)  + "\n" +
        "TP2 hits: "    + str(tp2_count)  + "\n" +
        "Stop losses: " + str(sl_count)   + "\n" +
        "Time stops: "  + str(time_count) + "\n\n" +
        "*PnL*\n" +
        "Total: " + sign + str(summary["total_pnl"]) + " USDT"
    )

def handle_pause():
    global paused_until
    paused_until = time.time() + 24 * 3600
    send_telegram("Bot paused for 24 hours.\nSend /resume to restart early.")

def handle_resume():
    global paused_until
    paused_until = 0
    send_telegram("Bot resumed.\nNext check in 5 minutes or send /check to run now.")

def handle_balance():
    bal = get_balance()
    send_telegram("Testnet USDT Balance: " + str(bal) + " USDT")

# ============================================================
# TRADE LOGGER
# ============================================================
def load_trades():
    if not os.path.exists(TRADES_FILE):
        return []
    try:
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_trades(trades):
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)

def log_trade(order):
    trades = load_trades()
    trades.append({
        "order_id":      order["order_id"],
        "tier":          order["tier"],
        "side":          order["side"],
        "entry_price":   order["entry_price"],
        "current_price": order["entry_price"],
        "quantity":      order["quantity"],
        "size_usdt":     order["size_usdt"],
        "stop_price":    order["stop_price"],
        "tp1_price":     order["tp1_price"],
        "tp2_price":     order["tp2_price"],
        "bb_mid":        order["bb_mid"],
        "bb_upper":      order["bb_upper"],
        "pnl_usdt":      0.0,
        "pnl_pct":       0.0,
        "status":        "open",
        "tp1_hit":       False,
        "open_time":     time.time(),
        "time":          time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    })
    save_trades(trades)

def update_trade(order_id, current_price):
    trades = load_trades()
    for t in trades:
        if t["order_id"] == order_id and t["status"] == "open":
            entry    = t["entry_price"]
            pnl_pct  = ((current_price - entry) / entry) * 100
            pnl_usdt = (pnl_pct / 100) * t["size_usdt"]
            t["current_price"] = round(current_price, 6)
            t["pnl_pct"]       = round(pnl_pct, 2)
            t["pnl_usdt"]      = round(pnl_usdt, 2)
    save_trades(trades)

def close_trade_log(order_id, reason, current_price):
    trades   = load_trades()
    pnl_usdt = 0
    for t in trades:
        if t["order_id"] == order_id:
            entry    = t["entry_price"]
            pnl_pct  = ((current_price - entry) / entry) * 100
            pnl_usdt = round((pnl_pct / 100) * t["size_usdt"], 2)
            t["current_price"] = round(current_price, 6)
            t["pnl_pct"]       = round(pnl_pct, 2)
            t["pnl_usdt"]      = pnl_usdt
            t["status"]        = reason
            t["close_time"]    = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    save_trades(trades)
    return pnl_usdt

def get_summary():
    trades    = load_trades()
    closed    = [t for t in trades if t["status"] != "open"]
    open_t    = [t for t in trades if t["status"] == "open"]
    total_pnl = sum(t.get("pnl_usdt", 0) for t in closed)
    wins      = len([t for t in closed if t.get("pnl_usdt", 0) > 0])
    losses    = len([t for t in closed if t.get("pnl_usdt", 0) <= 0])
    win_rate  = round((wins / len(closed)) * 100, 1) if closed else 0
    return {
        "total":     len(trades),
        "open":      len(open_t),
        "closed":    len(closed),
        "wins":      wins,
        "losses":    losses,
        "win_rate":  win_rate,
        "total_pnl": round(total_pnl, 2)
    }

# ============================================================
# STATE
# ============================================================
open_trades        = []
daily_trades       = 0
daily_losses       = 0.0
consecutive_losses = 0
paused_until       = 0

# ============================================================
# MODULE 1 — CONNECTION
# ============================================================
def get_balance():
    if not API_KEY or not SECRET_KEY:
        print("No API keys — skipping balance check")
        return 0
    try:
        timestamp = int(time.time() * 1000)
        qs        = f"timestamp={timestamp}"
        signature = hmac.new(SECRET_KEY.encode(), qs.encode(), hashlib.sha256).hexdigest()
        url       = f"{BASE_URL}/api/v3/account?{qs}&signature={signature}"
        data      = requests.get(url, headers={"X-MBX-APIKEY": API_KEY}, timeout=10).json()
        if "balances" in data:
            for asset in data["balances"]:
                if asset["asset"] == "USDT":
                    bal = float(asset["free"])
                    print("Testnet USDT Balance: " + str(bal))
                    return bal
        print("Balance failed: " + str(data))
    except Exception as e:
        print("Balance error: " + str(e))
    return 0

# ============================================================
# MODULE 2 — MARKET DATA (KuCoin)
# ============================================================
def get_candles(symbol=KUCOIN_SYMBOL, interval="5min", limit=150):
    try:
        r    = requests.get(
                   KUCOIN_URL + "/api/v1/market/candles",
                   params={"symbol": symbol, "type": interval},
                   timeout=10)
        data = r.json()
        if data.get("code") != "200000":
            print("Candle error: " + str(data))
            return []
        raw = list(reversed(data["data"]))[:limit]
        return [{"time":   int(c[0]), "open":  float(c[1]),
                 "close":  float(c[2]), "high": float(c[3]),
                 "low":    float(c[4]), "volume": float(c[5])}
                for c in raw]
    except Exception as e:
        print("Candle error: " + str(e))
        return []

def get_current_price():
    try:
        r    = requests.get(
                   KUCOIN_URL + "/api/v1/market/orderbook/level1",
                   params={"symbol": KUCOIN_SYMBOL}, timeout=10)
        data = r.json()
        if data.get("code") == "200000":
            return float(data["data"]["price"])
    except Exception as e:
        print("Price error: " + str(e))
    return None

# ============================================================
# MODULE 3 — INDICATORS
# ============================================================
def calculate_indicators(candles):
    df = pd.DataFrame(candles)

    # ATR
    df["prev_close"] = df["close"].shift(1)
    df["tr"] = df[["high", "low", "prev_close"]].apply(
        lambda r: max(r["high"] - r["low"],
                      abs(r["high"] - r["prev_close"]),
                      abs(r["low"]  - r["prev_close"])), axis=1)
    df["atr"]     = df["tr"].rolling(14).mean()
    df["atr_pct"] = (df["atr"] / df["close"]) * 100

    # EMA100 — trend direction filter
    df["ema100"]  = df["close"].ewm(span=100, adjust=False).mean()

    # RSI
    delta         = df["close"].diff()
    gain          = delta.where(delta > 0, 0).rolling(14).mean()
    loss          = -delta.where(delta < 0, 0).rolling(14).mean()
    df["rsi"]     = 100 - (100 / (1 + gain / loss))

    # Bollinger Bands (20 period, 2 std dev)
    df["bb_mid"]   = df["close"].rolling(20).mean()
    df["bb_std"]   = df["close"].rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + (2 * df["bb_std"])
    df["bb_lower"] = df["bb_mid"] - (2 * df["bb_std"])

    # Volume average
    df["vol_avg"]  = df["volume"].rolling(20).mean()

    return df

# ============================================================
# MODULE 4 — FILTERS + SIGNALS
# ============================================================
def run_filters(df):
    l = df.iloc[-1]

    # ---- HARD FILTERS (all 3 must pass) ----

    # H1 — RSI oversold
    rsi      = round(float(l["rsi"]), 2)
    h1_pass  = bool(rsi <= 35)

    # H2 — Price touches lower Bollinger Band
    h2_pass  = bool(l["close"] <= l["bb_lower"])

    # H3 — Price above EMA100 (not in strong downtrend)
    h3_pass  = bool(l["close"] > l["ema100"])

    hard_pass = bool(h1_pass and h2_pass and h3_pass)

    # ---- SOFT FILTERS (need 1 of 2) ----

    # S1 — Volume spike
    s1_pass  = bool(l["volume"] >= l["vol_avg"] * 1.5)

    # S2 — ATR in valid range (market moving but not crashing)
    atr_pct  = round(float(l["atr_pct"]), 2)
    s2_pass  = bool(1.0 <= atr_pct <= 6.0)

    soft_pass = bool(s1_pass or s2_pass)

    all_pass  = bool(hard_pass and soft_pass)

    # ---- Build Telegram filter summary ----
    def icon(p): return "✅" if p else "❌"
    filter_lines = (
        "*Hard Filters (all required):*\n" +
        icon(h1_pass) + " RSI: " + str(rsi) + " (need ≤35)\n" +
        icon(h2_pass) + " BB Lower Touch: $" + str(round(l["bb_lower"], 6)) + "\n" +
        icon(h3_pass) + " Above EMA100: $" + str(round(l["ema100"], 6)) + "\n\n" +
        "*Soft Filters (need 1 of 2):*\n" +
        icon(s1_pass) + " Volume spike: " + str(round(l["volume"], 0)) +
                        " vs Avg=" + str(round(l["vol_avg"], 0)) + "\n" +
        icon(s2_pass) + " ATR: " + str(atr_pct) + "% (need 1-6%)"
    )

    print("H1 RSI " + str(rsi) + " | " + str(h1_pass))
    print("H2 BB Lower Touch | " + str(h2_pass))
    print("H3 EMA100 | " + str(h3_pass))
    print("S1 Volume | " + str(s1_pass))
    print("S2 ATR " + str(atr_pct) + "% | " + str(s2_pass))
    print("ALL PASS: " + str(all_pass))

    return all_pass, l, filter_lines, rsi, atr_pct

# ============================================================
# MODULE 5 — POSITION SIZING
# ============================================================
def determine_size(rsi, atr_pct):
    if rsi <= 25:
        return 1000, 0.10, "Tier 1 (deeply oversold)"
    elif rsi <= 35:
        return 500, 0.20, "Tier 2 (moderately oversold)"
    return 0, 0, "No Trade"

# ============================================================
# MODULE 6 — ORDER EXECUTOR
# ============================================================
def place_order(side, size_usdt, stop_pct, tier, bb_mid, bb_upper):
    print("--- ORDER EXECUTOR ---")
    try:
        price = get_current_price()
        if not price:
            print("No price — skipping")
            return None

        qty  = round(size_usdt / price, 0)

        # Mean reversion targets — TP1 at BB mid, TP2 at BB upper
        stop   = round(price * (1 - stop_pct), 6)
        tp1    = round(bb_mid, 6)      # return to mean
        tp2    = round(bb_upper, 6)    # full reversion

        print("Entry: $" + str(price) +
              " | Stop: $" + str(stop) +
              " | TP1 (BB Mid): $" + str(tp1) +
              " | TP2 (BB Upper): $" + str(tp2))

        ts  = int(time.time() * 1000)
        p   = {"symbol": BINANCE_SYMBOL, "side": side, "type": "MARKET",
               "quantity": qty, "timestamp": ts}
        qs  = "&".join([f"{k}={v}" for k, v in p.items()])
        sig = hmac.new(SECRET_KEY.encode(), qs.encode(), hashlib.sha256).hexdigest()
        res = requests.post(
                  BASE_URL + "/api/v3/order?" + qs + "&signature=" + sig,
                  headers={"X-MBX-APIKEY": API_KEY}, timeout=10).json()

        if "orderId" in res:
            print("ORDER PLACED — ID: " + str(res["orderId"]))
            order = {
                "order_id":    res["orderId"],
                "entry_price": price,
                "quantity":    qty,
                "stop_price":  stop,
                "tp1_price":   tp1,
                "tp2_price":   tp2,
                "bb_mid":      bb_mid,
                "bb_upper":    bb_upper,
                "side":        side,
                "tier":        tier,
                "size_usdt":   size_usdt,
                "open_time":   time.time(),
                "tp1_hit":     False,
                "time":        time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
            }
            log_trade(order)
            send_telegram(
                "*BUY ORDER PLACED*\n" +
                "Symbol: " + KUCOIN_SYMBOL + "\n" +
                "Tier: " + tier + "\n" +
                "Entry: $" + str(price) + "\n" +
                "Size: " + str(size_usdt) + " USDT\n" +
                "Stop Loss: $" + str(stop) + "\n" +
                "TP1 (BB Mid): $" + str(tp1) + "\n" +
                "TP2 (BB Upper): $" + str(tp2)
            )
            return order
        else:
            print("Order failed: " + str(res))
            send_telegram("Order failed: " + str(res))
            return None
    except Exception as e:
        print("Order error: " + str(e))
        return None

# ============================================================
# MODULE 7 — EXIT MANAGER
# ============================================================
def monitor_exits():
    global open_trades, consecutive_losses, daily_losses
    if not open_trades:
        return

    price = get_current_price()
    if not price:
        return

    for trade in open_trades[:]:
        entry    = trade["entry_price"]
        pnl_pct  = ((price - entry) / entry) * 100
        pnl_usdt = round((pnl_pct / 100) * trade["size_usdt"], 2)

        update_trade(trade["order_id"], price)

        if price <= trade["stop_price"]:
            pnl = close_trade_log(trade["order_id"], "closed_sl", price)
            open_trades.remove(trade)
            consecutive_losses += 1
            daily_losses += abs(pnl)
            send_telegram(
                "*STOP LOSS HIT*\n" +
                KUCOIN_SYMBOL + "\n" +
                "Exit: $" + str(price) + "\n" +
                "Loss: " + str(pnl) + " USDT\n" +
                "Consecutive losses: " + str(consecutive_losses)
            )

        elif price >= trade["tp2_price"] and trade.get("tp1_hit"):
            pnl = close_trade_log(trade["order_id"], "closed_tp2", price)
            open_trades.remove(trade)
            consecutive_losses = 0
            send_telegram(
                "*TP2 HIT — Full Close*\n" +
                KUCOIN_SYMBOL + "\n" +
                "Exit: $" + str(price) + "\n" +
                "Profit: +" + str(pnl) + " USDT"
            )

        elif price >= trade["tp1_price"] and not trade.get("tp1_hit"):
            trade["tp1_hit"]    = True
            trade["stop_price"] = entry
            close_trade_log(trade["order_id"], "closed_tp1", price)
            consecutive_losses = 0
            send_telegram(
                "*TP1 HIT — 60% Closed*\n" +
                KUCOIN_SYMBOL + "\n" +
                "Price: $" + str(price) + "\n" +
                "Reached BB Mid (mean)\n" +
                "Stop moved to breakeven: $" + str(entry)
            )

        elif (time.time() - trade.get("open_time", time.time())) > 3 * 3600:
            pnl = close_trade_log(trade["order_id"], "closed_time", price)
            open_trades.remove(trade)
            send_telegram(
                "*TIME STOP — 3hr limit hit*\n" +
                KUCOIN_SYMBOL + "\n" +
                "Exit: $" + str(price) + "\n" +
                "PnL: " + str(pnl) + " USDT"
            )

        elif pnl_pct >= 2.0 and not trade.get("tp1_hit"):
            if round(entry, 6) > trade["stop_price"]:
                trade["stop_price"] = round(entry, 6)
                print("Stop trailed to breakeven")

# ============================================================
# MODULE 8 — CIRCUIT BREAKERS
# ============================================================
def check_circuit_breakers():
    global paused_until

    if time.time() < paused_until:
        remaining = round((paused_until - time.time()) / 3600, 1)
        print("Paused — " + str(remaining) + "h remaining")
        return False, "Bot paused — " + str(remaining) + "h remaining"
    if daily_trades >= 10:
        return False, "Max daily trades (10) reached"
    if len(open_trades) >= 2:
        return False, "Max concurrent trades (2) reached"
    if consecutive_losses >= 3:
        paused_until = time.time() + 2 * 3600
        send_telegram("3 consecutive losses — bot paused for 2 hours.\nSend /resume to restart early.")
        return False, "3 losses — paused 2h"
    if daily_losses >= 500:
        return False, "Drawdown limit hit (500 USDT)"

    return True, "All clear"

# ============================================================
# MAIN BOT LOOP
# ============================================================
def run_bot():
    global daily_trades, open_trades, consecutive_losses, daily_losses

    now = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    print("\n============================")
    print("Bot check: " + now)
    print("============================")

    get_balance()
    monitor_exits()

    cb_ok, cb_msg = check_circuit_breakers()
    if not cb_ok:
        print("Circuit breaker: " + cb_msg)
        return

    candles = get_candles()
    if not candles:
        print("No candle data — skipping")
        send_telegram("No candle data from KuCoin — skipping check")
        return

    price = candles[-1]["close"]
    print("DOGE Price: $" + str(price))

    df                                  = calculate_indicators(candles)
    all_pass, l, filter_lines, rsi, atr = run_filters(df)
    summary                             = get_summary()

    if all_pass:
        size, stop_pct, tier = determine_size(rsi, atr)

        if size > 0:
            bb_mid   = float(l["bb_mid"])
            bb_upper = float(l["bb_upper"])
            order    = place_order("BUY", size, stop_pct, tier, bb_mid, bb_upper)
            if order:
                order["open_time"] = time.time()
                open_trades.append(order)
                daily_trades      += 1
                consecutive_losses = 0
                summary = get_summary()
                send_telegram(
                    "*SUMMARY UPDATE*\n" +
                    "Trades today: " + str(daily_trades) + "/10\n" +
                    "Total trades: " + str(summary["total"]) + "\n" +
                    "Total PnL: "    + str(summary["total_pnl"]) + " USDT"
                )
        else:
            send_telegram(
                "*BOT CHECK — " + now + "*\n\n" +
                "DOGE: $" + str(price) + "\n\n" +
                filter_lines + "\n\n" +
                "Filters passed but sizing failed\n\n" +
                "*SUMMARY*\n" +
                "Trades: " + str(summary["total"]) + " | Open: " + str(summary["open"]) + "\n" +
                "Wins: "   + str(summary["wins"])  + " | Losses: " + str(summary["losses"]) + "\n" +
                "Total PnL: " + str(summary["total_pnl"]) + " USDT"
            )
    else:
        send_telegram(
            "*BOT CHECK — " + now + "*\n\n" +
            "DOGE: $" + str(price) + "\n\n" +
            filter_lines + "\n\n" +
            "Watching and waiting...\n\n" +
            "*SUMMARY*\n" +
            "Trades: " + str(summary["total"]) + " | Open: " + str(summary["open"]) + "\n" +
            "Wins: "   + str(summary["wins"])  + " | Losses: " + str(summary["losses"]) + "\n" +
            "Total PnL: " + str(summary["total_pnl"]) + " USDT"
        )

# ============================================================
# START
# ============================================================
send_telegram(
    "*DOGE Mean Reversion Bot — ONLINE*\n\n" +
    "Symbol: "         + KUCOIN_SYMBOL + "\n" +
    "Strategy: Mean Reversion\n" +
    "Timeframe: 5 minutes\n" +
    "Max risk/trade: " + str(MAX_RISK) + " USDT\n" +
    "Max daily trades: 10\n" +
    "Drawdown limit: 500 USDT\n\n" +
    "Type /help to see all commands."
)

threading.Thread(target=poll_telegram, daemon=True).start()
schedule.every(5).minutes.do(run_bot)

try:
    run_bot()
except Exception as e:
    msg = "CRASH on startup: " + str(e)
    print(msg)
    send_telegram(msg)

print("DOGE bot running. Checking every 5 minutes.")

while True:
    try:
        monitor_exits()
        schedule.run_pending()
    except Exception as e:
        print("Loop error: " + str(e))
    time.sleep(15)
