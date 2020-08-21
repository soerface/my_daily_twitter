# My daily twitter bot

My daily twitter bot was created for https://twitter.com/myDailyZipTie,
but you can use it for any scheduled tweets that you want to manage via telegram.

Just use it: https://t.me/my_daily_twitter_bot

Running it with docker-compose is easy, set these environment variables or create a file `.env`:

    TELEGRAM_TOKEN=yourtoken
    TWITTER_CLIENT_ID=yourid
    TWITTER_CLIENT_SECRET=yoursecret
    LOG_LEVEL=INFO
    
Get the necessary information for twitter from https://developer.twitter.com/ and register your telegram bot with [@BotFather](http://t.me/BotFather)

Start everything:

    docker-compose up
