FROM python:3.8

RUN pip install pipenv
RUN mkdir /app

WORKDIR /app

COPY Pipfile* ./
RUN pipenv sync

COPY tg_bot.py ./
COPY tweet.py ./
COPY common.py ./
ENTRYPOINT ["pipenv", "run"]
CMD python tg_bot.py