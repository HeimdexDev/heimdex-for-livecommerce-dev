FROM ubuntu:22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        cmake \
        make \
        g++ \
        git \
        curl \
        ca-certificates \
        libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /

RUN git clone https://github.com/ggerganov/llama.cpp.git \
    && cd llama.cpp \
    && git checkout a0c91e8 \
    && cmake -B build -DGGML_NATIVE=ON -DLLAMA_CURL=ON . \
    && cmake --build build --config Release -j"$(nproc)" --target llama-server

FROM ubuntu:22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        libgomp1 \
        libcurl4 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
COPY --from=builder /llama.cpp/build/bin/lib*.so /usr/local/lib/
RUN ldconfig

RUN useradd --uid 1000 --create-home --shell /bin/bash appuser \
    && mkdir -p /models \
    && chown -R appuser:appuser /models

COPY download-models.sh /usr/local/bin/download-models.sh
COPY healthcheck.sh /usr/local/bin/healthcheck.sh
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod +x /usr/local/bin/download-models.sh /usr/local/bin/healthcheck.sh /usr/local/bin/entrypoint.sh

ENV LD_LIBRARY_PATH=/usr/local/lib
ENV LLAMA_THREADS=2
ENV LLAMA_API_KEY=
ENV LLAMA_MLOCK=false

USER appuser

EXPOSE 8089

HEALTHCHECK --interval=15s --timeout=10s --retries=3 --start-period=120s \
  CMD ["/usr/local/bin/healthcheck.sh"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
