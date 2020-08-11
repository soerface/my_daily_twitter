FROM python:3.8

RUN pip install pipenv
RUN mkdir /app

WORKDIR /app

COPY Pipfile* ./
RUN pipenv sync

COPY app.py ./
ENTRYPOINT ["pipenv", "run"]
CMD python app.py