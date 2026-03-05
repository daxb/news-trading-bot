# ── Macro Trader Bot ──────────────────────────────────────────────────────────
# Supports linux/amd64 (x86 VPS) and linux/arm64 (Oracle Ampere / Apple M-series)
FROM python:3.12-slim

# System dependencies
# gcc/g++  — compile C extensions in some Python packages
# libgomp1 — OpenMP runtime required by PyTorch CPU builds
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python dependencies (separate layer so source changes don't re-install) ──
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Pre-download FinBERT (~440 MB, baked into image layer) ───────────────────
# Runs BEFORE copying source so that editing source code doesn't trigger
# a re-download on the next build.
RUN python - <<'EOF'
from transformers import pipeline
pipeline(
    "text-classification",
    model="ProsusAI/finbert",
    truncation=True,
    max_length=512,
)
print("FinBERT cached successfully")
EOF

# ── Application source ────────────────────────────────────────────────────────
COPY . .

# Ensure the data directory exists inside the image
RUN mkdir -p /app/data

# Make startup script executable
RUN chmod +x scripts/start.sh

CMD ["bash", "scripts/start.sh"]
