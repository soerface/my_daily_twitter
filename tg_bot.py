#!/usr/bin/env python3
import os
import sentry_sdk
from datetime import datetime
from typing import List

import tweepy

import logging

from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.integrations.tornado import TornadoIntegration
from telegram import BotCommand, Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, ReplyKeyboardRemove
from telegram.ext import CommandHandler, CallbackContext, MessageHandler, Filters, CallbackQueryHandler
import pytz
from pytz import timezone

from common import TWEET_CHARACTER_LIMIT, redis, get_twitter_auth, get_twitter_api, MAX_QUEUE_SIZE, \
    get_telegram_updater, build_tweet_url, check_env_variables

sentry_sdk.init(
    os.environ.get('SENTRY_DSN'),
    traces_sample_rate=1.0,
    integrations=[RedisIntegration(), TornadoIntegration()],
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.getLevelName(os.environ.get('LOG_LEVEL', 'INFO')))


def get_timezone_region_markup(continents):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(x, callback_data=':'.join(['timezone', x])) for x in continents[i:i + 3]]
         for i in range(0, len(continents), 3)]
    )


def handle_timezone_command(update: Update, context: CallbackContext):
    continents = sorted(set([x.partition('/')[0] for x in pytz.common_timezones]))
    current_timezone = redis.get(f'chat:{update.message.chat_id}:settings:timezone')
    reply = get_timezone_region_markup(continents)
    context.bot.send_message(chat_id=update.message.chat_id,
                             text=f'Your current timezone is set to "{current_timezone}". '
                                  'If you want to change it, choose your region',
                             reply_markup=reply)


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
                                  'Everything you send me will be added to a queue and tweeted later. ',
                             reply_markup=ReplyKeyboardRemove())
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
    tz = redis.get(f'chat:{chat_id}:settings:timezone')
    if not redis.get(f'chat:{chat_id}:settings:tweet_time'):
        redis.set(f'chat:{chat_id}:settings:tweet_time', '12:00')
    tweet_time = redis.get(f'chat:{chat_id}:settings:tweet_time')
    context.bot.send_message(chat_id=chat_id,
                             text="You're all set! If you want to, you can test if "
                                  "everything works by posting a tweet: /test_tweet")
    context.bot.send_message(chat_id=chat_id,
                             text=f'I will tweet at {tweet_time} ({tz}). You can change that: /tweet_time, /timezone')


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
    tweet_time = redis.get(f'chat:{chat_id}:settings:tweet_time')
    context.bot.send_message(chat_id=chat_id,
                             text=f'Ok, I will tweet that at {tweet_time}! You now have {queue_size} tweet(s) in your queue.')


def handle_migrate_chat(update: Update, context: CallbackContext):
    old_chat_id = update.message.migrate_from_chat_id
    new_chat_id = update.message.chat_id
    if old_chat_id is None or new_chat_id is None:
        return
    logging.info(f'Supergroup migration. Renaming redis keys chat:{old_chat_id}:* to chat:{new_chat_id}:*')
    for key in redis.keys(f'chat:{old_chat_id}:*'):
        new_key = key.replace(f'chat:{old_chat_id}:', f'chat:{new_chat_id}:')
        redis.rename(key, new_key)


def handle_tweet_time_command(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id

    buttons = []
    for hour in range(24):
        buttons.append([InlineKeyboardButton(
            f'{hour:02}:{minute:02}', callback_data=f'tweet_time:{hour}:{minute}'
        ) for minute in range(0, 60, 15)])
    buttons.append([InlineKeyboardButton('Cancel', callback_data=f'cancel')])
    reply = InlineKeyboardMarkup(buttons, one_time_keyboard=True)
    tweet_time = redis.get(f'chat:{chat_id}:settings:tweet_time')
    context.bot.send_message(chat_id=update.message.chat_id,
                             text=f'Your current tweet time is {tweet_time}. Do you want to change it?',
                             reply_markup=reply)


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

    context.bot.send_message(chat_id=chat_id, text="I've deleted your latest tweet. This was the text: " + tweet_text)
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


def handle_inlinebutton_click(update: Update, context: CallbackContext):
    query: CallbackQuery = update.callback_query
    cmd, *args = query.data.split(':')

    if cmd == 'timezone':
        inlinebutton_timezone(update, context, query, args)
    elif cmd == 'tweet_time':
        inlinebutton_tweet_time(update, context, query, args)
    elif cmd == 'cancel':
        query.edit_message_text('Canceled')

    query.answer()


def inlinebutton_timezone(update: Update, context: CallbackContext, query: CallbackQuery, args: List[str]):
    continents = sorted(set([x.partition('/')[0] for x in pytz.common_timezones]))
    location = args[0]
    if location == 'region_selection':
        reply = get_timezone_region_markup(continents)
        query.edit_message_text('Choose your region')
        query.edit_message_reply_markup(reply)
    elif location in pytz.all_timezones:
        redis.set(f'chat:{query.message.chat_id}:settings:timezone', location)
        tz = timezone(location)
        local_time = query.message.date.astimezone(tz).strftime('%X')
        reply = InlineKeyboardMarkup(
            [[(InlineKeyboardButton('Change timezone', callback_data='timezone:region_selection'))]]
        )
        query.edit_message_text(
            f'Timezone of this chat was set to {location}. '
            f'Looks like it was {local_time} when you sent the last /timezone command. '
            'If this is incorrect, please execute /timezone again or click the button below.'
        )
        query.edit_message_reply_markup(reply)
    elif location in continents:
        zones = [x for x in pytz.all_timezones if x.startswith(location)]
        reply = InlineKeyboardMarkup(
            [[InlineKeyboardButton(x.partition('/')[2], callback_data=':'.join(['timezone', x]))] for x in zones]
            + [[(InlineKeyboardButton('« Back', callback_data='timezone:region_selection'))]],
        )
        query.edit_message_text('Choose your timezone')
        query.edit_message_reply_markup(reply)


def inlinebutton_tweet_time(update: Update, context: CallbackContext, query: CallbackQuery, args: List[str]):
    try:
        tweet_time = datetime.strptime(':'.join(args), '%H:%M').strftime("%H:%M")
    except ValueError:
        query.edit_message_text("Sorry, I didn't understand that time. Time must be in format %H:%M")
        return
    redis.set(f'chat:{query.message.chat_id}:settings:tweet_time', tweet_time)
    query.edit_message_text(f'I will tweet at {tweet_time}')


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
    telegram_updater.dispatcher.add_handler(CallbackQueryHandler(handle_inlinebutton_click))
    telegram_updater.dispatcher.add_handler(
        MessageHandler((Filters.private | Filters.group) & (Filters.text | Filters.photo | Filters.document),
                       handle_messages))
    telegram_updater.dispatcher.add_handler(MessageHandler(Filters.status_update.migrate, handle_migrate_chat))

    logging.info('Ready, now polling telegram')
    telegram_updater.start_polling()


if __name__ == '__main__':
    main()
