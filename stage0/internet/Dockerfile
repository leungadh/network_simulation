FROM nginx:1.27-alpine

# iproute2 is needed to install the return route via cSRX. Without it the
# server receives requests from 10.10.x.x and has no idea how to reply.
# tcpdump: nginx's access_log only records COMPLETED requests, so it cannot
# distinguish 'no packets arrived' from 'handshake never finished'.
RUN apk add --no-cache iproute2 ethtool tcpdump

COPY nginx.conf /etc/nginx/nginx.conf
COPY entrypoint.sh /entrypoint.sh
COPY site/ /usr/share/nginx/html/

# Fixed-size payloads so flows have varied, predictable byte counts.
RUN dd if=/dev/urandom of=/usr/share/nginx/html/medium.bin bs=1k count=256 2>/dev/null \
 && dd if=/dev/urandom of=/usr/share/nginx/html/large.bin  bs=1M count=4   2>/dev/null \
 && chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
