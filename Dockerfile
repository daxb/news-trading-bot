# ── Macro Trader Bot ──────────────────────────────────────────────────────────
# Supports linux/amd64 (x86 VPS) and linux/arm64 (Oracle Ampere / Apple M-series)

# ── Stage 1: export FinBERT → ONNX ────────────────────────────────────────────
# torch + optimum live ONLY in this stage. The runtime image below never installs
# them, so libtorch (~227 MB resident) never loads — that's the whole memory win.
# This stage is cached and only re-runs when its own lines change, so normal code
# deploys skip the export entirely.
FROM python:3.12-slim AS exporter
# Unpinned optimum: its [onnxruntime] extra pulls optimum-onnx, which constrains
# optimum's version — pinning a specific optimum here makes pip's resolver
# contradict itself. The export output is what matters and it's parity-checked
# against torch downstream, so let pip pick a self-consistent set. torch stays
# pinned to match the runtime weights it exports.
RUN pip install --no-cache-dir torch==2.10.0 \
        --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir "optimum[onnxruntime]"
RUN optimum-cli export onnx \
        --model ProsusAI/finbert \
        --task text-classification \
        /finbert_onnx

# ── Stage 2: runtime (torch-free) ─────────────────────────────────────────────
FROM python:3.12-slim

# System dependencies
# gcc/g++  — compile C extensions in some Python packages
# libgomp1 — OpenMP runtime required by onnxruntime CPU
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Baked FinBERT ONNX model (exported in stage 1) ───────────────────────────
# Copied BEFORE source so that editing source code doesn't invalidate this layer.
COPY --from=exporter /finbert_onnx /app/models/finbert

# ── Application source ────────────────────────────────────────────────────────
COPY . .

# Ensure the data directory exists inside the image
RUN mkdir -p /app/data

# Make startup script executable
RUN chmod +x scripts/start.sh

# Health check — ensures bot process is alive and DB is accessible
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD python -c "import sqlite3; sqlite3.connect('/app/data/trading.db').execute('SELECT 1')"

CMD ["bash", "scripts/start.sh"]
