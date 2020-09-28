FROM centos:7
RUN yum install libfreetype.so.6 -y yum install libpthread.so.0 -y yum install fontconfig -y 
COPY ["CLI/glasswallCLI"           , "/usr/bin"        ] 
COPY ["Library/libglasswall.classic.so", "/usr/lib"        ]
COPY ["CLI/Configs/*"              , "/home/glasswall/"]
RUN ln -s /usr/lib/libglasswall.classic.so /usr/bin/libglasswall.classic.so
RUN ldconfig
RUN chmod +x /usr/bin/glasswallCLI

#ENV API_URL https://gzlhbtpvk2.execute-api.eu-west-1.amazonaws.com/Prod/api/rebuild/file

WORKDIR /application
COPY requirement.txt .
RUN curl -L -O https://artifacts.elastic.co/downloads/beats/filebeat/filebeat-7.9.2-x86_64.rpm
RUN rpm -vi filebeat-7.9.2-x86_64.rpm
COPY filebeat.yml /etc/filebeat

RUN mkdir /input
RUN mkdir /output

RUN yum update -y
RUN yum install -y python3
RUN curl "https://bootstrap.pypa.io/get-pip.py" -o "get-pip.py"
RUN python get-pip.py
RUN pip install -r requirement.txt --user
COPY processor.py .
COPY logging.conf .

CMD ["python", "processor.py"]
