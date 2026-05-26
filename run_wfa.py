#!/usr/bin/env python3
"""
Shadow AI Trading System - WFA Runner Script
=============================================

CRITICAL FIX #1: Execute Walk-Forward Analysis

Usage:
    python run_wfa.py
    
This script runs Walk-Forward Analysis on the backtest engine to validate
statistical robustness across market regimes.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest_engine import BacktestEngine, CONFIG
from lib.wfa import run_walk_forward_analysis


def main():
    print("=" * 70)
    print("SHADOW AI TRADING SYSTEM - WALK-FORWARD ANALYSIS")
    print("=" * 70)
    print("\n⚠️  This analysis may take 5-15 minutes depending on data size.\n")
    
    # Initialize backtest engine
    engine = BacktestEngine()
    
    # Run WFA
    print("Starting Walk-Forward Analysis...")
    print("Configuration:")
    print(f"  Symbol: {CONFIG['SYMBOL']}")
    print(f"  Period: {CONFIG['START_DATE']} to {CONFIG['END_DATE']}")
    print(f"  In-Sample Window: 6 months")
    print(f"  Out-of-Sample Window: 2 months")
    print(f"  Step Size: 2 months")
    print(f"  Parameters to optimize: ADX threshold [12, 14, 16, 18]")
    print("\n" + "=" * 70)
    
    try:
        results = run_walk_forward_analysis(
            engine,
            start_date=CONFIG['START_DATE'],
            end_date=CONFIG['END_DATE']
        )
        
        # Print report
        report = results.generate_report(results)
        print(report)
        
        # Save results to file
        output_file = "./backtest_results/wfa_results.json"
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        import json
        from dataclasses import asdict
        
        results_dict = {
            'total_segments': results.total_segments,
            'avg_out_of_sample_pf': results.avg_out_of_sample_pf,
            'avg_out_of_sample_dd': results.avg_out_of_sample_dd,
            'avg_out_of_sample_return': results.avg_out_of_sample_return,
            'pf_degradation_pct': results.pf_degradation_pct,
            'dd_increase_pct': results.dd_increase_pct,
            'consistency_score': results.consistency_score,
            'pass_criteria': results.pass_criteria,
            'monte_carlo_ruin_probability': results.monte_carlo_ruin_probability,
            'minimum_sample_achieved': results.minimum_sample_achieved,
            'segment_results': [asdict(s) for s in results.segment_results]
        }
        
        with open(output_file, 'w') as f:
            json.dump(results_dict, f, indent=2)
        
        print(f"\n✅ Results saved to: {output_file}")
        
        # Final verdict
        print("\n" + "=" * 70)
        if results.pass_criteria:
            print("🟢 VERDICT: STRATEGY PASSES STATISTICAL VALIDATION")
            print("\nNext steps:")
            print("  1. ✅ WFA Complete")
            print("  2. ⏳ Implement Pydantic schema validation (DONE)")
            print("  3. ⏳ Deploy OANDA paper integration")
            print("  4. ⏳ Begin 30-day paper trading crucible")
        else:
            print("🔴 VERDICT: STRATEGY FAILS STATISTICAL VALIDATION")
            print("\nRecommended actions:")
            print("  - Reduce risk per trade")
            print("  - Tighten regime filters")
            print("  - Re-evaluate SMC logic")
            print("  - Do NOT proceed to live trading")
        
        print("=" * 70)
        
        return results.pass_criteria
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
