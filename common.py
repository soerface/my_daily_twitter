import os

import tweepy
from redis import Redis

TWEET_CHARACTER_LIMIT = 280
MAX_QUEUE_SIZE = 365

redis = Redis(host=os.environ.get('REDIS_HOST', 'redis'), port=os.environ.get('REDIS_PORT', 6379))


def get_twitter_auth():
    return tweepy.OAuthHandler(os.environ['TWITTER_CLIENT_ID'], os.environ['TWITTER_CLIENT_SECRET'])


def get_twitter_api(chat_id) -> tweepy.API:
    auth = get_twitter_auth()
    access_token = redis.get(f'chat:{chat_id}:oauth:access_token')
    secret = redis.get(f'chat:{chat_id}:oauth:access_token_secret')
    auth.set_access_token(access_token, secret)
    return tweepy.API(auth)