"""
Statistical utilities: bootstrap CI, permutation tests, t-stats, Sharpe.
"""
import numpy as np
from scipy import stats


def tstat_and_pvalue(returns: np.ndarray) -> tuple[float, float]:
    """One-sample t-test: is the mean return different from zero?"""
    if len(returns) < 2:
        return float("nan"), float("nan")
    t, p = stats.ttest_1samp(returns, 0.0)
    return float(t), float(p)


def sharpe(returns: np.ndarray, periods_per_year: int = 252) -> float:
    """Annualized Sharpe ratio (assumes zero risk-free rate)."""
    if returns.std() == 0:
        return float("nan")
    return float((returns.mean() / returns.std()) * np.sqrt(periods_per_year))


def win_rate(returns: np.ndarray) -> float:
    return float((returns > 0).mean())


def bootstrap_ci(returns: np.ndarray, n: int = 10_000, ci: float = 0.95) -> tuple[float, float]:
    """Bootstrap confidence interval for the mean return."""
    rng = np.random.default_rng(42)
    means = np.array([
        rng.choice(returns, size=len(returns), replace=True).mean()
        for _ in range(n)
    ])
    lo = (1 - ci) / 2
    return float(np.quantile(means, lo)), float(np.quantile(means, 1 - lo))


def permutation_pvalue(returns: np.ndarray, n: int = 10_000) -> float:
    """
    Permutation test: what fraction of shuffled samples have a mean
    as extreme as the observed mean? (two-tailed)
    """
    rng = np.random.default_rng(42)
    observed = abs(returns.mean())
    null = np.array([
        abs(rng.permutation(returns).mean())
        for _ in range(n)
    ])
    return float((null >= observed).mean())


def summarize(returns: np.ndarray, label: str = "") -> dict:
    """Full stats summary for a set of returns."""
    t, p_t = tstat_and_pvalue(returns)
    lo, hi = bootstrap_ci(returns)
    p_perm = permutation_pvalue(returns)
    return {
        "label": label,
        "n": len(returns),
        "mean_pct": round(returns.mean() * 100, 4),
        "win_rate": round(win_rate(returns), 4),
        "sharpe": round(sharpe(returns), 3),
        "t_stat": round(t, 3),
        "p_ttest": round(p_t, 6),
        "p_permutation": round(p_perm, 6),
        "ci_95_lo": round(lo * 100, 4),
        "ci_95_hi": round(hi * 100, 4),
    }
