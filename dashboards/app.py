"""Calendly Marketing Insights dashboard (Streamlit).

Reads the CSV exports written by notebook 03_gold to gold/export/ and synced to
dashboards/data/export/ with sync_gold.cmd. Six metric pages (brief, Step 5) and an
operations page. Run from the repository root:

    streamlit run dashboards/app.py
"""

from __future__ import annotations

import glob
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

DATA_ROOT = Path(__file__).resolve().parent / "data" / "export"
DAY_ORDER = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
CHANNEL_LABELS = {
    "facebook_paid_ads": "Facebook",
    "youtube_paid_ads": "YouTube",
    "tiktok_paid_ads": "TikTok",
    "other": "Other",
}

st.set_page_config(page_title="Calendly Marketing Insights", layout="wide")


@st.cache_data(show_spinner=False)
def load(table: str) -> pd.DataFrame:
    files = sorted(glob.glob(str(DATA_ROOT / table / "*.csv")))
    if not files:
        return pd.DataFrame()
    frame = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)
    for col in ("date", "week_start", "period_start", "period_end"):
        if col in frame.columns:
            frame[col] = pd.to_datetime(frame[col], errors="coerce")
    if "channel" in frame.columns:
        frame["channel_label"] = frame["channel"].map(CHANNEL_LABELS).fillna(frame["channel"])
    return frame


def empty_notice(what: str) -> None:
    st.info(
        f"No {what} yet. Campaign bookings appear here once the Calendly webhook subscription "
        "is active and the hourly job has run."
    )


def date_filter(frame: pd.DataFrame, col: str = "date") -> pd.DataFrame:
    if frame.empty or col not in frame.columns:
        return frame
    lo, hi = frame[col].min().date(), frame[col].max().date()
    if lo == hi:
        return frame
    start, end = st.sidebar.slider("Date range", lo, hi, (lo, hi), key=f"range_{col}")
    mask = (frame[col].dt.date >= start) & (frame[col].dt.date <= end)
    return frame[mask]


# ----------------------------------------------------------------------------- pages


def page_daily_bookings() -> None:
    st.header("1.1 Daily calls booked by source")
    daily = date_filter(load("daily_bookings_by_channel"))
    if daily.empty:
        empty_notice("campaign bookings")
        return
    fig = px.line(
        daily.sort_values("date"),
        x="date",
        y="bookings",
        color="channel_label",
        markers=True,
        labels={"date": "Date", "bookings": "Bookings", "channel_label": "Source"},
    )
    st.plotly_chart(fig, use_container_width=True)
    pivot = daily.pivot_table(
        index="date", columns="channel_label", values="bookings", aggfunc="sum", fill_value=0
    )
    pivot["Total"] = pivot.sum(axis=1)
    st.subheader("Daily comparison by source")
    st.dataframe(pivot.sort_index(ascending=False), use_container_width=True)


def page_cpb() -> None:
    st.header("1.2 Cost per booking by channel")
    st.caption(
        "Spend arrives one day behind (Day-1), so the latest day shows bookings without spend."
    )
    cpb = date_filter(load("daily_spend_and_cpb"))
    if cpb.empty:
        empty_notice("spend or booking data")
        return
    totals = cpb.groupby(["channel", "channel_label"], as_index=False).agg(
        spend_usd=("spend_usd", "sum"), bookings=("bookings", "sum")
    )
    totals["cpb_usd"] = totals.apply(
        lambda r: round(r.spend_usd / r.bookings, 2) if r.bookings > 0 else None, axis=1
    )
    total_spend = totals.spend_usd.sum()
    total_bookings = int(totals.bookings.sum())
    avg_cpb = round(total_spend / total_bookings, 2) if total_bookings else None

    c1, c2, c3 = st.columns(3)
    c1.metric("Total bookings", f"{total_bookings:,}")
    c2.metric("Total spend", f"${total_spend:,.2f}")
    c3.metric("Average CPB", f"${avg_cpb:,.2f}" if avg_cpb is not None else "n/a")

    plot = totals.dropna(subset=["cpb_usd"])
    if plot.empty:
        st.warning("CPB is not available until at least one campaign booking is recorded.")
    else:
        fig = px.bar(
            plot,
            x="channel_label",
            y="cpb_usd",
            text_auto=".2f",
            labels={"channel_label": "Channel", "cpb_usd": "CPB (USD)"},
        )
        st.plotly_chart(fig, use_container_width=True)
    st.subheader("Channel summary (sortable)")
    st.dataframe(
        totals[["channel_label", "spend_usd", "bookings", "cpb_usd"]]
        .rename(
            columns={
                "channel_label": "Channel",
                "spend_usd": "Spend (USD)",
                "bookings": "Bookings",
                "cpb_usd": "CPB (USD)",
            }
        )
        .sort_values("Spend (USD)", ascending=False),
        use_container_width=True,
        hide_index=True,
    )


def page_trend() -> None:
    st.header("1.3 Bookings trend over time")
    daily = date_filter(load("daily_bookings_by_channel"))
    if daily.empty:
        empty_notice("campaign bookings")
        return
    grain = st.radio("Grain", ["Daily", "Weekly"], horizontal=True)
    frame = daily.copy()
    if grain == "Weekly":
        frame["date"] = frame["date"].dt.to_period("W").dt.start_time
        frame = frame.groupby(["date", "channel_label"], as_index=False).bookings.sum()
    frame = frame.sort_values("date")
    st.plotly_chart(
        px.line(
            frame,
            x="date",
            y="bookings",
            color="channel_label",
            markers=True,
            labels={"channel_label": "Source"},
        ),
        use_container_width=True,
    )
    frame["cumulative"] = frame.groupby("channel_label").bookings.cumsum()
    st.plotly_chart(
        px.area(
            frame,
            x="date",
            y="cumulative",
            color="channel_label",
            labels={"cumulative": "Cumulative bookings", "channel_label": "Source"},
        ),
        use_container_width=True,
    )


def page_attribution() -> None:
    st.header("1.4 Channel attribution")
    attr = load("channel_attribution")
    if attr.empty:
        empty_notice("attribution data")
        return
    board = attr.sort_values("total_bookings", ascending=False)[
        [
            "channel_label",
            "campaign",
            "total_bookings",
            "total_spend_usd",
            "cpb_usd",
            "rank_by_bookings",
            "rank_by_cpb",
        ]
    ].rename(
        columns={
            "channel_label": "Source",
            "campaign": "Campaign",
            "total_bookings": "Total bookings",
            "total_spend_usd": "Spend (USD)",
            "cpb_usd": "CPB (USD)",
            "rank_by_bookings": "Rank (volume)",
            "rank_by_cpb": "Rank (cost)",
        }
    )
    st.subheader("Leaderboard")
    st.dataframe(board, use_container_width=True, hide_index=True)

    cpb = load("daily_spend_and_cpb")
    if not cpb.empty and cpb.cpb_usd.notna().any():
        cpb["month"] = cpb["date"].dt.to_period("M").astype(str)
        heat = cpb.groupby(["channel_label", "month"], as_index=False).agg(
            spend=("spend_usd", "sum"), bookings=("bookings", "sum")
        )
        heat["cpb"] = heat.apply(lambda r: r.spend / r.bookings if r.bookings else None, axis=1)
        pivot = heat.pivot(index="channel_label", columns="month", values="cpb")
        st.subheader("CPB by channel and month (USD)")
        st.plotly_chart(
            px.imshow(pivot, text_auto=".0f", aspect="auto", color_continuous_scale="Blues"),
            use_container_width=True,
        )
    st.subheader("Top sources by bookings")
    st.plotly_chart(
        px.bar(
            attr.sort_values("total_bookings", ascending=False),
            x="channel_label",
            y="total_bookings",
            text_auto=True,
            labels={"channel_label": "Source", "total_bookings": "Bookings"},
        ),
        use_container_width=True,
    )


def page_time_slots() -> None:
    st.header("1.5 Booking volume by time slot and day of week")
    st.caption("Meeting start time, Eastern time.")
    slots = load("bookings_by_time_slot")
    if slots.empty:
        empty_notice("campaign bookings")
        return
    channels = ["All"] + sorted(slots.channel_label.unique())
    pick = st.selectbox("Channel", channels)
    frame = slots if pick == "All" else slots[slots.channel_label == pick]
    heat = frame.groupby(["day_of_week", "hour"], as_index=False).bookings.sum()
    pivot = (
        heat.pivot(index="day_of_week", columns="hour", values="bookings")
        .reindex(DAY_ORDER)
        .fillna(0)
    )
    pivot = pivot.reindex(columns=range(24), fill_value=0)
    st.plotly_chart(
        px.imshow(
            pivot,
            text_auto=True,
            aspect="auto",
            labels={"x": "Hour", "y": "Day", "color": "Bookings"},
            color_continuous_scale="Blues",
        ),
        use_container_width=True,
    )
    c1, c2 = st.columns(2)
    by_hour = frame.groupby("hour", as_index=False).bookings.sum()
    c1.plotly_chart(
        px.bar(by_hour, x="hour", y="bookings", title="Bookings by hour"), use_container_width=True
    )
    by_day = frame.groupby("day_of_week", as_index=False).bookings.sum()
    by_day["day_of_week"] = pd.Categorical(by_day.day_of_week, DAY_ORDER, ordered=True)
    c2.plotly_chart(
        px.pie(
            by_day.sort_values("day_of_week"),
            names="day_of_week",
            values="bookings",
            title="Bookings by day of week",
        ),
        use_container_width=True,
    )


def page_employee_load() -> None:
    st.header("1.6 Meeting load per employee")
    st.caption("All event types; canceled meetings excluded.")
    load_df = load("employee_meeting_load")
    weekly = load("employee_weekly_meetings")
    if load_df.empty:
        empty_notice("meetings")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Total meetings", f"{int(load_df.total_meetings.sum()):,}")
    c2.metric("Max in a week", int(load_df.max_week.max()))
    c3.metric("Min in a week", int(load_df.min_week.min()))
    st.plotly_chart(
        px.bar(
            load_df.sort_values("avg_meetings_per_week", ascending=False),
            x="host_name",
            y="avg_meetings_per_week",
            text_auto=".1f",
            labels={"host_name": "Employee", "avg_meetings_per_week": "Average meetings per week"},
        ),
        use_container_width=True,
    )
    if not weekly.empty:
        st.plotly_chart(
            px.line(
                weekly.sort_values("week_start"),
                x="week_start",
                y="meetings",
                color="host_name",
                markers=True,
                labels={"week_start": "Week", "meetings": "Meetings", "host_name": "Employee"},
            ),
            use_container_width=True,
        )
    st.dataframe(
        load_df[
            [
                "host_name",
                "total_meetings",
                "weeks_observed",
                "avg_meetings_per_week",
                "max_week",
                "min_week",
            ]
        ].rename(
            columns={
                "host_name": "Employee",
                "total_meetings": "Meetings",
                "weeks_observed": "Weeks",
                "avg_meetings_per_week": "Avg / week",
                "max_week": "Max week",
                "min_week": "Min week",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )


def page_operations() -> None:
    st.header("Operations")
    cpb = load("daily_spend_and_cpb")
    daily = load("daily_bookings_by_channel")
    c1, c2, c3 = st.columns(3)
    spend_dates = (
        cpb.loc[cpb.spend_usd.notna(), "date"]
        if not cpb.empty
        else pd.Series(dtype="datetime64[ns]")
    )
    c1.metric(
        "Spend through", spend_dates.max().date().isoformat() if not spend_dates.empty else "n/a"
    )
    c2.metric(
        "Latest campaign booking",
        daily.date.max().date().isoformat() if not daily.empty else "none yet",
    )
    c3.metric("Spend days loaded", int(spend_dates.nunique()))
    st.caption(
        "Spend is published one day behind at 06:00 AM Eastern and fetched between 06:15 and 12:45; "
        "the Databricks job rebuilds all layers hourly. Data files are synced with dashboards\\sync_gold.cmd."
    )
    if not cpb.empty:
        st.subheader("Daily spend by channel")
        st.plotly_chart(
            px.bar(
                cpb.dropna(subset=["spend_usd"]).sort_values("date"),
                x="date",
                y="spend_usd",
                color="channel_label",
                labels={"spend_usd": "Spend (USD)", "channel_label": "Channel"},
            ),
            use_container_width=True,
        )


PAGES = {
    "1.1 Daily calls booked": page_daily_bookings,
    "1.2 Cost per booking": page_cpb,
    "1.3 Bookings trend": page_trend,
    "1.4 Channel attribution": page_attribution,
    "1.5 Time slots": page_time_slots,
    "1.6 Meeting load": page_employee_load,
    "Operations": page_operations,
}

st.sidebar.title("Calendly Marketing Insights")
choice = st.sidebar.radio("Page", list(PAGES))
if not DATA_ROOT.exists():
    st.error("No data found. Run dashboards\\sync_gold.cmd first to download the Gold exports.")
else:
    PAGES[choice]()
    st.sidebar.caption("Data Engineering Project 6 · Krishna C. Mukherjee")
