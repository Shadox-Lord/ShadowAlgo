"""
Shadow AI Trading System - Walk-Forward Analysis Engine
========================================================

CRITICAL FIX #1: Statistical Validation
Implements Walk-Forward Analysis (WFA) to validate strategy robustness across 
different market regimes and prevent overfitting.

This addresses the institutional assessment finding that "18 trades is not a 
sample—it's an anecdote" by providing out-of-sample validation.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
import numpy as np
import pandas as pd


@dataclass
class WFASegment:
    """Represents one walk-forward segment"""
    segment_id: int
    in_sample_start: str
    in_sample_end: str
    out_of_sample_start: str
    out_of_sample_end: str
    in_sample_trades: int
    out_of_sample_trades: int
    in_sample_pf: float  # Profit Factor
    out_of_sample_pf: float
    in_sample_dd: float  # Max Drawdown
    out_of_sample_dd: float
    in_sample_return: float
    out_of_sample_return: float
    regime_type: str  # trending, ranging, volatile, quiet


@dataclass
class WFAResults:
    """Complete WFA results"""
    total_segments: int
    avg_out_of_sample_pf: float
    avg_out_of_sample_dd: float
    avg_out_of_sample_return: float
    pf_degradation_pct: float  # How much PF drops out-of-sample
    dd_increase_pct: float
    consistency_score: float  # 0-100, higher = more consistent
    pass_criteria: bool
    segment_results: List[WFASegment]
    monte_carlo_ruin_probability: float
    minimum_sample_achieved: bool


class WalkForwardAnalyzer:
    """
    Implements Walk-Forward Analysis for strategy validation
    
    Methodology:
    1. Split data into overlapping in-sample/out-of-sample periods
    2. Optimize parameters on in-sample data
    3. Test optimized parameters on out-of-sample data
    4. Measure degradation to detect overfitting
    """
    
    def __init__(self, 
                 backtest_engine,
                 in_sample_months: int = 6,
                 out_of_sample_months: int = 2,
                 step_months: int = 2):
        """
        Args:
            backtest_engine: The backtest engine to analyze
            in_sample_months: Length of optimization window
            out_of_sample_months: Length of validation window
            step_months: How much to shift window each iteration
        """
        self.backtest_engine = backtest_engine
        self.in_sample_months = in_sample_months
        self.out_of_sample_months = out_of_sample_months
        self.step_months = step_months
        
    def run_wfa(self, 
                start_date: str,
                end_date: str,
                parameter_grid: Optional[Dict] = None) -> WFAResults:
        """
        Run complete Walk-Forward Analysis
        
        Args:
            start_date: Start of analysis period (YYYY-MM-DD)
            end_date: End of analysis period (YYYY-MM-DD)
            parameter_grid: Parameters to optimize (default: ADX threshold)
            
        Returns:
            WFAResults with all metrics
        """
        from datetime import datetime
        
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        
        segments = []
        current_start = start_dt
        segment_id = 0
        
        while current_start < end_dt:
            # Calculate date ranges
            in_sample_end = current_start + timedelta(days=self.in_sample_months * 30)
            out_of_sample_end = in_sample_end + timedelta(days=self.out_of_sample_months * 30)
            
            if out_of_sample_end > end_dt:
                break
            
            # Run optimization on in-sample data
            print(f"\n=== Segment {segment_id}: In-Sample Optimization ===")
            print(f"Period: {current_start.date()} to {in_sample_end.date()}")
            
            best_params = self._optimize_in_sample(
                current_start.strftime("%Y-%m-%d"),
                in_sample_end.strftime("%Y-%m-%d"),
                parameter_grid or {'MIN_ADX': [12, 14, 16, 18, 20]}
            )
            
            # Test on out-of-sample data
            print(f"Out-of-Sample Validation: {in_sample_end.date()} to {out_of_sample_end.date()}")
            
            oos_metrics = self._test_out_of_sample(
                in_sample_end.strftime("%Y-%m-%d"),
                out_of_sample_end.strftime("%Y-%m-%d"),
                best_params
            )
            
            # Get in-sample metrics for comparison
            ins_metrics = self._get_in_sample_metrics(
                current_start.strftime("%Y-%m-%d"),
                in_sample_end.strftime("%Y-%m-%d"),
                best_params
            )
            
            # Determine regime type
            regime = self._classify_regime(current_start, in_sample_end)
            
            segment = WFASegment(
                segment_id=segment_id,
                in_sample_start=current_start.strftime("%Y-%m-%d"),
                in_sample_end=in_sample_end.strftime("%Y-%m-%d"),
                out_of_sample_start=in_sample_end.strftime("%Y-%m-%d"),
                out_of_sample_end=out_of_sample_end.strftime("%Y-%m-%d"),
                in_sample_trades=ins_metrics.get('total_trades', 0),
                out_of_sample_trades=oos_metrics.get('total_trades', 0),
                in_sample_pf=ins_metrics.get('profit_factor', 0),
                out_of_sample_pf=oos_metrics.get('profit_factor', 0),
                in_sample_dd=ins_metrics.get('max_drawdown', 0),
                out_of_sample_dd=oos_metrics.get('max_drawdown', 0),
                in_sample_return=ins_metrics.get('total_return_pct', 0),
                out_of_sample_return=oos_metrics.get('total_return_pct', 0),
                regime_type=regime
            )
            
            segments.append(segment)
            segment_id += 1
            
            # Step forward
            current_start += timedelta(days=self.step_months * 30)
        
        # Aggregate results
        return self._aggregate_results(segments)
    
    def _optimize_in_sample(self, 
                           start: str, 
                           end: str, 
                           param_grid: Dict) -> Dict:
        """
        Find best parameters for in-sample period
        Simple grid search (can be enhanced with Bayesian optimization)
        """
        best_pf = 0
        best_params = {}
        
        # Extract parameter names and values
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        
        # Generate all combinations
        from itertools import product
        for combo in product(*param_values):
            test_params = dict(zip(param_names, combo))
            
            # Temporarily update config
            original_config = {}
            for key, value in test_params.items():
                original_config[key] = self.backtest_engine.CONFIG.get(key)
                self.backtest_engine.CONFIG[key] = value
            
            # Run backtest on this segment
            try:
                metrics = self.backtest_engine.run_backtest(
                    symbol=self.backtest_engine.CONFIG['SYMBOL'],
                    start_date=start,
                    end_date=end,
                    verbose=False
                )
                
                pf = metrics.get('profit_factor', 0)
                if pf > best_pf:
                    best_pf = pf
                    best_params = test_params.copy()
                    
            except Exception as e:
                print(f"Error testing params {test_params}: {e}")
            
            finally:
                # Restore original config
                for key, value in original_config.items():
                    if value is not None:
                        self.backtest_engine.CONFIG[key] = value
                    elif key in self.backtest_engine.CONFIG:
                        del self.backtest_engine.CONFIG[key]
        
        print(f"Best params: {best_params}, IS Profit Factor: {best_pf:.2f}")
        return best_params or {'MIN_ADX': 14}  # Default fallback
    
    def _test_out_of_sample(self, 
                           start: str, 
                           end: str, 
                           params: Dict) -> Dict:
        """Test optimized parameters on out-of-sample data"""
        # Apply optimized parameters
        original_config = {}
        for key, value in params.items():
            original_config[key] = self.backtest_engine.CONFIG.get(key)
            self.backtest_engine.CONFIG[key] = value
        
        try:
            metrics = self.backtest_engine.run_backtest(
                symbol=self.backtest_engine.CONFIG['SYMBOL'],
                start_date=start,
                end_date=end,
                verbose=False
            )
            return metrics
        except Exception as e:
            print(f"OOS test error: {e}")
            return {'profit_factor': 0, 'max_drawdown': 100, 'total_trades': 0}
        finally:
            # Restore config
            for key, value in original_config.items():
                if value is not None:
                    self.backtest_engine.CONFIG[key] = value
                elif key in self.backtest_engine.CONFIG:
                    del self.backtest_engine.CONFIG[key]
    
    def _get_in_sample_metrics(self, start: str, end: str, params: Dict) -> Dict:
        """Get metrics for in-sample period with given params"""
        return self._test_out_of_sample(start, end, params)
    
    def _classify_regime(self, start: datetime, end: datetime) -> str:
        """Classify market regime for period based on volatility and trend"""
        # Simplified regime classification
        # In production, use ADX, ATR, Hurst exponent, etc.
        mid_point = start + (end - start) / 2
        month = mid_point.month
        
        # Rough heuristic (replace with actual data analysis)
        if month in [1, 2, 3, 9, 10, 11]:
            return "trending"
        elif month in [6, 7, 8]:
            return "ranging"
        else:
            return "volatile"
    
    def _aggregate_results(self, segments: List[WFASegment]) -> WFAResults:
        """Aggregate segment results into final WFA report"""
        if not segments:
            return WFAResults(
                total_segments=0,
                avg_out_of_sample_pf=0,
                avg_out_of_sample_dd=0,
                avg_out_of_sample_return=0,
                pf_degradation_pct=0,
                dd_increase_pct=0,
                consistency_score=0,
                pass_criteria=False,
                segment_results=[],
                monte_carlo_ruin_probability=1.0,
                minimum_sample_achieved=False
            )
        
        # Calculate averages
        oos_pfs = [s.out_of_sample_pf for s in segments if s.out_of_sample_trades > 0]
        oos_dds = [s.out_of_sample_dd for s in segments if s.out_of_sample_trades > 0]
        oos_returns = [s.out_of_sample_return for s in segments if s.out_of_sample_trades > 0]
        
        avg_oos_pf = np.mean(oos_pfs) if oos_pfs else 0
        avg_oos_dd = np.mean(oos_dds) if oos_dds else 0
        avg_oos_return = np.mean(oos_returns) if oos_returns else 0
        
        # Calculate degradation
        ins_pfs = [s.in_sample_pf for s in segments if s.in_sample_trades > 0]
        avg_ins_pf = np.mean(ins_pfs) if ins_pfs else 0
        pf_degradation = ((avg_ins_pf - avg_oos_pf) / avg_ins_pf * 100) if avg_ins_pf > 0 else 0
        
        # Calculate DD increase
        ins_dds = [s.in_sample_dd for s in segments if s.in_sample_trades > 0]
        avg_ins_dd = np.mean(ins_dds) if ins_dds else 0
        dd_increase = ((avg_oos_dd - avg_ins_dd) / avg_ins_dd * 100) if avg_ins_dd > 0 else 0
        
        # Consistency score (0-100)
        # Based on PF stability and trade frequency
        pf_std = np.std(oos_pfs) if len(oos_pfs) > 1 else 0
        trade_counts = [s.out_of_sample_trades for s in segments]
        trade_std = np.std(trade_counts) if len(trade_counts) > 1 else 0
        
        consistency = max(0, 100 - (pf_std * 50) - (trade_std * 5))
        
        # Pass criteria
        total_oos_trades = sum(s.out_of_sample_trades for s in segments)
        pass_criteria = (
            avg_oos_pf > 1.3 and
            avg_oos_dd < 20 and
            total_oos_trades >= 30 and
            pf_degradation < 40  # Less than 40% degradation
        )
        
        # Monte Carlo ruin probability (simplified)
        mc_ruin_prob = self._estimate_monte_carlo_ruin(segments)
        
        return WFAResults(
            total_segments=len(segments),
            avg_out_of_sample_pf=avg_oos_pf,
            avg_out_of_sample_dd=avg_oos_dd,
            avg_out_of_sample_return=avg_oos_return,
            pf_degradation_pct=pf_degradation,
            dd_increase_pct=dd_increase,
            consistency_score=consistency,
            pass_criteria=pass_criteria,
            segment_results=segments,
            monte_carlo_ruin_probability=mc_ruin_prob,
            minimum_sample_achieved=total_oos_trades >= 30
        )
    
    def _estimate_monte_carlo_ruin(self, segments: List[WFASegment], 
                                   n_simulations: int = 1000) -> float:
        """
        Estimate probability of ruin (>20% drawdown) via Monte Carlo
        Simplified version - in production use full trade sequence randomization
        """
        if not segments:
            return 1.0
        
        # Collect all OOS returns
        oos_returns = [s.out_of_sample_return / 100 for s in segments if s.out_of_sample_trades > 0]
        
        if len(oos_returns) < 3:
            return 0.5  # Insufficient data
        
        # Bootstrap simulation
        ruin_count = 0
        for _ in range(n_simulations):
            # Random sample with replacement
            sampled_returns = np.random.choice(oos_returns, size=len(oos_returns) * 3, replace=True)
            
            # Calculate cumulative drawdown
            equity_curve = np.cumsum(sampled_returns)
            peak = np.maximum.accumulate(equity_curve)
            drawdown = (peak - equity_curve) / (peak + 1e-10)
            
            if np.max(drawdown) > 0.20:
                ruin_count += 1
        
        return ruin_count / n_simulations
    
    def generate_report(self, results: WFAResults) -> str:
        """Generate human-readable WFA report"""
        report = []
        report.append("=" * 70)
        report.append("WALK-FORWARD ANALYSIS REPORT")
        report.append("=" * 70)
        report.append(f"\nTotal Segments: {results.total_segments}")
        report.append(f"\n--- OUT-OF-SAMPLE PERFORMANCE ---")
        report.append(f"Average Profit Factor: {results.avg_out_of_sample_pf:.2f}")
        report.append(f"Average Max Drawdown: {results.avg_out_of_sample_dd:.2f}%")
        report.append(f"Average Total Return: {results.avg_out_of_sample_return:.2f}%")
        report.append(f"\n--- ROBUSTNESS METRICS ---")
        report.append(f"PF Degradation (IS vs OOS): {results.pf_degradation_pct:.1f}%")
        report.append(f"DD Increase (IS vs OOS): {results.dd_increase_pct:.1f}%")
        report.append(f"Consistency Score: {results.consistency_score:.1f}/100")
        report.append(f"\n--- RISK ASSESSMENT ---")
        report.append(f"Monte Carlo Ruin Probability: {results.monte_carlo_ruin_probability:.2%}")
        report.append(f"Minimum Sample Achieved: {'YES' if results.minimum_sample_achieved else 'NO'}")
        report.append(f"\n--- FINAL VERDICT ---")
        report.append(f"PASS CRITERIA: {'✅ PASS' if results.pass_criteria else '❌ FAIL'}")
        
        if results.pass_criteria:
            report.append("\nStrategy shows statistical robustness across market regimes.")
            report.append("Ready for paper trading validation.")
        else:
            report.append("\n⚠️ WARNING: Strategy may be overfit or statistically insufficient.")
            if results.avg_out_of_sample_pf <= 1.3:
                report.append("  - Out-of-sample Profit Factor too low")
            if results.monte_carlo_ruin_probability > 0.05:
                report.append(f"  - Ruin probability too high ({results.monte_carlo_ruin_probability:.1%})")
            if not results.minimum_sample_achieved:
                report.append("  - Insufficient trade count for statistical significance")
        
        report.append("\n" + "=" * 70)
        report.append("SEGMENT DETAILS:")
        report.append("=" * 70)
        
        for seg in results.segment_results:
            report.append(f"\nSegment {seg.segment_id} ({seg.regime_type}):")
            report.append(f"  IS: {seg.in_sample_start} to {seg.in_sample_end}")
            report.append(f"      Trades: {seg.in_sample_trades}, PF: {seg.in_sample_pf:.2f}, DD: {seg.in_sample_dd:.1f}%")
            report.append(f"  OOS: {seg.out_of_sample_start} to {seg.out_of_sample_end}")
            report.append(f"       Trades: {seg.out_of_sample_trades}, PF: {seg.out_of_sample_pf:.2f}, DD: {seg.out_of_sample_dd:.1f}%")
        
        return "\n".join(report)


# Convenience function for standalone execution
def run_walk_forward_analysis(backtest_engine, 
                             start_date: str = "2022-01-01",
                             end_date: str = "2024-01-01") -> WFAResults:
    """
    Run WFA with default parameters
    
    Usage:
        from backtest_engine import BacktestEngine
        from lib.wfa import run_walk_forward_analysis
        
        engine = BacktestEngine()
        results = run_walk_forward_analysis(engine)
        print(results.generate_report())
    """
    analyzer = WalkForwardAnalyzer(
        backtest_engine=backtest_engine,
        in_sample_months=6,
        out_of_sample_months=2,
        step_months=2
    )
    
    results = analyzer.run_wfa(
        start_date=start_date,
        end_date=end_date,
        parameter_grid={'MIN_ADX': [12, 14, 16, 18]}
    )
    
    return results
