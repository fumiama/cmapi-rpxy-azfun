package main

import (
	"bytes"
	"crypto/tls"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"reflect"
	"strconv"
	"strings"

	base14 "github.com/fumiama/go-base16384"
)

func main() {
	pipe := flag.String("pipe", "", "pipe mode headers map[string][]string in json")
	flag.Parse()
	cli := &http.Client{Transport: &http.Transport{
		TLSClientConfig: &tls.Config{
			InsecureSkipVerify: true,
		},
	}}
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
		defer func() {
			if x := recover(); x != nil {
				internalerr(errors.New(fmt.Sprint("recovered: ", x)))
			}
		}()
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
		_, _ = io.Copy(os.Stdout, outbuf)
		return
	}
}
