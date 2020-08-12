#!/usr/bin/env python3
import logging
import os
import sys
import threading
from time import sleep
from datetime import datetime

import tweepy

from common import redis, get_twitter_api, telegram_updater, FILE_STORAGE_PATH, build_tweet_url

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.getLevelName(os.environ.get('LOG_LEVEL', 'INFO')))


def run_threaded(job_func):
    job_thread = threading.Thread(target=job_func)
    job_thread.start()


def loop():
    now = datetime.now()
    logging.debug(f'Running with timestamp {now}')
    for key in redis.keys('*:settings:tweet_time'):
        key = key.decode()
        chat_id = key.split(':')[1]
        desired_time = redis.get(key).split(b':')
        desired_hour = int(desired_time[0])
        desired_minute = int(desired_time[1])
        if desired_hour != now.hour or desired_minute != now.minute:
            continue
        queue_size = redis.get(f'chat:{chat_id}:queue_size') or 0
        queue_size = int(queue_size)
        if queue_size <= 0:
            continue
        queue_size -= 1
        tweet_text = redis.get(f'chat:{chat_id}:queue:{queue_size}:text')
        if tweet_text is not None:
            tweet_text = tweet_text.decode()
        tg_attachment_id = redis.get(f'chat:{chat_id}:queue:{queue_size}:tg_attachment_id')
        if tg_attachment_id is not None:
            tg_attachment_id = tg_attachment_id.decode()

        twitter = get_twitter_api(chat_id)

        if not tg_attachment_id:
            try:
                status = twitter.update_status(tweet_text)
            except tweepy.error.TweepError as e:
                logging.warning(f'Unable to tweet for chat:{chat_id}:queue:{queue_size} (without attachment)')
                telegram_updater.bot.send_message(chat_id=chat_id, text=e.reason)
                telegram_updater.bot.send_message(chat_id=chat_id, text='Sorry, I was unable to post your daily tweet. '
                                                                        'This is your tweet:')
                telegram_updater.bot.send_message(chat_id=chat_id, text=tweet_text)
                telegram_updater.bot.send_message(chat_id=chat_id,
                                                  text='You may delete it from the queue: /delete_last')
                return
        else:
            # download telegram photo
            logging.debug('Downloading telegram attachment')
            file = telegram_updater.bot.getFile(tg_attachment_id)
            filename = FILE_STORAGE_PATH / tg_attachment_id
            file.download(filename)

            try:
                status = twitter.update_with_media(filename, tweet_text)
            except tweepy.error.TweepError as e:
                logging.warning(f'Unable to tweet for chat:{chat_id}:queue:{queue_size} (with attachment)')
                telegram_updater.bot.send_message(chat_id=chat_id, text=e.reason)
                telegram_updater.bot.send_message(chat_id=chat_id,
                                                  text='Sorry, I was unable to post your daily tweet. '
                                                       'This is your tweet, and it contained one attachment:')
                telegram_updater.bot.send_message(chat_id=chat_id, text=tweet_text)
                telegram_updater.bot.send_message(chat_id=chat_id,
                                                  text='You may delete it from the queue: /delete_last')
                return
            finally:
                filename.unlink(missing_ok=True)
        logging.debug('Deleting stored tweet and attachment id')
        redis.delete(f'chat:{chat_id}:queue:{queue_size}:text')
        redis.delete(f'chat:{chat_id}:queue:{queue_size}:tg_attachment_id')

        tweet_url = build_tweet_url(status)
        logging.info(f'Tweeted: {tweet_url} for chat_id {chat_id}')
        telegram_updater.bot.send_message(chat_id=chat_id, text=f'I just tweeted this: {tweet_url}\n'
                                                                f'\n'
                                                                f'Tweets in queue: {queue_size}')
        if queue_size <= 0:
            telegram_updater.bot.send_message(chat_id=chat_id, text="Your queue is now empty. I will not tweet "
                                                                    "tomorrow if you won't give me new stuff!")
        redis.set(f'chat:{chat_id}:queue_size', queue_size)


if __name__ == '__main__':
    FILE_STORAGE_PATH.mkdir(parents=True, exist_ok=True)
    logging.info('Scheduled tweeting')
    while True:
        try:
            # TODO: although we are using threads, we still get a slight drift
            #       (each run gets executed after 60 seconds + a couple milliseconds)
            #       we may therefore sometimes miss posting a tweet
            run_threaded(loop)
            sleep(60)
        except KeyboardInterrupt:
            logging.info('Shutting down')
            sys.exit(0)
