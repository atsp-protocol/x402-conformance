// XC-56 parity harness for the official Go library (github.com/x402-foundation/x402/go/v2 at the pin).
//
// Reads JSON lines on stdin: one {config}, then one {vector} per line. Writes one outcome line per vector and a last
// {done} line. Built and started by x402conf parity.
//
//	verify      x402Facilitator.Verify(ctx, payloadBytes, requirementsBytes) with the exact EVM scheme registered for
//	            the config's network and a stub signer: GetCode answers no code (so signatures are recovered locally),
//	            every other read fails, and every write is refused and counted. A *x402.VerifyError is the library's
//	            rejection (isValid false); any other error or a panic is recorded as threw.
//	paid-route  GET /paid on a net/http server behind the stock nethttp PaymentMiddleware, on loopback, whose
//	            facilitator is the runner's recording double, with the vector's PAYMENT-SIGNATURE header.
//
// http.DefaultTransport, the facilitator client's transport and the Go resolver refuse and count any connection to
// an address that is not loopback. Go has no process-wide socket hook, so a library that builds its own transport is
// outside this guard. Faults (self-test only) substitute the library's decision at this boundary, except
// wildcard-network, which registers two networks of the family.
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"net"
	"net/http"
	"os"
	"runtime/debug"
	"strings"
	"sync/atomic"
	"time"

	x402 "github.com/x402-foundation/x402/go/v2"
	x402http "github.com/x402-foundation/x402/go/v2/http"
	nethttpmw "github.com/x402-foundation/x402/go/v2/http/nethttp"
	"github.com/x402-foundation/x402/go/v2/mechanisms/evm"
	exactfacilitator "github.com/x402-foundation/x402/go/v2/mechanisms/evm/exact/facilitator"
	exactserver "github.com/x402-foundation/x402/go/v2/mechanisms/evm/exact/server"
)

const module = "github.com/x402-foundation/x402/go/v2"

var (
	outbound, reads, writes atomic.Int64
	loopback                = map[string]bool{"127.0.0.1": true, "::1": true, "localhost": true}
)

func guardedDial(ctx context.Context, network, addr string) (net.Conn, error) {
	host, _, err := net.SplitHostPort(addr)
	if err != nil || !loopback[host] {
		outbound.Add(1)
		return nil, fmt.Errorf("parity guard: refused a connection to %s", addr)
	}
	return (&net.Dialer{Timeout: 10 * time.Second}).DialContext(ctx, network, addr)
}

func installGuard() *http.Client {
	tr := &http.Transport{DialContext: guardedDial, Proxy: nil}
	http.DefaultTransport = tr
	net.DefaultResolver = &net.Resolver{PreferGo: true, Dial: guardedDial}
	return &http.Client{Transport: tr, Timeout: 15 * time.Second}
}

// stubSigner is an evm.FacilitatorEvmSigner with no chain behind it.
type stubSigner struct{}

var errNoChain = errors.New("parity stub signer: no chain")

func (stubSigner) GetAddresses() []string {
	reads.Add(1)
	return []string{"0x209693Bc6afc0C5328bA36FaF03C514EF312287C"}
}
func (stubSigner) ReadContract(context.Context, string, []byte, string, ...interface{}) (interface{}, error) {
	reads.Add(1)
	return nil, errNoChain
}
func (stubSigner) VerifyTypedData(context.Context, string, evm.TypedDataDomain, map[string][]evm.TypedDataField, string,
	map[string]interface{}, []byte) (bool, error) {
	reads.Add(1)
	return false, errNoChain
}
func (stubSigner) WriteContract(context.Context, string, []byte, string, []byte, ...interface{}) (string, error) {
	writes.Add(1)
	return "", errors.New("parity stub signer: writes are refused")
}
func (stubSigner) SendTransaction(context.Context, string, []byte) (string, error) {
	writes.Add(1)
	return "", errors.New("parity stub signer: writes are refused")
}
func (stubSigner) WaitForTransactionReceipt(context.Context, string) (*evm.TransactionReceipt, error) {
	writes.Add(1)
	return nil, errors.New("parity stub signer: writes are refused")
}
func (stubSigner) GetBalance(context.Context, string, string) (*big.Int, error) {
	reads.Add(1)
	return nil, errNoChain
}
func (stubSigner) GetChainID(context.Context) (*big.Int, error) {
	reads.Add(1)
	return nil, errNoChain
}
func (stubSigner) GetCode(context.Context, string) ([]byte, error) {
	reads.Add(1)
	return []byte{}, nil
}

type config struct {
	Network        string `json:"network"`
	PayTo          string `json:"payTo"`
	FacilitatorURL string `json:"facilitator_url"`
	Fault          string `json:"fault"`
	ProbeOutbound  bool   `json:"probe_outbound"`
}

type vector struct {
	ID     string `json:"id"`
	Target string `json:"target"`
	Input  struct {
		Payload      json.RawMessage `json:"payload"`
		Requirements json.RawMessage `json:"requirements"`
		Header       string          `json:"header"`
	} `json:"input"`
}

type outcome struct {
	Vector        string  `json:"vector"`
	Status        *int    `json:"status"`
	ContentType   *string `json:"content_type"`
	IsValid       *bool   `json:"isValid"`
	InvalidReason *string `json:"invalidReason"`
	Threw         bool    `json:"threw"`
	Error         *string `json:"error"`
}

func str(s string) *string {
	if len(s) > 200 {
		s = s[:200]
	}
	return &s
}

func verify(f *x402.X402Facilitator, v vector, cfg config) (out outcome) {
	out.Vector = v.ID
	defer func() {
		if r := recover(); r != nil {
			out.Threw, out.IsValid, out.InvalidReason = true, nil, nil
			out.Error = str(fmt.Sprintf("panic: %v", r))
		}
		if cfg.Fault == "swallow-reason" && out.IsValid != nil && !*out.IsValid {
			out.InvalidReason = nil
		}
	}()
	resp, err := f.Verify(context.Background(), v.Input.Payload, v.Input.Requirements)
	var ve *x402.VerifyError
	switch {
	case err == nil:
		ok := resp.IsValid
		out.IsValid = &ok
		if resp.InvalidReason != "" {
			out.InvalidReason = str(resp.InvalidReason)
		}
	case errors.As(err, &ve):
		no := false
		out.IsValid, out.InvalidReason = &no, str(ve.InvalidReason)
	default:
		out.Threw, out.Error = true, str(err.Error())
	}
	return out
}

func startRoute(cfg config, client *http.Client) (string, *http.Server, error) {
	fc := x402http.NewHTTPFacilitatorClient(&x402http.FacilitatorConfig{URL: cfg.FacilitatorURL, HTTPClient: client})
	routes := x402http.RoutesConfig{"GET /paid": {
		Accepts:     x402http.PaymentOptions{{Scheme: "exact", Price: "$0.001", Network: x402.Network(cfg.Network), PayTo: cfg.PayTo}},
		Description: "parity", MimeType: "application/json",
	}}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /paid", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"content":"paid content"}`))
	})
	mw := nethttpmw.PaymentMiddlewareFromConfig(routes, nethttpmw.WithFacilitatorClient(fc),
		nethttpmw.WithScheme(x402.Network(cfg.Network), exactserver.NewExactEvmScheme()))
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return "", nil, err
	}
	srv := &http.Server{Handler: mw(mux), ReadHeaderTimeout: 10 * time.Second}
	go func() { _ = srv.Serve(ln) }()
	return "http://" + ln.Addr().String() + "/paid", srv, nil
}

func paidRoute(client *http.Client, url string, v vector, cfg config) (out outcome) {
	out.Vector = v.ID
	req, _ := http.NewRequest(http.MethodGet, url, nil)
	req.Header.Set("PAYMENT-SIGNATURE", v.Input.Header)
	resp, err := client.Do(req)
	if err != nil {
		out.Error = str("no answer: " + err.Error())
		return out
	}
	_, _ = io.Copy(io.Discard, resp.Body)
	_ = resp.Body.Close()
	status := resp.StatusCode
	if cfg.Fault == "status" && status >= 400 && status < 500 {
		status = 500
	}
	out.Status = &status
	if ct := resp.Header.Values("Content-Type"); len(ct) > 0 {
		out.ContentType = str(strings.Join(ct, ", "))
	}
	return out
}

func version() string {
	if bi, ok := debug.ReadBuildInfo(); ok {
		for _, d := range bi.Deps {
			if d.Path == module {
				return d.Version
			}
		}
	}
	return ""
}

func main() {
	client := installGuard()
	var cfg *config
	var vectors []vector
	sc := bufio.NewScanner(os.Stdin)
	sc.Buffer(make([]byte, 1<<20), 1<<24)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" {
			continue
		}
		var msg struct {
			Config *config `json:"config"`
			Vector *vector `json:"vector"`
		}
		if err := json.Unmarshal([]byte(line), &msg); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		if msg.Config != nil {
			cfg = msg.Config
		}
		if msg.Vector != nil {
			vectors = append(vectors, *msg.Vector)
		}
	}
	if cfg == nil {
		fmt.Fprintln(os.Stderr, "no config line")
		os.Exit(1)
	}
	if cfg.ProbeOutbound {
		// TEST-NET-1 on port 80: the guard must refuse and count it.
		if resp, err := http.Get("http://192.0.2.1/"); err == nil {
			_ = resp.Body.Close()
		}
	}
	networks := []x402.Network{x402.Network(cfg.Network)}
	if cfg.Fault == "wildcard-network" {
		networks = append(networks, "eip155:84533")
	}
	f := x402.Newx402Facilitator().Register(networks, exactfacilitator.NewExactEvmScheme(stubSigner{}, nil))
	var url string
	var srv *http.Server
	for _, v := range vectors {
		if v.Target == "paid-route" && srv == nil {
			var err error
			if url, srv, err = startRoute(*cfg, client); err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
		}
	}
	enc := json.NewEncoder(os.Stdout)
	for _, v := range vectors {
		var out outcome
		if v.Target == "verify" {
			out = verify(f, v, *cfg)
		} else {
			out = paidRoute(client, url, v, *cfg)
		}
		_ = enc.Encode(out)
	}
	if srv != nil {
		_ = srv.Close()
	}
	time.Sleep(50 * time.Millisecond) // let a background asset check settle before counting
	_ = enc.Encode(map[string]interface{}{"done": true, "sdk": "go", "version": version(),
		"outbound_attempts": outbound.Load(), "signer_reads": reads.Load(), "signer_writes": writes.Load()})
}
