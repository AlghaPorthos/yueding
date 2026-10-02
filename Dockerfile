FROM node:22-alpine
WORKDIR /app
COPY package.json sse.mjs demo-api.html demo-api.css demo-api.js setup.html setup.js index.html app.js style.css ./
COPY server ./server
ENV HOST=0.0.0.0 PORT=8787 NODE_ENV=production
USER node
EXPOSE 8787
CMD ["node", "server/index.mjs"]
