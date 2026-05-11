package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"sync/atomic"
	"time"

	"github.com/gorilla/mux"
	amqp "github.com/rabbitmq/amqp091-go"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// ── Fault injection state (toggled by orchestrator via /fault/* endpoints) ──

var (
	faultLatencyMs    atomic.Int64  // add artificial latency to all requests
	faultAuthFailRate atomic.Int64  // % of requests to reject with 401
	faultRateLimitRPS atomic.Int64  // requests/sec limit (0 = disabled)
	faultTLSBroken    atomic.Bool   // signal broken TLS (logged, not enforced here)
	requestCounter    atomic.Int64  // for rate limiting
	windowStart       atomic.Int64  // unix nano for rate limit window
)

// ── Prometheus metrics ────────────────────────────────────────────────────────

var (
	httpRequestsTotal = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "api_gateway_requests_total",
		Help: "Total HTTP requests handled by the API gateway.",
	}, []string{"method", "path", "status"})

	httpRequestDuration = prometheus.NewHistogramVec(prometheus.HistogramOpts{
		Name:    "api_gateway_request_duration_seconds",
		Help:    "HTTP request latency.",
		Buckets: prometheus.DefBuckets,
	}, []string{"method", "path"})

	authFailuresTotal = prometheus.NewCounter(prometheus.CounterOpts{
		Name: "api_gateway_auth_failures_total",
		Help: "Total auth failures injected.",
	})

	rateLimitedTotal = prometheus.NewCounter(prometheus.CounterOpts{
		Name: "api_gateway_rate_limited_total",
		Help: "Total requests rate-limited.",
	})

	faultLatencyGauge = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "api_gateway_fault_latency_ms",
		Help: "Currently injected latency in milliseconds.",
	})

	activeConnections = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "api_gateway_active_connections",
		Help: "Current active HTTP connections.",
	})
)

func init() {
	prometheus.MustRegister(
		httpRequestsTotal,
		httpRequestDuration,
		authFailuresTotal,
		rateLimitedTotal,
		faultLatencyGauge,
		activeConnections,
	)
}

// ── Middleware ────────────────────────────────────────────────────────────────

func metricsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		activeConnections.Inc()
		defer activeConnections.Dec()

		start := time.Now()
		rw := &responseWriter{ResponseWriter: w, status: 200}

		// Rate limiting
		limit := faultRateLimitRPS.Load()
		if limit > 0 {
			now := time.Now().UnixNano()
			windowNs := int64(time.Second)
			if now-windowStart.Load() > windowNs {
				windowStart.Store(now)
				requestCounter.Store(0)
			}
			if requestCounter.Add(1) > limit {
				rateLimitedTotal.Inc()
				http.Error(w, `{"error":"rate limit exceeded"}`, http.StatusTooManyRequests)
				httpRequestsTotal.WithLabelValues(r.Method, r.URL.Path, "429").Inc()
				return
			}
		}

		// Auth failure injection
		failRate := faultAuthFailRate.Load()
		if failRate > 0 {
			count := requestCounter.Load()
			if count%100 < failRate {
				authFailuresTotal.Inc()
				http.Error(w, `{"error":"unauthorized"}`, http.StatusUnauthorized)
				httpRequestsTotal.WithLabelValues(r.Method, r.URL.Path, "401").Inc()
				return
			}
		}

		// Latency injection
		latency := faultLatencyMs.Load()
		if latency > 0 {
			time.Sleep(time.Duration(latency) * time.Millisecond)
		}
		faultLatencyGauge.Set(float64(latency))

		next.ServeHTTP(rw, r)

		duration := time.Since(start).Seconds()
		status := strconv.Itoa(rw.status)
		httpRequestsTotal.WithLabelValues(r.Method, r.URL.Path, status).Inc()
		httpRequestDuration.WithLabelValues(r.Method, r.URL.Path).Observe(duration)
	})
}

type responseWriter struct {
	http.ResponseWriter
	status int
}

func (rw *responseWriter) WriteHeader(code int) {
	rw.status = code
	rw.ResponseWriter.WriteHeader(code)
}

// ── Handlers ──────────────────────────────────────────────────────────────────

func healthHandler(w http.ResponseWriter, r *http.Request) {
	json.NewEncoder(w).Encode(map[string]string{"status": "ok", "service": "api-gateway"})
}

func readyHandler(w http.ResponseWriter, r *http.Request) {
	json.NewEncoder(w).Encode(map[string]string{"status": "ready"})
}

func ordersHandler(w http.ResponseWriter, r *http.Request) {
	// Publish to RabbitMQ
	conn := rabbitConn()
	if conn != nil {
		defer conn.Close()
		ch, _ := conn.Channel()
		if ch != nil {
			defer ch.Close()
			ch.QueueDeclare("orders", true, false, false, false, nil)
			ch.PublishWithContext(context.Background(), "", "orders", false, false,
				amqp.Publishing{
					ContentType: "application/json",
					Body:        []byte(`{"order_id":"ord-001","status":"received"}`),
				})
		}
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"order_id": "ord-001",
		"status":   "received",
		"ts":       time.Now().UTC(),
	})
}

func metricsStatusHandler(w http.ResponseWriter, r *http.Request) {
	json.NewEncoder(w).Encode(map[string]interface{}{
		"fault_latency_ms":    faultLatencyMs.Load(),
		"fault_auth_fail_pct": faultAuthFailRate.Load(),
		"fault_rate_limit":    faultRateLimitRPS.Load(),
		"fault_tls_broken":    faultTLSBroken.Load(),
	})
}

// ── Fault injection control endpoints (called by orchestrator) ────────────────

func faultLatencyHandler(w http.ResponseWriter, r *http.Request) {
	ms, _ := strconv.ParseInt(r.URL.Query().Get("ms"), 10, 64)
	faultLatencyMs.Store(ms)
	log.Printf("[FAULT] latency injection set to %dms", ms)
	json.NewEncoder(w).Encode(map[string]interface{}{"fault": "latency", "ms": ms})
}

func faultAuthHandler(w http.ResponseWriter, r *http.Request) {
	pct, _ := strconv.ParseInt(r.URL.Query().Get("pct"), 10, 64)
	faultAuthFailRate.Store(pct)
	log.Printf("[FAULT] auth failure rate set to %d%%", pct)
	json.NewEncoder(w).Encode(map[string]interface{}{"fault": "auth", "fail_pct": pct})
}

func faultRateLimitHandler(w http.ResponseWriter, r *http.Request) {
	rps, _ := strconv.ParseInt(r.URL.Query().Get("rps"), 10, 64)
	faultRateLimitRPS.Store(rps)
	log.Printf("[FAULT] rate limit set to %d rps", rps)
	json.NewEncoder(w).Encode(map[string]interface{}{"fault": "rate_limit", "rps": rps})
}

func faultTLSHandler(w http.ResponseWriter, r *http.Request) {
	broken := r.URL.Query().Get("broken") == "true"
	faultTLSBroken.Store(broken)
	log.Printf("[FAULT] TLS broken=%v", broken)
	json.NewEncoder(w).Encode(map[string]interface{}{"fault": "tls", "broken": broken})
}

func faultResetHandler(w http.ResponseWriter, r *http.Request) {
	faultLatencyMs.Store(0)
	faultAuthFailRate.Store(0)
	faultRateLimitRPS.Store(0)
	faultTLSBroken.Store(false)
	log.Printf("[FAULT] all faults reset")
	json.NewEncoder(w).Encode(map[string]string{"status": "all faults cleared"})
}

// ── RabbitMQ ──────────────────────────────────────────────────────────────────

func rabbitConn() *amqp.Connection {
	url := os.Getenv("RABBITMQ_URL")
	if url == "" {
		url = "amqp://guest:guest@rabbitmq:5672/"
	}
	conn, err := amqp.Dial(url)
	if err != nil {
		log.Printf("[WARN] RabbitMQ connect failed: %v", err)
		return nil
	}
	return conn
}

// ── Main ──────────────────────────────────────────────────────────────────────

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	r := mux.NewRouter()
	r.Use(metricsMiddleware)

	// Business endpoints
	r.HandleFunc("/health", healthHandler).Methods("GET")
	r.HandleFunc("/ready", readyHandler).Methods("GET")
	r.HandleFunc("/api/v1/orders", ordersHandler).Methods("POST")
	r.HandleFunc("/api/v1/status", metricsStatusHandler).Methods("GET")

	// Fault injection control
	r.HandleFunc("/fault/latency", faultLatencyHandler).Methods("POST")
	r.HandleFunc("/fault/auth", faultAuthHandler).Methods("POST")
	r.HandleFunc("/fault/rate-limit", faultRateLimitHandler).Methods("POST")
	r.HandleFunc("/fault/tls", faultTLSHandler).Methods("POST")
	r.HandleFunc("/fault/reset", faultResetHandler).Methods("POST")

	// Prometheus
	r.Handle("/metrics", promhttp.Handler())

	log.Printf("[api-gateway] listening on :%s", port)
	if err := http.ListenAndServe(fmt.Sprintf(":%s", port), r); err != nil {
		log.Fatal(err)
	}
}
