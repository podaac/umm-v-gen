FROM python:3.9-slim-buster

RUN apt-get update \
 && apt-get install gcc -y \
 && apt-get clean

COPY app/ /opt/

RUN ln -s /opt/ummvar_gen.py /usr/bin/ummvar_gen

RUN pip install -r /opt/requirements.txt

RUN useradd -ms /bin/bash datapub
USER datapub

ENV HOME /home/datapub
WORKDIR $HOME

ENTRYPOINT ["ummvar_gen", "/source"]
