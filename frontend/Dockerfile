# Omnicient investigation interface.
# Builds the static bundle, then serves it with Vite's preview server, which
# also proxies /api to the backend container.
FROM node:22-alpine

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

ENV OMNICIENT_API_URL=http://backend:8000
EXPOSE 5173
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "5173"]
