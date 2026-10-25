FROM public.ecr.aws/lambda/python:3.12
RUN dnf install -y tar xz && \
    curl -sL https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz | tar xJ -C /tmp && \
    cp /tmp/ffmpeg-*-amd64-static/ffmpeg /tmp/ffmpeg-*-amd64-static/ffprobe /usr/local/bin/ && rm -rf /tmp/ffmpeg-*
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY tools.py system.py scout_match.py lambda_handler.py ./
CMD ["lambda_handler.handler"]
