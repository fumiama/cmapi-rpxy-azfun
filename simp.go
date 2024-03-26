package main

import (
	"bytes"
	"crypto/rand"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"reflect"
	"strconv"
	"strings"
	"time"
	"unsafe"

	base14 "github.com/fumiama/go-base16384"
	tea "github.com/fumiama/gofastTEA"
	"golang.org/x/net/http2"
)

var allowedMethods = []string{"GET", "POST", "DELETE"}

var allowedMethodsMap = func() map[string]struct{} {
	m := make(map[string]struct{}, 16)
	for _, s := range allowedMethods {
		m[s] = struct{}{}
	}
	return m
}()

func allow(method string) bool {
	_, ok := allowedMethodsMap[method]
	return ok
}

func main() {
	addr := flag.String("addr", "[::]:8080", "listening adderss")
	key := flag.String("key", "", "tea key (base16384 format)")
	gen := flag.Bool("gen", false, "generate a new key and exit")
	bridge := flag.String("bridge", "", "just proxy requests to this address:port")
	test := flag.Bool("test", false, "test connectivity and exit")
	pipe := flag.String("pipe", "", "pipe mode headers map[string][]string in json")
	flag.Parse()
	if *gen {
		var buf [unsafe.Sizeof(tea.TEA{})]byte
		_, err := rand.Read(buf[:])
		if err != nil {
			panic(err)
		}
		x := base14.EncodeToString(buf[:])
		fmt.Println("New key:", x[:len(x)-3])
		return
	}
	cli := &http.Client{Transport: &http2.Transport{}}
	if *test {
		resp, err := cli.Get(flag.Args()[0])
		if err != nil {
			panic(err)
		}
		defer resp.Body.Close()
		fmt.Println("[T] response code", resp.StatusCode)
		for k, vs := range resp.Header {
			for _, v := range vs {
				fmt.Println("[T] response header", k+":", v)
			}
		}
		data, err := io.ReadAll(resp.Body)
		if err != nil {
			panic(err)
		}
		fmt.Println(base14.BytesToString(data))
		return
	}
	if *pipe != "" {
		type capsule struct {
			C int            // C code
			M string         // M method
			H map[string]any // H headers
			D string         // D url in stdin, base64 data in stdout
		}
		r := capsule{}
		internalerr := func(err error) {
			r.C = http.StatusInternalServerError
			r.H = nil
			r.D = base64.StdEncoding.EncodeToString(base14.StringToBytes(err.Error()))
			_ = json.NewEncoder(os.Stdout).Encode(&r)
		}
		err := json.Unmarshal(base14.StringToBytes(*pipe), &r)
		if err != nil {
			internalerr(err)
			return
		}
		var buf [8]byte
		_, err = io.ReadFull(os.Stdin, buf[:])
		if err != nil {
			internalerr(err)
			return
		}
		n := binary.LittleEndian.Uint64(buf[:])
		if n > 1024*1024*64 { // 64M
			internalerr(errors.New("body len too large: " + strconv.FormatUint(n/1024/1024, 10) + "M"))
			return
		}
		var body io.Reader
		var data []byte
		if n > 0 {
			data = make([]byte, n)
			_, err = io.ReadFull(os.Stdin, data)
			if err != nil {
				internalerr(err)
				return
			}
			body = bytes.NewReader(data)
		}
		req, err := http.NewRequest(r.M, r.D, body)
		if err != nil {
			internalerr(err)
			return
		}
		for k, vs := range r.H {
			lk := strings.ToLower(k)
			if strings.HasPrefix(lk, "x-") {
				continue
			}
			switch x := vs.(type) {
			case string:
				req.Header.Add(k, x)
			case []string:
				for _, v := range x {
					req.Header.Add(k, v)
				}
			default:
				internalerr(errors.New("unsupported H type " + reflect.ValueOf(x).Type().Name()))
				return
			}
		}
		resp, err := cli.Do(req)
		if err != nil {
			internalerr(err)
			return
		}
		defer resp.Body.Close()
		sb := strings.Builder{}
		enc := base64.NewEncoder(base64.StdEncoding, &sb)
		_, err = io.CopyN(enc, resp.Body, resp.ContentLength)
		_ = enc.Close()
		if err != nil {
			internalerr(err)
			return
		}
		r.C = resp.StatusCode
		r.H = make(map[string]any, len(resp.Header)*2)
		for k, vs := range resp.Header {
			if len(vs) == 1 {
				r.H[k] = vs[0]
				continue
			}
			r.H[k] = vs
		}
		r.D = sb.String()
		outbuf := bytes.NewBuffer(data[:0])
		err = json.NewEncoder(outbuf).Encode(&r)
		if err != nil {
			internalerr(err)
			return
		}
		binary.LittleEndian.PutUint64(buf[:], uint64(outbuf.Len()))
		_, _ = io.Copy(os.Stdout, &net.Buffers{buf[:], outbuf.Bytes()})
		return
	}
	if len([]rune(*key)) != 10 {
		panic("Invalid key length " + strconv.Itoa(len([]rune(*key))))
	}
	kb := base14.DecodeFromString(*key + "㴂")
	if uintptr(len(kb)) != unsafe.Sizeof(tea.TEA{}) {
		panic("Invalid decoded key length")
	}
	t := tea.NewTeaCipher(kb)
	if *bridge != "" {
		http.ListenAndServe(*addr, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if getu("[B]", &t, w, r) == "" {
				return
			}
			fmt.Println("[B] allow request from", r.RemoteAddr)
			req, err := http.NewRequest(r.Method, *bridge+r.URL.Path, r.Body)
			if err != nil {
				http.Error(w, "[B] 500 InternalServerError: "+err.Error(), http.StatusInternalServerError)
				return
			}
			for k, vs := range r.Header {
				lk := strings.ToLower(k)
				if strings.HasPrefix(lk, "x-") {
					fmt.Println("[B] ign header", k)
					continue
				}
				for _, v := range vs {
					req.Header.Add(k, v)
					fmt.Println("[B] add header", k+":", v)
				}
			}
			fmt.Println("[B] proxy to", req.URL, "with user agent:", req.UserAgent())
			resp, err := cli.Do(req)
			if err != nil {
				http.Error(w, "[B] 502 BadGateway: "+err.Error(), http.StatusBadGateway)
				return
			}
			fmt.Println("[B] response code", resp.StatusCode)
			defer resp.Body.Close()
			for k, vs := range resp.Header {
				for _, v := range vs {
					w.Header().Add(k, v)
					fmt.Println("[B] add response header", k+":", v)
				}
			}
			w.WriteHeader(resp.StatusCode)
			_, _ = io.Copy(w, resp.Body)
		}))
		return
	}
	http.ListenAndServe(*addr, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		u := getu("[S]", &t, w, r)
		if u == "" {
			return
		}
		fmt.Println("[S] allow request from", r.RemoteAddr)
		data, err := io.ReadAll(r.Body)
		if err != nil {
			http.Error(w, "[S] 404 BadRequest: "+err.Error(), http.StatusBadRequest)
			return
		}
		fmt.Println("[S] read", len(data), "bytes request body")
		if len(data) > 0 {
			data = t.Decrypt(data)
		}
		var dr io.Reader
		if len(data) > 0 {
			dr = bytes.NewReader(data)
		}
		req, err := http.NewRequest(r.Method, u, dr)
		if err != nil {
			http.Error(w, "[S] 500 InternalServerError: "+err.Error(), http.StatusInternalServerError)
			return
		}
		for k, vs := range r.Header {
			lk := strings.ToLower(k)
			if strings.HasPrefix(lk, "x-") || lk == "cmapiauth" {
				fmt.Println("[S] ign header", k)
				continue
			}
			for _, v := range vs {
				req.Header.Add(k, v)
				fmt.Println("[S] add header", k+":", v)
			}
		}
		fmt.Println("[S] request", u, "with user agent:", req.UserAgent())
		resp, err := cli.Do(req)
		if err != nil {
			http.Error(w, "[S] 502 BadGateway: "+err.Error(), http.StatusBadGateway)
			return
		}
		fmt.Println("[S] response code", resp.StatusCode)
		defer resp.Body.Close()
		for k, vs := range resp.Header {
			for _, v := range vs {
				w.Header().Add(k, v)
				fmt.Println("[S] add response header", k+":", v)
			}
		}
		w.WriteHeader(resp.StatusCode)
		_, _ = io.Copy(w, resp.Body)
	}))
}

func getu(head string, t *tea.TEA, w http.ResponseWriter, r *http.Request) string {
	if !allow(r.Method) {
		http.Error(w, head+" 405 MethodNotAllowed: "+r.Method, http.StatusMethodNotAllowed)
		return ""
	}
	u := strings.TrimLeft(r.URL.Path, "/")
	if len(u) == 0 {
		http.Error(w, head+" 404 BadRequest: Empty URL Path", http.StatusBadRequest)
		return ""
	}
	stamp, err := url.QueryUnescape(r.Header.Get("cmapiauth"))
	if err != nil {
		http.Error(w, head+" 401 Unauthorized: "+err.Error(), http.StatusUnauthorized)
		return ""
	}
	data := t.Decrypt(base14.StringToBytes(stamp))
	if len(data) != 8 {
		http.Error(w, head+" 401 Unauthorized: "+base14.EncodeString(stamp), http.StatusUnauthorized)
		return ""
	}
	remot := time.UnixMilli(int64(binary.LittleEndian.Uint64(data)))
	diff := time.Since(remot)
	if diff < 0 {
		diff = -diff
	}
	if diff > time.Second*10 {
		http.Error(w, head+" 401 Unauthorized: Replay Attack\n"+remot.String()+"\n"+hex.EncodeToString(data), http.StatusUnauthorized)
		return ""
	}
	u = base14.DecodeString(u)
	if len(u) == 0 || !strings.HasPrefix(u, "https://") {
		http.Error(w, head+" 404 BadRequest: Invalid URL Path", http.StatusBadRequest)
		return ""
	}
	return u
}
