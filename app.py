"""마케팅 채널 x AppsFlyer 통합 EDA 대시보드.

폴더 안의 *_channel.csv / *_appsflyer.csv 를 모두 읽어 날짜/채널/캠페인/그룹/소재 기준으로
조인하고, KPI/트렌드/채널·소재 성과/데이터 품질(EDA)을 한 화면에서 본다.

앱이 새로 열리거나(또는 새로고침 버튼 클릭) 시, 폴더를 다시 스캔해서 전날 추가된 파일까지
자동으로 반영한다 (get_folder_fingerprint가 캐시 키 역할).
"""

from __future__ import annotations

import altair as alt
import pandas as pd

import streamlit as st
from data_pipeline import build_dataset_from_files

CHART_HEIGHT = 300

st.set_page_config(
    page_title="채널 x AppsFlyer 대시보드",
    page_icon=":material/monitoring:",
    layout="wide",
)


@st.cache_data(ttl=600, show_spinner="데이터 로딩 및 조인 중...")
def load_data(channel_files: list, af_files: list, fingerprint: str) -> pd.DataFrame:
    return build_dataset_from_files(channel_files, af_files, fingerprint)


# =============================================================================
# 사이드바: 데이터 업로드 + 필터
# =============================================================================

with st.sidebar:
    st.markdown("### :material/upload_file: 데이터 업로드")
    channel_uploads = st.file_uploader(
        "채널 리포트 CSV (여러 개 선택 가능)", type="csv", accept_multiple_files=True
    )
    af_uploads = st.file_uploader(
        "AppsFlyer 리포트 CSV (여러 개 선택 가능)", type="csv", accept_multiple_files=True
    )

if not channel_uploads and not af_uploads:
    st.info("사이드바에서 채널 리포트 / AppsFlyer 리포트 CSV 파일을 업로드해주세요.")
    st.stop()

fingerprint = "|".join(
    f"{f.name}:{f.size}" for f in list(channel_uploads or []) + list(af_uploads or [])
)
df = load_data(channel_uploads or [], af_uploads or [], fingerprint)

if df.empty:
    st.warning("업로드한 CSV에서 유효한 데이터를 찾지 못했습니다. 파일 형식을 확인해주세요.")
    st.stop()

with st.sidebar:
    st.markdown("### :material/filter_alt: 필터")
    min_date, max_date = df["date"].min().date(), df["date"].max().date()
    date_range = st.date_input(
        "날짜 범위", value=(min_date, max_date), min_value=min_date, max_value=max_date
    )
    channels = st.multiselect(
        "채널", sorted(df["채널"].dropna().unique()), default=sorted(df["채널"].dropna().unique())
    )
    campaigns = st.multiselect(
        "캠페인",
        sorted(df["캠페인"].dropna().unique()),
        default=sorted(df["캠페인"].dropna().unique()),
    )
    groups = st.multiselect(
        "그룹", sorted(df["그룹"].dropna().unique()), default=sorted(df["그룹"].dropna().unique())
    )
    creatives = st.multiselect("소재 (비우면 전체)", sorted(df["소재"].dropna().unique()))

# =============================================================================
# 필터 적용
# =============================================================================

if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = min_date, max_date

mask = (
    (df["date"].dt.date >= start_date)
    & (df["date"].dt.date <= end_date)
    & df["채널"].isin(channels)
    & df["캠페인"].isin(campaigns)
    & df["그룹"].isin(groups)
)
if creatives:
    mask &= df["소재"].isin(creatives)

fdf = df[mask].copy()

st.markdown("# :material/monitoring: 채널 x AppsFlyer 대시보드")
st.caption(f"업로드된 파일 {len(channel_uploads or []) + len(af_uploads or [])}개 · {len(df):,}행 중 {len(fdf):,}행 표시 중")

if fdf.empty:
    st.info("선택한 필터에 해당하는 데이터가 없습니다.")
    st.stop()

tab_overview, tab_breakdown, tab_creative, tab_eda, tab_raw = st.tabs(
    [
        ":material/dashboard: 개요",
        ":material/bar_chart: 채널/캠페인 분석",
        ":material/ad: 소재 성과",
        ":material/query_stats: 데이터 품질 · EDA",
        ":material/table: Raw 데이터",
    ]
)

# =============================================================================
# 개요 탭: KPI + 트렌드
# =============================================================================

with tab_overview:
    total_impression = fdf["노출"].sum()
    total_click_channel = fdf["클릭_channel"].sum()
    total_cost = fdf["비용"].sum()
    total_purchase_af = fdf["구매_af"].sum()
    total_revenue_af = fdf["구매매출_af"].sum()
    ctr = (total_click_channel / total_impression * 100) if total_impression else 0
    cpa = (total_cost / total_purchase_af) if total_purchase_af else 0
    roas = (total_revenue_af / total_cost * 100) if total_cost else 0

    daily = (
        fdf.groupby(fdf["date"].dt.date)
        .agg(
            노출=("노출", "sum"),
            클릭_channel=("클릭_channel", "sum"),
            비용=("비용", "sum"),
            구매_af=("구매_af", "sum"),
            구매매출_af=("구매매출_af", "sum"),
        )
        .reset_index()
        .rename(columns={"date": "일자"})
    )
    daily["ROAS"] = (daily["구매매출_af"] / daily["비용"].replace(0, pd.NA) * 100).fillna(0)

    with st.container(horizontal=True):
        st.metric(
            "노출",
            f"{total_impression:,.0f}",
            border=True,
            chart_data=daily["노출"].tolist(),
            chart_type="line",
        )
        st.metric(
            "클릭 (채널 기준)",
            f"{total_click_channel:,.0f}",
            border=True,
            chart_data=daily["클릭_channel"].tolist(),
            chart_type="line",
        )
        st.metric("CTR", f"{ctr:.2f}%", border=True)
        st.metric("비용", f"₩{total_cost:,.0f}", border=True, chart_data=daily["비용"].tolist(), chart_type="bar")

    with st.container(horizontal=True):
        st.metric(
            "구매 (AF 기준)",
            f"{total_purchase_af:,.0f}",
            border=True,
            chart_data=daily["구매_af"].tolist(),
            chart_type="line",
        )
        st.metric(
            "구매매출 (AF 기준)",
            f"₩{total_revenue_af:,.0f}",
            border=True,
            chart_data=daily["구매매출_af"].tolist(),
            chart_type="bar",
        )
        st.metric("CPA", f"₩{cpa:,.0f}", border=True)
        st.metric("ROAS", f"{roas:.1f}%", border=True, chart_data=daily["ROAS"].tolist(), chart_type="line")

    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            st.markdown("**비용 vs 구매매출 추이**")
            melted = daily.melt(
                id_vars="일자", value_vars=["비용", "구매매출_af"], var_name="구분", value_name="값"
            )
            chart = (
                alt.Chart(melted)
                .mark_line(point=True)
                .encode(
                    x=alt.X("일자:T", title=None),
                    y=alt.Y("값:Q", title=None),
                    color=alt.Color("구분:N", title=None, legend=alt.Legend(orient="bottom")),
                    tooltip=["일자:T", "구분:N", alt.Tooltip("값:Q", format=",.0f")],
                )
                .properties(height=CHART_HEIGHT)
            )
            st.altair_chart(chart)

    with col2:
        with st.container(border=True):
            st.markdown("**채널별 비용 비중**")
            by_channel = fdf.groupby("채널", as_index=False)["비용"].sum()
            chart = (
                alt.Chart(by_channel)
                .mark_arc()
                .encode(
                    theta="비용:Q",
                    color=alt.Color("채널:N", legend=alt.Legend(orient="bottom")),
                    tooltip=["채널:N", alt.Tooltip("비용:Q", format=",.0f")],
                )
                .properties(height=CHART_HEIGHT)
            )
            st.altair_chart(chart)

# =============================================================================
# 채널/캠페인 분석 탭
# =============================================================================

with tab_breakdown:
    group_by = st.segmented_control(
        "기준", options=["채널", "캠페인", "그룹"], default="채널", key="breakdown_group_by"
    )
    group_by = group_by or "채널"

    agg = (
        fdf.groupby(group_by, as_index=False)
        .agg(
            노출=("노출", "sum"),
            클릭_channel=("클릭_channel", "sum"),
            비용=("비용", "sum"),
            구매_af=("구매_af", "sum"),
            구매매출_af=("구매매출_af", "sum"),
        )
        .sort_values("비용", ascending=False)
    )
    agg["CTR"] = (agg["클릭_channel"] / agg["노출"].replace(0, pd.NA) * 100).fillna(0)
    agg["CPA"] = (agg["비용"] / agg["구매_af"].replace(0, pd.NA)).fillna(0)
    agg["ROAS"] = (agg["구매매출_af"] / agg["비용"].replace(0, pd.NA) * 100).fillna(0)

    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            st.markdown(f"**{group_by}별 비용**")
            chart = (
                alt.Chart(agg)
                .mark_bar()
                .encode(
                    x=alt.X("비용:Q", title=None),
                    y=alt.Y(f"{group_by}:N", sort="-x", title=None),
                    tooltip=[f"{group_by}:N", alt.Tooltip("비용:Q", format=",.0f")],
                )
                .properties(height=CHART_HEIGHT)
            )
            st.altair_chart(chart)
    with col2:
        with st.container(border=True):
            st.markdown(f"**{group_by}별 ROAS**")
            chart = (
                alt.Chart(agg)
                .mark_bar(color="#2ca02c")
                .encode(
                    x=alt.X("ROAS:Q", title=None),
                    y=alt.Y(f"{group_by}:N", sort="-x", title=None),
                    tooltip=[f"{group_by}:N", alt.Tooltip("ROAS:Q", format=".1f")],
                )
                .properties(height=CHART_HEIGHT)
            )
            st.altair_chart(chart)

    with st.container(border=True):
        st.markdown(f"**{group_by}별 상세 지표**")
        st.dataframe(
            agg.style.format(
                {
                    "노출": "{:,.0f}",
                    "클릭_channel": "{:,.0f}",
                    "비용": "₩{:,.0f}",
                    "구매_af": "{:,.0f}",
                    "구매매출_af": "₩{:,.0f}",
                    "CTR": "{:.2f}%",
                    "CPA": "₩{:,.0f}",
                    "ROAS": "{:.1f}%",
                }
            ),
            hide_index=True,
        )

# =============================================================================
# 소재 성과 탭
# =============================================================================

with tab_creative:
    creative_agg = (
        fdf.groupby(["채널", "캠페인", "소재"], as_index=False)
        .agg(
            노출=("노출", "sum"),
            클릭_channel=("클릭_channel", "sum"),
            비용=("비용", "sum"),
            구매_af=("구매_af", "sum"),
            구매매출_af=("구매매출_af", "sum"),
        )
    )
    creative_agg["CTR"] = (
        creative_agg["클릭_channel"] / creative_agg["노출"].replace(0, pd.NA) * 100
    ).fillna(0)
    creative_agg["ROAS"] = (
        creative_agg["구매매출_af"] / creative_agg["비용"].replace(0, pd.NA) * 100
    ).fillna(0)
    creative_agg = creative_agg.sort_values("ROAS", ascending=False)

    with st.container(border=True):
        st.markdown("**소재별 ROAS 랭킹**")
        st.dataframe(
            creative_agg.style.format(
                {
                    "노출": "{:,.0f}",
                    "클릭_channel": "{:,.0f}",
                    "비용": "₩{:,.0f}",
                    "구매_af": "{:,.0f}",
                    "구매매출_af": "₩{:,.0f}",
                    "CTR": "{:.2f}%",
                    "ROAS": "{:.1f}%",
                }
            ),
            hide_index=True,
            height=500,
        )

# =============================================================================
# 데이터 품질 / EDA 탭
# =============================================================================

with tab_eda:
    st.markdown("**채널 리포트 vs AppsFlyer 매칭 현황**")
    st.caption("조인 키(날짜/채널/캠페인/그룹/소재) 기준으로 양쪽 데이터가 서로 잘 맞는지 확인합니다.")

    join_counts = fdf["__join_status"].value_counts().reset_index()
    join_counts.columns = ["매칭 상태", "행 수"]

    col1, col2 = st.columns([1, 2])
    with col1:
        with st.container(border=True):
            chart = (
                alt.Chart(join_counts)
                .mark_arc()
                .encode(
                    theta="행 수:Q",
                    color=alt.Color("매칭 상태:N", legend=alt.Legend(orient="bottom")),
                    tooltip=["매칭 상태:N", "행 수:Q"],
                )
                .properties(height=CHART_HEIGHT)
            )
            st.altair_chart(chart)
    with col2:
        with st.container(border=True):
            st.markdown("**채널 리포트 vs AF 클릭/매출 차이율 (채널별 평균)**")
            diff_agg = fdf.groupby("채널", as_index=False)[["클릭_차이율", "매출_차이율"]].mean()
            melted = diff_agg.melt(id_vars="채널", var_name="지표", value_name="차이율(%)")
            chart = (
                alt.Chart(melted)
                .mark_bar()
                .encode(
                    x=alt.X("채널:N", title=None),
                    y=alt.Y("차이율(%):Q"),
                    color=alt.Color("지표:N", legend=alt.Legend(orient="bottom")),
                    xOffset="지표:N",
                    tooltip=["채널:N", "지표:N", alt.Tooltip("차이율(%):Q", format=".1f")],
                )
                .properties(height=CHART_HEIGHT)
            )
            st.altair_chart(chart)
    st.caption(
        "차이율 = (채널 리포팅 값 - AF 어트리뷰션 값) / 채널 리포팅 값. "
        "양수면 채널 자체 집계가 AF보다 높게(과대) 잡힌다는 의미입니다."
    )

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            st.markdown("**결측치 현황**")
            missing = fdf.isna().sum()
            missing = missing[missing > 0]
            if missing.empty:
                st.success("결측치 없음")
            else:
                st.dataframe(missing.rename("결측 개수"))
    with col2:
        with st.container(border=True):
            st.markdown("**기초 통계 (describe)**")
            numeric_cols = [
                "노출",
                "클릭_channel",
                "클릭_af",
                "비용",
                "구매_af",
                "구매매출_af",
                "CTR",
                "ROAS",
            ]
            numeric_cols = [c for c in numeric_cols if c in fdf.columns]
            st.dataframe(fdf[numeric_cols].describe().T)

    with st.container(border=True):
        st.markdown("**주요 지표 상관관계**")
        corr_cols = [c for c in numeric_cols if c in fdf.columns]
        corr = fdf[corr_cols].corr().reset_index().melt(id_vars="index")
        corr.columns = ["지표1", "지표2", "상관계수"]
        chart = (
            alt.Chart(corr)
            .mark_rect()
            .encode(
                x=alt.X("지표1:N", title=None),
                y=alt.Y("지표2:N", title=None),
                color=alt.Color("상관계수:Q", scale=alt.Scale(scheme="redblue", domain=[-1, 1])),
                tooltip=["지표1:N", "지표2:N", alt.Tooltip("상관계수:Q", format=".2f")],
            )
            .properties(height=400)
        )
        st.altair_chart(chart)

# =============================================================================
# Raw 데이터 탭
# =============================================================================

with tab_raw:
    st.markdown(f"**필터 적용된 Raw 데이터** ({len(fdf):,}행)")
    st.dataframe(fdf, hide_index=True, height=500)
    st.download_button(
        ":material/download: CSV로 다운로드",
        data=fdf.to_csv(index=False).encode("utf-8-sig"),
        file_name="merged_marketing_data.csv",
        mime="text/csv",
    )
