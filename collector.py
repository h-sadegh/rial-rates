#!/usr/bin/env python3
"""rial-rates collector.

Fetches current Iranian market rates (USD/EUR/GBP, Emami & half coins, 18k
gram gold, Bitcoin-in-tomans) from public no-key JSON sources and appends a
sample to data/YYYY/MM/DD.json. Also rewrites latest.json at repo root.

Never raises: any failure is logged and the script exits 0 so the GitHub
Actions workflow is never marked red by a flaky upstream.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DATA_ROOT = REPO_ROOT / "data"

# Tehran is UTC+03:30 — fixed offset, no tz database needed.
TEHRAN = timezone(__import__("datetime").timedelta(hours=3, minutes=30))

SOURCES = [
    # (name, url) — all sources attempted; first hit per field wins.
    # Tested 2026-10-28: tgju works (needs curl fallback). brsapi.ir, torob.com
    # (bot-wall) and alanchand.com (DNS fail) are dead — kept out.
    ("tgju", "https://call.tgju.org/ajax.json"),
]

# our key -> list of upstream keys in priority order
FIELDS = {
    "usd_tmn": ["price_dollar_rl", "dollar"],
    "eur_tmn": ["price_eur", "eur"],
    "gbp_tmn": ["price_gbp", "gbp"],
    "emami_coin_tmn": ["sekee", "emami_coin"],
    "half_coin_tmn": ["nim", "half_coin"],
    "gram_gold_18k_tmn": ["geram18", "gold_18k"],
    "btc_tmn": ["crypto-bitcoin-irr", "bitcoin"],
}

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 rial-rates-collector/1.0"
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("collector")


def fetch_json(url: str, timeout: int = 30):
    # urllib first; tgju (and similar sites) sometimes reject Python's TLS/HTTP
    # fingerprint with 410, so fall back to curl which passes.
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        if e.code not in (400, 403, 404, 410, 429, 500, 502, 503):
            raise
        log.warning("urllib blocked (%s); retrying %s with curl", e, url)
        p = subprocess.run(
            ["curl", "-sS", "-m", str(timeout), "--compressed",
             "-A", UA, "-H", "Accept: application/json",
             url],
            capture_output=True, text=True, timeout=timeout + 10,
        )
        if p.returncode != 0:
            raise RuntimeError(f"curl failed rc={p.returncode}: {p.stderr[:200]}")
        return json.loads(p.stdout)


def to_num(raw):
    """tgju prices look like '2,685,000' — strip separators, coerce to int/float."""
    if raw is None:
        return None
    s = str(raw).replace(",", "").strip()
    if not s:
        return None
    try:
        f = float(s)
        return int(f) if f.is_integer() else f
    except ValueError:
        return None


def extract_tgju(payload: dict) -> dict:
    """tgju /ajax.json -> {'current': {key: {p, d, dp, ts, ...}}}"""
    out = {}
    current = (payload or {}).get("current") or {}
    for our_key, candidates in FIELDS.items():
        for cand in candidates:
            item = current.get(cand)
            if not item:
                continue
            price = to_num(item.get("p"))
            if price is None:
                continue
            out[our_key] = {
                "price": price,
                "change_amount": to_num(item.get("d")),
                "change_percent": to_num(item.get("dp")),
                "source_time": item.get("ts") or "",
            }
            break
    return out


def extract_brsapi(payload: dict) -> dict:
    """brsapi /market/json -> {'market': [{'symbol'/'name', 'price', ...}]}"""
    out = {}
    items = (payload or {}).get("market") or []
    symbol_map = {
        "price_dollar_rl": ["usd", "dollar", "price_dollar_rl"],
        "price_eur": ["eur", "price_eur"],
        "price_gbp": ["gbp", "price_gbp"],
        "sekee": ["sekee", "emami", "emami_coin"],
        "nim": ["nim", "half_coin"],
        "geram18": ["geram18", "gold_18k"],
        "crypto-bitcoin-irr": ["btc", "bitcoin"],
    }
    inverse = {c: ours for ours, cands in FIELDS.items() for c in cands}
    for item in items:
        ident = str(item.get("symbol") or item.get("name") or "").lower()
        for brs, ours in inverse.items():
            if ident == brs or ident in [s.lower() for s in symbol_map.get(brs, [])]:
                price = to_num(item.get("price") or item.get("p"))
                if price is not None and ours not in out:
                    out[ours] = {"price": price, "source_time": str(item.get("time") or "")}
    return out


def collect() -> dict | None:
    """Merge fields from all sources; return rates dict or None on total failure."""
    merged: dict = {}
    used_sources = []
    for name, url in SOURCES:
        try:
            payload = fetch_json(url)
        except Exception as exc:  # noqa: BLE001 — must never crash the workflow
            log.warning("source %s failed: %s", name, exc)
            continue
        fields = extract_tgju(payload) if name == "tgju" else extract_brsapi(payload)
        new = {k: v for k, v in fields.items() if k not in merged}
        if new:
            merged.update(new)
            used_sources.append(name)
            log.info("source %s contributed %d fields", name, len(new))
    if not merged:
        return None
    return {"rates": merged, "sources": used_sources}


def day_path(now: datetime) -> Path:
    return DATA_ROOT / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}.json"


def append_sample(path: Path, sample: dict) -> bool:
    """Append sample to a day file; dedupe on the minute bucket. Returns True if written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    day = {"date": path.stem, "samples": []}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("samples"), list):
                day = loaded
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("corrupt day file %s (%s); rewriting", path, exc)
    bucket = sample["fetched_at"][:16]  # 'YYYY-MM-DDTHH:MM' minute bucket
    if any(str(s.get("fetched_at", ""))[:16] == bucket for s in day["samples"]):
        log.info("sample for %s already present; skipping", bucket)
        return False
    day["samples"].append(sample)
    day["samples"].sort(key=lambda s: str(s.get("fetched_at", "")))
    path.write_text(json.dumps(day, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def write_latest(sample: dict) -> None:
    latest = {
        "updated_at": sample["fetched_at"],
        "timezone": "Asia/Tehran",
        "sources": sample["sources"],
        "rates": sample["rates"],
        "history": "data/{year}/{month}/{day}.json",
    }
    (REPO_ROOT / "latest.json").write_text(
        json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    now = datetime.now(TEHRAN)
    result = collect()
    if result is None:
        log.error("no source produced data this run; nothing written")
        return 0  # never fail the workflow
    sample = {
        "fetched_at": now.isoformat(timespec="seconds"),
        "sources": result["sources"],
        "rates": result["rates"],
    }
    try:
        written = append_sample(day_path(now), sample)
        write_latest(sample)
        log.info("done: %d fields, day-file %s", len(sample["rates"]), "updated" if written else "deduped")
    except OSError as exc:
        log.error("failed writing files: %s", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
