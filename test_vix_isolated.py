def get_vix_regime(vix: float) -> dict:
    """Returns regime name, position multiplier, and GPT instructions based on VIX."""
    if vix < 15:
        return {
            "name": "Normal Trading Mode",
            "multiplier": 1.0,
            "instruction": "Market is calm. Select best intraday and swing trades normally.",
            "color": "teal"
        }
    elif 15 <= vix < 20:
        return {
            "name": "Cautious Mode",
            "multiplier": 0.75,
            "instruction": "Market is slightly volatile. Prefer stocks with strong momentum and clear support levels. Tighter stop losses.",
            "color": "blue"
        }
    elif 20 <= vix < 25:
        return {
            "name": "High Volatility Mode",
            "multiplier": 0.50,
            "instruction": f"Market is highly volatile VIX at {vix}. Only recommend highest conviction trades. Wider stop losses. Prefer large cap stocks only — RELIANCE, HDFC, INFY, TCS, ICICIBANK, SBIN. No mid or small cap trades.",
            "color": "amber"
        }
    elif 25 <= vix < 30:
        return {
            "name": "Extreme Volatility Mode",
            "multiplier": 0.25,
            "instruction": f"VIX extremely high at {vix}. Only recommend SELL or SHORT trades on weak stocks. No BUY trades unless stock is showing exceptional strength vs market.",
            "color": "orange"
        }
    else: # vix >= 30
        return {
            "name": "Panic Mode",
            "multiplier": 0.0,
            "instruction": "Market in panic mode. Only recommend swing trades with 7-10 day horizon for strong fundamentally sound stocks at support levels. These are buying opportunities for patient traders.",
            "color": "red"
        }

def test_vix_regimes():
    test_cases = [
        (12.5, "Normal Trading Mode", 1.0),
        (11.0, "Normal Trading Mode", 1.0),
        (15.5, "Cautious Mode", 0.75),
        (19.9, "Cautious Mode", 0.75),
        (22.5, "High Volatility Mode", 0.50),
        (24.9, "High Volatility Mode", 0.50),
        (27.5, "Extreme Volatility Mode", 0.25),
        (29.9, "Extreme Volatility Mode", 0.25),
        (32.5, "Panic Mode", 0.0),
        (40.0, "Panic Mode", 0.0),
    ]
    
    print("Testing VIX Regimes...")
    all_passed = True
    for vix, expected_name, expected_multiplier in test_cases:
        regime = get_vix_regime(vix)
        if regime['name'] == expected_name and regime['multiplier'] == expected_multiplier:
            print(f"✅ VIX {vix}: {regime['name']} (multiplier: {regime['multiplier']})")
        else:
            print(f"❌ VIX {vix}: Expected {expected_name}/{expected_multiplier}, got {regime['name']}/{regime['multiplier']}")
            all_passed = False
            
    if all_passed:
        print("\nAll VIX regime tests passed!")
    else:
        print("\nSome tests failed.")
        import sys
        sys.exit(1)

if __name__ == "__main__":
    test_vix_regimes()
