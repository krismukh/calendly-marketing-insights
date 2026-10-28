# Databricks notebook source
# MAGIC %md
# MAGIC # 01_bronze: landing files to Bronze Delta tables
# MAGIC
# MAGIC Reads every file in the Bronze landing zone and rebuilds the two Bronze Delta tables.
# MAGIC Full rebuild from the retained landing files is idempotent and, at this volume
# MAGIC (tens of events per day, 30 spend files), takes seconds (decision 25).
# MAGIC
# MAGIC Tables: `calendly.bronze.calendly_events`, `calendly.bronze.spend_files`

# COMMAND ----------

from pyspark.sql import functions as F

STORAGE = "stcalendlykcm"
BRONZE_ROOT = f"abfss://bronze@{STORAGE}.dfs.core.windows.net"
CALENDLY_LANDING = f"{BRONZE_ROOT}/calendly/landing"
SPEND_LANDING = f"{BRONZE_ROOT}/spend/landing"
CATALOG = "calendly"

spark.sql(f"USE CATALOG {CATALOG}")

# COMMAND ----------

# MAGIC %md ## Calendly events

# COMMAND ----------

events = (
    spark.read.option("multiLine", "true")
    .json(f"{CALENDLY_LANDING}/*/*/*/*.json")
    .withColumn("landing_path", F.col("_metadata.file_path"))
    .withColumn("ingested_at_utc", F.current_timestamp())
    .withColumn("received_at_utc", F.to_timestamp("received_at_utc"))
)

(
    events.write.format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable("bronze.calendly_events")
)
print("bronze.calendly_events:", spark.table("bronze.calendly_events").count(), "rows")

# COMMAND ----------

# MAGIC %md ## Spend files

# COMMAND ----------

spend = (
    spark.read.option("multiLine", "true")
    .json(f"{SPEND_LANDING}/*.json")
    .withColumn("file_name", F.col("_metadata.file_name"))
    .withColumn("file_date", F.to_date(F.regexp_extract("file_name", r"(\d{4}-\d{2}-\d{2})", 1)))
    .withColumn("date", F.to_date("date"))
    .withColumn("spend", F.col("spend").cast("double"))
    .withColumn("ingested_at_utc", F.current_timestamp())
    .select("file_name", "file_date", "date", "channel", "spend", "ingested_at_utc")
)

(
    spend.write.format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable("bronze.spend_files")
)
print("bronze.spend_files:", spark.table("bronze.spend_files").count(), "rows")
display(spark.sql("SELECT file_date, COUNT(*) AS records FROM bronze.spend_files GROUP BY 1 ORDER BY 1 DESC LIMIT 5"))
