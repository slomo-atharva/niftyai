import sys
import os

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent.pre_market_scan import get_vix_regime

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
        sys.exit(1)

if __name__ == "__main__":
    test_vix_regimes()
