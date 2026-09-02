"""
kalman_filter.py

선형 칼만필터로, Phase 2가 만든 노이즈 낀 전류/전압 관측치에서
SOC를 역추정한다.

핵심 전제: 이 필터는 measurements.csv의 measured_current_A,
measured_voltage_V 두 컬럼만 입력으로 쓴다. true_soc 컬럼은
절대 읽지 않는다 (Phase 4 채점 때만 사용).

상태공간 (Phase 1과 동일한 물리모델):
    x = [SOC, V1]^T
    x[k+1] = A x[k] + B I[k]                  (선형 — Phase 1의 정확한 이산화 그대로)
    y[k]   = OCV(SOC[k]) - I[k]*R0 - V1[k]     (OCV(SOC)가 비선형이라 매 스텝 국소 선형화)

노이즈 공분산은 임의로 튜닝하지 않고, Phase 2에서 실제로 설정했던
센서 노이즈 표준편차를 그대로 가져와 이론적으로 유도한다.
"""

import numpy as np
import matplotlib.pyplot as plt

from battery_model import BatteryParams
from generate_noisy_measurements import CURRENT_NOISE_STD, VOLTAGE_NOISE_STD


# ------------------------------------------------------------------
# 1. 상태공간 행렬 (Phase 1의 이산화 공식과 동일)
# ------------------------------------------------------------------
def build_state_matrices(params: BatteryParams, dt: float):
    """Phase 1의 alpha, beta와 완전히 동일한 이산화 공식으로 A, B를 만든다."""
    tau = params.R1 * params.C1
    alpha = np.exp(-dt / tau)
    beta = params.R1 * (1.0 - alpha)

    A = np.array([[1.0, 0.0],
                  [0.0, alpha]])
    b_vec = np.array([-dt / params.Q_As, beta])   # B를 벡터로 (2,)
    return A, b_vec


def docv_dsoc(params: BatteryParams, soc: float, eps: float = 1e-4) -> float:
    """
    OCV-SOC 곡선의 국소 기울기(수치미분).
    측정방정식이 비선형(OCV 룩업테이블)이라, 매 스텝 지금 SOC 근처의
    기울기로 근사(선형화)해야 칼만필터의 선형 수식을 그대로 쓸 수 있다.
    """
    soc_hi = np.clip(soc + eps, 0.0, 1.0)
    soc_lo = np.clip(soc - eps, 0.0, 1.0)
    denom = soc_hi - soc_lo
    if denom == 0:
        return 0.0
    return (params.ocv(soc_hi) - params.ocv(soc_lo)) / denom


# ------------------------------------------------------------------
# 2. 칼만필터 본체
# ------------------------------------------------------------------
def kalman_filter_soc(params: BatteryParams, current: np.ndarray, voltage: np.ndarray,
                       dt: float, soc0_guess: float, v1_0_guess: float,
                       P0: np.ndarray, Q_proc: np.ndarray, R_meas: float):
    """
    Parameters
    ----------
    current, voltage : (N,) 노이즈 낀 측정치 (Phase 2 산출물)
    soc0_guess, v1_0_guess : 초기 상태 추정. 일부러 부정확한 값을 넣어서
                              필터가 진짜 값으로 수렴하는지 확인한다.
    P0     : 초기 추정 오차 공분산 (2x2) — 초기 추정을 얼마나 못 믿는지
    Q_proc : 프로세스 노이즈 공분산 (2x2) — 모델 예측을 얼마나 못 믿는지
    R_meas : 측정 노이즈 분산 (스칼라) — 센서 측정을 얼마나 못 믿는지

    설계 노트: 초기 추정이 크게 틀렸을 때, OCV-SOC 곡선을 국소 선형화한
    상태로 큰 보정을 하면 SOC가 물리적으로 불가능한 범위(0~1 밖)로
    튀어나갈 수 있다. 매 스텝 보정 직후 [0,1]로 clip해서 방지한다.
    """
    n = len(current)
    A, b_vec = build_state_matrices(params, dt)

    soc_est = np.zeros(n)
    v1_est = np.zeros(n)

    x_prior = np.array([soc0_guess, v1_0_guess])  # k시점 사전(예측) 추정
    P_prior = P0.copy()

    for k in range(n):
        # ---------------- 보정 (Update) ----------------
        # 지금 측정값(전류, 전압)으로 사전 추정을 고친다.
        soc_p, v1_p = x_prior
        H = np.array([docv_dsoc(params, soc_p), -1.0])   # 국소 선형화된 측정행렬

        y_pred = params.ocv(soc_p) - current[k] * params.R0 - v1_p
        innovation = voltage[k] - y_pred                  # "예측과 실측의 차이"

        S = H @ P_prior @ H.T + R_meas                     # 혁신 공분산
        K = (P_prior @ H) / S                               # 칼만 게인

        x_post = x_prior + K * innovation
        x_post[0] = np.clip(x_post[0], 0.0, 1.0)  # SOC는 물리적으로 0~100%를 벗어날 수 없음
        P_post = (np.eye(2) - np.outer(K, H)) @ P_prior

        soc_est[k] = x_post[0]
        v1_est[k] = x_post[1]

        # ---------------- 예측 (Predict) ----------------
        # 다음 스텝(k+1)으로 넘어갈 사전 추정을 Phase 1 물리모델로 계산.
        if k < n - 1:
            x_prior = A @ x_post + b_vec * current[k]
            P_prior = A @ P_post @ A.T + Q_proc

    return soc_est, v1_est


# ------------------------------------------------------------------
# 3. 실행
# ------------------------------------------------------------------
def main():
    params = BatteryParams()
    dt = 1.0

    data = np.genfromtxt("measurements.csv", delimiter=",", names=True)
    time = data["time_s"]
    measured_current = data["measured_current_A"]
    measured_voltage = data["measured_voltage_V"]
    true_soc = data["true_soc"]   # 채점에만 쓴다. 필터 입력으로는 절대 안 씀.

    # ------------------------------------------------------------
    # 노이즈 공분산: 임의 튜닝이 아니라 Phase 2에서 실제로 설정한
    # 센서 스펙에서 이론적으로 유도한다.
    # ------------------------------------------------------------
    _, b_vec = build_state_matrices(params, dt)
    # 전류 센서 노이즈가 B를 통해 상태(SOC, V1)로 어떻게 전파되는지 계산
    Q_proc = np.outer(b_vec, b_vec) * (CURRENT_NOISE_STD ** 2)
    R_meas = VOLTAGE_NOISE_STD ** 2

    # ------------------------------------------------------------
    # 일부러 틀린 초기값으로 시작 (진짜 SOC는 100%인데 80%로 가정)
    # -> 필터가 관측값만으로 진짜 값을 찾아가는지 확인하기 위함
    # ------------------------------------------------------------
    soc0_guess = 0.80
    v1_0_guess = 0.0
    P0 = np.diag([0.05 ** 2, 0.01 ** 2])

    soc_est, v1_est = kalman_filter_soc(
        params, measured_current, measured_voltage, dt,
        soc0_guess, v1_0_guess, P0, Q_proc, R_meas
    )

    # ------------------------------------------------------------
    # 결과 저장
    # ------------------------------------------------------------
    header = "time_s,estimated_soc,estimated_v1_V"
    out = np.column_stack([time, soc_est, v1_est])
    np.savetxt("kalman_estimates.csv", out, delimiter=",",
               header=header, comments="", fmt="%.6f")
    print(f"kalman_estimates.csv 저장 완료 ({len(time)}행)")

    # ------------------------------------------------------------
    # 간단 검증: 추정 SOC vs 진짜 SOC, 그리고 추정오차 수렴 여부
    # (정식 비교—쿨롱카운팅 대조군 포함—는 Phase 4에서)
    # ------------------------------------------------------------
    error_pct = (soc_est - true_soc) * 100

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)

    axes[0].plot(time / 60, true_soc * 100, color="#0F6E56",
                 linewidth=1.5, label="true SOC")
    axes[0].plot(time / 60, soc_est * 100, color="#D85A30",
                 linewidth=1.2, linestyle="--", label="Kalman estimate")
    axes[0].axhline(soc0_guess * 100, color="gray", linewidth=0.8, linestyle=":",
                     label="initial guess (wrong)")
    axes[0].set_ylabel("SOC [%]")
    axes[0].set_title("Kalman Filter SOC Estimation (sanity check)")
    axes[0].legend(loc="upper right")
    axes[0].grid(alpha=0.3)

    axes[1].plot(time / 60, error_pct, color="#7B4FC9", linewidth=1.2)
    axes[1].axhline(0, color="black", linewidth=0.6)
    axes[1].set_ylabel("Estimation Error [%p]")
    axes[1].set_xlabel("Time [min]")
    axes[1].grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig("kalman_sanity_check.png", dpi=150)
    print("kalman_sanity_check.png 저장 완료")

    print(f"\n초기 오차: {(soc0_guess - true_soc[0]) * 100:.1f}%p (일부러 틀리게 시작)")
    print(f"60초 시점 오차: {error_pct[59]:.2f}%p")
    print(f"600초 시점 오차: {error_pct[599]:.2f}%p")
    print(f"최종(3600초) 오차: {error_pct[-1]:.2f}%p")
    print(f"전체 구간 RMSE: {np.sqrt(np.mean(error_pct[300:] ** 2)):.3f}%p "
          f"(초기 수렴구간 300초 제외)")


if __name__ == "__main__":
    main()
