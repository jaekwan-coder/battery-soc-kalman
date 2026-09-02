"""
generate_noisy_measurements.py

Phase 1의 "진짜" 시뮬레이션(노이즈 없음)에 실제 센서처럼 무작위 노이즈를
섞어서, 칼만필터가 실전에서 마주할 법한 "지저분한 관측치"를 만든다.

핵심 설계 원칙:
    - true_soc, true_v1 은 저장은 하되, Phase 3의 칼만필터는 이 컬럼을
      절대 입력으로 사용하지 않는다. Phase 4 채점 때만 몰래 꺼내 쓴다.
    - 노이즈가 섞이는 대상은 오직 "실제로 측정 가능한 두 값"뿐이다:
      전류(current), 단자전압(terminal_voltage)
"""

import numpy as np
import matplotlib.pyplot as plt

from battery_model import BatteryParams, simulate_battery, generate_current_profile


# ------------------------------------------------------------------
# 1. 센서 노이즈 파라미터
# ------------------------------------------------------------------
# 실제 BMS에서 흔히 쓰이는 전류/전압 센서 정밀도 수준을 참고한 근사값
CURRENT_NOISE_STD = 0.02   # 전류 센서 노이즈 표준편차 [A]  (약 ±20mA 흔들림)
VOLTAGE_NOISE_STD = 0.005  # 전압 센서 노이즈 표준편차 [V]  (약 ±5mV 흔들림)
CURRENT_BIAS_A = 0.03      # 전류 센서 고정 편향(bias) [A]  (정격전류 2A의 1.5% 수준, 저가형 홀센서에서 흔한 스펙)
# bias를 넣는 이유: 실제 전류센서는 무작위로만 흔들리는 게 아니라, 그 센서
# 개체 특유의 "항상 이만큼 치우쳐서 읽는" 고정 오차도 갖는다. 이 고정 오차가
# 쿨롱카운팅에서 진짜 drift(누적 편향)를 만드는 주범이고, 무작위 노이즈만으로는
# 이 현상이 잘 재현되지 않는다.

RANDOM_SEED = 42  # 결과 재현을 위해 난수 시드 고정 (같은 노이즈 패턴 재생산)


def add_gaussian_noise(true_values: np.ndarray, noise_std: float,
                        rng: np.random.Generator) -> np.ndarray:
    """
    true_values 각 원소에 평균 0, 표준편차 noise_std인 정규분포(가우시안)
    노이즈를 더해서 돌려준다.

    가우시안 노이즈를 쓰는 이유: 실제 전자 센서의 열잡음(thermal noise)이
    통계적으로 정규분포에 가깝게 나타나기 때문. 칼만필터 이론 자체도
    "노이즈가 가우시안이다"라는 가정 위에 세워져 있다.
    """
    noise = rng.normal(loc=0.0, scale=noise_std, size=true_values.shape)
    return true_values + noise


def main():
    rng = np.random.default_rng(RANDOM_SEED)

    # ------------------------------------------------------------
    # Phase 1의 함수를 그대로 재사용해서 "진짜" 데이터를 재생성한다.
    # (battery_model.py의 if __name__=="__main__" 덕분에, 여기서
    #  import해도 그래프를 그리거나 CSV를 저장하는 부수효과 없이
    #  함수만 깨끗하게 빌려 쓸 수 있다.)
    # ------------------------------------------------------------
    params = BatteryParams()
    dt = 1.0

    current_profile = generate_current_profile(dt)
    time = np.arange(len(current_profile)) * dt

    true_soc, true_v1, true_v_terminal = simulate_battery(
        params, current_profile, dt, soc_init=1.0, v1_init=0.0
    )

    # ------------------------------------------------------------
    # 측정 가능한 두 값(전류, 전압)에만 노이즈를 섞는다.
    # SOC와 V1은 애초에 측정 불가능하므로 노이즈를 섞을 대상이 아니다.
    # ------------------------------------------------------------
    measured_current = add_gaussian_noise(current_profile, CURRENT_NOISE_STD, rng) + CURRENT_BIAS_A
    measured_voltage = add_gaussian_noise(true_v_terminal, VOLTAGE_NOISE_STD, rng)

    # ------------------------------------------------------------
    # 결과 저장
    # measured_* : Phase 3 칼만필터의 입력으로만 쓸 값
    # true_soc   : Phase 4 채점용. 칼만필터 코드에서는 참조 금지.
    # ------------------------------------------------------------
    header = "time_s,measured_current_A,measured_voltage_V,true_soc,true_current_A,true_voltage_V"
    data = np.column_stack([
        time, measured_current, measured_voltage,
        true_soc, current_profile, true_v_terminal
    ])
    np.savetxt("measurements.csv", data, delimiter=",",
               header=header, comments="", fmt="%.6f")
    print(f"measurements.csv 저장 완료 ({len(time)}행)")

    # ------------------------------------------------------------
    # 진짜 값 vs 노이즈 낀 값을 눈으로 비교하는 그래프
    # 전체 3600초를 다 그리면 노이즈가 눈에 안 보이므로, 앞부분 300초만 확대
    # ------------------------------------------------------------
    zoom = slice(0, 300)

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)

    axes[0].plot(time[zoom], current_profile[zoom], color="#0F6E56",
                 linewidth=1.5, label="true (Phase 1)")
    axes[0].plot(time[zoom], measured_current[zoom], color="#D85A30",
                 linewidth=0.7, alpha=0.8, label="measured (noisy)")
    axes[0].set_ylabel("Current [A]")
    axes[0].set_title("True vs Noisy Measurement (first 300s zoomed in)")
    axes[0].legend(loc="upper right")
    axes[0].grid(alpha=0.3)

    axes[1].plot(time[zoom], true_v_terminal[zoom], color="#0F6E56",
                 linewidth=1.5, label="true (Phase 1)")
    axes[1].plot(time[zoom], measured_voltage[zoom], color="#378ADD",
                 linewidth=0.7, alpha=0.8, label="measured (noisy)")
    axes[1].set_ylabel("Terminal Voltage [V]")
    axes[1].set_xlabel("Time [s]")
    axes[1].legend(loc="upper right")
    axes[1].grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig("noisy_measurements.png", dpi=150)
    print("noisy_measurements.png 저장 완료")

    # 노이즈가 실제로 얼마나 섞였는지 숫자로도 확인
    actual_current_std = np.std(measured_current - current_profile)
    actual_voltage_std = np.std(measured_voltage - true_v_terminal)
    print(f"\n설정한 전류 노이즈 표준편차: {CURRENT_NOISE_STD} A "
          f"/ 실제 생성된 값: {actual_current_std:.4f} A")
    print(f"설정한 전압 노이즈 표준편차: {VOLTAGE_NOISE_STD} V "
          f"/ 실제 생성된 값: {actual_voltage_std:.4f} V")


if __name__ == "__main__":
    main()
