# Copyright 2018 Iguazio
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

ARG GO_VERSION=1.19

FROM gcr.io/iguazio/golang:${GO_VERSION} as build-binary

RUN mkdir /app
WORKDIR /app

# copy `go.mod` for definitions and `go.sum` to invalidate the next layer
# in case of a change in the dependencies
COPY go.mod go.sum /app/

RUN go mod download

ADD . /app/

# build
RUN GOOS=linux \
    GOARCH=amd64 \
    CGO_ENABLED=0 \
    go build -a -installsuffix cgo -ldflags="-s -w" -o main cmd/logcollector/main.go

FROM alpine:latest as install-health-probe

ARG GRPC_HEALTH_PROBE_VERSION=v0.4.14

RUN mkdir /app
WORKDIR /app

RUN wget -qO/app/grpc_health_probe \
    https://github.com/grpc-ecosystem/grpc-health-probe/releases/download/${GRPC_HEALTH_PROBE_VERSION}/grpc_health_probe-linux-amd64 && \
    chmod +x /app/grpc_health_probe

FROM gcr.io/iguazio/alpine:3.17
COPY --from=build-binary /app/main /main
COPY --from=install-health-probe /app/grpc_health_probe /grpc_health_probe

EXPOSE 8080
VOLUME /var/mlrun

CMD ["/main"]
