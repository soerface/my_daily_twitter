#!/usr/bin/env python3
import os
import sys

import tweepy
from redis import Redis

import logging

from telegram import BotCommand, Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Updater, CommandHandler, Filters, CallbackContext
import pytz
from pytz import timezone

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.getLevelName(os.environ.get('LOG_LEVEL', 'INFO')))

redis = Redis(host=os.environ.get('REDIS_HOST', 'redis'), port=os.environ.get('REDIS_PORT', 6379))


def get_twitter_auth():
    return tweepy.OAuthHandler(os.environ['TWITTER_CLIENT_ID'], os.environ['TWITTER_CLIENT_SECRET'])


def get_twitter_api(chat_id) -> tweepy.API:
    auth = get_twitter_auth()
    access_token = redis.get(f'chat:{chat_id}:oauth:access_token')
    secret = redis.get(f'chat:{chat_id}:oauth:access_token_secret')
    auth.set_access_token(access_token, secret)
    return tweepy.API(auth)


def handle_timezone_command(update: Update, context: CallbackContext):
    continents = sorted(set([x.partition('/')[0] for x in pytz.common_timezones]))
    if len(context.args) == 0:
        current_timezone = redis.get(f'chat:{update.message.chat_id}:settings:timezone')
        reply = ReplyKeyboardMarkup(
            [[KeyboardButton(f'/timezone {x}') for x in continents[i:i + 3]] for i in range(0, len(continents), 3)],
            one_time_keyboard=True
        )
        context.bot.send_message(chat_id=update.message.chat_id,
                                 text=f'Your current timezone is set to "{current_timezone}". '
                                      'If you want to change it, choose your region',
                                 reply_markup=reply)
        return
    location = context.args[0]
    if location in pytz.all_timezones:
        redis.set(f'chat:{update.message.chat_id}:settings:timezone', location)
        tz = timezone(location)
        local_time = update.message.date.astimezone(tz).strftime('%X')
        context.bot.send_message(chat_id=update.message.chat_id,
                                 text=f'Timezone of this chat was set to {location}. Looks like it is {local_time}. '
                                      f'If this is incorrect, please execute /timezone again.')
    elif location in continents:
        zones = [x for x in pytz.all_timezones if x.startswith(location)]
        reply = ReplyKeyboardMarkup(
            [[KeyboardButton(f'/timezone {zone}')] for zone in zones],
            one_time_keyboard=True
        )
        context.bot.send_message(chat_id=update.message.chat_id, text='Choose your timezone', reply_markup=reply)
    else:
        context.bot.send_message(chat_id=update.message.chat_id, text="Sorry, I've never heard of that timezone")


def handle_clock_command(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    current_timezone = redis.get(f'chat:{chat_id}:settings:timezone')
    if not current_timezone:
        context.bot.send_message(chat_id=chat_id,
                                 text="Sorry to interrupt you, but you need to set a /timezone")
        return
    tz = timezone(current_timezone)
    msg_sent_date = update.message.date.astimezone(tz)
    context.bot.send_message(chat_id=update.message.chat_id, text=f'I received your message at {msg_sent_date}')


def handle_start_command(update: Update, context: CallbackContext):
    auth = get_twitter_auth()
    auth_url = auth.get_authorization_url()
    chat_id = update.message.chat_id
    context.bot.send_message(chat_id=chat_id,
                             text='I will tweet a message or photo from you each day. '
                                  'Everything you send me will be added to a queue and tweeted later. ')
    if update.message.chat.type != update.message.chat.GROUP:
        context.bot.send_message(chat_id=chat_id, text='You can also add me to groups!')
    context.bot.send_message(chat_id=chat_id,
                             text=f'Start by giving me access your twitter account: {auth_url}')


def handle_test_tweet_command(update: Update, context: CallbackContext):
    twitter = get_twitter_api(chat_id=update.message.chat_id)
    try:
        status = twitter.update_status(
            'https://t.me/my_daily_twitter_bot was successfully configured for this account!')
    except tweepy.error.TweepError as e:
        context.bot.send_message(chat_id=update.message.chat_id, text=e.reason)
        context.bot.send_message(chat_id=update.message.chat_id,
                                 text='Sorry, I was unable to tweet something. Try /start')
        return
    print(status)
    print(dir(status))
    tweet_url = f'https://twitter.com/{status.author.name}/status/{status.id}'
    context.bot.send_message(chat_id=update.message.chat_id, text=f'Here is your tweet: {tweet_url}')


def handle_authorize_command(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    auth = get_twitter_auth()
    if not update.message:
        return
    try:
        _, oauth_token, oauth_verifier = update.message.text.split()
    except ValueError:
        context.bot.send_message(chat_id=chat_id,
                                 text='Invalid authentication details. Expected OAUTH_TOKEN OAUTH_VERIFIER. '
                                      'If you want to start authorization, click on /start')
        return
    auth.request_token = {
        'oauth_token': oauth_token,
        'oauth_token_secret': oauth_verifier,
    }
    try:
        access_token, access_token_secret = auth.get_access_token(oauth_verifier)
    except tweepy.TweepError:
        context.bot.send_message(chat_id=chat_id,
                                 text='I was unable to get an access token. Try again: /start')
        return
    redis.set(f'chat:{chat_id}:oauth:access_token', access_token)
    redis.set(f'chat:{chat_id}:oauth:access_token_secret', access_token_secret)
    context.bot.send_message(chat_id=chat_id,
                             text="You're all set! If you want to, you can test if "
                                  "everything works by posting a tweet: /test_tweet")


def main():
    if 'TELEGRAM_TOKEN' not in os.environ:
        logging.error('You need to set the environment variable "TELEGRAM_TOKEN"')
        return sys.exit(1)
    if 'TWITTER_CLIENT_ID' not in os.environ:
        logging.error('You need to set the environment variable "TWITTER_CLIENT_ID"')
        return sys.exit(1)
    if 'TWITTER_CLIENT_SECRET' not in os.environ:
        logging.error('You need to set the environment variable "TWITTER_CLIENT_SECRET"')
        return sys.exit(1)

    updater = Updater(token=os.environ.get('TELEGRAM_TOKEN'), use_context=True)
    updater.bot.set_my_commands([
        BotCommand('start', 'Starts the authorization process'),
        BotCommand('timezone', 'Changes the timezone of a chat'),
        BotCommand('test_tweet', 'Instantly sends a tweet to test authorization'),
        # BotCommand('clock', 'Outputs the date of the received message'),
    ])
    updater.dispatcher.add_handler(CommandHandler('start', handle_start_command))
    updater.dispatcher.add_handler(CommandHandler('timezone', handle_timezone_command))
    updater.dispatcher.add_handler(CommandHandler('clock', handle_clock_command))
    updater.dispatcher.add_handler(CommandHandler('test_tweet', handle_test_tweet_command))
    updater.dispatcher.add_handler(CommandHandler('authorize', handle_authorize_command))

    updater.start_polling()


if __name__ == '__main__':
    main()
