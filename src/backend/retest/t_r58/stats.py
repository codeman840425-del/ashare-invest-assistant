"""选参与统计推断，出处：方案 §7.3、§8.2。"""

from math import e, erf, sqrt
from statistics import NormalDist

import numpy as np


def block_bootstrap_mean(
    leg_day: np.ndarray,
    values: np.ndarray,
    n_days: int,
    block: int = 5,
    reps: int = 2000,
    seed: int = 0,
) -> tuple[float, float]:
    if len(values) == 0 or n_days == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    counts = np.bincount(leg_day, minlength=n_days)
    totals = np.bincount(leg_day, weights=values, minlength=n_days)
    samples = []
    for _ in range(reps):
        starts = rng.integers(0, n_days, size=(n_days + block - 1) // block)
        days = ((starts[:, None] + np.arange(block)) % n_days).ravel()[:n_days]
        count = counts[days].sum()
        if count:
            samples.append(totals[days].sum() / count)
    if not samples:
        return float("nan"), float("nan")
    lo, hi = np.quantile(samples, [0.025, 0.975])
    return float(lo), float(hi)


def block_bootstrap_paired(
    leg_day: np.ndarray,
    a_vals: np.ndarray,
    b_vals: np.ndarray,
    n_days: int,
    block: int = 5,
    reps: int = 2000,
    seed: int = 0,
) -> tuple[float, float]:
    return block_bootstrap_mean(
        leg_day,
        np.asarray(a_vals) - np.asarray(b_vals),
        n_days,
        block,
        reps,
        seed,
    )


def holm(pvals: list[float]) -> list[float]:
    if any(not np.isfinite(p) or not 0 <= p <= 1 for p in pvals):
        raise ValueError(
            "Holm requires finite p values within [0, 1]; undefined trials must be disclosed"
        )
    order = np.argsort(pvals)
    result = [0.0] * len(pvals)
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, (len(pvals) - rank) * pvals[idx])
        result[idx] = round(min(running, 1.0), 12)
    return result


def neighborhood_median(grid: dict[tuple[int, ...], float], point: tuple[int, ...]) -> float:
    neighbors = [grid[point]]
    for dim in range(len(point)):
        for step in (-1, 1):
            neighbor = (*point[:dim], point[dim] + step, *point[dim + 1 :])
            if neighbor in grid:
                neighbors.append(grid[neighbor])
    return float(np.median(neighbors))


def deflated_sharpe(
    sr: float,
    sr_trials: list[float],
    n_obs: int,
    skew: float,
    kurt: float,
) -> float:
    n = len(sr_trials)
    if n_obs <= 1 or n == 0:
        return float("nan")
    sr0 = 0.0
    if n > 1:
        gamma = 0.5772156649
        normal = NormalDist()
        sr0 = sqrt(float(np.var(sr_trials))) * (
            (1 - gamma) * normal.inv_cdf(1 - 1 / n) + gamma * normal.inv_cdf(1 - 1 / (n * e))
        )
    variance = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    if variance <= 0:
        return float("nan")
    z = (sr - sr0) * sqrt(n_obs - 1) / sqrt(variance)
    return (1 + erf(z / sqrt(2))) / 2
