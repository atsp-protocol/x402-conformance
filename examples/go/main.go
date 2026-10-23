// The smallest paid route on Go gin: the x402 Go SDK's gin middleware with its defaults, one GET /paid at $0.001.
// X402_FACILITATOR_URL names the facilitator (the probe sets it), PORT the port, EXAMPLE_NETWORK the network
// (Solana devnet by default, or eip155:84532 for Base Sepolia). Run: go run .
package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	ginfw "github.com/gin-gonic/gin"
	x402 "github.com/x402-foundation/x402/go"
	x402http "github.com/x402-foundation/x402/go/http"
	ginmw "github.com/x402-foundation/x402/go/http/gin"
	evm "github.com/x402-foundation/x402/go/mechanisms/evm/exact/server"
	svm "github.com/x402-foundation/x402/go/mechanisms/svm/exact/server"
)

func main() {
	network := os.Getenv("EXAMPLE_NETWORK")
	if network == "" {
		network = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
	}
	port := os.Getenv("PORT")
	if port == "" {
		port = "4040"
	}
	payTo := "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"
	var scheme x402.SchemeNetworkServer = svm.NewExactSvmScheme()
	if strings.HasPrefix(network, "eip155:") {
		payTo = "0x209693Bc6afc0C5328bA36FaF03C514EF312287C"
		scheme = evm.NewExactEvmScheme()
	}
	routes := x402http.RoutesConfig{
		"GET /paid": {
			Accepts:     x402http.PaymentOptions{{Scheme: "exact", Price: "$0.001", Network: x402.Network(network), PayTo: payTo}},
			Description: "quickstart",
			MimeType:    "application/json",
		},
	}
	ginfw.SetMode(ginfw.ReleaseMode)
	r := ginfw.New()
	r.Use(ginmw.X402Payment(ginmw.Config{
		Routes:      routes,
		Facilitator: x402http.NewHTTPFacilitatorClient(&x402http.FacilitatorConfig{URL: os.Getenv("X402_FACILITATOR_URL")}),
		Schemes:     []ginmw.SchemeConfig{{Network: x402.Network(network), Server: scheme}},
		Timeout:     30 * time.Second,
	}))
	r.GET("/paid", func(c *ginfw.Context) { c.JSON(http.StatusOK, ginfw.H{"content": "paid content"}) })
	line, _ := json.Marshal(map[string]string{"listening": "http://127.0.0.1:" + port + "/paid"})
	fmt.Println(string(line))
	if err := r.Run("127.0.0.1:" + port); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
