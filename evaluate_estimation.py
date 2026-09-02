"""
evaluate_estimation.py

Phase 4: 칼만필터의 SOC 추정 성능을 정량적으로 검증하고,
비교군인 "단순 쿨롱카운팅만 썼을 때"와 나란히 비교한다.

이 스크립트에서만 유일하게 true_soc 컬럼을 "채점" 목적으로 사용한다.
Phase 3의 칼만필터 자체는 이 컬럼을 절대 참조하지 않았다.

공정성을 위한 설계:
    - 칼만필터: 일부러 틀린 초기값(80%, 진짜는 100%)에서 시작 — 불리한 조건
    - 쿨롱카운팅: 정확한 초기값(100%)에서 시작 — 유리한 조건
    이렇게 쿨롱카운팅에게 유리하게 설정해도 칼만필터가 결국 더 정확한지 보는 것이
    "칼만필터가 필요하다"는 주장을 훨씬 설득력 있게 만든다.
"""

import numpy as np
import matplotlib.pyplot as plt

from battery_model import BatteryParams
from kalman_filter import kalman_filter_soc, build_state_matrices
from generate_noisy_measurements import CURRENT_NOISE_STD, VOLTAGE_NOISE_STD


def coulomb_counting_only(current: np.ndarray, dt: float, Q_As: float,
                           soc_init: float) -> np.ndarray:
    """
    칼만필터 없이, 노이즈 낀 전류만 그대로 적분한 SOC 추정.
    한번 시작하면 전압 측정값으로 자기 자신을 고칠 방법이 전혀 없다 —
    이게 바로 Phase 0에서 이야기한 "drift" 문제를 그대로 재현한다.
    """
    n = len(current)
    soc = np.zeros(n)
    soc[0] = soc_init
    for k in range(n - 1):
        soc[k + 1] = soc[k] - current[k] * dt / Q_As
    return soc


def main():
    params = BatteryParams()
    dt = 1.0

    data = np.genfromtxt("measurements.csv", delimiter=",", names=True)
    time = data["time_s"]
    measured_current = data["measured_current_A"]
    measured_voltage = data["measured_voltage_V"]
    true_soc = data["true_soc"]

    # ------------------------------------------------------------
    # 칼만필터 (Phase 3과 동일 설정, 일부러 틀린 초기값)
    # ------------------------------------------------------------
    _, b_vec = build_state_matrices(params, dt)
    Q_proc = np.outer(b_vec, b_vec) * (CURRENT_NOISE_STD ** 2)
    R_meas = VOLTAGE_NOISE_STD ** 2
    P0 = np.diag([0.05 ** 2, 0.01 ** 2])

    soc_kalman, _ = kalman_filter_soc(
        params, measured_current, measured_voltage, dt,
        soc0_guess=0.80, v1_0_guess=0.0, P0=P0, Q_proc=Q_proc, R_meas=R_meas
    )

    # ------------------------------------------------------------
    # 비교군: 쿨롱카운팅만 (정확한 초기값 — 쿨롱카운팅에게 가장 유리한 조건)
    # ------------------------------------------------------------
    soc_cc = coulomb_counting_only(measured_current, dt, params.Q_As,
                                    soc_init=true_soc[0])

    # ------------------------------------------------------------
    # 채점
    # ------------------------------------------------------------
    err_kalman = (soc_kalman - true_soc) * 100
    err_cc = (soc_cc - true_soc) * 100

    # 칼만필터는 초기 수렴 구간(300초) 제외하고 채점 (Phase 3와 동일 기준)
    rmse_kalman = np.sqrt(np.mean(err_kalman[300:] ** 2))
    rmse_cc = np.sqrt(np.mean(err_cc ** 2))
    final_err_kalman = err_kalman[-1]
    final_err_cc = err_cc[-1]

    print(f"칼만필터   RMSE(수렴 후): {rmse_kalman:.3f}%p   최종오차: {final_err_kalman:.2f}%p")
    print(f"쿨롱카운팅 RMSE(전구간) : {rmse_cc:.3f}%p   최종오차: {final_err_cc:.2f}%p")
    print(f"\n칼만필터가 쿨롱카운팅보다 RMSE 기준 {rmse_cc / rmse_kalman:.1f}배 더 정확함")
    print("(쿨롱카운팅은 정확한 초기값이라는 유리한 조건에서 시작했는데도 이 결과)")

    # ------------------------------------------------------------
    # 최종 검증 그래프
    # ------------------------------------------------------------
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)

    axes[0].plot(time / 60, true_soc * 100, color="#0F6E56",
                 linewidth=2.0, label="True SOC (정답)")
    axes[0].plot(time / 60, soc_kalman * 100, color="#D85A30",
                 linewidth=1.3, linestyle="--", label="Kalman filter (초기값 80%, 틀리게 시작)")
    axes[0].plot(time / 60, soc_cc * 100, color="#7B7B7B",
                 linewidth=1.3, linestyle=":", label="Coulomb counting only (초기값 100%, 정확하게 시작)")
    axes[0].set_ylabel("SOC [%]")
    axes[0].set_title("Phase 4 — Kalman Filter vs Coulomb-Counting-Only")
    axes[0].legend(loc="upper right", fontsize=9)
    axes[0].grid(alpha=0.3)

    axes[1].plot(time / 60, err_kalman, color="#D85A30", linewidth=1.3,
                 label=f"Kalman error (RMSE {rmse_kalman:.2f}%p)")
    axes[1].plot(time / 60, err_cc, color="#7B7B7B", linewidth=1.3,
                 label=f"Coulomb-counting error (RMSE {rmse_cc:.2f}%p)")
    axes[1].axhline(0, color="black", linewidth=0.6)
    axes[1].set_ylabel("Estimation Error [%p]")
    axes[1].set_xlabel("Time [min]")
    axes[1].legend(loc="upper right", fontsize=9)
    axes[1].grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig("soc_estimation_result.png", dpi=150)
    print("\nsoc_estimation_result.png 저장 완료")


if __name__ == "__main__":
    main()
