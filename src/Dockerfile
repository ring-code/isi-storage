FROM python:3.11-slim

WORKDIR /app

# copy and install requirements first
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# copy app
COPY . .

# add scripts, make entrypoint executable
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 5050

# set entrypoint for container
ENTRYPOINT ["/app/entrypoint.sh"]
