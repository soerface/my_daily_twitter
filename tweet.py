#!/usr/bin/env python3
import logging
import sys
from time import sleep
from datetime import datetime

import schedule as schedule
from common import redis


def loop():
    now = datetime.now()
    for key in redis.keys('*:settings:post_time'):
        key = key.decode()
        chat_id = key.split(':')[1]
        desired_time = redis.get(key).split(b':')
        desired_hour = int(desired_time[0])
        desired_minute = int(desired_time[1])
        if desired_hour != now.hour or desired_minute != now.minute:
            pass  # continue
        queue_size = redis.get(f'chat:{chat_id}:queue_size') or 0
        queue_size = int(queue_size)
        if queue_size <= 0:
            continue
        queue_size -= 1
        tweet_text = redis.get(f'chat:{chat_id}:queue:{queue_size}:text')
        tg_attachment_id = redis.get(f'chat:{chat_id}:queue:{queue_size}:tg_attachment_id')
        print(tweet_text, tg_attachment_id)
        # redis.set(f'chat:{chat_id}:queue_size', queue_size)


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
