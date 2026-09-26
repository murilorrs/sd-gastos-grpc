# Frontend em dois estágios: o Node compila, o nginx serve.
#
# A imagem final não tem Node nem node_modules — só os arquivos estáticos do
# build e o nginx que os publica e repassa /api para o Gateway. É o mesmo
# arranjo da vm-client no GCP.

FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --silent
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# No compose o Gateway é alcançado pelo nome do serviço, não por IP.
COPY docker-nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
