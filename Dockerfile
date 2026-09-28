FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup --system app && adduser --system --ingroup app app

COPY --chown=app:app . .

RUN chmod +x entrypoint.sh

USER app

EXPOSE 8002

ENTRYPOINT ["./entrypoint.sh"]
