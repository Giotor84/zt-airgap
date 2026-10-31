# zt-airgap

[![tests](https://github.com/Giotor84/zt-airgap/actions/workflows/tests.yml/badge.svg)](https://github.com/Giotor84/zt-airgap/actions/workflows/tests.yml) [![license](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE) ![python](https://img.shields.io/badge/python-3.10%2B-blue)

**In italiano:** modello collaudato di pipeline LLM per ambienti senza internet (SageMaker dietro proxy, Bedrock): codice rilasciato via S3 con manifest SHA-256, numeri calcolati in Python, dashboard HTML offline.

**A tested template for LLM pipelines where the model environment has no internet** — the common case in banks,
insurers and credit servicers running Amazon SageMaker behind a corporate proxy, with Bedrock as the only model
endpoint. Distilled from several production pipelines (document analysis, call analytics, legal spend, auction
data) built on the same platform.

```
[Tier A — PC with internet]        ETL, scraping, enrichment  ──record.json──►  S3
[Tier B — SageMaker, no internet]  modules from S3 → load → Bedrock (via proxy) → HTML dashboard
                                   chat listener: S3 inbox → facts (pandas) + prose (LLM) → S3 outbox
[Tier C — user PC]                 opens the HTML offline; localhost bridge ⇄ S3 for the chat (no LLM here)
```

## What the template enforces

| rule | where |
|---|---|
| **No `pip install`, no CDN on Tier B**: code travels through S3 as a release with a SHA-256 manifest; a partial or tampered upload is refused instead of failing with `ImportError` later | `deploy.release`, `deploy.bootstrap` |
| **Numbers in Python, prose from the LLM**: metrics are computed before the call and written back after it, so a hallucinated number never reaches the dashboard | `analysis.build_prompt`, `analysis.post_process` |
| **One failing record does not stop the batch** and is recorded as an error, not dropped | `analysis.analyse_all` |
| **Bedrock `converse` behind the proxy**, IAM role credentials, empty answers keep `stopReason` and usage | `bedrock` |
| **Chat without a public API**: localhost bridge → S3 inbox → listener → outbox; the bridge never calls the model; facts-only fallback when the model is down | `bridge`, `chat` |
| **Dashboard as one offline HTML file**, light/dark, data embedded safely, no external URLs | `dashboard.render` |
| **Run status for read-only monitoring**, with the real event time and a "silent" check | `status` |
| **Everything testable without AWS**: in-memory S3 and Bedrock fakes | `s3io.FakeS3`, `bedrock.FakeBedrock` |

Contracts between tiers: [docs/SCHEMA.md](docs/SCHEMA.md). Notebook cells for the SageMaker side:
[notebook/pipeline_cells.py](notebook/pipeline_cells.py).

## Quickstart

```bash
pip install -e ".[dev]"
pytest                      # 10 tests, no AWS needed
```

On the dev PC, release the code (all modules together) and copy the two bootstrap files:

```python
import boto3
from pathlib import Path
from zt_airgap import deploy

s3 = boto3.client("s3")
deploy.release(s3, "my-bucket", "myproject/", Path("src").rglob("*.py"), "2026.10.31", root="src")
```

Then run the notebook cells 1 → 3 → 4 → 6 → 7 on SageMaker, and on the user's PC:

```bash
python -m zt_airgap.bridge --bucket my-bucket --prefix myproject/ --port 8765
```

## Lessons that shaped it

- "SageMaker only talks to S3" is imprecise: there is no public internet, but AWS endpoints (S3, Bedrock, SES)
  are reachable through the proxy. Anything that needs the web belongs to Tier A.
- Upload one module without the others and you get an `ImportError` in front of the business user. Release as
  a unit, verify on load.
- Most "model errors" in extraction were prompt errors. Keep prompts and schemas versioned and A/B-test changes
  on live data before switching.
- Read-only monitoring found the real problems: pipelines silently stopped for weeks because an upstream input
  was no longer regenerated.

## Professional services

I help teams design and run these pipelines (document AI, call analytics, portfolio dashboards) inside closed
environments, with PII protection and honest evaluation. Contact via my [GitHub profile](https://github.com/Giotor84).

## Known limits

- A template, not a framework: the S3 and Bedrock fakes cover the contracts between tiers, not every AWS error.
- Tier B assumes a SageMaker environment where S3 and Bedrock are reachable through the proxy; other platforms need their own adapters.
- The chat goes through files on S3 (inbox and outbox): it is meant for questions on a dashboard, not for low-latency use.

## Related projects

- [zt-anchor](https://github.com/Giotor84/zt-anchor) — anchoring, abstention and frozen-holdout evaluation for document AI
- [zt-legal-analysis-core](https://github.com/Giotor84/zt-legal-analysis-core) — OCR cascade and rolling synthesis for case files larger than the context
- [zt-legal-graph](https://github.com/Giotor84/zt-legal-graph) — local, source-anchored drafting for Italian civil cases
- [zt-backtest](https://github.com/Giotor84/zt-backtest) — honest forecast evaluation with blind windows
- All projects: [github.com/Giotor84](https://github.com/Giotor84)

## License

Apache-2.0 — see [LICENSE](LICENSE).
