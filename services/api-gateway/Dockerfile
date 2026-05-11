FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod ./
COPY main.go ./
RUN go mod tidy
RUN CGO_ENABLED=0 GOOS=linux go build -o api-gateway .

FROM alpine:3.19
RUN apk --no-cache add ca-certificates tzdata
WORKDIR /app
COPY --from=builder /app/api-gateway .
EXPOSE 8080
ENTRYPOINT ["./api-gateway"]
