#!/usr/bin/env python3
import logging
import sys
from time import sleep
from datetime import datetime

import schedule as schedule
from common import redis


def loop():
    now = datetime.now()
    print(now.hour, now.minute)
    print(redis.get('chat:*'))


if __name__ == '__main__':
    loop()
    # schedule.every().minute.do(loop)
    schedule.every(5).seconds.do(loop)
    while True:
        try:
            schedule.run_pending()
            sleep(1)
        except KeyboardInterrupt:
            logging.info('Shutting down')
            sys.exit(0)
