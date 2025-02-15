FROM python:3.12-alpine

RUN apk update

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /backend

COPY ./app ./app
COPY ./migrations ./migrations
COPY ./app/google-services.json ./
COPY ./pyproject.toml ./
COPY ./.python-version ./
COPY ./uv.lock ./

RUN uv pip compile pyproject.toml --output-file requirements.txt
RUN uv pip install --system --no-cache -r requirements.txt
