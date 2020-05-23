FROM python:3.7-alpine

#RUN apk add --update alpine-sdk glib-dev

WORKDIR /usr/src/esp-ota

COPY Pipfile ./
COPY Pipfile.lock ./

RUN pip install --no-cache-dir pipenv
RUN pipenv install --system --deploy --ignore-pipfile

COPY *.py ./
RUN mkdir logs

CMD [ "python", "./app.py"]
