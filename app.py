#!/usr/bin/env python3
import os
import sys

from redis import Redis

import logging

from telegram import BotCommand
from telegram.ext import Updater, CommandHandler, Filters

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.getLevelName(os.environ.get('LOG_LEVEL', 'INFO')))

redis = Redis(host=os.environ.get('REDIS_HOST', 'redis'), port=os.environ.get('REDIS_PORT', 6379))


def main():
    if 'TELEGRAM_TOKEN' not in os.environ:
        logging.error('You need to set the environment variable "TELEGRAM_TOKEN"')
        return sys.exit(-1)
    updater = Updater(token=os.environ.get('TELEGRAM_TOKEN'), use_context=True)
    updater.bot.set_my_commands([
        BotCommand('start', 'Returns a warming welcome message'),
        BotCommand('timezone', 'Changes the timezone of a group'),
        BotCommand('clock', 'Outputs the date of the received message'),
    ])
    updater.dispatcher.add_handler(CommandHandler('timezone', handle_timezone_command, Filters.group))

    updater.start_polling()


if __name__ == '__main__':
    main()
