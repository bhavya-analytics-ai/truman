FROM ghcr.io/puppeteer/puppeteer:latest

WORKDIR /app

COPY --chown=pptruser:pptruser package.json ./
RUN npm install
COPY --chown=pptruser:pptruser index.js whatsapp_bridge.js ./

CMD ["node", "index.js"]
