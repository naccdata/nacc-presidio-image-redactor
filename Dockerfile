FROM python@sha256:44122e46edb1c3ae2a144778db3e01c78b6de3af20ddcc38d43032decffb00cf
# (python:3.9.19-slim-bookworm, linux/amd64)
ENV FLYWHEEL="/flywheel/v0"
WORKDIR ${FLYWHEEL}

# Dev install. git for pip editable install.
RUN apt-get update &&  \
    apt-get install --no-install-recommends -y git && \
    apt-get -y install tesseract-ocr && \
    apt-get -y install libtesseract-dev && \
    apt-get clean -y && \
    apt-get autoclean -y && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# cv2 dependencies...
RUN apt-get update && apt-get install ffmpeg libsm6 libxext6  -y

# Installing main dependencies
COPY requirements.txt $FLYWHEEL/
RUN pip install --no-cache-dir -r $FLYWHEEL/requirements.txt
RUN pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.7.1/en_core_web_lg-3.7.1-py3-none-any.whl --no-cache-dir

# Installing the current project (most likely to change, above layer can be cached)
COPY ./ $FLYWHEEL/
RUN pip install --no-cache-dir .

# Copy the list of packages or directly install huggingface_hub
ARG REPO_ID="obi/deid_roberta_i2b2"
ARG LOCAL_DIR_PATH="$FLYWHEEL/.cache/huggingface/hub/models/obi_deid_roberta_i2b2"
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='$REPO_ID',local_dir='$LOCAL_DIR_PATH')"

# Configure entrypoint
RUN chmod a+x $FLYWHEEL/run.py
ENTRYPOINT ["python","/flywheel/v0/run.py"]
