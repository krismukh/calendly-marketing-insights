# Databricks notebook source
# MAGIC %md
# MAGIC # 03_gold: the six metric tables and the run log
# MAGIC
# MAGIC Recomputes every Gold table from Silver (full overwrite in one Delta transaction each),
# MAGIC appends a row to `gold.pipeline_runs`, and exports CSV copies for the Streamlit
# MAGIC dashboard to `gold/export/` (decision 26).
# MAGIC
# MAGIC Metric definitions: proposal Section 6. Marketing metrics (1.1 to 1.5) use campaign
# MAGIC bookings only; meeting load (1.6) uses all event types (SME, decision 20).

# COMMAND ----------

from pyspark.sql import Window
from pyspark.sql import functions as F

CATALOG = "calendly"
STORAGE = "stcalendlykcm"
EXPORT_ROOT = f"abfss://gold@{STORAGE}.dfs.core.windows.net/export"
spark.sql(f"USE CATALOG {CATALOG}")


def save(df, name):
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(name)
    print(f"{name}: {spark.table(name).count()} rows")


# COMMAND ----------

# MAGIC %md ## 1.1 and 1.3 Daily bookings by channel

# COMMAND ----------

daily = spark.sql("""
    SELECT booking_date AS date, channel,
           COUNT(*) AS bookings,
           SUM(CASE WHEN is_canceled THEN 1 ELSE 0 END) AS canceled,
           COUNT(*) - SUM(CASE WHEN is_canceled THEN 1 ELSE 0 END) AS net_bookings
    FROM silver.bookings
    WHERE is_campaign_booking
    GROUP BY booking_date, channel
""")
save(daily, "gold.daily_bookings_by_channel")

# COMMAND ----------

# MAGIC %md ## 1.2 Daily spend and cost per booking (spend is Day-1; CPB is null when bookings = 0)

# COMMAND ----------

spend_cpb = spark.sql("""
    SELECT COALESCE(s.date, b.date) AS date,
           COALESCE(s.channel, b.channel) AS channel,
           s.spend_usd,
           COALESCE(b.bookings, 0) AS bookings,
           CASE WHEN COALESCE(b.bookings, 0) > 0 THEN ROUND(s.spend_usd / b.bookings, 2) END AS cpb_usd
    FROM silver.spend s
    FULL OUTER JOIN gold.daily_bookings_by_channel b
      ON s.date = b.date AND s.channel = b.channel
""")
save(spend_cpb, "gold.daily_spend_and_cpb")

# COMMAND ----------

# MAGIC %md ## 1.4 Channel attribution (leaderboard over the full period)

# COMMAND ----------

attribution = spark.sql("""
    WITH b AS (
        SELECT channel, COUNT(*) AS total_bookings, MIN(booking_date) AS first_booking, MAX(booking_date) AS last_booking
        FROM silver.bookings WHERE is_campaign_booking GROUP BY channel
    ),
    s AS (
        SELECT channel, ROUND(SUM(spend_usd), 2) AS total_spend_usd, MIN(date) AS first_spend, MAX(date) AS last_spend
        FROM silver.spend GROUP BY channel
    )
    SELECT COALESCE(s.channel, b.channel) AS channel,
           COALESCE(s.channel, b.channel) AS campaign,
           COALESCE(b.total_bookings, 0) AS total_bookings,
           s.total_spend_usd,
           CASE WHEN COALESCE(b.total_bookings, 0) > 0 THEN ROUND(s.total_spend_usd / b.total_bookings, 2) END AS cpb_usd,
           LEAST(COALESCE(b.first_booking, s.first_spend), COALESCE(s.first_spend, b.first_booking)) AS period_start,
           GREATEST(COALESCE(b.last_booking, s.last_spend), COALESCE(s.last_spend, b.last_booking)) AS period_end
    FROM s FULL OUTER JOIN b ON s.channel = b.channel
""")
attribution = attribution.withColumn(
    "rank_by_bookings", F.dense_rank().over(Window.orderBy(F.col("total_bookings").desc()))
).withColumn("rank_by_cpb", F.dense_rank().over(Window.orderBy(F.col("cpb_usd").asc_nulls_last())))
save(attribution, "gold.channel_attribution")

# COMMAND ----------

# MAGIC %md ## 1.5 Booking volume by time slot and day of week (meeting start, Eastern time)

# COMMAND ----------

slots = spark.sql("""
    SELECT channel, meeting_day_number AS day_number, meeting_day_of_week AS day_of_week,
           meeting_hour AS hour, COUNT(*) AS bookings
    FROM silver.bookings
    WHERE is_campaign_booking
    GROUP BY channel, meeting_day_number, meeting_day_of_week, meeting_hour
""")
save(slots, "gold.bookings_by_time_slot")

# COMMAND ----------

# MAGIC %md ## 1.6 Meeting load per employee (all event types, canceled meetings excluded)

# COMMAND ----------

weekly = spark.sql("""
    SELECT employee_id, MAX(host_name) AS host_name, meeting_week AS week_start, COUNT(*) AS meetings
    FROM silver.meetings
    WHERE NOT is_canceled
    GROUP BY employee_id, meeting_week
""")
save(weekly, "gold.employee_weekly_meetings")

load = spark.sql("""
    SELECT employee_id, MAX(host_name) AS host_name,
           SUM(meetings) AS total_meetings,
           COUNT(*) AS weeks_observed,
           ROUND(SUM(meetings) / COUNT(*), 2) AS avg_meetings_per_week,
           MAX(meetings) AS max_week, MIN(meetings) AS min_week
    FROM gold.employee_weekly_meetings
    GROUP BY employee_id
""")
save(load, "gold.employee_meeting_load")

# COMMAND ----------

# MAGIC %md ## Run log and reconciliation

# COMMAND ----------

counts = {
    "bronze_events": spark.table("bronze.calendly_events").count(),
    "bronze_spend_rows": spark.table("bronze.spend_files").count(),
    "silver_bookings": spark.table("silver.bookings").count(),
    "silver_campaign_bookings": spark.table("silver.bookings").filter("is_campaign_booking").count(),
    "silver_meetings": spark.table("silver.meetings").count(),
    "silver_spend_rows": spark.table("silver.spend").count(),
    "gold_daily_rows": spark.table("gold.daily_bookings_by_channel").count(),
}
created_events = spark.table("bronze.calendly_events").filter("event_name = 'invitee.created'").select("invitee_uuid").distinct().count()
counts["reconciled"] = created_events == counts["silver_bookings"]

run = spark.createDataFrame([({k: str(v) for k, v in counts.items()},)], "counts map<string,string>").select(
    F.current_timestamp().alias("run_ts_utc"), F.col("counts")
)
spark.sql("CREATE TABLE IF NOT EXISTS gold.pipeline_runs (run_ts_utc timestamp, counts map<string,string>)")
run.write.format("delta").mode("append").saveAsTable("gold.pipeline_runs")
print(counts)
assert counts["reconciled"], "distinct created invitees in Bronze do not match Silver bookings"

# COMMAND ----------

# MAGIC %md ## CSV export for the Streamlit dashboard

# COMMAND ----------

for table in [
    "daily_bookings_by_channel",
    "daily_spend_and_cpb",
    "channel_attribution",
    "bookings_by_time_slot",
    "employee_weekly_meetings",
    "employee_meeting_load",
]:
    (
        spark.table(f"gold.{table}")
        .coalesce(1)
        .write.mode("overwrite")
        .option("header", "true")
        .csv(f"{EXPORT_ROOT}/{table}")
    )
print("exported to", EXPORT_ROOT)
