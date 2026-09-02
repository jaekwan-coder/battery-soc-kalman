"""
battery_model.py

배터리 1차 RC 등가회로(Equivalent Circuit Model) 시뮬레이션

회로 구성: OCV(SOC) 전압원 -- R0(직렬저항) -- [R1 ‖ C1](분극 RC) -- V_t(단자전압, 측정가능)

상태공간 표현 (STATCOM 캡스톤에서 쓴 x' = Ax + Bu 와 동일한 틀):
    상태변수 x = [SOC, V1]^T
    입력 u = I(t)  (양수 = 방전전류)

    dSOC/dt = -I / Q            (쿨롱카운팅. Q는 정격용량[As])
    dV1/dt  = -V1/(R1*C1) + I/C1

    출력(측정가능한 값): V_t = OCV(SOC) - I*R0 - V1

이 스크립트는 "진짜" 시뮬레이션(노이즈 없음)을 만든다.
Phase 2에서 여기에 노이즈를 섞어 "측정값처럼" 오염시키고,
Phase 3의 칼만필터가 그 오염된 값에서 다시 SOC를 역추정하게 된다.
"""

import numpy as np
import matplotlib.pyplot as plt


# ------------------------------------------------------------------
# 1. 배터리 파라미터 (전형적인 NMC 계열 소형 리튬이온 셀 기준 근사값)
# ------------------------------------------------------------------
class BatteryParams:
    def __init__(self):
        self.Q_Ah = 2.0          # 정격 용량 [Ah]
        self.Q_As = self.Q_Ah * 3600.0  # 정격 용량 [A*s] (적분에 사용)
        self.R0 = 0.010          # 직렬 내부저항 [Ohm]
        self.R1 = 0.015          # 분극저항 [Ohm]
        self.C1 = 2000.0         # 분극 커패시턴스 [F]  (R1*C1 = 30s 시정수)

        # OCV-SOC 룩업테이블 (일반적인 NMC 셀 개방전압 곡선 근사)
        # 중간 구간이 상대적으로 평평한 전형적 리튬이온 특성을 반영
        self.soc_points = np.array(
            [0.00, 0.10, 0.20, 0.30, 0.40, 0.50,
             0.60, 0.70, 0.80, 0.90, 1.00]
        )
        self.ocv_points = np.array(
            [3.00, 3.35, 3.55, 3.62, 3.68, 3.72,
             3.77, 3.82, 3.88, 3.95, 4.15]
        )

    def ocv(self, soc):
        """SOC(0~1) -> OCV(V). 룩업테이블 선형보간."""
        soc_clipped = np.clip(soc, 0.0, 1.0)
        return np.interp(soc_clipped, self.soc_points, self.ocv_points)

# 일단 그림을 그려두는거네. 데이터를 먼저 만들어두는 꼴.
# SOC - 충전 %, OCV - 개방 회로 전압 미리 지정.

# ------------------------------------------------------------------
# 2. 이산시간 상태공간 시뮬레이터
# ------------------------------------------------------------------
def simulate_battery(params: BatteryParams, current_profile: np.ndarray,
                      dt: float, soc_init: float = 1.0, v1_init: float = 0.0):
    """
    1차 RC 등가회로를 이산시간으로 시뮬레이션한다.

    SOC는 단순 적분(오일러)으로, V1은 RC 시정수를 이용한 정확한(exact)
    이산화 공식으로 계산한다 (Plett의 배터리 모델링 표준 방식).

    Parameters
    ----------
    params : BatteryParams
    current_profile : (N,) 배열. 각 타임스텝의 방전전류[A] (양수=방전)
    dt : 샘플링 주기 [s]
    soc_init, v1_init : 초기 상태

    Returns
    -------
    soc, v1, v_terminal : 각각 (N,) 배열
    """
    n = len(current_profile)
    soc = np.zeros(n)
    v1 = np.zeros(n)
    v_terminal = np.zeros(n)

    soc[0] = soc_init
    v1[0] = v1_init

    # RC 시정수 기반 이산화 계수
    tau = params.R1 * params.C1
    alpha = np.exp(-dt / tau)          # V1의 자연 감쇠 계수
    beta = params.R1 * (1.0 - alpha)   # 전류 입력에 의한 V1 상승분

    for k in range(n):
        I_k = current_profile[k]

        # 출력 방정식: 현재 스텝의 단자전압
        v_terminal[k] = params.ocv(soc[k]) - I_k * params.R0 - v1[k]

        # 다음 스텝 상태 업데이트 (마지막 스텝이면 생략)
        if k < n - 1:
            soc[k + 1] = soc[k] - (I_k * dt) / params.Q_As
            v1[k + 1] = alpha * v1[k] + beta * I_k

    return soc, v1, v_terminal


# ------------------------------------------------------------------
# 3. 방전 전류 프로파일 생성 (방전-휴지 반복, HPPC 테스트와 유사한 패턴)
# ------------------------------------------------------------------
def generate_current_profile(dt: float, n_cycles: int = 6,
                              discharge_s: float = 500.0,
                              rest_s: float = 100.0,
                              discharge_current: float = 2.0):
    """
    "discharge_s 초 방전 -> rest_s 초 휴지"를 n_cycles번 반복하는
    전류 프로파일을 생성한다.

    휴지 구간을 넣는 이유: 전류를 끊었을 때 단자전압이 서서히
    회복되는 분극(relaxation) 현상을 시뮬레이션으로 재현하기 위함.
    이 현상이 바로 R1-C1 병렬회로가 존재하는 이유를 눈으로 보여준다.
    """
    profile = []
    for _ in range(n_cycles):
        profile.extend([discharge_current] * int(discharge_s / dt))
        profile.extend([0.0] * int(rest_s / dt))
    return np.array(profile)


# ------------------------------------------------------------------
# 4. 실행 및 시각화
# ------------------------------------------------------------------
def main():
    params = BatteryParams()
    dt = 1.0  # 1초 샘플링

    current_profile = generate_current_profile(dt)
    time = np.arange(len(current_profile)) * dt

    soc, v1, v_terminal = simulate_battery(params, current_profile, dt,
                                            soc_init=1.0, v1_init=0.0)

    # 결과를 CSV로 저장 (Phase 2에서 노이즈를 섞을 "진짜" 데이터로 재사용)
    header = "time_s,current_A,true_soc,v1_V,terminal_voltage_V"
    data = np.column_stack([time, current_profile, soc, v1, v_terminal])
    np.savetxt("true_simulation.csv", data, delimiter=",",
               header=header, comments="", fmt="%.6f")
    print(f"true_simulation.csv 저장 완료 ({len(time)}행)")

    # 시각화: 전류 프로파일 / 단자전압 / SOC 세 개 서브플롯
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)

    axes[0].plot(time / 60, current_profile, color="#D85A30", linewidth=1.2)
    axes[0].set_ylabel("Current [A]")
    axes[0].set_title("1st-order RC Equivalent Circuit — Discharge Simulation")
    axes[0].grid(alpha=0.3)

    axes[1].plot(time / 60, v_terminal, color="#378ADD", linewidth=1.2)
    axes[1].set_ylabel("Terminal Voltage $V_t$ [V]")
    axes[1].grid(alpha=0.3)

    axes[2].plot(time / 60, soc * 100, color="#0F6E56", linewidth=1.2)
    axes[2].set_ylabel("True SOC [%]")
    axes[2].set_xlabel("Time [min]")
    axes[2].grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig("discharge_simulation.png", dpi=150)
    print("discharge_simulation.png 저장 완료")

    print(f"\n최종 SOC: {soc[-1]*100:.1f}%  "
          f"(초기 100% 대비 {(1-soc[-1])*100:.1f}%p 방전)")
    print(f"최종 단자전압: {v_terminal[-1]:.3f} V")


if __name__ == "__main__":
    main()
