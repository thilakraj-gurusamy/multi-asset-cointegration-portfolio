# One image, two roles (FRD Section 10): docker-compose.yml runs this same image as both the
# paper-trading scheduler ("app") and the dashboard, distinguished only by the `command:`
# override on each service -- no need for two separate images to maintain.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "pipeline.paper_trading.scheduler"]
