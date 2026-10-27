FROM oven/bun:1.4.4 AS production

WORKDIR /app

ENV PI_CODING_AGENT_DIR=/opt/pi/agent

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile --production

COPY src ./src
COPY packages ./packages
COPY --chown=1000:1000 config/pi /opt/pi/agent

ENV NODE_ENV=production
ENV BRAIN_DB_PATH=/data/brain.surreal

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8000

HEALTHCHECK --interval=5s --timeout=3s --start-period=15s --retries=3 \
  CMD curl --fail --silent http://127.0.0.1:8000/health || exit 1

CMD ["bun", "run", "src/main.ts"]
