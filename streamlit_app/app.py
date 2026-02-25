import pandas as pd
import numpy as np
import streamlit as st
from pathlib import Path

st.set_page_config(page_title="UAC Capacity Dashboard", layout="wide")
st.title("System Capacity & Care Load Analytics — Unaccompanied Children")

# ---- Load data ----
# Load data using repo-relative path (works locally + on Streamlit Cloud)
ROOT_DIR = Path(__file__).resolve().parents[1]
processed_dir = ROOT_DIR / "data" / "processed"

csv_files = list(processed_dir.glob("*.csv"))

if len(csv_files) == 0:
    st.error("No CSV found in data/processed folder")
    st.stop()

data_path = csv_files[0]
st.write("Loading:", data_path.name)

@st.cache_data
def load_data(path):
    df = pd.read_csv(path, parse_dates=["date"])
    return df

df = load_data(data_path)

# ---- Sidebar filters ----
st.sidebar.header("Filters")
granularity = st.sidebar.selectbox("Time granularity", ["Daily", "Weekly", "Monthly"])
metrics_to_show = st.sidebar.multiselect(
    "Show metrics",
    ["total_system_load", "cbp_custody", "hhs_care", "net_hhs_intake"],
    default=["total_system_load"],
    key="metric_toggle"
)
min_date = df["date"].min()
max_date = df["date"].max()

start_date, end_date = st.sidebar.date_input(
    "Date range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date
)

# Convert date_input output to datetime
start_date = pd.to_datetime(start_date)
end_date = pd.to_datetime(end_date)

df_f = df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()

# Use only reported rows for KPIs (avoid NaNs from missing calendar days)
df_reported = df_f[df_f["is_reported"] == True].copy()
df_plot = df_reported.copy()

if granularity == "Weekly":
    df_plot = df_plot.set_index("date").resample("W").agg({
        "total_system_load": "mean",
        "cbp_custody": "mean",
        "hhs_care": "mean",
        "net_hhs_intake": "sum"
    }).reset_index()

elif granularity == "Monthly":
    df_plot = df_plot.set_index("date").resample("M").agg({
        "total_system_load": "mean",
        "cbp_custody": "mean",
        "hhs_care": "mean",
        "net_hhs_intake": "sum"
    }).reset_index()


# ---- Strain detection (high load + positive net intake) ----
# If strain_flag exists from preprocessing, use it; otherwise compute it on the filtered dataset.
if "strain_flag" not in df_reported.columns:
    threshold = df_reported["total_system_load"].quantile(0.85)
    df_reported["strain_flag"] = (
        (df_reported["total_system_load"] > threshold) &
        (df_reported["net_hhs_intake"] > 0)
    )


# ---- KPI Cards (latest available day) ----
st.subheader("KPI Summary (Latest Reported Day in Selected Range)")

latest = df_reported.dropna(subset=["total_system_load"]).sort_values("date").tail(1)

c1, c2, c3, c4, c5 = st.columns(5)

if len(latest) == 1:
    row = latest.iloc[0]

    c1.metric("Total System Load", f"{int(row['total_system_load']):,}")
    c2.metric("CBP Custody", f"{int(row['cbp_custody']):,}")
    c3.metric("HHS Care", f"{int(row['hhs_care']):,}")
    c4.metric("Net HHS Intake (day)", f"{int(row['net_hhs_intake']):,}")
    # backlog streak might be missing if not computed in your CSV
    if "backlog_streak" in df_reported.columns and pd.notna(row.get("backlog_streak", np.nan)):
        c5.metric("Backlog Streak (days)", f"{int(row['backlog_streak'])}")
    else:
        c5.metric("Backlog Streak (days)", "—")
else:
    st.info("No reported data in the selected date range.")

st.divider()

st.subheader("Selected Metrics")
if metrics_to_show:
    st.line_chart(df_plot.set_index("date")[metrics_to_show])
else:
    st.info("Select at least one metric from the sidebar to display.")

# ---- Charts ----
st.subheader("Total System Load Trend")
st.line_chart(df_plot.set_index("date")[["total_system_load"]])

st.subheader("CBP vs HHS Load")
st.line_chart(df_plot.set_index("date")[["total_system_load"]])

st.subheader("Net HHS Intake (Transfers - Discharges)")
st.bar_chart(df_reported.set_index("date")[["net_hhs_intake"]])
st.subheader("Selected Metrics")

if metrics_to_show:
    st.line_chart(df_plot.set_index("date")[metrics_to_show])
else:
    st.info("Select at least one metric from sidebar.")

st.subheader("Strain Days (High Load + Positive Net Intake)")

strain_days = df_reported[df_reported["strain_flag"] == True][
    ["date", "total_system_load", "net_hhs_intake", "cbp_custody", "hhs_care"]
].sort_values("date", ascending=False)

st.write(f"Strain days in selected range: **{len(strain_days)}**")
st.dataframe(strain_days.head(200))

# ---- Data Quality Flags ----
flag_cols = [c for c in ["flag_transfer_gt_cbp", "flag_discharge_gt_hhs", "flag_negative"] if c in df_reported.columns]

if flag_cols:
    st.subheader("Data Quality Flags (Reported Days)")
    flagged = df_reported[df_reported[flag_cols].any(axis=1)][["date"] + flag_cols].sort_values("date", ascending=False)
    st.dataframe(flagged.head(200))


with st.expander("Metric Definitions (How to interpret this dashboard)"):
    st.markdown("""
**Stocks (point-in-time counts)**
- **CBP Custody**: Children currently in CBP custody.
- **HHS Care**: Children currently in HHS care.
- **Total System Load** = CBP Custody + HHS Care.

**Flows (daily movement)**
- **Transfers to HHS**: Children transferred out of CBP custody into HHS.
- **Discharges**: Children discharged from HHS care (sponsor placement).
- **Net HHS Intake** = Transfers to HHS − Discharges.
  - Positive → backlog pressure
  - Negative → relief

**Strain Day**
- A day flagged when **Total System Load is high** (top 15% within selected range)
  AND **Net HHS Intake is positive**.
""")