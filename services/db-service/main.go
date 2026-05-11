package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gorilla/mux"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// ── Fault state ───────────────────────────────────────────────────────────────

var (
	faultExhaustPool  atomic.Bool
	exhaustedConns    []*pgxpool.Conn
	exhaustMu         sync.Mutex
	faultSlowQueryMs  atomic.Int64
)

// ── Prometheus metrics ────────────────────────────────────────────────────────

var (
	dbQueryTotal = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "db_service_queries_total",
		Help: "Total database queries executed.",
	}, []string{"operation", "status"})

	dbQueryDuration = prometheus.NewHistogramVec(prometheus.HistogramOpts{
		Name:    "db_service_query_duration_seconds",
		Help:    "Database query latency.",
		Buckets: []float64{.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5},
	}, []string{"operation"})

	dbPoolAcquired = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "db_service_pool_acquired_connections",
		Help: "Currently acquired pool connections.",
	})

	dbPoolIdle = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "db_service_pool_idle_connections",
		Help: "Idle pool connections.",
	})

	dbPoolTotal = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "db_service_pool_total_connections",
		Help: "Total pool connections.",
	})

	dbErrors = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "db_service_errors_total",
		Help: "Total database errors.",
	}, []string{"type"})

	faultExhaustGauge = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "db_service_fault_pool_exhausted",
		Help: "1 when pool exhaustion fault is active.",
	})
)

func init() {
	prometheus.MustRegister(
		dbQueryTotal, dbQueryDuration,
		dbPoolAcquired, dbPoolIdle, dbPoolTotal,
		dbErrors, faultExhaustGauge,
	)
}

// ── DB pool ───────────────────────────────────────────────────────────────────

var pool *pgxpool.Pool

func initPool() {
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		dsn = "postgres://demo:demo@postgres:5432/ocp?sslmode=disable"
	}

	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		log.Fatalf("[db-service] parse DSN: %v", err)
	}
	cfg.MaxConns = 10
	cfg.MinConns = 2
	cfg.MaxConnLifetime = 30 * time.Minute
	cfg.MaxConnIdleTime = 5 * time.Minute

	for {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		p, err := pgxpool.NewWithConfig(ctx, cfg)
		if err == nil {
			if pingErr := p.Ping(ctx); pingErr == nil {
				cancel()
				pool = p
				log.Printf("[db-service] connected to PostgreSQL (max_conns=%d)", cfg.MaxConns)
				return
			}
			p.Close()
		}
		cancel()
		log.Printf("[db-service] waiting for PostgreSQL: %v", err)
		time.Sleep(2 * time.Second)
	}
}

func updatePoolMetrics() {
	if pool == nil {
		return
	}
	stat := pool.Stat()
	dbPoolAcquired.Set(float64(stat.AcquiredConns()))
	dbPoolIdle.Set(float64(stat.IdleConns()))
	dbPoolTotal.Set(float64(stat.TotalConns()))
}

// ── Handlers ──────────────────────────────────────────────────────────────────

func healthHandler(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err := pool.Ping(ctx); err != nil {
		http.Error(w, `{"status":"unhealthy"}`, http.StatusServiceUnavailable)
		return
	}
	json.NewEncoder(w).Encode(map[string]string{"status": "ok", "service": "db-service"})
}

func queryHandler(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	ctx := r.Context()

	slowMs := faultSlowQueryMs.Load()
	if slowMs > 0 {
		_, err := pool.Exec(ctx, fmt.Sprintf("SELECT pg_sleep(%f)", float64(slowMs)/1000.0))
		if err != nil {
			log.Printf("[db-service] slow query injection error: %v", err)
		}
	}

	rows, err := pool.Query(ctx, "SELECT id, created_at FROM events ORDER BY created_at DESC LIMIT 10")
	if err != nil {
		dbErrors.WithLabelValues("query").Inc()
		dbQueryTotal.WithLabelValues("select", "error").Inc()
		http.Error(w, fmt.Sprintf(`{"error":"%v"}`, err), http.StatusInternalServerError)
		return
	}
	defer rows.Close()

	var results []map[string]interface{}
	for rows.Next() {
		var id int64
		var ts time.Time
		rows.Scan(&id, &ts)
		results = append(results, map[string]interface{}{"id": id, "created_at": ts})
	}

	dbQueryTotal.WithLabelValues("select", "ok").Inc()
	dbQueryDuration.WithLabelValues("select").Observe(time.Since(start).Seconds())
	updatePoolMetrics()

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{"rows": results, "count": len(results)})
}

func insertHandler(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	ctx := r.Context()

	_, err := pool.Exec(ctx,
		"INSERT INTO events (payload, created_at) VALUES ($1, NOW())",
		fmt.Sprintf(`{"source":"api","ts":"%s"}`, time.Now().UTC()),
	)
	if err != nil {
		dbErrors.WithLabelValues("insert").Inc()
		dbQueryTotal.WithLabelValues("insert", "error").Inc()
		http.Error(w, fmt.Sprintf(`{"error":"%v"}`, err), http.StatusInternalServerError)
		return
	}

	dbQueryTotal.WithLabelValues("insert", "ok").Inc()
	dbQueryDuration.WithLabelValues("insert").Observe(time.Since(start).Seconds())
	updatePoolMetrics()

	json.NewEncoder(w).Encode(map[string]string{"status": "inserted"})
}

// ── Fault handlers ────────────────────────────────────────────────────────────

func faultExhaustHandler(w http.ResponseWriter, r *http.Request) {
	enable := r.URL.Query().Get("enable") == "true"
	if enable {
		faultExhaustPool.Store(true)
		faultExhaustGauge.Set(1)
		log.Printf("[FAULT] pool exhaustion enabled — holding all connections")
		// Acquire all connections and hold them
		go func() {
			conns := make([]*pgxpool.Conn, 0, 10)
			for i := 0; i < 12; i++ {
				conn, err := pool.Acquire(context.Background())
				if err != nil {
					break
				}
				conns = append(conns, conn)
			}
			exhaustMu.Lock()
			for faultExhaustPool.Load() {
				exhaustMu.Unlock()
				time.Sleep(500 * time.Millisecond)
				exhaustMu.Lock()
			}
			for _, c := range conns {
				c.Release()
			}
			exhaustMu.Unlock()
		}()
	} else {
		faultExhaustPool.Store(false)
		faultExhaustGauge.Set(0)
		log.Printf("[FAULT] pool exhaustion disabled")
	}
	json.NewEncoder(w).Encode(map[string]interface{}{"fault": "db_exhaustion", "active": enable})
}

func faultSlowQueryHandler(w http.ResponseWriter, r *http.Request) {
	ms, _ := strconv.ParseInt(r.URL.Query().Get("ms"), 10, 64)
	faultSlowQueryMs.Store(ms)
	log.Printf("[FAULT] slow query injection set to %dms", ms)
	json.NewEncoder(w).Encode(map[string]interface{}{"fault": "slow_query", "ms": ms})
}

func faultResetHandler(w http.ResponseWriter, r *http.Request) {
	faultExhaustPool.Store(false)
	faultExhaustGauge.Set(0)
	faultSlowQueryMs.Store(0)
	log.Printf("[FAULT] db faults reset")
	json.NewEncoder(w).Encode(map[string]string{"status": "db faults cleared"})
}

// ── Pool metrics loop ─────────────────────────────────────────────────────────

func metricsLoop() {
	for {
		updatePoolMetrics()
		time.Sleep(5 * time.Second)
	}
}

// ── Main ──────────────────────────────────────────────────────────────────────

func main() {
	initPool()
	go metricsLoop()

	port := os.Getenv("PORT")
	if port == "" {
		port = "8081"
	}

	r := mux.NewRouter()
	r.HandleFunc("/health", healthHandler).Methods("GET")
	r.HandleFunc("/api/v1/events", queryHandler).Methods("GET")
	r.HandleFunc("/api/v1/events", insertHandler).Methods("POST")
	r.HandleFunc("/fault/exhaust", faultExhaustHandler).Methods("POST")
	r.HandleFunc("/fault/slow-query", faultSlowQueryHandler).Methods("POST")
	r.HandleFunc("/fault/reset", faultResetHandler).Methods("POST")
	r.Handle("/metrics", promhttp.Handler())

	log.Printf("[db-service] listening on :%s", port)
	if err := http.ListenAndServe(fmt.Sprintf(":%s", port), r); err != nil {
		log.Fatal(err)
	}
}
