FROM python:3.12-alpine
RUN apk add --no-cache tzdata
WORKDIR /app
COPY feed.py server.py ./
USER 65534:65534
EXPOSE 8767
CMD ["python", "-u", "server.py"]
