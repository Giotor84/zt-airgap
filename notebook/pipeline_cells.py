# Notebook cells for the air-gapped SageMaker side (open with Jupytext, or copy each "# %%" block into a cell).
# Order: 1 -> 3 -> 4 -> 6 -> 7. Shortcut after a UI change only: 1 -> 3 -> 6.

# %% Cell 1 — bootstrap: boto3 via IAM role, proxy, runtime modules from S3 (no pip install here)
import os
import boto3

BUCKET = os.environ.get("AIRGAP_BUCKET", "my-bucket")
PREFIX = os.environ.get("AIRGAP_PREFIX", "myproject/")
MODEL_ID = os.environ.get("AIRGAP_MODEL_ID", "<model-enabled-in-your-account>")
# os.environ["AIRGAP_PROXY"] = "proxy.example.internal:3128"   # your corporate proxy, host:port

s3 = boto3.client("s3")
# On the dev PC, once per release:
#   deploy.release(s3, BUCKET, PREFIX, Path('src').rglob('*.py'), '2026.10.31', root='src')
#   and copy src/zt_airgap/s3io.py + deploy.py to s3://BUCKET/PREFIX/bootstrap/ (they bootstrap everything else).
import sys, tempfile, pathlib
_boot = pathlib.Path(tempfile.mkdtemp())
for name in ("s3io.py", "deploy.py"):
    (_boot / name).write_bytes(s3.get_object(Bucket=BUCKET, Key=f"{PREFIX}bootstrap/{name}")["Body"].read())
sys.path.insert(0, str(_boot))
import deploy  # noqa: E402

deploy.bootstrap(s3, BUCKET, PREFIX)  # verifies SHA-256 of every module of the current release
from zt_airgap import analysis, bedrock, chat, dashboard, status  # noqa: E402

bedrock_runtime = bedrock.make_client()

# %% Cell 3 — load records written by Tier A
records = analysis.load_records(s3, BUCKET, PREFIX)
print(len(records), "records")

# %% Cell 4 — per-entity analysis (numbers stay those computed in Python)
results = analysis.analyse_all(s3, BUCKET, PREFIX, bedrock_runtime, MODEL_ID, records)
status.write_status(s3, BUCKET, PREFIX, "analysis", "ok" if all(r["status"] == "ok" for r in results.values()) else "warning",
                    counts={"records": len(results), "errors": sum(r["status"] != "ok" for r in results.values())})

# %% Cell 6 — standalone dashboard
rows = [{"entity_id": k, **records[k].get("metrics_precalc", {}), "status": v["status"],
         "summary": v.get("summary", "")} for k, v in results.items()]
page = dashboard.render("My project", {"records": len(rows)}, rows, ["entity_id", "status", "summary"])
pathlib.Path.home().joinpath("dashboard.html").write_text(page, encoding="utf-8")

# %% Cell 7 — chat listener: facts from pandas, prose from the model
import pandas as pd  # noqa: E402

df = pd.DataFrame([{"entity_id": k, **r.get("metrics_precalc", {})} for k, r in records.items()])


def tool(message, filters):
    return {"records": int(len(df)), "totals": df.select_dtypes("number").sum().round(2).to_dict()}


chat.run_listener(s3, BUCKET, PREFIX, tool, bedrock_runtime, MODEL_ID, max_idle_minutes=60)
