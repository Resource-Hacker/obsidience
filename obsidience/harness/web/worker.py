"""Disposable DDGS search worker; stdin and stdout are one JSON envelope."""

from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        query = str(request["query"])
        limit = max(1, min(int(request["limit"]), 8))
        from ddgs import DDGS

        results = DDGS(timeout=10).text(
            query,
            region="us-en",
            safesearch="moderate",
            max_results=limit,
            backend="auto",
        )
        print(json.dumps({"ok": True, "results": results}, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001 - parent receives one bounded failure
        print(json.dumps({"ok": False, "error": str(exc)[:500]}))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
