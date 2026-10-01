
import streamlit as st

st.set_page_config(
    page_title="주사실 당일 운영 현황판",
    page_icon="💉",
    layout="wide",
)

# -----------------------------
# Helpers
# -----------------------------
TIMES = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "16:00", "18:00"]

def protocol_band(x: float) -> int:
    if x >= 39:
        return 3
    if x >= 33.5:
        return 2
    if x >= 23:
        return 1
    return 0

def openrun_band(x: float) -> int:
    if x >= 41.4:
        return 3
    if x >= 34:
        return 2
    if x >= 27:
        return 1
    return 0

def scenario(openrun: int, protocol: int):
    """
    IMPORTANT:
    10:00 이후 수치는 실제 관측값이 아니라
    현재 MVP 화면 검증용 시나리오 값입니다.
    환자별 접수/입실/퇴실 자료가 들어오면 교체할 예정입니다.
    """
    stress = min(1.55, max(0.7, (openrun / 27 + protocol / 23) / 2))

    received_base = [openrun, 58, 92, 118, 138, 154, 169, 188, 200]
    wait_base = [openrun, 18, 21, 23, 18, 13, 8, 4, 1]
    treating_base = [0, 39, 53, 53, 53, 51, 47, 37, 20]
    wait30_base = [0, 4, 9, 13, 11, 8, 5, 2, 0]
    wait60_base = [0, 0, 2, 5, 4, 3, 1, 0, 0]
    release_base = [0, 5, 6, 8, 10, 11, 12, 10, 7]

    received, waiting, treating, done, wait30, wait60, release = [], [], [], [], [], [], []

    for i in range(len(TIMES)):
        rec = round(received_base[i] * stress)
        wai = max(0, round(wait_base[i] * stress))
        tre = 0 if i == 0 else min(53, round(treating_base[i] * (0.92 + 0.08 * stress)))
        don = max(0, rec - wai - tre)

        received.append(rec)
        waiting.append(wai)
        treating.append(tre)
        done.append(don)
        wait30.append(min(wai, round(wait30_base[i] * stress)))
        wait60.append(min(wait30[-1], round(wait60_base[i] * stress)))
        release.append(round(release_base[i] * (0.85 + 0.15 / stress)))

    return {
        "received": received,
        "waiting": waiting,
        "treating": treating,
        "done": done,
        "wait30": wait30,
        "wait60": wait60,
        "release": release,
    }

def morning_risk(openrun: int, protocol: int):
    score = openrun_band(openrun) + protocol_band(protocol)

    if score >= 5:
        return "높음", "오전 대기와 침상 포화가 길어질 가능성이 큽니다.", score
    if score >= 3:
        return "주의", "평소보다 대기가 길어질 수 있습니다.", score
    return "보통", "과거 보통 운영일 범위에 가깝습니다.", score

def flow_label(score: int, protocol: int):
    return {
        "08–10시": "매우 혼잡" if score >= 5 else "혼잡" if score >= 3 else "보통",
        "10–12시": "혼잡 지속" if score >= 5 else "주의" if score >= 3 else "보통",
        "12–14시": "완화 시작" if score >= 4 else "회복",
        "14–16시": "회복" if protocol >= 33.5 else "안정",
        "16시 이후": "늦은 종료 주의" if protocol >= 39 else "안정",
    }


def bed_allocation(openrun: int, protocol: int, idx: int, d: dict):
    """
    Prototype bed-allocation heuristic.
    This is NOT a validated staffing/scheduling rule.
    Total = 53 chairs/beds.

    Long-treatment allocation rises with protocol load and, later in the day,
    with currently occupied chairs. Quick-turn allocation rises with open-run
    pressure / current queue. A flexible pool is always preserved.
    """
    total = 53

    # 08:00 starting recommendation from observed morning inputs.
    long_beds = 24
    if protocol >= 23:
        long_beds += 2
    if protocol >= 33.5:
        long_beds += 3
    if protocol >= 39:
        long_beds += 3

    quick_beds = 12
    if openrun >= 27:
        quick_beds += 1
    if openrun >= 34:
        quick_beds += 2
    if openrun >= 41.4:
        quick_beds += 2

    # During the day, use the scenario state to illustrate adaptive allocation.
    if idx > 0:
        occupied = d["treating"][idx]
        waiting = d["waiting"][idx]

        if occupied >= 50:
            long_beds += 2
        elif occupied <= 40:
            long_beds -= 2

        if waiting >= 20:
            quick_beds += 2
        elif waiting <= 5:
            quick_beds -= 2

    # Always preserve a flexible/common pool.
    long_beds = max(20, min(34, long_beds))
    quick_beds = max(10, min(18, quick_beds))

    flex_beds = total - long_beds - quick_beds
    if flex_beds < 5:
        shortage = 5 - flex_beds
        # Reduce the larger dedicated pool first.
        if long_beds >= quick_beds:
            long_beds -= shortage
        else:
            quick_beds -= shortage
        flex_beds = total - long_beds - quick_beds

    return long_beds, quick_beds, flex_beds

def current_summary(idx: int, d: dict):
    if idx == 0:
        return (
            "08:00 정각에는 침상 점유를 0에서 시작합니다. "
            "이 시점에서는 실제 오픈런 환자 수와 당일 프로토콜 예정 환자 수로 "
            "오전 혼잡 가능성을 먼저 판단합니다."
        )

    if d["waiting"][idx] >= 20 or d["treating"][idx] >= 50:
        return (
            "현재 시나리오에서는 대기 환자가 많고 침상도 거의 찬 상태입니다. "
            "이 구간에서는 신규 유입 자체보다 어떤 환자가 빨리 회전할 수 있는지, "
            "다음 1시간에 몇 침상이 풀릴지가 더 중요합니다."
        )

    if d["waiting"][idx] >= 8:
        return (
            "혼잡이 완화되기 시작했지만 아직 대기가 남아 있는 구간입니다. "
            "실제 퇴실 속도가 예상과 비슷한지 확인하면서 오후 수용 여력을 다시 판단하는 시점입니다."
        )

    return (
        "대기가 많이 줄고 침상 여유가 생기기 시작한 구간입니다. "
        "늦게 시작한 장시간 치료와 당일 추가 오더가 남아 있는지 확인하면 됩니다."
    )

def action_items(idx: int, d: dict):
    if idx == 0:
        return [
            ("오픈런 규모 확인", "07:59까지 대기표 환자 수가 평소보다 많은지 먼저 봅니다."),
            ("긴 항암 예정량 확인", "프로토콜 항암 수가 높은 날이면 오전 침상 회전이 느려질 수 있습니다."),
        ]

    if d["waiting"][idx] >= 20 or d["treating"][idx] >= 50:
        return [
            ("짧은 치료용 침상 보호", "짧은 환자가 긴 항암 뒤에 묶이지 않도록 회전 가능한 침상을 남겨둡니다."),
            ("다음 1시간 퇴실 확인", "예상보다 실제 퇴실이 적으면 오후 혼잡이 더 길어질 수 있습니다."),
        ]

    if d["waiting"][idx] >= 8:
        return [
            ("실제 퇴실 속도 비교", "예상보다 빨리 풀리면 추가 수용 여력이 생길 수 있습니다."),
            ("긴 치료 늦은 시작 주의", "오후 늦게 장시간 항암을 시작하면 20시 이후로 밀릴 수 있습니다."),
        ]

    return [
        ("남은 장시간 치료 확인", "20시 이후 종료 가능성이 있는 환자를 확인합니다."),
        ("당일 운영 정리", "오늘 혼잡이 언제 시작되고 언제 풀렸는지 기록해 다음 운영 기준에 활용합니다."),
    ]

# -----------------------------
# Header
# -----------------------------
st.title("주사실 당일 운영 현황판")
st.caption(
    "08:00에는 실제 아침 대기·프로토콜 수로 시작하고, 이후 시간대는 시나리오로 "
    "하루 운영 흐름을 미리 재생해보는 Prototype입니다."
)

st.warning(
    "현재 버전은 실제 환자별 시간데이터 연결 전입니다. "
    "10:00 이후 수치는 실제값이 아니라 화면·운영 로직 검증용 시나리오입니다.",
    icon="⚠️",
)

# -----------------------------
# Inputs
# -----------------------------
st.subheader("오늘 시작 조건")

c1, c2 = st.columns(2)
with c1:
    openrun = st.number_input(
        "07:59까지 대기표를 뽑은 환자 수",
        min_value=0,
        max_value=100,
        value=34,
        step=1,
    )

with c2:
    protocol = st.number_input(
        "오늘 예정 프로토콜 항암 환자 수",
        min_value=0,
        max_value=80,
        value=34,
        step=1,
    )

risk_label, risk_text, score = morning_risk(openrun, protocol)

# -----------------------------
# Morning overview
# -----------------------------
st.subheader("08:00 시작 상황")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("아침 대기 환자", f"{openrun}명")
m1.caption("과거 중앙값 27 · 상위25% 34 · 상위10% 41.4")

m2.metric("프로토콜 항암", f"{protocol}명")
m2.caption("과거 중앙값 23 · 상위25% 33.5 · 상위10% 39")

m3.metric("오전 혼잡 예상", risk_label)
m3.caption(risk_text)

m4.metric("침상/치료의자", "53개")
m4.caption("08:00 정각은 점유 0에서 시작")

m5.metric("주입펌프", "43대")
m5.caption("현재 Prototype은 독립 제약으로 미반영")

# -----------------------------
# Time slider
# -----------------------------
st.divider()
st.subheader("시간을 움직여 오늘 흐름 보기")

time_idx = st.select_slider(
    "시간",
    options=list(range(len(TIMES))),
    value=2,
    format_func=lambda x: TIMES[x],
)

d = scenario(openrun, protocol)

received = d["received"][time_idx]
waiting = d["waiting"][time_idx]
treating = d["treating"][time_idx]
done = d["done"][time_idx]
free_beds = max(0, 53 - treating)
wait30 = d["wait30"][time_idx]
wait60 = d["wait60"][time_idx]
release = d["release"][time_idx]

st.markdown(f"### {TIMES[time_idx]} 현황")

k1, k2, k3, k4 = st.columns(4)
k1.metric("오늘 접수", f"{received}명")
k2.metric("현재 대기", f"{waiting}명")
k3.metric("현재 치료 중", f"{treating}명")
k4.metric("치료 완료", f"{done}명")

k5, k6, k7, k8 = st.columns(4)
k5.metric("빈 침상", f"{free_beds}개")
k6.metric("30분 이상 대기", f"{wait30}명")
k7.metric("60분 이상 대기", f"{wait60}명")
k8.metric("1시간 내 퇴실 예상", f"{release}명")

st.info(current_summary(time_idx, d), icon="ℹ️")


# -----------------------------
# Bed allocation recommendation
# -----------------------------
st.divider()
st.subheader("오늘의 침상 운영 제안")
st.caption(
    "53개 침상을 고정된 전용 침상으로 나누는 것이 아니라, 장시간 치료에 우선 사용할 침상과 "
    "빠른 회전을 위해 보호할 침상, 상황에 따라 유동적으로 사용할 침상의 권장 배분을 제시하는 "
    "Prototype입니다. 실제 환자별 침상 점유시간 자료가 들어오면 이 계산식을 보정합니다."
)

long_beds, quick_beds, flex_beds = bed_allocation(openrun, protocol, time_idx, d)

b1, b2, b3 = st.columns(3)

with b1:
    with st.container(border=True):
        st.markdown("**장시간 치료 우선**")
        st.markdown(f"## {long_beds}개")
        st.caption(
            "프로토콜 항암 등 장시간 침상 점유가 예상되는 환자를 우선 배치하는 영역"
        )

with b2:
    with st.container(border=True):
        st.markdown("**빠른 회전 보호**")
        st.markdown(f"## {quick_beds}개")
        st.caption(
            "짧은 치료 환자가 장시간 치료 뒤에서 오래 기다리지 않도록 회전을 보호하는 영역"
        )

with b3:
    with st.container(border=True):
        st.markdown("**유동 운영**")
        st.markdown(f"## {flex_beds}개")
        st.caption(
            "당일 추가 오더, 예상보다 긴 치료, 갑작스러운 대기 증가에 맞춰 유연하게 사용하는 영역"
        )

st.progress(long_beds / 53, text=f"장시간 치료 우선 {long_beds}/53")
st.progress(quick_beds / 53, text=f"빠른 회전 보호 {quick_beds}/53")
st.progress(flex_beds / 53, text=f"유동 운영 {flex_beds}/53")

if time_idx == 0:
    st.info(
        f"08:00 제안 근거: 07:59까지 대기 {openrun}명, 오늘 프로토콜 항암 {protocol}명을 "
        "과거 분포와 비교했습니다. 이 숫자는 현재 검증 전 운영 가설이며, "
        "환자별 실제 입실–퇴실시간을 받으면 과거 점유시간 분포로 다시 계산해야 합니다.",
        icon="ℹ️",
    )
else:
    st.info(
        f"{TIMES[time_idx]} 시나리오에서는 현재 대기 {waiting}명, 치료 중 {treating}명, "
        f"빈 침상 {free_beds}개를 반영해 배분 제안을 조정했습니다. "
        "현재는 시나리오 기반이며 실제 실시간 현황값이 아닙니다.",
        icon="ℹ️",
    )


# -----------------------------
# Operational actions
# -----------------------------
left, right = st.columns([1.2, 1])

with left:
    st.subheader("이 시점에서 볼 것")
    for title, body in action_items(time_idx, d):
        with st.container(border=True):
            st.markdown(f"**{title}**")
            st.write(body)

with right:
    st.subheader("긴 항암 / 짧은 치료 운영 참고")

    long_msg = "침상 보호 필요" if protocol_band(protocol) >= 2 else "일반 운영 가능"
    short_msg = "회전 침상 확보" if openrun_band(openrun) >= 2 else "일반 운영 가능"

    with st.container(border=True):
        st.markdown("**긴 항암**")
        st.markdown(f"### {long_msg}")
        if protocol_band(protocol) >= 2:
            st.caption(
                "프로토콜 항암 환자가 많은 날입니다. 장시간 점유가 예상되는 환자용 침상을 "
                "충분히 확보하지 않으면 오전 회전이 느려질 수 있습니다."
            )
        else:
            st.caption(
                "프로토콜 항암 수는 과거 보통 범위에 가깝습니다. "
                "실제 장시간 치료 환자 수를 확인하며 운영합니다."
            )

    with st.container(border=True):
        st.markdown("**짧은 치료**")
        st.markdown(f"### {short_msg}")
        if openrun_band(openrun) >= 2:
            st.caption(
                "아침 대기 환자가 많은 날입니다. 짧은 치료 환자를 위한 회전 침상을 일부 확보하면 "
                "전체 흐름이 덜 막힐 수 있습니다."
            )
        else:
            st.caption(
                "아침 대기 환자는 보통 범위입니다. 별도 분리 운영이 꼭 필요하지 않을 수 있습니다."
            )

# -----------------------------
# Whole-day flow
# -----------------------------
st.divider()
st.subheader("오늘 예상 흐름")

labels = flow_label(score, protocol)
f1, f2, f3, f4, f5 = st.columns(5)

for col, (period, label) in zip(
    [f1, f2, f3, f4, f5],
    labels.items()
):
    with col:
        st.markdown(f"**{period}**")
        st.markdown(f"### {label}")

# -----------------------------
# Explainability
# -----------------------------
st.divider()
e1, e2, e3 = st.columns(3)

with e1:
    st.subheader("왜 이렇게 예상했나요?")
    st.write(
        f"07:59까지 대기표 **{openrun}명**과 프로토콜 항암 **{protocol}명**을 "
        "과거 87일 분포와 비교해 초기 혼잡도를 정합니다."
    )
    st.write(
        "현재 실제 환자별 시간자료가 없기 때문에 10시 이후 숫자는 "
        "이 시작 조건에 맞춰 변하는 **시나리오 값**입니다."
    )

with e2:
    st.subheader("실제 데이터가 들어오면")
    st.write(
        "환자별 **접수시간·입실시간·퇴실시간**을 연결하면 "
        "현재 대기 / 치료 중 / 완료 / 빈 침상은 실제값으로 계산할 수 있습니다."
    )
    st.write(
        "이후에는 과거 입·퇴실 패턴으로 **다음 1시간 퇴실 가능성**도 "
        "실제 데이터 기반으로 바꿀 수 있습니다."
    )

with e3:
    st.subheader("현재 버전의 한계")
    st.write(
        "10시 이후 수치는 **실제 관측값이 아니라 시나리오**입니다. "
        "프로토콜별 실제 치료시간, 외래 당일 추가 오더, 환자 종류별 침상 점유시간은 "
        "아직 직접 반영하지 않았습니다."
    )
    st.write("이 버전의 목적은 **화면과 운영 판단 구조를 먼저 검증**하는 것입니다.")

st.caption(
    "Prototype framing: '몇 명을 막을지'보다 "
    "'현재 얼마나 밀렸는지, 언제 풀릴지, 긴 항암과 짧은 치료를 어떻게 운영할지'를 "
    "빠르게 보는 당일 운영지원 현황판."
)
