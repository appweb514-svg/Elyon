FROM node:22-slim

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@10 --activate

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . ./

RUN pnpm build

EXPOSE 3000

CMD ["pnpm", "exec", "next", "start", "--port", "3000", "--hostname", "0.0.0.0"]
