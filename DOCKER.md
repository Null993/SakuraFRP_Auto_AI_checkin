# Docker deployment

This image runs one long-lived scheduler process. Each day it picks one random
second in the configured window, sleeps until then, and runs `main.py --both`.

## 1. Prepare runtime files

Create a `data` directory beside `docker-compose.yml`:

```bash
mkdir -p data
cp env.example data/.env
```

Create `data/account.txt`:

```text
your_username
your_password
```

Edit `data/.env` and set at least:

```env
ZHIPU_API_KEY=your_api_key_here
ZHIPU_MODEL_VISION=glm-4v-flash
ZHIPU_MODEL_TEXT=glm-4-flash

# Option A: pick a random time from 07:30:00 to 08:30:59.
SCHEDULE_TIME=08:00
SCHEDULE_WINDOW_MINUTES=30

# Option B: use an explicit time range instead of SCHEDULE_TIME.
# CHECKIN_WINDOW_START=07:30
# CHECKIN_WINDOW_END=08:30

HTTP_PROXY=
```

## 2. Build and run

```bash
docker compose up -d --build
```

View scheduler and check-in output:

```bash
docker compose logs -f
```

The mounted `data` directory stores `.env`, `account.txt`, `state.json`,
`logs/`, screenshots, random time files, and daily execution locks.

## 3. NAS notes

On a NAS, upload this project directory, create the `data` directory as above,
then start it with the NAS Docker/Container Manager UI or with
`docker compose up -d --build`.

Keep `TZ=Asia/Shanghai` unless your NAS uses another timezone.
