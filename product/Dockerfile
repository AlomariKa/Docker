FROM python:3.13

ENV PYTHONDONTWRITEBYCODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /product

COPY ../Pipfile ../Pipfile.lock /product/

RUN pip install pipenv && pipenv install --system

COPY product/product.py product/instance/product.db /product/

CMD ["python","./product.py"]