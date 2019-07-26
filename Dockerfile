FROM	    alpine:latest
MAINTAINER  Peter Bui <pbui@yld.bx612.space>

RUN	    apk update && \
	    apk add python3 py3-pip

RUN	    pip3 install telethon tornado==5.1.1

RUN	    wget -O - https://gitlab.com/pbui/irtelegramd/-/archive/master/irtelegramd-master.tar.gz | tar xzvf -

COPY	    irtelegramd.py /irtelegramd-master

EXPOSE	    6667
ENTRYPOINT  ["/irtelegramd-master/irtelegramd.py", "--address=0.0.0.0", "--config_dir=/var/lib/irtelegramd"]
