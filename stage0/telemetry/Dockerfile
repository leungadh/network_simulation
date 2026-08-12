FROM python:3.12-alpine

WORKDIR /app
COPY syslog_sink.py .

# UDP/514 is privileged, but containers get CAP_NET_BIND_SERVICE by default.
EXPOSE 514/udp

CMD ["python", "-u", "syslog_sink.py"]
