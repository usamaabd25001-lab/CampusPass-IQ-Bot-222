FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates postgresql-client gnupg fontconfig fonts-noto-core fonts-dejavu-core libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 libjpeg62-turbo libopenjp2-7 \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system bot \
    && adduser --system --ingroup bot bot

COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY . /app
RUN python -m compileall -q app scripts ops alembic \
    && python scripts/verify_v10_railway_turbo.py \
    && python scripts/validate_v10_5_final_hardening.py \
    && python scripts/validate_v10_6_platform_referral.py \
    && python scripts/validate_final_ui_authorization_patch.py \
    && python scripts/validate_v10_7_emergency_stabilization.py \
    && python scripts/validate_v11_1_student_commerce.py \
    && python scripts/validate_v11_2_provider_operations.py \
    && python scripts/validate_v11_3_friends_warranty.py \
    && python scripts/validate_v11_4_owner_commerce.py \
    && python scripts/validate_v11_5_reports_branding_health.py \
    && python scripts/validate_v11_6_render_e2e.py \
    && python scripts/validate_v11_7_lts_turbo.py \
    && python scripts/validate_v11_7_1_all_features.py \
    && rm -rf /app/.pytest_cache /app/.v9_original /app/.v10_before \
    && find /app -type d -name '__pycache__' -prune -exec rm -rf {} + \
    && chown -R bot:bot /app

USER bot
EXPOSE 10000
CMD ["python", "-m", "app.main"]
