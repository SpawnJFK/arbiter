# Arbiter API + worker image. The same image runs both:
#   API:    default CMD (uvicorn arbiter.api.app:app)
#   worker: command: ["python", "-m", "arbiter.pipeline.worker"]
# Build context: services/api

FROM python:3.13-slim AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
RUN pip install --no-cache-dir uv
WORKDIR /src
# Dependency layer first so code edits do not reinstall everything.
COPY pyproject.toml ./
RUN uv venv /opt/venv \
 && python -c "import tomllib;d=tomllib.load(open('pyproject.toml','rb'));print('\n'.join(d['project']['dependencies']))" > /tmp/req.txt \
 && VIRTUAL_ENV=/opt/venv uv pip install -r /tmp/req.txt
COPY . .
RUN VIRTUAL_ENV=/opt/venv uv pip install --no-deps .

FROM python:3.13-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ARBITER_STORAGE_DIR=/var/lib/arbiter/storage
RUN groupadd --system --gid 10001 arbiter \
 && useradd --system --uid 10001 --gid arbiter --home-dir /app --shell /usr/sbin/nologin arbiter \
 && mkdir -p /var/lib/arbiter/storage \
 && chown -R arbiter:arbiter /var/lib/arbiter
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
# Alembic needs the ini file and the migrations folder next to it.
COPY --chown=arbiter:arbiter alembic.ini ./
COPY --chown=arbiter:arbiter migrations ./migrations
COPY --chown=arbiter:arbiter docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh
USER arbiter
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=4).status==200 else 1)" || exit 1
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "arbiter.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
