                         
  from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

APP_VERSION = "cloud-v1"

# Must be the first Streamlit command
st.set_page_config(page_title="UAC Capacity Dashboard", layout="wide")

st.title("System Capacity & Care Load Analytics — Unaccompanied Children")
st.caption(f"App version: {APP_VERSION}")

# -------------------------------------------------------------------
# Paths (app.py is inside streamlit_app/, so repo root is parent.parent)
# -------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_ROOT / "data" / "processed" / "uac_metrics_final.csv"

# Optional: show paths (helpful while debugging on cloud)
with st.expander("Debug: paths", expanded=False):
    st.write("REPO_ROOT:", str(REPO_ROOT))
    st.write("DATA_PATH:", str(DATA_PATH))
    st.write("DATA_PATH exists?:", DATA_PATH.exists())

if not DATA_PATH.exists():
    st.error("CSV not found at data/processed/uac_metrics_final.csv. Make sure it is committed to GitHub.")
    st.stop()

@st.cache_data
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df

df = load_data(str(DATA_PATH))

# Basic validation
required_cols = {"date", "total_system_load", "cbp_custody", "hhs_care", "net_hhs_intake", "is_reported"}
missing = required_cols - set(df.columns)
if missing:
    st.error(f"CSV is missing required columns: {sorted(list(missing))}")
    st.stop()

# -------------------
# Sidebar filters
# -------------------
st.sidebar.header("Filters")

granularity = st.sidebar.selectbox("Time granularity", ["Daily", "Weekly", "Monthly"], index=0)

metrics_to_show = st.sidebar.multiselect(
    "Show metrics",
    ["total_system_load", "cbp_custody", "hhs_care", "net_hhs_intake"],
    default=["total_system_load"],
)

min_date = df["date"].min()
max_date = df["date"].max()

date_range = st.sidebar.date_input(
    "Date range",
    value=(min_date.date(), max_date.date()),
    min_value=min_date.date(),
    max_value=max_date.date(),
)

# date_input can return a single date if user clicks once
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date = date_range
    end_date = date_range

start_date = pd.to_datetime(start_date)
end_date = pd.to_datetime(end_date)

df_f = df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()

# Use only reported rows for KPI + charts
df_reported = df_f[df_f["is_reported"] == True].copy()
if df_reported.empty:
    st.warning("No reported data in the selected date range.")
    st.stop()

# Resample for plotting
df_plot = df_reported.copy().set_index("date").sort_index()

if granularity == "Weekly":
    df_plot = df_plot.resample("W").agg(
        total_system_load=("total_system_load", "mean"),
        cbp_custody=("cbp_custody", "mean"),
        hhs_care=("hhs_care", "mean"),
        net_hhs_intake=("net_hhs_intake", "sum"),
    )

elif granularity == "Monthly":
    df_plot = df_plot.resample("M").agg(
        total_system_load=("total_system_load", "mean"),
        cbp_custody=("cbp_custody", "mean"),
        hhs_care=("hhs_care", "mean"),
        net_hhs_intake=("net_hhs_intake", "sum"),
    )

# -------------------
# Strain flag
# -------------------
if "strain_flag" not in df_reported.columns:
    threshold = df_reported["total_system_load"].quantile(0.85)
    df_reported["strain_flag"] = (df_reported["total_system_load"] > threshold) & (df_reported["net_hhs_intake"] > 0)

# -------------------
# KPI Cards (latest day)
# -------------------
st.subheader("KPI Summary (Latest Reported Day in Selected Range)")

latest = df_reported.dropna(subset=["total_system_load"]).sort_values("date").tail(1)
row = latest.iloc[0]

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total System Load", f"{int(row['total_system_load']):,}")
c2.metric("CBP Custody", f"{int(row['cbp_custody']):,}")
c3.metric("HHS Care", f"{int(row['hhs_care']):,}")
c4.metric("Net HHS Intake (day)", f"{int(row['net_hhs_intake']):,}")

if "backlog_streak" in df_reported.columns and pd.notna(row.get("backlog_streak", np.nan)):
    c5.metric("Backlog Streak (days)", f"{int(row['backlog_streak']):,}")
else:
    c5.metric("Backlog Streak (days)", "—")

st.divider()

# -------------------
# Charts
# -------------------
st.subheader("Selected Metrics")
if metrics_to_show:
    st.line_chart(df_plot[metrics_to_show])
else:
    st.info("Select at least one metric from the sidebar to display.")

st.subheader("Total System Load Trend")
st.line_chart(df_plot[["total_system_load"]])

st.subheader("CBP vs HHS Load")
st.line_chart(df_plot[["cbp_custody", "hhs_care"]])

st.subheader("Net HHS Intake (Transfers - Discharges)")
st.bar_chart(df_reported.set_index("date")[["net_hhs_intake"]].sort_index())

# -------------------
# Strain days table
# -------------------
st.subheader("Strain Days (High Load + Positive Net Intake)")

strain_days = df_reported[df_reported["strain_flag"] == True][
    ["date", "total_system_load", "net_hhs_intake", "cbp_custody", "hhs_care"]
].sort_values("date", ascending=False)

st.write(f"Strain days in selected range: **{len(strain_days)}**")
st.dataframe(strain_days.head(200), use_container_width=True)

# -------------------
# Data quality flags (optional)
# -------------------
flag_cols = [c for c in ["flag_transfer_gt_cbp", "flag_discharge_gt_hhs", "flag_negative"] if c in df_reported.columns]
if flag_cols:
    st.subheader("Data Quality Flags (Reported Days)")
    flagged = df_reported[df_reported[flag_cols].any(axis=1)][["date"] + flag_cols].sort_values("date", ascending=False)
    st.dataframe(flagged.head(200), use_container_width=True)

with st.expander("Metric Definitions (How to interpret this dashboard)"):
    st.markdown(
        """
**Stocks (point-in-time counts)**
- **CBP Custody**: Children currently in CBP custody.
- **HHS Care**: Children currently in HHS care.
- **Total System Load** = CBP Custody + HHS Care.

**Flows (daily movement)**
- **Net HHS Intake** = Transfers to HHS − Discharges.
  - Positive → backlog pressure
  - Negative → relief

**Strain Day**
- A day flagged when **Total System Load is high** (top 15% within selected range)
  AND **Net HHS Intake is positive**.
"""
    )