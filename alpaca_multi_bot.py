import os, json, datetime, requests, yfinance as yf
from strategy_engine import analyze

API_KEY, SECRET_KEY = os.environ.get("ALPACA_API_KEY", "").strip(), os.environ.get("ALPACA_SECRET_KEY", "").strip()
DISCORD_URL, EVENT_NAME = os.environ.get("DISCORD_WEBHOOK_URL", "").strip(), os.environ.get("GITHUB_EVENT_NAME", "")
BASE_URL = "https://" + "paper-api." + "alpaca.markets"
CRYPTO_POT, ETF_POT, INIT_PCT, ADD_PCT, STATE_FILE = 50.0, 50.0, 0.40, 0.10, "alpaca_state.json"
ASSETS = [("XRP-USD","XRP/USD","XRPUSD","crypto",False),("DOGE-USD","DOGE/USD","DOGEUSD","crypto",False),("UNI7083-USD","UNI/USD","UNIUSD","crypto",False),("MSTR","MSTR","MSTR","etf",True),("NVDA","NVDA","NVDA","etf",True),("TSLA","TSLA","TSLA","etf",True),("TQQQ","TQQQ","TQQQ","etf",True),("SOXL","SOXL","SOXL","etf",True),("QQQ","QQQ","QQQ","etf",True),("AMZN","AMZN","AMZN","etf",True),("AMD","AMD","AMD","etf",True),("PLTR","PLTR","PLTR","etf",True),("SMH","SMH","SMH","etf",True),("UPRO","UPRO","UPRO","etf",True),("SBIT","SBIT","SBIT","etf",False),("ERO","ERO","ERO","etf",True),("GOLD","GOLD","GOLD","etf",True),("AAPL","AAPL","AAPL","etf",True),("GSAT","GSAT","GSAT","etf",True),("SCHD","SCHD","SCHD","etf",True),("MAC","MAC","MAC","etf",True),("F","F","F","etf",True),("NOW","NOW","NOW","etf",True),("UUUU","UUUU","UUUU","etf",True),("WULF","WULF","WULF","etf",True),("INTC","INTC","INTC","etf",True),("LITE","LITE","LITE","etf",True),("MUU","MUU","MUU","etf",True),("DELL","DELL","DELL","etf",True),("TXN","TXN","TXN","etf",True),("ADI","ADI","ADI","etf",True),("MX","MX","MX","etf",True),("SLV","SLV","SLV","etf",True),("BA","BA","BA","etf",True)]
HEADERS = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": SECRET_KEY, "Content-Type": "application/json"}

def send_discord(msg):
    if DISCORD_URL:
        lines, chunk = msg.split("\n"), ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 1900:
                try: requests.post(DISCORD_URL, json={"content": chunk}, timeout=10)
                except Exception: pass
                chunk = line
            else: chunk = f"{chunk}\n{line}" if chunk else line
        if chunk:
            try: requests.post(DISCORD_URL, json={"content": chunk}, timeout=10)
            except Exception: pass

def api_get(path):
    try: r = requests.get(f"{BASE_URL}{path}", headers=HEADERS, timeout=10); return r.json() if r.status_code == 200 else {}
    except Exception: return {}

def totals(state):
    tot = sum(float(state.get(s, {}).get("pot", CRYPTO_POT if k=="crypto" else ETF_POT)) for _, s, _, k, _ in ASSETS)
    dep = sum(float(state.get(s, {}).get("alloc", 0.0)) for _, s, _, _, _ in ASSETS if state.get(s, {}).get("in_pos"))
    return round(tot, 2), round(dep, 2), round(max(0.0, tot - dep), 2)

def fmt_line(sym, px_txt, st):
    spot = float(st.get("pot", 50.0))
    used = float(st.get("alloc", 0.0)) if st.get("in_pos") else 0.0
    entry = float(st.get("entry", 0.0))
    qty = float(st.get("qty", 0.0)) if float(st.get("qty", 0.0)) > 0 else (used / entry if entry > 0 else 0.0)
    pos = f"{st.get('side','long').upper()} {qty:.2f} sh @ ${entry:.4f} (${used:.2f})" if st.get("in_pos") else "Flat"
    return f"{sym}: {px_txt} | Pos: {pos} | Slice: ${used:.2f}/${spot:.2f}"

def run():
    state = json.load(open(STATE_FILE)) if os.path.exists(STATE_FILE) else {}
    state.pop("_master_pot", None)
    etf_open, bp, today, out = bool(api_get("/v2/clock").get("is_open", False)), float(api_get("/v2/account").get("buying_power", 0)), str(datetime.date.today()), []
    for yfs, sym, psym, kind, can_short in ASSETS:
        bpot, min_ord = (CRYPTO_POT, 10.0) if kind == "crypto" else (ETF_POT, 1.0)
        st = state.setdefault(sym, {"in_pos":False,"side":"long","pot":bpot,"alloc":0.0,"qty":0.0,"entry":0.0,"tp":0.0,"sl":0.0,"be_trig":0.0,"be_sl":0.0,"be_on":False,"added":False,"bar":"","date":""})
        st.setdefault("pot", bpot)
        if st["in_pos"] and float(st.get("alloc", 0)) <= 0: st["alloc"] = float(st["pot"])
        side = st.get("side", "long")
        if kind == "etf" and not etf_open: out.append(fmt_line(sym, "Closed", st)); continue
        try:
            bull, b_exit, l_type, short, g_exit, s_type, atr, cpx, bts = analyze(yfs)
            px = float(yf.Ticker(yfs).fast_info.get("lastPrice") or cpx)
            spot = float(st["pot"])
            if st["in_pos"]:
                pdt = (kind == "etf" and st.get("date") == today)
                if side == "long":
                    if not st.get("be_on") and st.get("be_trig", 0) > 0 and px >= st["be_trig"]: st["sl"], st["be_on"] = st["be_sl"], True
                    rsn = "TP HIT" if px >= st["tp"] else "SL HIT" if px <= st["sl"] else "BEAR EXIT" if (b_exit and not pdt) else None
                else:
                    if not st.get("be_on") and st.get("be_trig", 0) > 0 and px <= st["be_trig"]: st["sl"], st["be_on"] = st["be_sl"], True
                    rsn = "TP HIT" if px <= st["tp"] else "SL HIT" if px >= st["sl"] else "BULL EXIT" if (g_exit and not pdt) else None
                if rsn and requests.delete(f"{BASE_URL}/v2/positions/{psym}", headers=HEADERS, timeout=15).status_code in (200, 204):
                    alloc = float(st["alloc"])
                    pnl = alloc * ((px - st["entry"]) / st["entry"]) if side == "long" else alloc * ((st["entry"] - px) / st["entry"])
                    npot = round(max(bpot, spot + pnl), 2)
                    msg = f"🔴 **ALPACA {'SELL' if side=='long' else 'COVER'} {sym} ({rsn})** @ `${px:.4f}` | PnL: `${pnl:+.2f}` | Stock Pot: `${npot:.2f}`"; print(msg); send_discord(msg)
                    state[sym] = {"in_pos":False,"side":"long","pot":npot,"alloc":0.0,"qty":0.0,"entry":0.0,"tp":0.0,"sl":0.0,"be_trig":0.0,"be_sl":0.0,"be_on":False,"added":False,"bar":"","date":""}
                elif not rsn and not st.get("added", False) and st.get("bar") != bts:
                    room = max(0.0, spot - float(st["alloc"]))
                    add_sp = min(bp, room, max(min_ord, round(spot * ADD_PCT, 2)))
                    if side == "long" and bull and add_sp >= min_ord and requests.post(f"{BASE_URL}/v2/orders", headers=HEADERS, json={"symbol":sym,"notional":f"{add_sp:.2f}","side":"buy","type":"market","time_in_force":"gtc" if kind=="crypto" else "day"}, timeout=15).status_code in (200, 201):
                        old_a = float(st["alloc"])
                        st["entry"] = round(((old_a * st["entry"]) + (add_sp * px)) / (old_a + add_sp), 6)
                        st["alloc"], st["qty"], st["added"], st["bar"] = round(old_a + add_sp, 2), round((old_a + add_sp)/st["entry"], 4), True, bts
                        msg = f"➕ **ALPACA ADD +10% LONG {sym}!** +`${add_sp:.2f}` @ `${px:.4f}` | Slice: `${st['alloc']:.2f}/${spot:.2f}`"; print(msg); send_discord(msg)
                    elif side == "short" and can_short and short and bp >= px and room >= px:
                        add_sh = max(1, int(min(room, max(px, spot * ADD_PCT)) // px))
                        if requests.post(f"{BASE_URL}/v2/orders", headers=HEADERS, json={"symbol":sym,"qty":str(add_sh),"side":"sell","type":"market","time_in_force":"day"}, timeout=15).status_code in (200, 201):
                            old_q, old_a = float(st.get("qty", 1)), float(st["alloc"])
                            st["entry"] = round((old_a + (add_sh * px)) / (old_q + add_sh), 6)
                            st["qty"], st["alloc"], st["added"], st["bar"] = old_q + add_sh, round(old_a + add_sh * px, 2), True, bts
                            msg = f"➕ **ALPACA ADD +10% SHORT {sym}!** +`{add_sh} sh` @ `${px:.4f}` | Slice: `${st['alloc']:.2f}/${spot:.2f}`"; print(msg); send_discord(msg)
            else:
                sp = min(bp, spot, max(min_ord, round(spot * INIT_PCT, 2)))
                if bull and sp >= min_ord and requests.post(f"{BASE_URL}/v2/orders", headers=HEADERS, json={"symbol":sym,"notional":f"{sp:.2f}","side":"buy","type":"market","time_in_force":"gtc" if kind=="crypto" else "day"}, timeout=15).status_code in (200, 201):
                    tp, sl, be_t, be_s = px + atr * 6.0, px - atr * 4.0, px + atr * 6.0, px + atr * 0.15
                    msg = f"🟢 **ALPACA {sym} {l_type.upper()}!** `${sp:.2f}` @ `${px:.4f}` | TP: `${tp:.4f}` | SL: `${sl:.4f}`"; print(msg); send_discord(msg)
                    state[sym] = {"in_pos":True,"side":"long","pot":spot,"alloc":sp,"qty":round(sp/px, 4),"entry":px,"tp":tp,"sl":sl,"be_trig":be_t,"be_sl":be_s,"be_on":False,"added":False,"bar":bts,"date":today}
                elif can_short and short and bp >= px and spot >= px:
                    sh_qty = max(1, int(min(spot, max(px, spot * INIT_PCT)) // px))
                    if requests.post(f"{BASE_URL}/v2/orders", headers=HEADERS, json={"symbol":sym,"qty":str(sh_qty),"side":"sell","type":"market","time_in_force":"day"}, timeout=15).status_code in (200, 201):
                        tp, sl, be_t, be_s = px - atr * 4.5, px + atr * 3.0, px - atr * 2.5, px - atr * 0.15
                        msg = f"🟣 **ALPACA {sym} {s_type.upper()}!** `{sh_qty} sh` (`${sh_qty*px:.2f}`) @ `${px:.4f}` | TP: `${tp:.4f}` | SL: `${sl:.4f}`"; print(msg); send_discord(msg)
                        state[sym] = {"in_pos":True,"side":"short","pot":spot,"alloc":round(sh_qty * px, 2),"qty":sh_qty,"entry":px,"tp":tp,"sl":sl,"be_trig":be_t,"be_sl":be_s,"be_on":False,"added":False,"bar":bts,"date":today}
            out.append(fmt_line(sym, f"${px:.4f}", state[sym]))
        except Exception as e: print(f"[SKIP {sym}] {e}"); out.append(f"{sym}: Data Skip")
    json.dump(state, open(STATE_FILE, "w"), indent=2)
    m_tot, dep, m_left = totals(state)
    hdr = f"Master Used: ${dep:.2f} / ${m_tot:.2f} (Left: ${m_left:.2f})"
    print(f"[{hdr}] " + " | ".join(out))
    if EVENT_NAME == "push": send_discord(f"✅ **Alpaca Bot Online!**\n💰 **{hdr}**\n" + "\n".join(out))

run()
