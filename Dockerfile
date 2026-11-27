# For a VPS / your own server (Oracle free VM, a spare PC ...). Each video runs in `docker run --rm`, so the container
# (and everything in it) is deleted when the video is done.   Build:  docker build -t videobot .
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv xvfb openbox ffmpeg espeak-ng wget gnupg ca-certificates \
      fonts-noto-core fonts-noto-color-emoji fonts-liberation fonts-dejavu-core \
    && wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y /tmp/chrome.deb || apt-get install -y chromium \
    && rm -rf /var/lib/apt/lists/* /tmp/chrome.deb
WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir -r requirements.txt
ENV PATH="/venv/bin:$PATH"
COPY . .
# usage:  docker run --rm --shm-size=1g --memory=3g --cpus=2 --network=bridge \
#           -e TELEGRAM_BOT_TOKEN -e GEMINI_API_KEY -v /path/payload.json:/job.json:ro videobot python autovideo.py job /job.json
CMD ["python", "autovideo.py"]
