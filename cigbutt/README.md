# cigbutt

Refactored standalone cigbutt workflow library in standard `src/` layout.

## Quick start

```bash
uv run --project cigbutt python -m cigbutt --help
```

## CLI examples

```bash
uv run --project cigbutt python -m cigbutt e2e-test \
  --out-csv /tmp/cigbutt-e2e.csv \
  --out-debug-json /tmp/cigbutt-e2e-debug.json \
  --out-trace-json /tmp/cigbutt-e2e-trace.json

uv run --project cigbutt python -m cigbutt scan-market \
  --market HK \
  --limit 30 \
  --out-csv /tmp/cigbutt-hk-candidates.csv \
  --out-all-csv /tmp/cigbutt-hk-all.csv
```

## Python API

```python
from cigbutt import run_market_scan

result = run_market_scan(
    market="US",
    out_csv="/tmp/cigbutt-us-candidates.csv",
    out_all_csv="/tmp/cigbutt-us-all.csv",
    out_debug_json=None,
    out_trace_json=None,
    debug=False,
    limit=30,
    inventory_haircut=0.7,
    dividend_tax_rate=0.1,
    annual_dividend_since_year=2010,
)
print(result["summary"])
```

## DashScope Config

Default config file:

```toml
# ~/.config/cigbutt/config.toml
[dashscope]
api_key = "your-api-key"
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
model = "qwen-3.5-plus"
timeout_seconds = 45
```

Environment variables override file values:

- `DASHSCOPE_API_KEY`
- `DASHSCOPE_BASE_URL`
- `DASHSCOPE_MODEL`
- `DASHSCOPE_TIMEOUT_SECONDS`
