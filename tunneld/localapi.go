package main

import (
	"context"
	"fmt"
	"io"
	"net"
	"net/http"
	"strconv"
	"sync/atomic"
	"time"

	"tailscale.com/client/local"
	"tailscale.com/tsnet"
)

// localAPI is the loopback control surface consumed by the Python CLI in
// place of `tailscale status --json` / `tailscale serve status --json`.
type localAPI struct {
	srv        *tsnet.Server
	lc         *local.Client
	forwardsUp atomic.Bool
}

func (a *localAPI) markForwardsUp() { a.forwardsUp.Store(true) }

func (a *localAPI) handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /status", a.handleStatus)
	mux.HandleFunc("GET /health", a.handleHealth)
	mux.HandleFunc("GET /probe", a.handleProbe)
	return mux
}

// handleStatus emits ipnstate.Status, which marshals to the same JSON schema
// as `tailscale status --json` (Self.DNSName, Self.TailscaleIPs, Peer,
// CurrentTailnet.MagicDNSSuffix, ...), so existing parsers keep working.
func (a *localAPI) handleStatus(w http.ResponseWriter, r *http.Request) {
	st, err := a.lc.Status(r.Context())
	if err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{"error": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, st)
}

func (a *localAPI) handleHealth(w http.ResponseWriter, r *http.Request) {
	payload := map[string]any{
		"forwards_up": a.forwardsUp.Load(),
		"forwards": map[string]string{
			strconv.Itoa(openbaseTailnetPort): "http://" + openbaseLocalAddr,
			strconv.Itoa(livekitTailnetPort):  "tcp://" + livekitLocalAddr,
		},
	}
	st, err := a.lc.Status(r.Context())
	if err != nil {
		payload["backend_state"] = "Unknown"
		payload["error"] = err.Error()
		writeJSON(w, http.StatusOK, payload)
		return
	}
	payload["backend_state"] = st.BackendState
	payload["auth_url"] = st.AuthURL
	if st.Self != nil {
		payload["self_dns_name"] = st.Self.DNSName
	}
	writeJSON(w, http.StatusOK, payload)
}

// handleProbe dials a tailnet peer through the embedded node and relays the
// response, because the host network stack can no longer reach tailnet IPs.
// Example: /probe?host=phone.tailxxxx.ts.net&port=18080&path=/api/health/
func (a *localAPI) handleProbe(w http.ResponseWriter, r *http.Request) {
	host := r.URL.Query().Get("host")
	if host == "" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "missing host parameter"})
		return
	}
	port := r.URL.Query().Get("port")
	if port == "" {
		port = strconv.Itoa(openbaseTailnetPort)
	}
	path := r.URL.Query().Get("path")
	if path == "" {
		path = "/api/health/"
	}

	client := &http.Client{
		Timeout: probeTimeout,
		Transport: &http.Transport{
			DialContext: func(ctx context.Context, network, addr string) (conn net.Conn, err error) {
				return a.srv.Dial(ctx, network, addr)
			},
		},
	}
	url := fmt.Sprintf("http://%s:%s%s", host, port, path)
	start := time.Now()
	resp, err := client.Get(url)
	if err != nil {
		writeJSON(w, http.StatusOK, map[string]any{
			"url": url, "ok": false, "error": err.Error(),
		})
		return
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	writeJSON(w, http.StatusOK, map[string]any{
		"url":         url,
		"ok":          resp.StatusCode == http.StatusOK,
		"status_code": resp.StatusCode,
		"body":        string(body),
		"elapsed_ms":  time.Since(start).Milliseconds(),
	})
}
