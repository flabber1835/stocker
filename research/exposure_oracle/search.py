"""Finite-grid exact dynamic programs; no drawdown bins or beam pruning."""
from dataclasses import dataclass
import math

import numpy as np

TOL = 1e-13


class SearchLimit(RuntimeError):
    pass


@dataclass(frozen=True)
class Solution:
    path: list[int]
    log_wealth: float
    labels: int
    max_layer: int


def unconstrained(matrices, initial: int, size: int) -> Solution:
    wealth = np.full(size, -np.inf)
    wealth[initial] = 0.
    parents = []
    for matrix in matrices:
        scores = wealth[:, None]+matrix
        parent = scores.argmax(axis=0)
        wealth = scores[parent, np.arange(size)]
        parents.append(parent.astype(np.int32))
    current = int(wealth.argmax())
    if not np.isfinite(wealth[current]):
        raise ValueError('no feasible exposure path')
    best, path = float(wealth[current]), []
    for parent in reversed(parents):
        path.append(current)
        current = int(parent[current])
    return Solution(path[::-1], best, len(parents)*size, size)


def bound(cap: float) -> float:
    if not math.isfinite(cap) or not 0 <= cap < 1:
        raise ValueError('drawdown cap must be in [0,1)')
    return -math.log1p(-cap)


def feasible(matrices: np.ndarray, initial: int, cap: float) -> bool:
    limit = bound(cap)
    depth = np.full(matrices.shape[1], np.inf)
    depth[initial] = 0.
    for matrix in matrices:
        depth = np.maximum(0., depth[:, None]-matrix).min(axis=0)
        depth[depth > limit+TOL] = np.inf
        if not np.isfinite(depth).any():
            return False
    return True


def minimum_cap(matrices: np.ndarray, initial: int, upper: float) -> tuple[float, float]:
    if feasible(matrices, initial, 0.):
        return 0., 0.
    if not feasible(matrices, initial, upper):
        raise ValueError('upper drawdown bracket is infeasible')
    lower = 0.
    for _ in range(32):
        mid = (lower+upper)/2
        if feasible(matrices, initial, mid):
            upper = mid
        else:
            lower = mid
    return lower, upper


def nondominated(wealth: np.ndarray, depth: np.ndarray) -> np.ndarray:
    """Sort depth ascending, wealth descending; retain strict wealth improvements."""
    order = np.lexsort((-wealth, depth))
    values = wealth[order]
    prior_best = np.r_[-np.inf, np.maximum.accumulate(values[:-1])]
    return order[values > prior_best]


def constrained(matrices: np.ndarray, initial: int, cap: float, *,
                max_layer=100000, max_labels=5000000) -> Solution | None:
    limit, size = bound(cap), matrices.shape[1]
    wealth, depth, action = np.array([0.]), np.array([0.]), np.array([initial], dtype=np.int32)
    history, count, widest = [], 0, 0
    for matrix in matrices:
        w_next, d_next, parents, actions = [], [], [], []
        for target in range(size):
            factor = matrix[action, target]
            candidate_w = wealth+factor
            candidate_d = np.maximum(0., depth-factor)
            eligible = np.flatnonzero(np.isfinite(candidate_w) & (candidate_d <= limit+TOL))
            if not len(eligible):
                continue
            keep = eligible[nondominated(candidate_w[eligible], candidate_d[eligible])]
            w_next.append(candidate_w[keep]); d_next.append(candidate_d[keep])
            parents.append(keep.astype(np.int32)); actions.append(np.full(len(keep), target, dtype=np.int32))
        if not parents:
            return None
        parent, action = np.concatenate(parents), np.concatenate(actions)
        count += len(parent)
        widest = max(widest, len(parent))
        if len(parent) > max_layer or count > max_labels:
            raise SearchLimit(f'exact search resource bound: layer={len(parent)}, total={count}')
        history.append((parent, action))
        wealth, depth = np.concatenate(w_next), np.concatenate(d_next)
    current = int(wealth.argmax())
    best, path = float(wealth[current]), []
    for parent, action in reversed(history):
        path.append(int(action[current]))
        current = int(parent[current])
    return Solution(path[::-1], best, count, widest)
