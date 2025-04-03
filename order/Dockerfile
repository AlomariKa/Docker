FROM python:3.13

ENV PYTHONDONTWRITEBYCODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /order

COPY ../Pipfile ../Pipfile.lock /order/

RUN pip install pipenv && pipenv install --system

COPY order/order.py order/instance/order.db /order/

CMD ["python","./order.py"]