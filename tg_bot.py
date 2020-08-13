#!/usr/bin/env python3
import os
from datetime import datetime

import tweepy

import logging

from telegram import BotCommand, Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CommandHandler, CallbackContext, MessageHandler, Filters
import pytz
from pytz import timezone

from common import TWEET_CHARACTER_LIMIT, redis, get_twitter_auth, get_twitter_api, MAX_QUEUE_SIZE, \
    get_telegram_updater, build_tweet_url, check_env_variables

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.getLevelName(os.environ.get('LOG_LEVEL', 'INFO')))


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
            f'https://t.me/{context.bot.username} was successfully configured for this account!')
    except tweepy.error.TweepError as e:
        context.bot.send_message(chat_id=update.message.chat_id, text=e.reason)
        context.bot.send_message(chat_id=update.message.chat_id,
                                 text='Sorry, I was unable to tweet something. Try /start')
        return
    tweet_url = build_tweet_url(status)
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
    if not redis.get(f'chat:{chat_id}:settings:timezone'):
        redis.set(f'chat:{chat_id}:settings:timezone', 'UTC')
    if not redis.get(f'chat:{chat_id}:settings:tweet_time'):
        redis.set(f'chat:{chat_id}:settings:tweet_time', '12:00')
    context.bot.send_message(chat_id=chat_id,
                             text="You're all set! If you want to, you can test if "
                                  "everything works by posting a tweet: /test_tweet")


def find_largest_photo(photos):
    largest_index = 0
    max_size = 0
    for i, photo in enumerate(photos):
        size = photo.height * photo.width
        if size > max_size:
            max_size = size
            largest_index = i
    return photos[largest_index]


def handle_messages(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    if not redis.get(f'chat:{chat_id}:oauth:access_token'):
        context.bot.send_message(chat_id=chat_id, text='You need to set me up first. Click on /start')
        return
    text = update.message.text or update.message.caption or ''
    if len(text) > TWEET_CHARACTER_LIMIT:
        context.bot.send_message(chat_id=chat_id,
                                 text=f'Sorry, your text exceeds the limit of {TWEET_CHARACTER_LIMIT} characters.')
    queue_size = redis.get(f'chat:{chat_id}:queue_size')
    if queue_size is None:
        queue_size = 0
    queue_size = int(queue_size)
    if queue_size >= MAX_QUEUE_SIZE:
        context.bot.send_message(chat_id=chat_id, text='You have exceeded the maximum queue size.')
    redis.set(f'chat:{chat_id}:queue:{queue_size}:text', text)
    if update.message.document:
        redis.set(f'chat:{chat_id}:queue:{queue_size}:tg_attachment_id', update.message.document.file_id)
    elif update.message.photo:
        redis.set(f'chat:{chat_id}:queue:{queue_size}:tg_attachment_id',
                  find_largest_photo(update.message.photo).file_id)
    queue_size += 1
    redis.set(f'chat:{chat_id}:queue_size', queue_size)
    context.bot.send_message(chat_id=chat_id,
                             text=f'Ok, I will tweet that! You now have {queue_size} tweet(s) in your queue.')


def handle_tweet_time_command(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id

    if len(context.args) == 0:
        buttons = []
        for hour in range(24):
            buttons.append([KeyboardButton(f'/tweet_time {hour:02}:{minute:02}') for minute in range(0, 60, 15)])
        reply = ReplyKeyboardMarkup(buttons, one_time_keyboard=True)
        tweet_time = redis.get(f'chat:{chat_id}:settings:tweet_time')
        context.bot.send_message(chat_id=update.message.chat_id,
                                 text=f'Your current tweet time is {tweet_time}. Do you want to change it?',
                                 reply_markup=reply)
        return

    try:
        tweet_time = datetime.strptime(context.args[0], '%H:%M').strftime("%H:%M")
    except ValueError:
        context.bot.send_message(chat_id=chat_id, text="Sorry, I didn't understand that time. "
                                                       "Time must be in format %H:%M")
        return
    redis.set(f'chat:{chat_id}:settings:tweet_time', tweet_time)
    context.bot.send_message(chat_id=chat_id,
                             text=f'I will tweet at {tweet_time}')


def handle_delete_last_command(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    queue_size = redis.get(f'chat:{chat_id}:queue_size')
    if queue_size is None:
        queue_size = 0
    queue_size = int(queue_size)
    if queue_size <= 0:
        context.bot.send_message(chat_id=chat_id, text='Queue is empty')
        return
    queue_size -= 1

    tweet_text = redis.get(f'chat:{chat_id}:queue:{queue_size}:text') or ''
    tg_attachment_id = redis.get(f'chat:{chat_id}:queue:{queue_size}:tg_attachment_id')

    redis.delete(f'chat:{chat_id}:queue:{queue_size}:text')
    redis.delete(f'chat:{chat_id}:queue:{queue_size}:tg_attachment_id')

    redis.set(f'chat:{chat_id}:queue_size', queue_size)

    context.bot.send_message(chat_id=chat_id, text="I've deleted your latest tweet. This was the text:")
    context.bot.send_message(chat_id=chat_id, text=tweet_text)
    if tg_attachment_id:
        context.bot.send_message(chat_id=chat_id, text='It also had an attachment')


def handle_help_command(update: Update, context: CallbackContext):
    context.bot.send_message(chat_id=update.message.chat_id,
                             text='Send me messages and photos - I will put each message in a queue. '
                                  'Every day, I post the first item of the queue on twitter.\n'
                                  '\n'
                                  '/start - connect me to twitter\n'
                                  '/tweet_time - when do you want me to tweet?\n'
                                  '/timezone - configure your timezone\n'
                                  '\n'
                                  'If you experience any issues, '
                                  'let me know at https://github.com/soerface/my_daily_twitter/issues')


def main():
    check_env_variables()

    telegram_updater = get_telegram_updater()

    telegram_updater.bot.set_my_commands([
        BotCommand('start', 'Starts the authorization process'),
        BotCommand('delete_last', 'Removes the last item from your queue. Does not delete already posted tweets.'),
        BotCommand('help', 'Display help'),
        BotCommand('timezone', 'Changes the timezone of a chat'),
        BotCommand('tweet_time', 'When do you want me to tweet?'),
        BotCommand('test_tweet', 'Instantly sends a tweet to test authorization'),
        # BotCommand('clock', 'Outputs the date of the received message'),
    ])
    telegram_updater.dispatcher.add_handler(CommandHandler('start', handle_start_command))
    telegram_updater.dispatcher.add_handler(CommandHandler('delete_last', handle_delete_last_command))
    telegram_updater.dispatcher.add_handler(CommandHandler('help', handle_help_command))
    telegram_updater.dispatcher.add_handler(CommandHandler('timezone', handle_timezone_command))
    telegram_updater.dispatcher.add_handler(CommandHandler('clock', handle_clock_command))
    telegram_updater.dispatcher.add_handler(CommandHandler('tweet_time', handle_tweet_time_command))
    telegram_updater.dispatcher.add_handler(CommandHandler('test_tweet', handle_test_tweet_command))
    telegram_updater.dispatcher.add_handler(CommandHandler('authorize', handle_authorize_command))
    telegram_updater.dispatcher.add_handler(
        MessageHandler((Filters.private | Filters.group) & (Filters.text | Filters.photo | Filters.document),
                       handle_messages))

    logging.info('Ready, now polling telegram')
    telegram_updater.start_polling()


if __name__ == '__main__':
    main()
