from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status

import config
from api.deps import read_only_connection, require_permission
from api.routes.stocks import disposition_detail
from api.schemas import success_response

router = APIRouter(tags=["ai-analysis"])
ROOT = Path(__import__("os").environ.get("DISPOSITION_AI_ROOT", "/data/appdata/disposition-pwa/ai-analysis"))
SKILL_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0.0"

def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds")

def _base(market: str, stock_id: str, disposition_id: str) -> Path:
    return ROOT / market / stock_id / disposition_id

def _report(snapshot: dict, provider: str, generated: str, analysis_id: str, digest: str) -> str:
    s = snapshot["data"]; stock = s["stock"]; disp = s["disposition"]
    sections = ["分析摘要", "強勢原因", "籌碼面", "法人進出", "券商分點", "大戶與散戶持股", "基本面", "營收趨勢", "財報與獲利", "公司自結資料", "題材面", "技術面", "處置期間觀察", "正面因素", "風險因素", "資料不足與限制", "結論"]
    text = [
        "---", f'analysis_id: "{analysis_id}"', f'market: "{stock["market"]}"',
        f'stock_id: "{stock["stock_id"]}"', f'stock_name: "{stock["stock_name"]}"',
        f'disposition_id: "{disp["id"]}"', f'provider: "{provider}"',
        f'skill_version: "{SKILL_VERSION}"', f'snapshot_hash: "sha256:{digest}"',
        f'data_as_of: "{snapshot["meta"]["as_of_date"]}"', f'generated_at: "{generated}"',
        "---", f'# {stock["stock_name"]}（{stock["stock_id"]}）AI 分析'
    ]
    text += [f"## {title}\n目前資料快照未包含足夠的完整資料，僅能依現有 VeriStockDB 快照整理；不得據此推論未提供的數字。" for title in sections]
    text.append("\n---\n\n本內容為資料整理與模型解讀，不構成投資建議。")
    return "\n\n".join(text) + "\n"

def _run_codex(snapshot_path: Path, output_path: Path) -> str:
    skill = Path(__file__).resolve().parents[2] / "skills/disposition-stock-analysis/SKILL.md"
    prompt = f"""請先閱讀共用 Skill：{skill}，再分析同一目錄的 snapshot.json。只輸出 Skill 規定的 Markdown 正文，不要輸出 YAML front matter。只能使用 snapshot.json，不得編造資料。"""
    try:
        completed = subprocess.run([
            "/home/timewu/.local/bin/codex", "exec", "-s", "read-only", "--ephemeral", "--skip-git-repo-check",
            "-C", str(snapshot_path.parent), "-o", str(output_path), prompt,
        ], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=503, detail=f"Codex provider unavailable: {exc}") from exc
    if completed.returncode != 0 or not output_path.exists() or not output_path.read_text().strip():
        log = Path("/srv/veristockdb/logs/ai-analysis.log")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text((completed.stderr or completed.stdout or "empty Codex output")[-8000:])
        raise HTTPException(status_code=503, detail=f"Codex provider failed (exit={completed.returncode}); see ai-analysis.log")
    return output_path.read_text()

@router.get("/stocks/{market}/{stock_id}/ai-analyses/latest")
def latest(market: str, stock_id: str, disposition_id: str = Query(...), _: None = Depends(require_permission("read"))):
    path = _base(market, stock_id, disposition_id) / "latest.json"
    if not path.exists(): return success_response({"status": "not_found"})
    info = json.loads(path.read_text())
    report = path.parent / info["relative_path"]
    return success_response({**info, "status": "completed", "markdown": report.read_text()})

@router.get("/stocks/{market}/{stock_id}/ai-analyses")
def history(market: str, stock_id: str, disposition_id: str = Query(...), _: None = Depends(require_permission("read"))):
    path = _base(market, stock_id, disposition_id) / "history.json"
    return success_response(json.loads(path.read_text()) if path.exists() else {"items": []})

@router.post("/stocks/{market}/{stock_id}/ai-analyses")
def create(market: str, stock_id: str, body: dict, _: None = Depends(require_permission("read")), conn: sqlite3.Connection = Depends(read_only_connection)):
    disposition_id = str(body.get("disposition_id") or "").strip()
    if not disposition_id: raise HTTPException(status_code=400, detail="disposition_id is required")
    snapshot = disposition_detail(market, stock_id, disposition_id, None, conn, __import__("api.routes.stocks", fromlist=["_taipei_today"])._taipei_today())
    raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str).encode(); digest = hashlib.sha256(raw).hexdigest()
    root = _base(market, stock_id, disposition_id); root.joinpath("work").mkdir(parents=True, exist_ok=True); root.joinpath("analyses").mkdir(exist_ok=True)
    generated = _now(); analysis_id = generated.replace("-", "").replace(":", "").replace("+08:00", "") + "-codex"; folder = root / "analyses" / analysis_id; folder.mkdir()
    (folder / "snapshot.json").write_bytes(raw)
    markdown = _run_codex(folder / "snapshot.json", folder / "result.tmp.md")
    (folder / "analysis.md").write_text(markdown)
    (folder / "metadata.json").write_text(json.dumps({"analysis_id": analysis_id, "provider": "codex", "snapshot_hash": f"sha256:{digest}", "generated_at": generated, "status": "completed"}, ensure_ascii=False, indent=2))
    info = {"analysis_id": analysis_id, "generated_at": generated, "provider": "codex", "data_as_of": snapshot["meta"]["as_of_date"], "relative_path": f"analyses/{analysis_id}/analysis.md"}
    root.joinpath("latest.json").write_text(json.dumps(info, ensure_ascii=False, indent=2)); root.joinpath("history.json").write_text(json.dumps({"items": [info]}, ensure_ascii=False, indent=2))
    return success_response({"status": "completed", **info, "markdown": markdown})
