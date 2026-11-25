import os, sys, subprocess, json, time, uuid, base64, requests
from strategy_engine import analyze
try: from nacl.signing import SigningKey
except ModuleNotFoundError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "pynacl"])
    from nacl.signing import SigningKey

API_KEY = (os.environ.get("RH_API_KEY") or os.environ.get("ROBINHOOD_API_KEY") or "").strip()
PRIV_B64 = (os.environ.get("RH_PRIVATE_KEY") or os.environ.get("ROBINHOOD_PRIVATE_KEY") or "").strip()
DISCORD_URL, EVENT_NAME = os.environ.get("DISCORD_WEBHOOK_URL", "").strip(), os.environ.get("GITHUB_EVENT_NAME", "")
RH_BASE = "https://" + "trading." + "robinhood.com"
SYMBOL, YF_SYM, COIN, STATE_FILE, OTHER_STATE, STARTING_POT, INIT_PCT, ADD_PCT = "DOGE-USD", "DOGE-USD", "DOGE", "doge_rh_state.json", "xrp_rh_state.json", 10.0, 0.40, 0.10

def send_discord(msg):
    if DISCORD_URL:
        try: requests.post(DISCORD_URL, json={"content": msg}, timeout=10)
        except Exception: pass

def rh_req(method, path, body=""):
    ts = str(int(time.time()))
    sig = base64.b64encode(SigningKey(base64.b64decode(PRIV_B64)[:32]).sign(f"{API_KEY}{ts}{path}{method}{body}".encode()).signature).decode()
    r = requests.request(method, f"{RH_BASE}{path}", headers={"x-api-key": API_KEY, "x-timestamp": ts, "x-signature": sig, "Content-Type": "application/json"}, data=body if body else None, timeout=15)
    if r.status_code not in (200, 201): print(f"[RH DEBUG] {method} {r.url} -> {r.status_code} | Body: {r.text[:160]}")
    return r

def place_tp_limit(qty, tp):
    tp_r = rh_req("POST", "/api/v1/crypto/trading/orders/", json.dumps({"client_order_id": str(uuid.uuid4()), "side": "sell", "type": "limit", "symbol": SYMBOL, "limit_order_config": {"asset_quantity": f"{qty:.0f}", "limit_price": f"{round(float(tp), 5):.5f}", "time_in_force": "gtc"}}))
    return tp_r.json().get("id", "") if tp_r.status_code in (200, 201) else ""

def get_live_bid_ask(fallback):
    try:
        r = requests.get("https://kraken.com", timeout=8)
        if r.status_code == 200:
            res = list(r.json()["result"].values())
            if float(res["b"]) > 0 and float(res["a"]) > 0: return float(res["b"]), float(res["a"]), "Kraken"
    except Exception: pass
    return fallback, fallback, "YF-Close"

def fmt_status(st, src, bid, ask):
    dep = round(st["qty"] * st["entry"], 2) if st["in_pos"] else 0.0
    ost = json.load(open(OTHER_STATE)) if os.path.exists(OTHER_STATE) else {"in_pos": False, "pot": STARTING_POT, "qty": 0.0, "entry": 0.0}
    odep = round(ost.get("qty", 0.0) * ost.get("entry", 0.0), 2) if ost.get("in_pos") else 0.0
    rh_tot, rh_used = round(st["pot"] + float(ost.get("pot", STARTING_POT)), 2), round(dep + odep, 2)
    pos = f"LONG {st['qty']:.0f} {COIN} @ ${st['entry']:.5f} (${dep:.2f})" if st["in_pos"] else "Flat"
    return f"{COIN} ({src}) Bid: ${bid:.5f} | Ask: ${ask:.5f} | Pos: {pos} | Coin Pot: ${dep:.2f}/${st['pot']:.2f} | RH Master: ${rh_used:.2f}/${rh_tot:.2f}"

def run():
    st = json.load(open(STATE_FILE)) if os.path.exists(STATE_FILE) else {"in_pos":False,"pot":STARTING_POT,"entry":0.0,"qty":0.0,"tp":0.0,"sl":0.0,"tp_order_id":"","added":False,"bar":""}
    bull, bear, l_type, _, _, _, atr, cpx, bts = analyze(YF_SYM)
    bid, ask, src = get_live_bid_ask(cpx)
    spread_pct = ((ask - bid) / bid * 100.0) if bid > 0 else 0.0
    if st["in_pos"]:
        if st.get("tp_order_id"):
            chk = rh_req("GET", f"/api/v1/crypto/trading/orders/{st['tp_order_id']}/")
            if chk.status_code == 200 and chk.json().get("state") == "filled":
                pnl = st["qty"] * (st["tp"] - st["entry"])
                npot = round(max(4.0, st["pot"] + pnl), 2)
                st = {"in_pos":False,"pot":npot,"entry":0.0,"qty":0.0,"tp":0.0,"sl":0.0,"tp_order_id":"","added":False,"bar":""}; json.dump(st, open(STATE_FILE, "w"), indent=2)
                msg = f"🟢 **RH {COIN} TP FILLED!** @ `${st['tp'] or bid:.5f}` | PnL: `${pnl:+.2f}`\n{fmt_status(st, src, bid, ask)}"; print(msg); send_discord(msg); return
        else:
            tp_id = place_tp_limit(st["qty"], st["tp"])
            if tp_id: st["tp_order_id"] = tp_id; json.dump(st, open(STATE_FILE, "w"), indent=2)
        rsn = "TP HIT" if bid >= st["tp"] else ("SL HIT" if bid <= st["sl"] else ("BEAR EXIT" if bear else None))
        if rsn:
            if st.get("tp_order_id"): rh_req("POST", f"/api/v1/crypto/trading/orders/{st['tp_order_id']}/cancel/"); time.sleep(2)
            if rh_req("POST", "/api/v1/crypto/trading/orders/", json.dumps({"client_order_id":str(uuid.uuid4()),"side":"sell","type":"market","symbol":SYMBOL,"market_order_config":{"asset_quantity":f"{st['qty']:.0f}"}})).status_code in (200, 201):
                pnl = st["qty"] * (bid - st["entry"])
                npot = round(max(4.0, st["pot"] + pnl), 2)
                st = {"in_pos":False,"pot":npot,"entry":0.0,"qty":0.0,"tp":0.0,"sl":0.0,"tp_order_id":"","added":False,"bar":""}; json.dump(st, open(STATE_FILE, "w"), indent=2)
                msg = f"🔴 **RH SELL {COIN} ({rsn})** @ `${bid:.5f}` | PnL: `${pnl:+.2f}`\n{fmt_status(st, src, bid, ask)}"; print(msg); send_discord(msg)
        elif bull and spread_pct <= 0.50 and not st.get("added", False) and st.get("bar") != bts:
            add_sp, add_q = round(st["pot"] * ADD_PCT, 2), round((st["pot"] * ADD_PCT) / ask, 0)
            if add_sp >= 1.0 and add_q >= 1:
                if st.get("tp_order_id"): rh_req("POST", f"/api/v1/crypto/trading/orders/{st['tp_order_id']}/cancel/"); time.sleep(2)
                if rh_req("POST", "/api/v1/crypto/trading/orders/", json.dumps({"client_order_id":str(uuid.uuid4()),"side":"buy","type":"market","symbol":SYMBOL,"market_order_config":{"asset_quantity":f"{add_q:.0f}"}})).status_code in (200, 201):
                    time.sleep(3); tot_q = round(st["qty"] + add_q, 0); avg_e = round(((st["qty"] * st["entry"]) + (add_q * ask)) / tot_q, 5)
                    st = {"in_pos":True,"pot":st["pot"],"entry":avg_e,"qty":tot_q,"tp":st["tp"],"sl":st["sl"],"tp_order_id":place_tp_limit(tot_q, st["tp"]),"added":True,"bar":bts}; json.dump(st, open(STATE_FILE, "w"), indent=2)
                    msg = f"➕ **RH ADD +10% {COIN}!** +`${add_sp:.2f}` @ `${ask:.5f}`\n{fmt_status(st, src, bid, ask)}"; print(msg); send_discord(msg)
    elif bull and spread_pct <= 0.50:
        sp, q = round(st["pot"] * INIT_PCT, 2), round((st["pot"] * INIT_PCT) / ask, 0)
        if sp >= 1.0 and q >= 1 and rh_req("POST", "/api/v1/crypto/trading/orders/", json.dumps({"client_order_id":str(uuid.uuid4()),"side":"buy","type":"market","symbol":SYMBOL,"market_order_config":{"asset_quantity":f"{q:.0f}"}})).status_code in (200, 201):
            time.sleep(3); tp, sl = round(ask + atr * 6.0, 5), round(ask - atr * 4.0, 5)
            st = {"in_pos":True,"pot":st["pot"],"entry":ask,"qty":q,"tp":tp,"sl":sl,"tp_order_id":place_tp_limit(q, tp),"added":False,"bar":bts}; json.dump(st, open(STATE_FILE, "w"), indent=2)
            msg = f"🟢 **RH {COIN} {l_type.upper()}!** `${sp:.2f}` @ `${ask:.5f}` | TP: `${tp:.5f}` | SL: `${sl:.5f}`\n{fmt_status(st, src, bid, ask)}"; print(msg); send_discord(msg)
    status = fmt_status(st, src, bid, ask); print(status)
    if EVENT_NAME == "push": send_discord(f"✅ **Robinhood {COIN} Bot Online!**\n{status}")

run()
