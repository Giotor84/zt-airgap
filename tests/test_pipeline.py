import json
import re
import sys
import threading
from datetime import datetime, timedelta, timezone

import pytest

from zt_airgap import analysis, bridge, chat, dashboard, deploy, status
from zt_airgap.bedrock import EmptyResponse, FakeBedrock, converse_json, converse_text
from zt_airgap.s3io import FakeS3, get_json, list_keys, put_json

B, P = "bucket", "demo/"


def _records(s3):
    for i, (gbv, paid) in enumerate([(100000, 12000), (250000, 0)], 1):
        put_json(s3, B, f"{P}records/E{i}/record.json", {
            "entity_id": f"E{i}", "attributes": {"segment": "secured" if i == 1 else "unsecured"},
            "metrics_precalc": {"exposure": gbv, "paid_12m": paid, "recovery_rate_pct": round(100 * paid / gbv, 1)},
        })


def test_release_and_bootstrap_verify_hashes(tmp_path):
    s3 = FakeS3()
    mod = tmp_path / "metriche_demo.py"
    mod.write_text("def double(x):\n    return 2 * x\n")
    deploy.release(s3, B, P, [mod], "2026.10.31")
    target = deploy.bootstrap(s3, B, P, tmp_path / "loaded")
    import importlib
    assert importlib.import_module("metriche_demo").double(21) == 42
    sys.path.remove(str(target))
    s3.put_object(Bucket=B, Key=f"{P}modules/2026.10.31/metriche_demo.py", Body=b"def double(x): return 0\n")
    with pytest.raises(deploy.ReleaseMismatch):
        deploy.bootstrap(s3, B, P, tmp_path / "loaded2")


def test_analysis_overwrites_hallucinated_numbers_and_records_failures():
    s3 = FakeS3()
    _records(s3)

    def model(prompt):
        if '"E2"' in prompt or "unsecured" in prompt:
            return "sorry, I cannot"  # not JSON: the record must be marked as error, not dropped
        return '```json\n{"summary": "Paying.", "risks": [], "recommendations": ["keep"], ' \
               '"qualitative_score": "low", "metrics": {"recovery_rate_pct": 99}}\n```'

    fb = FakeBedrock(model)
    res = analysis.analyse_all(s3, B, P, fb, "model-x")
    assert res["E1"]["status"] == "ok" and res["E1"]["metrics"]["recovery_rate_pct"] == 12.0
    assert res["E2"]["status"] == "error"
    assert "Do not compute new numbers" in fb.calls[0]["messages"][0]["content"][0]["text"]
    assert len(list(list_keys(s3, B, f"{P}ai_analysis/"))) == 2


def _tool(message, filters):
    return {"records": 2, "total_exposure": 350000}


def test_chat_numbers_from_tool_prose_from_llm():
    s3 = FakeS3()
    put_json(s3, B, f"{P}chat/inbox/r1.json", {"request_id": "r1", "message": "How much exposure?"})
    fb = FakeBedrock(lambda p: "Total exposure is 350000 across 2 records.")
    assert chat.process_inbox(s3, B, P, _tool, fb, "model-x") == 1
    out = get_json(s3, B, f"{P}chat/outbox/r1.json")
    assert out["facts"]["total_exposure"] == 350000 and out["llm"] is True
    assert not list(list_keys(s3, B, f"{P}chat/inbox/")) and list(list_keys(s3, B, f"{P}chat/done/"))


def test_chat_without_llm_falls_back_to_facts():
    out = chat.answer("q", {}, _tool, bedrock=None)
    assert json.loads(out["answer"])["records"] == 2 and out["llm"] is False


def test_bridge_relay_round_trip():
    s3 = FakeS3()
    stop = threading.Event()

    def listener():
        while not stop.is_set():
            chat.process_inbox(s3, B, P, _tool)

    t = threading.Thread(target=listener, daemon=True)
    t.start()
    try:
        out = bridge.relay(s3, B, P, "hello", timeout_s=5, poll_s=0.05)
    finally:
        stop.set()
        t.join(2)
    assert out["status"] == "done" and out["facts"]["records"] == 2


def test_bridge_timeout_when_no_listener():
    out = bridge.relay(FakeS3(), B, P, "hello", timeout_s=0.2, poll_s=0.05)
    assert out["status"] == "timeout"


def test_dashboard_is_offline_and_escapes_script():
    page = dashboard.render("Demo", {"records": 2}, [{"entity_id": "E1", "note": "</script><b>x"}],
                           ["entity_id", "note"])
    urls = set(re.findall(r"https?://[^\s'\"<>)]+", page))
    assert urls == {"http://127.0.0.1:8765/chat"}
    assert "</script><b>" not in page.split('<script id="data"')[1].split("</script>")[0]


def test_status_and_silence():
    s3 = FakeS3()
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds")
    doc = status.write_status(s3, B, P, "scraper", "ok", counts={"files": 12}, event_time=old)
    assert ":" not in doc["batch_id"] and status.is_silent(doc, max_age_hours=48)
    with pytest.raises(ValueError):
        status.write_status(s3, B, P, "scraper", "fine")


def test_empty_bedrock_response_keeps_stop_reason():
    class Empty:
        def converse(self, **kw):
            return {"output": {"message": {"content": []}}, "stopReason": "max_tokens", "usage": {"outputTokens": 0}}

    with pytest.raises(EmptyResponse) as e:
        converse_text(Empty(), "m", "p")
    assert e.value.stop_reason == "max_tokens"
    assert converse_json(FakeBedrock(lambda p: 'Here: {"a": 1} ok'), "m", "p") == {"a": 1}


def test_release_package_folder_and_flat_bootstrap(tmp_path):
    from pathlib import Path
    s3 = FakeS3()
    src = Path(__file__).resolve().parents[1] / "src"
    deploy.release(s3, B, P, sorted(src.rglob("*.py")), "v1", root=src)
    keys = set(get_json(s3, B, f"{P}modules/v1/MANIFEST.json")["files"])
    assert "zt_airgap/chat.py" in keys and "zt_airgap/__init__.py" in keys
    target = deploy.bootstrap(s3, B, P, tmp_path / "mods")
    assert (target / "zt_airgap" / "bridge.py").is_file()
    sys.path.remove(str(target))


def test_parse_json_handles_trailing_braces_in_prose_and_arrays():
    from zt_airgap.bedrock import parse_json
    assert parse_json('{"ok": true, "importo": 100}\nNota: campo {extra} omesso.') == {"ok": True, "importo": 100}
    assert parse_json('Ecco la lista:\n[{"id": 1}]\nFine {nota}.') == [{"id": 1}]
