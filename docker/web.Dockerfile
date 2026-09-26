FROM nginxinc/nginx-unprivileged:1.27.5-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY site/ /usr/share/nginx/html/
COPY docker/runtime-config.json /usr/share/nginx/html/runtime-config.json
