package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"sync/atomic"
	"time"

	"github.com/gorilla/mux"
	amqp "github.com/rabbitmq/amqp091-go"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// ── Fault state ───────────────────────────────────────────────────────────────

var (
	faultQueueLag       atomic.Int64 // ms to sleep before processing each message
	faultWebhookFail    atomic.Bool  // force webhook delivery to fail
	faultConsumerPaused atomic.Bool  // stop consuming entirely
	processedTotal      atomic.Int64
	queueDepth          atomic.Int64
)

// ── Prometheus metrics ────────────────────────────────────────────────────────

var (
	messagesProcessed = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "queue_worker_messages_processed_total",
		Help: "Total messages consumed from the queue.",
	}, []string{"status"})

	messageProcessingDuration = prometheus.NewHistogram(prometheus.HistogramOpts{
		Name:    "queue_worker_processing_duration_seconds",
		Help:    "Time to process a single message.",
		Buckets: []float64{.01, .05, .1, .25, .5, 1, 2.5, 5, 10},
	})

	queueDepthGauge = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "queue_worker_queue_depth",
		Help: "Estimated pending messages in the queue.",
	})

	webhookDeliveries = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "queue_worker_webhook_deliveries_total",
		Help: "Total webhook delivery attempts.",
	}, []string{"status"})

	webhookRetries = prometheus.NewCounter(prometheus.CounterOpts{
		Name: "queue_worker_webhook_retries_total",
		Help: "Total webhook retry attempts.",
	})

	lagGauge = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "queue_worker_fault_lag_ms",
		Help: "Currently injected processing lag in milliseconds.",
	})

	consumerPausedGauge = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "queue_worker_consumer_paused",
		Help: "1 when consumer is paused (queue lag fault).",
	})
)

func init() {
	prometheus.MustRegister(
		messagesProcessed, messageProcessingDuration,
		queueDepthGauge, webhookDeliveries, webhookRetries,
		lagGauge, consumerPausedGauge,
	)
}

// ── RabbitMQ consumer ─────────────────────────────────────────────────────────

func connectRabbit() (*amqp.Connection, *amqp.Channel) {
	url := os.Getenv("RABBITMQ_URL")
	if url == "" {
		url = "amqp://guest:guest@rabbitmq:5672/"
	}
	for {
		conn, err := amqp.Dial(url)
		if err != nil {
			log.Printf("[queue-worker] waiting for RabbitMQ: %v", err)
			time.Sleep(3 * time.Second)
			continue
		}
		ch, err := conn.Channel()
		if err != nil {
			conn.Close()
			time.Sleep(3 * time.Second)
			continue
		}
		ch.Qos(10, 0, false)
		log.Printf("[queue-worker] connected to RabbitMQ")
		return conn, ch
	}
}

func deliverWebhook(payload []byte) error {
	webhookURL := os.Getenv("WEBHOOK_URL")
	if webhookURL == "" {
		webhookURL = "http://api-gateway:8080/api/v1/webhook"
	}

	if faultWebhookFail.Load() {
		webhookDeliveries.WithLabelValues("fail").Inc()
		return fmt.Errorf("webhook delivery failed (fault injected)")
	}

	for attempt := 1; attempt <= 3; attempt++ {
		resp, err := http.Post(webhookURL, "application/json", bytes.NewReader(payload))
		if err == nil && resp.StatusCode < 300 {
			webhookDeliveries.WithLabelValues("ok").Inc()
			return nil
		}
		webhookRetries.Inc()
		log.Printf("[queue-worker] webhook attempt %d failed, retrying...", attempt)
		time.Sleep(time.Duration(attempt) * time.Second)
	}
	webhookDeliveries.WithLabelValues("fail").Inc()
	return fmt.Errorf("webhook failed after 3 attempts")
}

func consume(ch *amqp.Channel) {
	q, _ := ch.QueueDeclare("orders", true, false, false, false, nil)
	msgs, _ := ch.Consume(q.Name, "", false, false, false, false, nil)

	for msg := range msgs {
		if faultConsumerPaused.Load() {
			consumerPausedGauge.Set(1)
			msg.Nack(false, true) // requeue
			time.Sleep(500 * time.Millisecond)
			continue
		}
		consumerPausedGauge.Set(0)

		start := time.Now()
		queueDepth.Add(-1)
		if queueDepth.Load() < 0 {
			queueDepth.Store(0)
		}
		queueDepthGauge.Set(float64(queueDepth.Load()))

		// Inject lag
		lag := faultQueueLag.Load()
		if lag > 0 {
			lagGauge.Set(float64(lag))
			time.Sleep(time.Duration(lag) * time.Millisecond)
		} else {
			lagGauge.Set(0)
		}

		// Deliver webhook
		if err := deliverWebhook(msg.Body); err != nil {
			log.Printf("[queue-worker] webhook error: %v", err)
			messagesProcessed.WithLabelValues("error").Inc()
			msg.Nack(false, true)
		} else {
			messagesProcessed.WithLabelValues("ok").Inc()
			processedTotal.Add(1)
			msg.Ack(false)
		}

		messageProcessingDuration.Observe(time.Since(start).Seconds())
	}
}

// ── Fault handlers ────────────────────────────────────────────────────────────

func faultLagHandler(w http.ResponseWriter, r *http.Request) {
	var ms int64
	fmt.Sscanf(r.URL.Query().Get("ms"), "%d", &ms)
	faultQueueLag.Store(ms)
	log.Printf("[FAULT] queue lag set to %dms", ms)
	json.NewEncoder(w).Encode(map[string]interface{}{"fault": "queue_lag", "ms": ms})
}

func faultWebhookHandler(w http.ResponseWriter, r *http.Request) {
	fail := r.URL.Query().Get("fail") == "true"
	faultWebhookFail.Store(fail)
	log.Printf("[FAULT] webhook fail=%v", fail)
	json.NewEncoder(w).Encode(map[string]interface{}{"fault": "webhook", "fail": fail})
}

func faultPauseHandler(w http.ResponseWriter, r *http.Request) {
	pause := r.URL.Query().Get("pause") == "true"
	faultConsumerPaused.Store(pause)
	log.Printf("[FAULT] consumer paused=%v", pause)
	json.NewEncoder(w).Encode(map[string]interface{}{"fault": "consumer_pause", "paused": pause})
}

func faultResetHandler(w http.ResponseWriter, r *http.Request) {
	faultQueueLag.Store(0)
	faultWebhookFail.Store(false)
	faultConsumerPaused.Store(false)
	lagGauge.Set(0)
	consumerPausedGauge.Set(0)
	log.Printf("[FAULT] queue faults reset")
	json.NewEncoder(w).Encode(map[string]string{"status": "queue faults cleared"})
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":          "ok",
		"service":         "queue-worker",
		"processed_total": processedTotal.Load(),
		"queue_depth":     queueDepth.Load(),
	})
}

// ── Main ──────────────────────────────────────────────────────────────────────

func main() {
	conn, ch := connectRabbit()
	defer conn.Close()
	defer ch.Close()

	go consume(ch)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8082"
	}

	r := mux.NewRouter()
	r.HandleFunc("/health", healthHandler).Methods("GET")
	r.HandleFunc("/fault/lag", faultLagHandler).Methods("POST")
	r.HandleFunc("/fault/webhook", faultWebhookHandler).Methods("POST")
	r.HandleFunc("/fault/pause", faultPauseHandler).Methods("POST")
	r.HandleFunc("/fault/reset", faultResetHandler).Methods("POST")
	r.Handle("/metrics", promhttp.Handler())

	log.Printf("[queue-worker] listening on :%s", port)
	http.ListenAndServe(fmt.Sprintf(":%s", port), r)
}
