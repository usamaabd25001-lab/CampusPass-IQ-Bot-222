FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates postgresql-client gnupg fontconfig \
       fonts-noto-core fonts-dejavu-core \
       libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
       libjpeg62-turbo libopenjp2-7 \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system bot \
    && adduser --system --ingroup bot bot

COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY . /app

# One release-aware production gate. Historical validators remain available in
# scripts/ for audit, but are not executed here because several pin older
# release identifiers literally and can reject a valid newer release.
RUN python -m compileall -q app scripts ops alembic \
    && python -c "import app, scripts; print('Project package import validation passed')" \
    && python -m scripts.validate_ai_support_integration \
    && python -m scripts.validate_import_architecture \
    && python -m scripts.validate_webapp_contract \
    && python -m scripts.validate_navigation_contract \
    && python -m scripts.validate_ui_public_api \
    && python -m scripts.render_build_verify \
    && rm -rf /app/.pytest_cache /app/.v9_original /app/.v10_before \
    && find /app -type d -name '__pycache__' -prune -exec rm -rf {} + \
    && chown -R bot:bot /app

USER bot
EXPOSE 10000
CMD ["python", "-m", "app.main"]
