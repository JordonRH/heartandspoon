FROM ubuntu:24.04
ARG RUNNER_VERSION=2.338.2
ARG RUNNER_SHA256=baebf204307bac6193480852732f0aba2ae97b6c5597c244f4d5558390147c40
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl git libicu74 tar \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /runner-template /usr/libexec/docker/cli-plugins \
 && curl --fail --location --retry 3 "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz" -o /tmp/runner.tar.gz \
 && echo "${RUNNER_SHA256}  /tmp/runner.tar.gz" | sha256sum --check - \
 && tar -xzf /tmp/runner.tar.gz -C /runner-template \
 && chown -R 1000:1000 /runner-template \
 && rm /tmp/runner.tar.gz
COPY deploy/runner/entrypoint.sh /usr/local/bin/hearth-runner
RUN chmod 755 /usr/local/bin/hearth-runner
USER 1000:1000
WORKDIR /runner
ENTRYPOINT ["/usr/local/bin/hearth-runner"]
