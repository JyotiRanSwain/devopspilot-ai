#!/usr/bin/env sh
docker rm -f $(docker ps -aq --filter label=devopspilot.demo=true) 2>/dev/null || true
