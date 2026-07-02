"""채널(매체) 리포트와 AppsFlyer(MMP) 리포트를 로딩·조인·전처리하는 파이프라인.

두 소스 모두 클릭/회원가입/구매/구매매출을 각자 집계해서 갖고 있어 값이 어긋날 수 있으므로
(매체 자체 리포팅 vs MMP 어트리뷰션 차이) 접미사(_channel/_af)로 양쪽을 모두 보존한다.
채널 리포트는 한글 채널명(구글/메타/네이버), AppsFlyer는 미디어소스 코드(googleadwords_int 등)를
쓰기 때문에 조인 전에 매핑이 필요하다.
"""

from __future__ import annotations

import glob
import os

import pandas as pd

# 채널 리포트의 한글 채널명 <-> AppsFlyer 미디어소스 코드 매핑.
# 새로운 매체가 추가되면 여기에 한 줄만 추가하면 된다.
CHANNEL_TO_MEDIA_SOURCE = {
    "구글": "googleadwords_int",
    "메타": "Facebook Ads",
    "네이버": "naver_search",
}
MEDIA_SOURCE_TO_CHANNEL = {v: k for k, v in CHANNEL_TO_MEDIA_SOURCE.items()}

JOIN_KEYS = ["date", "채널", "캠페인", "그룹", "소재"]
OVERLAP_METRICS = ["클릭", "회원가입", "구매", "구매매출"]


def get_folder_fingerprint(base_folder: str) -> str:
    """channel/appsflyer 하위 폴더의 CSV 목록+수정시각+크기로 만든 지문.

    새 날짜의 파일이 추가되거나 기존 파일이 바뀌면 이 값이 달라져서,
    이 값을 캐시 키로 쓰는 build_dataset()의 캐시가 자동으로 무효화된다.
    """
    parts = []
    for subfolder in ("channel", "appsflyer"):
        folder = os.path.join(base_folder, subfolder)
        if not os.path.isdir(folder):
            parts.append(f"{subfolder}:MISSING")
            continue
        for path in sorted(glob.glob(os.path.join(folder, "*.csv"))):
            stat = os.stat(path)
            parts.append(f"{subfolder}/{os.path.basename(path)}:{stat.st_mtime_ns}:{stat.st_size}")
    return "|".join(parts)


def _read_csvs(paths: list[str]) -> pd.DataFrame:
    frames = []
    for path in paths:
        df = pd.read_csv(path)
        df["__source_file"] = os.path.basename(path)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def load_channel_data(base_folder: str) -> pd.DataFrame:
    """<base_folder>/channel/ 안의 일별 CSV 전부를 읽어 하나로 합친다."""
    paths = sorted(glob.glob(os.path.join(base_folder, "channel", "*.csv")))
    df = _read_csvs(paths)
    if df.empty:
        return df
    df = df.rename(columns={"일": "date"})
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_appsflyer_data(base_folder: str) -> pd.DataFrame:
    """<base_folder>/appsflyer/ 안의 일별 CSV 전부를 읽어 합치고, 미디어소스를 채널명으로 매핑한다."""
    paths = sorted(glob.glob(os.path.join(base_folder, "appsflyer", "*.csv")))
    df = _read_csvs(paths)
    if df.empty:
        return df
    df = df.rename(columns={"일": "date"})
    df["date"] = pd.to_datetime(df["date"])
    df["채널"] = df["미디어소스"].map(MEDIA_SOURCE_TO_CHANNEL).fillna(df["미디어소스"])
    return df


def merge_channel_appsflyer(channel_df: pd.DataFrame, af_df: pd.DataFrame) -> pd.DataFrame:
    """날짜/채널/캠페인/그룹/소재 기준 outer join. 중복 지표는 _channel/_af로 분리 보존."""
    if channel_df.empty and af_df.empty:
        return pd.DataFrame()
    if channel_df.empty:
        channel_df = pd.DataFrame(columns=JOIN_KEYS)
    if af_df.empty:
        af_df = pd.DataFrame(columns=JOIN_KEYS)

    merged = pd.merge(
        channel_df,
        af_df,
        on=JOIN_KEYS,
        how="outer",
        suffixes=("_channel", "_af"),
        indicator="__join_status",
    )

    for col in OVERLAP_METRICS:
        for suffix in ("_channel", "_af"):
            col_name = f"{col}{suffix}"
            if col_name in merged.columns:
                merged[col_name] = merged[col_name].fillna(0)

    for col in ["노출", "비용"]:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0)

    merged["__join_status"] = merged["__join_status"].map(
        {"both": "매칭", "left_only": "채널만", "right_only": "앱스플라이어만"}
    )

    return merged


def compute_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """CTR/CVR/CPA/ROAS 및 채널-어트리뷰션 차이율 파생 지표 계산."""
    if df.empty:
        return df
    df = df.copy()
    df["CTR"] = (df["클릭_channel"] / df["노출"].replace(0, pd.NA) * 100).fillna(0)
    df["CVR_af"] = (df["구매_af"] / df["클릭_af"].replace(0, pd.NA) * 100).fillna(0)
    df["CPA"] = (df["비용"] / df["구매_af"].replace(0, pd.NA)).fillna(0)
    df["ROAS"] = (df["구매매출_af"] / df["비용"].replace(0, pd.NA) * 100).fillna(0)
    df["클릭_차이율"] = (
        (df["클릭_channel"] - df["클릭_af"]) / df["클릭_channel"].replace(0, pd.NA) * 100
    ).fillna(0)
    df["매출_차이율"] = (
        (df["구매매출_channel"] - df["구매매출_af"]) / df["구매매출_channel"].replace(0, pd.NA) * 100
    ).fillna(0)
    return df


def build_dataset(base_folder: str, _fingerprint: str) -> pd.DataFrame:
    """<base_folder>/channel, <base_folder>/appsflyer의 일별 CSV를 읽어
    조인 + 파생지표 계산까지 완료한 데이터셋 반환.

    _fingerprint는 캐시 무효화 트리거 용도로만 쓰인다 (get_folder_fingerprint 참고).
    """
    channel_df = load_channel_data(base_folder)
    af_df = load_appsflyer_data(base_folder)
    merged = merge_channel_appsflyer(channel_df, af_df)
    return compute_metrics(merged)
