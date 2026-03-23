from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fetch_current_polymarket import fetch_polymarket_data_struct
from fetch_current_kalshi import fetch_kalshi_data_struct
import datetime

# Fee rates (approximate) — update these if platform fees change
POLYMARKET_FEE_RATE = 0.02  # ~2% on winnings
KALSHI_FEE_RATE = 0.07      # ~7% on profits (capped at contract price for taker)

app = FastAPI()

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all for dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _estimate_fees(poly_cost, kalshi_cost):
    """Estimate trading fees for both legs. Returns total estimated fees."""
    # Polymarket: fee on profit (winning leg pays out $1, profit = $1 - cost)
    poly_profit = 1.00 - poly_cost
    poly_fee = poly_profit * POLYMARKET_FEE_RATE if poly_profit > 0 else 0

    # Kalshi: fee on profit (winning leg pays out $1, profit = $1 - cost)
    kalshi_profit = 1.00 - kalshi_cost
    kalshi_fee = kalshi_profit * KALSHI_FEE_RATE if kalshi_profit > 0 else 0

    return round(poly_fee + kalshi_fee, 4)

def _add_fee_info(check):
    """Add fee estimation fields to an arbitrage check dict."""
    est_fees = _estimate_fees(check["poly_cost"], check["kalshi_cost"])
    check["estimated_fees"] = est_fees
    check["margin_after_fees"] = round(check["margin"] - est_fees, 4)
    check["profitable_after_fees"] = check["margin_after_fees"] > 0

@app.get("/arbitrage")
def get_arbitrage_data():
    # Fetch Data
    poly_data, poly_err = fetch_polymarket_data_struct()
    kalshi_data, kalshi_err = fetch_kalshi_data_struct()
    
    response = {
        "timestamp": datetime.datetime.now().isoformat(),
        "polymarket": poly_data,
        "kalshi": kalshi_data,
        "checks": [],
        "opportunities": [],
        "errors": []
    }
    
    if poly_err:
        response["errors"].append(poly_err)
    if kalshi_err:
        response["errors"].append(kalshi_err)
        
    if not poly_data or not kalshi_data:
        return response

    # Logic
    poly_strike = poly_data['price_to_beat']
    poly_up_cost = poly_data['prices'].get('Up', 0.0)
    poly_down_cost = poly_data['prices'].get('Down', 0.0)
    
    if poly_strike is None:
        response["errors"].append("Polymarket Strike is None")
        return response

    # Sanity check: Up + Down should be approximately $1.00 for a binary market
    poly_sum = poly_up_cost + poly_down_cost
    if poly_sum > 0 and (poly_sum < 0.85 or poly_sum > 1.15):
        response["errors"].append(
            f"Polymarket price sanity check failed: Up ({poly_up_cost:.3f}) + Down ({poly_down_cost:.3f}) = {poly_sum:.3f}, expected ~1.00"
        )
        return response

    kalshi_markets = kalshi_data.get('markets', [])
    
    # Ensure sorted by strike
    kalshi_markets.sort(key=lambda x: x['strike'])
    
    # Find index closest to poly_strike
    closest_idx = 0
    min_diff = float('inf')
    for i, m in enumerate(kalshi_markets):
        diff = abs(m['strike'] - poly_strike)
        if diff < min_diff:
            min_diff = diff
            closest_idx = i
            
    # Select 4 below and 4 above (approx 8-9 markets total)
    # If closest is at index C, we want [C-4, C+5] roughly
    start_idx = max(0, closest_idx - 4)
    end_idx = min(len(kalshi_markets), closest_idx + 5) # +5 to include the closest and 4 above
    
    selected_markets = kalshi_markets[start_idx:end_idx]
    
    for km in selected_markets:
        kalshi_strike = km['strike']
        # Values are already in dollars (normalized by fetch_current_kalshi)
        kalshi_yes_cost = km['yes_ask']
        kalshi_no_cost = km['no_ask']

        # Skip markets with unpriced legs (0 = no quote available)
        if kalshi_yes_cost == 0 or kalshi_no_cost == 0:
            continue
            
        check_data = {
            "kalshi_strike": kalshi_strike,
            "kalshi_yes": kalshi_yes_cost,
            "kalshi_no": kalshi_no_cost,
            "type": "",
            "poly_leg": "",
            "kalshi_leg": "",
            "poly_cost": 0,
            "kalshi_cost": 0,
            "total_cost": 0,
            "is_arbitrage": False,
            "margin": 0
        }

        if poly_strike > kalshi_strike:
            check_data["type"] = "Poly > Kalshi"
            check_data["poly_leg"] = "Down"
            check_data["kalshi_leg"] = "Yes"
            check_data["poly_cost"] = poly_down_cost
            check_data["kalshi_cost"] = kalshi_yes_cost
            check_data["total_cost"] = poly_down_cost + kalshi_yes_cost
            
        elif poly_strike < kalshi_strike:
            check_data["type"] = "Poly < Kalshi"
            check_data["poly_leg"] = "Up"
            check_data["kalshi_leg"] = "No"
            check_data["poly_cost"] = poly_up_cost
            check_data["kalshi_cost"] = kalshi_no_cost
            check_data["total_cost"] = poly_up_cost + kalshi_no_cost
            
        elif poly_strike == kalshi_strike:
            # Check 1
            check1 = check_data.copy()
            check1["type"] = "Equal"
            check1["poly_leg"] = "Down"
            check1["kalshi_leg"] = "Yes"
            check1["poly_cost"] = poly_down_cost
            check1["kalshi_cost"] = kalshi_yes_cost
            check1["total_cost"] = poly_down_cost + kalshi_yes_cost
            
            if check1["total_cost"] < 1.00:
                check1["is_arbitrage"] = True
                check1["margin"] = 1.00 - check1["total_cost"]
                _add_fee_info(check1)
                response["opportunities"].append(check1)
            response["checks"].append(check1)
            
            # Check 2
            check2 = check_data.copy()
            check2["type"] = "Equal"
            check2["poly_leg"] = "Up"
            check2["kalshi_leg"] = "No"
            check2["poly_cost"] = poly_up_cost
            check2["kalshi_cost"] = kalshi_no_cost
            check2["total_cost"] = poly_up_cost + kalshi_no_cost
            
            if check2["total_cost"] < 1.00:
                check2["is_arbitrage"] = True
                check2["margin"] = 1.00 - check2["total_cost"]
                _add_fee_info(check2)
                response["opportunities"].append(check2)
            response["checks"].append(check2)
            continue # Skip adding the base check_data

        if check_data["total_cost"] < 1.00:
            check_data["is_arbitrage"] = True
            check_data["margin"] = 1.00 - check_data["total_cost"]
            _add_fee_info(check_data)
            response["opportunities"].append(check_data)
            
        response["checks"].append(check_data)
        
    return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
