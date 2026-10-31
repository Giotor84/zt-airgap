# S3 contracts

All paths are under `{PREFIX}`. What matters is **who writes and who reads**; file names inside a folder are free.

| path | content | writer | reader |
|---|---|---|---|
| `records/{id}/record.json` | raw data of one entity | Tier A (PC with internet) | cell 3 |
| `ai_analysis/{id}/analysis_{ts}.json` | model output, numbers overwritten by Python | cell 4 | dashboard, chat |
| `modules/{version}/*.py` + `MANIFEST.json` | runtime code + SHA-256 | `deploy.release` | `deploy.bootstrap` |
| `modules/CURRENT.json` | `{"version": ...}` | `deploy.release` | `deploy.bootstrap` |
| `chat/inbox/{uuid}.json` | `{"request_id","message","filters","timestamp"}` | bridge (Tier C) | listener |
| `chat/outbox/{uuid}.json` | `{"request_id","answer","facts","status","llm"}` | listener | bridge |
| `chat/done/{uuid}.json` | archived request | listener | — |
| `status/{system}/latest.json` | `{"system","state","counts","message","event_time","written_at","batch_id"}` | every pipeline | control dashboard |

## record.json

```json
{
  "entity_id": "E1",
  "attributes": {},
  "metrics_precalc": {},
  "history": []
}
```

`metrics_precalc` holds every number already computed on Tier A or in Python: the model never recomputes them,
and `analysis.post_process` puts them back after the call.

No personal data in `status/` (counts and opaque ids only). Personal data in `records/` should be pseudonymised
before it reaches the model (e.g. with a local PII anonymizer).
