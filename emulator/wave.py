"""진동 파형 합성. 회전 차수 성분과 베어링 충격파를 더한다."""

from __future__ import annotations

import numpy as np

PRESETS = {
    "normal": "정상 (작은 1x + 노이즈)",
    "imbalance": "불균형 (1x 성분 증가)",
    "misalignment": "축 정렬 불량 (2x 성분 증가)",
    "bearing_outer": "베어링 외륜 결함 (충격파)",
    "looseness": "풀림 (고조파 증가)",
}

ALLOWED_N = (256, 512, 1024, 2048, 4096, 8192)


def synthesize(
    sample_rate: int,
    n: int,
    rpm: float,
    preset: str,
    severity: float,
    rng: np.random.Generator,
) -> np.ndarray:
    severity = float(np.clip(severity, 0.0, 1.0))
    t = np.arange(n, dtype=np.float64) / sample_rate
    f1 = max(rpm, 0.0) / 60.0
    x = rng.normal(0.0, 0.015, n)
    if f1 > 0.2:
        x += 0.04 * np.sin(2 * np.pi * f1 * t)
        x += 0.01 * np.sin(2 * np.pi * 2 * f1 * t + 0.4)
    if preset == "imbalance" and f1 > 0.2:
        x += (0.15 + 0.9 * severity) * np.sin(2 * np.pi * f1 * t)
    elif preset == "misalignment" and f1 > 0.2:
        x += (0.12 + 0.8 * severity) * np.sin(2 * np.pi * 2 * f1 * t)
        x += 0.15 * severity * np.sin(2 * np.pi * 3 * f1 * t)
    elif preset == "bearing_outer" and f1 > 0.2:
        x += _impacts(t, sample_rate, 3.05 * f1, 900.0, 0.05 + 0.55 * severity, rng)
    elif preset == "looseness" and f1 > 0.2:
        for k in range(1, 8):
            x += (0.08 * severity / k) * np.sin(2 * np.pi * k * f1 * t + k * 0.2)
        x += rng.normal(0.0, 0.02 * severity, n)
    return x.astype(np.float32)


def _impacts(
    t: np.ndarray,
    sample_rate: int,
    fault_hz: float,
    resonance_hz: float,
    amp: float,
    rng: np.random.Generator,
) -> np.ndarray:
    n = t.size
    y = np.zeros(n, dtype=np.float64)
    if fault_hz <= 0:
        return y
    period = 1.0 / fault_hz
    impulse_n = max(8, int(sample_rate * 0.008))
    tau = np.arange(impulse_n) / sample_rate
    kernel = amp * np.exp(-tau / 0.002) * np.sin(2 * np.pi * resonance_hz * tau)
    cursor = rng.random() * period
    while cursor < t[-1]:
        idx = int(cursor * sample_rate)
        end = min(n, idx + impulse_n)
        y[idx:end] += kernel[: end - idx]
        cursor += period * (1 + rng.normal(0, 0.01))
    return y
