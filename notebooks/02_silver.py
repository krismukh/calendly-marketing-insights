# Databricks notebook source
# MAGIC %md
# MAGIC # 02_silver: typed, flattened, deduplicated tables
# MAGIC
# MAGIC Rebuilds the Silver tables from Bronze (full recompute, decision 25). No invitee
# MAGIC personal data (name, email, phone) is carried into Silver (decision 10).
# MAGIC
# MAGIC Tables: `calendly.silver.channel_map`, `calendly.silver.bookings`,
# MAGIC `calendly.silver.meetings`, `calendly.silver.spend`

# COMMAND ----------

from pyspark.sql import Window
from pyspark.sql import functions as F

CATALOG = "calendly"
TZ = "America/New_York"
spark.sql(f"USE CATALOG {CATALOG}")


def save(df, name):
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(name)
    print(f"{name}: {spark.table(name).count()} rows")


# COMMAND ----------

# MAGIC %md ## Channel map (the three campaign event types from the brief)

# COMMAND ----------

channel_map = spark.createDataFrame(
    [
        ("https://api.calendly.com/event_types/79652b8a-1688-4d0b-ba8f-733c70856de4", "facebook_paid_ads"),
        ("https://api.calendly.com/event_types/2b5580c2-13e9-4283-8b4d-56401cf31554", "youtube_paid_ads"),
        ("https://api.calendly.com/event_types/70022cde-e64f-49a0-9362-a815186005dc", "tiktok_paid_ads"),
    ],
    "event_type_uri string, channel string",
).withColumn("campaign", F.col("channel")).withColumn("is_campaign", F.lit(True))
save(channel_map, "silver.channel_map")

# COMMAND ----------

# MAGIC %md ## Bookings: one row per invitee; a canceled event updates the status

# COMMAND ----------

events = spark.table("bronze.calendly_events")

# Keep the latest delivery of each (invitee, event name); repeated deliveries are identical.
w = Window.partitionBy("invitee_uuid", "event_name").orderBy(F.col("received_at_utc").desc())
deduped = events.withColumn("rn", F.row_number().over(w)).filter("rn = 1").drop("rn")

created = deduped.filter("event_name = 'invitee.created'").alias("c")
canceled = (
    deduped.filter("event_name = 'invitee.canceled'")
    .select("invitee_uuid", F.to_timestamp("body.created_at").alias("canceled_at_utc"))
    .alias("x")
)
cmap = spark.table("silver.channel_map").alias("m")

joined = created.join(canceled, "invitee_uuid", "left").join(
    cmap, F.col("c.event_type_uri") == F.col("m.event_type_uri"), "left"
)

p = "c.body.payload"
se = f"{p}.scheduled_event"
tr = f"{p}.tracking"

bookings = joined.select(
    F.col(f"{p}.uri").alias("booking_id"),
    F.col("invitee_uuid"),
    F.col(f"{se}.uri").alias("meeting_id"),
    F.col("c.event_type_uri").alias("event_type_uri"),
    F.col(f"{se}.name").alias("event_type_name"),
    F.coalesce(F.col("m.channel"), F.lit("other")).alias("channel"),
    F.coalesce(F.col("m.is_campaign"), F.lit(False)).alias("is_campaign_booking"),
    F.to_timestamp(F.col(f"{p}.created_at")).alias("booking_ts_utc"),
    F.to_timestamp(F.col(f"{se}.start_time")).alias("meeting_start_ts_utc"),
    F.to_timestamp(F.col(f"{se}.end_time")).alias("meeting_end_ts_utc"),
    F.col(f"{p}.timezone").alias("invitee_timezone"),
    F.col(f"{p}.status").alias("calendly_status"),
    F.col("canceled_at_utc"),
    F.col(f"{p}.rescheduled").cast("boolean").alias("rescheduled"),
    F.col(f"{tr}.utm_source").alias("utm_source"),
    F.col(f"{tr}.utm_medium").alias("utm_medium"),
    F.col(f"{tr}.utm_campaign").alias("utm_campaign"),
    F.col(f"{tr}.utm_content").alias("utm_content"),
    F.col(f"{tr}.utm_term").alias("utm_term"),
    F.col(f"{se}.event_memberships")[0]["user"].alias("host_user_uri"),
    F.col(f"{se}.event_memberships")[0]["user_name"].alias("host_name"),
    F.col("c.received_at_utc").alias("received_at_utc"),
).withColumns(
    {
        "is_canceled": F.col("canceled_at_utc").isNotNull(),
        "status": F.when(F.col("canceled_at_utc").isNotNull(), "canceled").otherwise(F.col("calendly_status")),
        "booking_date": F.to_date(F.from_utc_timestamp("booking_ts_utc", TZ)),
        "meeting_start_local": F.from_utc_timestamp("meeting_start_ts_utc", TZ),
        "updated_at_utc": F.current_timestamp(),
    }
).withColumns(
    {
        "meeting_date": F.to_date("meeting_start_local"),
        "meeting_hour": F.hour("meeting_start_local"),
        "meeting_day_of_week": F.date_format("meeting_start_local", "EEEE"),
        "meeting_day_number": F.dayofweek("meeting_start_local"),  # 1 = Sunday
    }
)
save(bookings, "silver.bookings")

# COMMAND ----------

# MAGIC %md ## Meetings: one row per host per scheduled event (all event types)

# COMMAND ----------

meetings = (
    created.select(
        F.col(f"{se}.uri").alias("meeting_id"),
        F.col(f"{se}.name").alias("event_type_name"),
        F.col("c.event_type_uri").alias("event_type_uri"),
        F.to_timestamp(F.col(f"{se}.start_time")).alias("meeting_start_ts_utc"),
        F.explode(F.col(f"{se}.event_memberships")).alias("m"),
        F.col("invitee_uuid"),
    )
    .join(canceled, "invitee_uuid", "left")
    .select(
        "meeting_id",
        F.col("m.user").alias("employee_id"),
        F.col("m.user_name").alias("host_name"),
        F.col("m.user_email").alias("host_email"),
        "event_type_name",
        "event_type_uri",
        "meeting_start_ts_utc",
        F.col("canceled_at_utc").isNotNull().alias("is_canceled"),
    )
    .withColumn("meeting_start_local", F.from_utc_timestamp("meeting_start_ts_utc", TZ))
    .withColumn("meeting_date", F.to_date("meeting_start_local"))
    .withColumn("meeting_week", F.date_trunc("week", "meeting_start_local").cast("date"))
    .dropDuplicates(["meeting_id", "employee_id"])
)
save(meetings, "silver.meetings")

# COMMAND ----------

# MAGIC %md ## Spend: one row per date and channel; the most recent file wins (decision 9)

# COMMAND ----------

ws = Window.partitionBy("date", "channel").orderBy(F.col("file_date").desc())
spend = (
    spark.table("bronze.spend_files")
    .withColumn("rn", F.row_number().over(ws))
    .filter("rn = 1")
    .select(
        "date",
        "channel",
        F.col("spend").alias("spend_usd"),
        F.col("file_name").alias("source_file"),
        F.col("file_date").alias("source_file_date"),
        F.current_timestamp().alias("updated_at_utc"),
    )
)
save(spend, "silver.spend")

# COMMAND ----------

display(spark.sql("SELECT channel, is_campaign_booking, status, COUNT(*) AS n FROM silver.bookings GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"))
display(spark.sql("SELECT MIN(date) AS first_day, MAX(date) AS last_day, COUNT(*) AS rows, ROUND(SUM(spend_usd), 2) AS total_usd FROM silver.spend"))
