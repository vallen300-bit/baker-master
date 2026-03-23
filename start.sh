#!/bin/bash
# Baker start script

exec uvicorn outputs.dashboard:app --host 0.0.0.0 --port $PORT
