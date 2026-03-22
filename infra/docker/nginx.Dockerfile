FROM nginx:1.27-alpine
COPY infra/nginx/alaya-enrollment.conf /etc/nginx/conf.d/default.conf
