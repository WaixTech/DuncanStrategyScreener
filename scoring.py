import math

WEIGHTS = {"discount": 40, "valuation": 15, "momentum": 15, "catalyst": 10, "quality": 10, "sentiment": 10}

def clamp(x, lo, hi): return max(lo, min(hi, x))

def compute_duncan_score(row, return_components=False):
    disc = row.get("discount", 0) or 0.0
    s_discount = clamp(disc/0.25, 0, 1) * WEIGHTS["discount"]

    pe = row.get("pe", float("nan"))
    if pe is None or math.isnan(pe): s_val = WEIGHTS["valuation"] * 0.3
    else:
        v = 1.0 if pe <= 10 else 0.0 if pe >= 40 else (40 - pe)/30.0
        s_val = v * WEIGHTS["valuation"]

    m3 = row.get("mom_3m", 0) or 0.0
    s_mom = clamp((m3 + 0.15)/0.30, 0, 1) * WEIGHTS["momentum"]

    days = row.get("days_to_event", None)
    s_cat = WEIGHTS["catalyst"] if isinstance(days,(int,float)) and 0 <= days <= 21 else WEIGHTS["catalyst"]*0.4

    roe = row.get("roe", float("nan"))
    de  = row.get("debt_ebitda", float("nan"))
    q = 0.0
    if not math.isnan(roe): q += clamp(roe/20.0, 0, 1) * 0.6
    if not math.isnan(de):
        q += 0.4 if de <= 1 else 0.0 if de >= 5 else (5 - de)/4.0 * 0.4
    s_qual = q * WEIGHTS["quality"]

    s_sent = WEIGHTS["sentiment"] * 0.5

    total = s_discount + s_val + s_mom + s_cat + s_qual + s_sent
    if return_components:
        return {"discount": round(s_discount,2),"valuation": round(s_val,2),"momentum": round(s_mom,2),
                "catalyst": round(s_cat,2),"quality": round(s_qual,2),"sentiment": round(s_sent,2),"total": round(total,2)}
    return round(total, 2)