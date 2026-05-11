FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod ./
COPY main.go ./
RUN go mod tidy
RUN CGO_ENABLED=0 GOOS=linux go build -o background-job .

FROM alpine:3.19
RUN apk --no-cache add ca-certificates tzdata
WORKDIR /app
COPY --from=builder /app/background-job .
EXPOSE 8083
ENTRYPOINT ["./background-job"]
