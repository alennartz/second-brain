FROM oven/bun:1.4.4 AS production

WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile --production

COPY src ./src

ENV NODE_ENV=production
ENV BRAIN_DB_PATH=/data/brain.surreal

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8000

CMD ["bun", "run", "src/main.ts"]
