package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"runtime"
	"sync/atomic"
	"time"

	"github.com/go-redis/redis/v8"
	"github.com/gorilla/mux"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// ── Fault state ───────────────────────────────────────────────────────────────

var (
	faultMemoryPressure atomic.Bool
	memoryBallast       [][]byte // holds allocated memory
	jobsRun             atomic.Int64
	lastJobDurationMs   atomic.Int64
)

// ── Prometheus metrics ────────────────────────────────────────────────────────

var (
	jobsTotal = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "background_job_runs_total",
		Help: "Total background job executions.",
	}, []string{"job", "status"})

	jobDuration = prometheus.NewHistogramVec(prometheus.HistogramOpts{
		Name:    "background_job_duration_seconds",
		Help:    "Background job execution duration.",
		Buckets: []float64{.1, .5, 1, 2.5, 5, 10, 30},
	}, []string{"job"})

	memoryUsageBytes = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "background_job_memory_bytes",
		Help: "Current memory usage of the background job service.",
	})

	redisOpsTotal = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "background_job_redis_ops_total",
		Help: "Total Redis operations.",
	}, []string{"op", "status"})

	memoryPressureGauge = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "background_job_fault_memory_pressure",
		Help: "1 when memory pressure fault is active.",
	})

	goroutinesGauge = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "background_job_goroutines",
		Help: "Current number of goroutines.",
	})
)

func init() {
	prometheus.MustRegister(
		jobsTotal, jobDuration,
		memoryUsageBytes, redisOpsTotal,
		memoryPressureGauge, goroutinesGauge,
	)
}

// ── Redis ─────────────────────────────────────────────────────────────────────

var rdb *redis.Client

func initRedis() {
	addr := os.Getenv("REDIS_URL")
	if addr == "" {
		addr = "redis:6379"
	}
	rdb = redis.NewClient(&redis.Options{Addr: addr})
	for {
		if err := rdb.Ping(context.Background()).Err(); err == nil {
			log.Printf("[background-job] connected to Redis")
			return
		}
		log.Printf("[background-job] waiting for Redis...")
		time.Sleep(2 * time.Second)
	}
}

// ── Jobs ──────────────────────────────────────────────────────────────────────

func runCleanupJob(ctx context.Context) {
	start := time.Now()
	// Simulate work: increment a Redis counter
	if err := rdb.Incr(ctx, "cleanup:runs").Err(); err != nil {
		redisOpsTotal.WithLabelValues("incr", "error").Inc()
		jobsTotal.WithLabelValues("cleanup", "error").Inc()
		log.Printf("[background-job] cleanup redis error: %v", err)
		return
	}
	redisOpsTotal.WithLabelValues("incr", "ok").Inc()

	// Cache a heartbeat
	rdb.Set(ctx, "cleanup:last_run", time.Now().UTC().Format(time.RFC3339), 10*time.Minute)
	redisOpsTotal.WithLabelValues("set", "ok").Inc()

	elapsed := time.Since(start)
	jobDuration.WithLabelValues("cleanup").Observe(elapsed.Seconds())
	jobsTotal.WithLabelValues("cleanup", "ok").Inc()
	jobsRun.Add(1)
	lastJobDurationMs.Store(elapsed.Milliseconds())
}

func runMetricsJob(ctx context.Context) {
	start := time.Now()
	var ms runtime.MemStats
	runtime.ReadMemStats(&ms)
	memoryUsageBytes.Set(float64(ms.Alloc))
	goroutinesGauge.Set(float64(runtime.NumGoroutine()))

	// Store in Redis
	payload, _ := json.Marshal(map[string]interface{}{
		"alloc_bytes": ms.Alloc,
		"goroutines":  runtime.NumGoroutine(),
		"ts":          time.Now().UTC(),
	})
	rdb.LPush(ctx, "metrics:snapshots", payload)
	rdb.LTrim(ctx, "metrics:snapshots", 0, 99) // keep last 100
	redisOpsTotal.WithLabelValues("lpush", "ok").Inc()

	jobDuration.WithLabelValues("metrics_snapshot").Observe(time.Since(start).Seconds())
	jobsTotal.WithLabelValues("metrics_snapshot", "ok").Inc()
}

// ── Job scheduler ─────────────────────────────────────────────────────────────

func scheduler() {
	cleanupTicker := time.NewTicker(30 * time.Second)
	metricsTicker := time.NewTicker(10 * time.Second)

	for {
		select {
		case <-cleanupTicker.C:
			ctx := context.Background()
			if !faultMemoryPressure.Load() {
				runCleanupJob(ctx)
			} else {
				// Under memory pressure jobs run slowly
				time.Sleep(5 * time.Second)
				runCleanupJob(ctx)
			}
		case <-metricsTicker.C:
			runMetricsJob(context.Background())
		}
	}
}

// ── Fault handlers ────────────────────────────────────────────────────────────

func faultMemoryHandler(w http.ResponseWriter, r *http.Request) {
	enable := r.URL.Query().Get("enable") == "true"
	if enable {
		faultMemoryPressure.Store(true)
		memoryPressureGauge.Set(1)
		// Allocate ~256MB in 1MB chunks
		memoryBallast = make([][]byte, 0, 256)
		for i := 0; i < 256; i++ {
			chunk := make([]byte, 1<<20) // 1MB
			for j := range chunk {
				chunk[j] = byte(j) // prevent optimisation
			}
			memoryBallast = append(memoryBallast, chunk)
		}
		log.Printf("[FAULT] memory pressure enabled — allocated ~256MB")
	} else {
		faultMemoryPressure.Store(false)
		memoryPressureGauge.Set(0)
		memoryBallast = nil
		runtime.GC()
		log.Printf("[FAULT] memory pressure disabled — released ballast")
	}
	json.NewEncoder(w).Encode(map[string]interface{}{"fault": "memory_pressure", "active": enable})
}

func faultResetHandler(w http.ResponseWriter, r *http.Request) {
	faultMemoryPressure.Store(false)
	memoryPressureGauge.Set(0)
	memoryBallast = nil
	runtime.GC()
	log.Printf("[FAULT] background-job faults reset")
	json.NewEncoder(w).Encode(map[string]string{"status": "background-job faults cleared"})
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	redisOk := rdb.Ping(ctx).Err() == nil
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":              "ok",
		"service":             "background-job",
		"redis":               redisOk,
		"jobs_run":            jobsRun.Load(),
		"last_job_duration_ms": lastJobDurationMs.Load(),
		"memory_pressure":     faultMemoryPressure.Load(),
	})
}

// ── Main ──────────────────────────────────────────────────────────────────────

func main() {
	initRedis()
	go scheduler()

	port := os.Getenv("PORT")
	if port == "" {
		port = "8083"
	}

	r := mux.NewRouter()
	r.HandleFunc("/health", healthHandler).Methods("GET")
	r.HandleFunc("/fault/memory", faultMemoryHandler).Methods("POST")
	r.HandleFunc("/fault/reset", faultResetHandler).Methods("POST")
	r.Handle("/metrics", promhttp.Handler())

	log.Printf("[background-job] listening on :%s", port)
	if err := http.ListenAndServe(fmt.Sprintf(":%s", port), r); err != nil {
		log.Fatal(err)
	}
}
