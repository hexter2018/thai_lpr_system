FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files
COPY package.json ./

# Install dependencies
RUN npm install

# Copy source files
COPY . .

# Build-time frontend env (Vite reads these at build time)
ARG VITE_API_BASE=/api
ARG VITE_MJPEG_BASE=/stream
ARG VITE_STREAM_BASE=/stream
ENV VITE_API_BASE=$VITE_API_BASE
ENV VITE_MJPEG_BASE=$VITE_MJPEG_BASE
ENV VITE_STREAM_BASE=$VITE_STREAM_BASE

# Build
RUN npm run build

# Production stage
FROM nginx:alpine

# Copy built files
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
