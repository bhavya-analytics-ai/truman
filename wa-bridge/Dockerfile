FROM ghcr.io/puppeteer/puppeteer:latest

WORKDIR /app

# Copy bridge files (Docker build context = repo root)
COPY --chown=pptruser:pptruser wa-bridge/package.json ./wa-bridge/
COPY --chown=pptruser:pptruser wa-bridge/index.js ./wa-bridge/
COPY --chown=pptruser:pptruser truman/integrations/whatsapp_bridge.js ./truman/integrations/

RUN cd wa-bridge && npm install

WORKDIR /app/wa-bridge

CMD ["node", "index.js"]
