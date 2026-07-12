FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dev tooling (pytest, ruff, the factories) is a liability in production: more code to be
# vulnerable, and it parks a test suite that can mint superusers next to real money. Dev
# and CI build with INSTALL_DEV=1; the production build does not.
ARG INSTALL_DEV=1

COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements.txt \
    && if [ "$INSTALL_DEV" = "1" ]; then pip install -r requirements-dev.txt; fi

COPY . .

# Run as a nobody. Root in the container is one bad mount away from root on the box, so
# a bug that gets code execution should not also get privileges. It costs nothing.
#
# The app writes nothing into its own tree (static files are collected to a volume), so
# it does not need to own /app — which is also what lets the container run read_only.
RUN useradd --system --create-home --uid 10001 wifios \
    && chown -R wifios:wifios /app
USER wifios

EXPOSE 8000

# Compose overrides this in every environment; it is the safe default if it does not.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
