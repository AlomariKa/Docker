FROM python:3.13

ENV PYTHONDONTWRITEBYCODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /inventory

COPY ../Pipfile ../Pipfile.lock /inventory/

RUN pip install pipenv && pipenv install --system

COPY inventory/inventory.py inventory/instance/inventory.db /inventory/

CMD ["python","./inventory.py"]