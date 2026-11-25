import pandas as pd, yfinance as yf

def analyze(yf_sym):
    raw = yf.download(yf_sym, period="60d", interval="1h", progress=False)
    if isinstance(raw.columns, pd.MultiIndex): raw.columns = raw.columns.get_level_values(0)
    df = raw.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last"}).dropna().iloc[:-1]
    c, o, h, l = df["Close"], df["Open"], df["High"], df["Low"]
    ema20, d = c.ewm(span=20, adjust=False).mean(), c.diff()
    rsi = 100 - (100 / (1 + (d.clip(lower=0).ewm(alpha=1/9, adjust=False).mean() / (-d.clip(upper=0)).ewm(alpha=1/9, adjust=False).mean())))
    r_avg, hist = rsi.rolling(9).mean(), c.ewm(span=9, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    hist = hist - hist.ewm(span=9, adjust=False).mean()
    atr = pd.concat((h - l, (h - c.shift()).abs(), (l - c.shift()).abs()), axis=1).max(axis=1).ewm(alpha=1/12, adjust=False).mean()
    rd = bm = rm = gs = rs = bc = rc = 0
    for i in range(1, len(df)):
        if rsi.iat[i-1] <= r_avg.iat[i-1] and rsi.iat[i] > r_avg.iat[i]: rd = 1
        elif rsi.iat[i-1] >= r_avg.iat[i-1] and rsi.iat[i] < r_avg.iat[i]: rd = -1
        iz = 40.0 <= rsi.iat[i] <= 60.0
        bm = bm + 1 if (hist.iat[i] > 0 and hist.iat[i] > hist.iat[i-1]) else 0
        rm = rm + 1 if (hist.iat[i] < 0 and hist.iat[i] < hist.iat[i-1]) else 0
        gs = gs + 1 if (int(rd == 1 and iz) + int(bm >= 2) + int(c.iat[i] > ema20.iat[i])) == 3 else 0
        rs = rs + 1 if (int(rd == -1 and iz) + int(rm >= 2) + int(c.iat[i] < ema20.iat[i])) == 3 else 0
        vb = abs(c.iat[i] - o.iat[i]) >= atr.iat[i] * 0.15
        bc = bc + 1 if (c.iat[i] > o.iat[i] and vb) else 0
        rc = rc + 1 if (c.iat[i] < o.iat[i] and vb) else 0
    la, lc, lo, le, bts = float(atr.iat[-1]), float(c.iat[-1]), float(o.iat[-1]), float(ema20.iat[-1]), str(df.index[-1])
    sok, ins = float(h.iat[-1] - l.iat[-1]) <= la * 3.25, (float(h.iat[-2]) <= float(h.iat[-3])) and (float(l.iat[-2]) >= float(l.iat[-3]))
    tok_l = ((le - float(ema20.iat[-6])) >= 0) and (lc > le + la * 0.25)
    b212 = (float(c.iat[-3]) > float(o.iat[-3])) and (abs(float(c.iat[-3]) - float(o.iat[-3])) >= la * 0.15) and ins and (lc > lo) and (abs(lc - lo) >= la * 0.15) and (lc > float(h.iat[-2])) and tok_l
    nb, ob = (((2 <= gs <= 3 and lc > lo) or (2 <= bc <= 3))) and tok_l, (2 <= bc <= 3) and (float(rsi.iloc[-4:].min()) < 30.0) and (lc > lo) and (abs(lc - lo) >= la * 0.20)
    bull, l_type = (nb or ob or b212) and sok, ("2-1-2 Buy" if (b212 and not nb and not ob) else ("Oversold Buy" if (ob and not nb) else "Trend Buy"))
    tok_s = ((le - float(ema20.iat[-6])) <= 0) and (lc < le - la * 0.25)
    s212 = (float(c.iat[-3]) < float(o.iat[-3])) and (abs(float(c.iat[-3]) - float(o.iat[-3])) >= la * 0.15) and ins and (lc < lo) and (abs(lc - lo) >= la * 0.15) and (lc < float(l.iat[-2])) and tok_s
    ns, os_s = (((2 <= rs <= 3 and lc < lo) or (2 <= rc <= 3))) and tok_s, (2 <= rc <= 3) and (float(rsi.iloc[-4:].max()) > 70.0) and (lc < lo) and (abs(lc - lo) >= la * 0.20)
    short, s_type = (ns or os_s or s212) and sok, ("2-1-2 Short" if (s212 and not ns and not os_s) else ("Overbought Short" if (os_s and not ns) else "Trend Short"))
    return bull, (((rs >= 3 and lc < lo) or (rc >= 3))) and not bull, l_type, short, (((gs >= 3 and lc > lo) or (bc >= 3))) and not short, s_type, la, lc, bts
