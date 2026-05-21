"""
Network Agent — Full network scanning, monitoring, WiFi, VPN, proxy, and HTTP tooling.
Real implementations: port scanning, traceroute, bandwidth monitoring,
packet capture hooks, HTTP client, WebSocket ping, DNS enumeration,
IP geolocation, SSL cert inspection, and Windows WiFi management.
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
import winreg
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.base_agent import BaseAgent

logger = logging.getLogger("NetworkAgent")

IS_WINDOWS = os.name == "nt"
IS_LINUX   = sys.platform.startswith("linux")
IS_MAC     = sys.platform == "darwin"


# ─────────────────────────────────────────────────────────────────────────────
#  Data Classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PortScanResult:
    host:   str
    port:   int
    open:   bool
    banner: str = ""
    service: str = ""


@dataclass
class NetworkHost:
    ip:       str
    hostname: str
    mac:      str
    open_ports: List[int] = field(default_factory=list)
    os_guess:   str = ""


@dataclass
class HTTPResponse:
    url:         str
    status_code: int
    headers:     Dict[str, str]
    body:        str
    elapsed_ms:  float
    redirects:   int
    ssl_valid:   Optional[bool]


# ─────────────────────────────────────────────────────────────────────────────
#  Network Agent
# ─────────────────────────────────────────────────────────────────────────────

class NetworkAgent(BaseAgent):
    """
    Complete network operations and security scanning agent.
    Performs port scanning, HTTP requests, DNS, SSL verification,
    and local network management.
    """

    # Common service port map
    SERVICE_MAP = {
        21: "FTP",       22: "SSH",      23: "Telnet",   25: "SMTP",
        53: "DNS",       80: "HTTP",     110: "POP3",    143: "IMAP",
        443: "HTTPS",    445: "SMB",     587: "SMTP-S",  993: "IMAP-S",
        995: "POP3-S",   1433: "MSSQL",  1521: "Oracle",
        3306: "MySQL",   3389: "RDP",    5432: "PostgreSQL",
        5900: "VNC",     6379: "Redis",  8080: "HTTP-Alt",
        8443: "HTTPS-Alt", 8888: "Jupyter", 9200: "Elasticsearch",
        27017: "MongoDB", 5672: "AMQP",  4369: "Erlang",
    }

    COMMON_PORTS = [21, 22, 23, 25, 53, 80, 110, 143, 443, 445, 587,
                    993, 995, 1433, 3306, 3389, 5432, 5900, 6379,
                    8080, 8443, 9200, 27017]

    def __init__(self):
        super().__init__()
        self._requests = self._try_import("requests")
        self._psutil   = self._try_import("psutil")
        self._scan_history: List[Dict] = []
        self._http_history: List[Dict] = []
        self.handlers = {
            # Port scanning
            "scan_port":          self.scan_single_port,
            "scan_ports":         self.scan_port_range,
            "scan_common_ports":  self.scan_common_ports,
            "scan_host":          self.full_host_scan,
            "scan_subnet":        self.scan_subnet,
            # Host discovery
            "discover_hosts":     self.discover_hosts,
            "ping_sweep":         self.ping_sweep,
            "get_local_hosts":    self.get_local_network_hosts,
            # DNS
            "dns_lookup":         self.dns_lookup,
            "reverse_dns":        self.reverse_dns,
            "dns_mx":             self.dns_mx_lookup,
            "dns_txt":            self.dns_txt_lookup,
            "dns_enumerate":      self.dns_enumerate,
            "check_spf":          self.check_spf,
            "check_dmarc":        self.check_dmarc,
            # HTTP
            "http_get":           self.http_get,
            "http_post":          self.http_post,
            "http_put":           self.http_put,
            "http_delete":        self.http_delete,
            "http_head":          self.http_head,
            "check_url":          self.check_url_accessible,
            "download_file":      self.download_file,
            "check_redirect":     self.check_redirects,
            "http_status":        self.check_http_status,
            # SSL/TLS
            "check_ssl":          self.check_ssl_certificate,
            "get_ssl_info":       self.get_ssl_details,
            # WiFi
            "scan_wifi":          self.scan_wifi,
            "get_wifi_profile":   self.get_wifi_profile,
            "connect_wifi":       self.connect_wifi,
            "disconnect_wifi":    self.disconnect_wifi,
            "get_wifi_password":  self.get_saved_wifi_password,
            "forget_wifi":        self.forget_wifi_network,
            # IP / Geolocation
            "get_public_ip":      self.get_public_ip,
            "geolocate_ip":       self.geolocate_ip,
            "get_ip_info":        self.get_ip_info,
            "is_vpn":             self.detect_vpn,
            "ip_reputation":      self.check_ip_reputation,
            # Monitoring
            "monitor_bandwidth":  self.monitor_bandwidth,
            "get_connections":    self.get_active_connections,
            "get_open_ports":     self.get_open_listening_ports,
            "monitor_host":       self.monitor_host_availability,
            "latency_test":       self.latency_test,
            # Proxy
            "set_proxy":          self.set_system_proxy,
            "clear_proxy":        self.clear_system_proxy,
            "get_proxy":          self.get_current_proxy,
            "test_proxy":         self.test_proxy,
            # Traceroute / Path
            "traceroute":         self.traceroute,
            "mtr":                self.mtr_trace,
            # Misc
            "whois":              self.whois_lookup,
            "get_route_table":    self.get_route_table,
            "flush_arp":          self.flush_arp_cache,
            "get_arp":            self.get_arp_table,
            "netstat":            self.netstat_summary,
            "get_history":        self._get_history,
        }


    # ─────────────────────────────────────────────────────────────────────────
    #  Port Scanning
    # ─────────────────────────────────────────────────────────────────────────

    def scan_single_port(self, host: str, port: int,
                          timeout: float = 1.0,
                          grab_banner: bool = True) -> Dict:
        """Check if a single TCP port is open."""
        result = self._tcp_connect(host, port, timeout)
        banner = ""
        if result and grab_banner:
            banner = self._grab_banner(host, port, timeout=1.0)
        service = self.SERVICE_MAP.get(port, "unknown")
        self._log_scan(host, [port], [result])
        return {
            "success":  True,
            "host":     host,
            "port":     port,
            "open":     result,
            "service":  service,
            "banner":   banner,
        }

    def scan_port_range(self, host: str,
                         start_port: int = 1,
                         end_port: int = 1024,
                         timeout: float = 0.5,
                         max_threads: int = 100) -> Dict:
        """Scan a range of ports concurrently."""
        ports   = list(range(start_port, end_port + 1))
        return self._parallel_scan(host, ports, timeout, max_threads)

    def scan_common_ports(self, host: str,
                           timeout: float = 0.5,
                           max_threads: int = 50) -> Dict:
        """Scan the most common ports."""
        return self._parallel_scan(host, self.COMMON_PORTS, timeout, max_threads)

    def full_host_scan(self, host: str, timeout: float = 0.5) -> Dict:
        """Full host scan: resolve, ping, common ports, OS guess."""
        # Resolve
        try:
            ip = socket.gethostbyname(host)
        except socket.gaierror:
            return {"success": False, "error": f"Cannot resolve: {host}"}

        ping_r    = self.latency_test(host, count=3)
        port_r    = self.scan_common_ports(host, timeout=timeout)
        ssl_r     = self.check_ssl_certificate(host) if port_r.get("open_ports") and 443 in port_r.get("open_ports", []) else {}

        return {
            "success":    True,
            "host":       host,
            "ip":         ip,
            "reachable":  ping_r.get("reachable", False),
            "avg_ms":     ping_r.get("avg_ms"),
            "open_ports": port_r.get("open_ports", []),
            "services":   port_r.get("services", {}),
            "ssl":        ssl_r,
            "scanned_at": datetime.now().isoformat(),
        }

    def scan_subnet(self, subnet: str = None,
                     timeout: float = 0.3,
                     ports: List[int] = None) -> Dict:
        """Scan all hosts in a /24 subnet. Auto-detect local subnet if not given."""
        if not subnet:
            subnet = self._detect_local_subnet()
        if not subnet:
            return {"success": False, "error": "Could not detect local subnet"}

        # Build IPs for /24
        base   = ".".join(subnet.split(".")[:3])
        ips    = [f"{base}.{i}" for i in range(1, 255)]
        ports  = ports or [22, 80, 443, 3389, 445]

        alive: List[Dict] = []

        def scan_one(ip: str) -> Optional[Dict]:
            if self._is_alive(ip, timeout=timeout):
                open_p = [p for p in ports if self._tcp_connect(ip, p, timeout)]
                try:
                    hostname = socket.gethostbyaddr(ip)[0]
                except Exception:
                    hostname = ""
                return {"ip": ip, "hostname": hostname, "open_ports": open_p}
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as ex:
            futures = {ex.submit(scan_one, ip): ip for ip in ips}
            for f in concurrent.futures.as_completed(futures):
                r = f.result()
                if r:
                    alive.append(r)

        alive.sort(key=lambda x: [int(p) for p in x["ip"].split(".")])
        return {
            "success":    True,
            "subnet":     subnet,
            "hosts_found": len(alive),
            "hosts":      alive,
        }

    def _parallel_scan(self, host: str, ports: List[int],
                        timeout: float, max_threads: int) -> Dict:
        open_ports:  List[int] = []
        closed_ports: List[int] = []

        def check(p: int) -> Tuple[int, bool]:
            return (p, self._tcp_connect(host, p, timeout))

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as ex:
            for port, is_open in ex.map(check, ports):
                (open_ports if is_open else closed_ports).append(port)

        open_ports.sort()
        services = {p: self.SERVICE_MAP.get(p, "?") for p in open_ports}
        self._log_scan(host, ports, [p in open_ports for p in ports])
        return {
            "success":      True,
            "host":         host,
            "open_ports":   open_ports,
            "open_count":   len(open_ports),
            "closed_count": len(closed_ports),
            "services":     services,
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  Host Discovery
    # ─────────────────────────────────────────────────────────────────────────

    def discover_hosts(self, subnet: str = None, timeout: float = 0.2) -> Dict:
        """Discover live hosts via TCP on port 80/443/22."""
        return self.scan_subnet(subnet, timeout=timeout, ports=[22, 80, 443])

    def ping_sweep(self, subnet: str = None, timeout: float = 1.0) -> Dict:
        """ICMP ping sweep using OS ping."""
        if not subnet:
            subnet = self._detect_local_subnet() or "192.168.1"

        base = ".".join(subnet.split(".")[:3])
        ips  = [f"{base}.{i}" for i in range(1, 255)]
        alive: List[str] = []

        def ping_one(ip: str) -> Optional[str]:
            return ip if self._is_alive(ip, timeout) else None

        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as ex:
            for result in ex.map(ping_one, ips):
                if result:
                    alive.append(result)

        return {"success": True, "subnet": subnet, "alive": sorted(alive),
                "count": len(alive)}

    def get_local_network_hosts(self) -> Dict:
        """Get hosts from ARP table (already discovered by OS)."""
        return self.get_arp_table()

    # ─────────────────────────────────────────────────────────────────────────
    #  DNS
    # ─────────────────────────────────────────────────────────────────────────

    def dns_lookup(self, hostname: str,
                    record_type: str = "A") -> Dict:
        """Resolve hostname. For advanced record types, falls back to dig/nslookup."""
        try:
            results = socket.getaddrinfo(hostname, None)
            ips     = list({r[4][0] for r in results})
            return {"success": True, "hostname": hostname,
                    "type": record_type, "results": ips}
        except socket.gaierror as e:
            return {"success": False, "error": str(e), "hostname": hostname}

    def reverse_dns(self, ip: str) -> Dict:
        """Reverse DNS lookup for an IP address."""
        try:
            hostname = socket.gethostbyaddr(ip)[0]
            return {"success": True, "ip": ip, "hostname": hostname}
        except socket.herror as e:
            return {"success": False, "ip": ip, "error": str(e)}

    def dns_mx_lookup(self, domain: str) -> Dict:
        """Look up MX records for a domain using nslookup/dig."""
        return self._dns_query(domain, "MX")

    def dns_txt_lookup(self, domain: str) -> Dict:
        """Look up TXT records (SPF, DKIM, etc.)."""
        return self._dns_query(domain, "TXT")

    def dns_enumerate(self, domain: str) -> Dict:
        """Enumerate common subdomains for a domain."""
        subdomains = [
            "www", "mail", "ftp", "smtp", "pop", "imap", "vpn",
            "remote", "webmail", "admin", "api", "dev", "test",
            "staging", "blog", "shop", "portal", "cdn", "ns1", "ns2",
        ]
        found: List[Dict] = []
        for sub in subdomains:
            host = f"{sub}.{domain}"
            try:
                ip = socket.gethostbyname(host)
                found.append({"subdomain": host, "ip": ip})
            except socket.gaierror:
                pass
        return {
            "success": True,
            "domain":  domain,
            "found":   found,
            "count":   len(found),
        }

    def check_spf(self, domain: str) -> Dict:
        """Check if domain has a valid SPF record."""
        r = self.dns_txt_lookup(domain)
        if not r["success"]:
            return r
        txt_records = r.get("output", "")
        has_spf = "v=spf1" in txt_records.lower()
        return {
            "success":  True,
            "domain":   domain,
            "has_spf":  has_spf,
            "spf_record": next((l for l in txt_records.splitlines()
                                if "v=spf1" in l.lower()), ""),
        }

    def check_dmarc(self, domain: str) -> Dict:
        """Check DMARC policy record."""
        r = self._dns_query(f"_dmarc.{domain}", "TXT")
        output = r.get("output", "")
        has_dmarc = "v=DMARC1" in output.upper()
        return {
            "success":    True,
            "domain":     domain,
            "has_dmarc":  has_dmarc,
            "policy":     re.search(r"p=(\w+)", output, re.IGNORECASE).group(1)
                          if has_dmarc and re.search(r"p=(\w+)", output, re.IGNORECASE) else "",
        }

    def _dns_query(self, name: str, record_type: str) -> Dict:
        """Use nslookup/dig to query DNS record."""
        dig = shutil.which("dig")
        if dig:
            r = subprocess.run(
                [dig, "+short", name, record_type],
                capture_output=True, text=True, timeout=30,
            )
            return {"success": r.returncode == 0, "output": r.stdout.strip(),
                    "name": name, "type": record_type}

        nslookup = shutil.which("nslookup")
        if nslookup:
            r = subprocess.run(
                [nslookup, "-type=" + record_type, name],
                capture_output=True, text=True, timeout=30,
            )
            return {"success": r.returncode == 0, "output": r.stdout.strip(),
                    "name": name, "type": record_type}

        return {"success": False, "error": "dig and nslookup not found"}

    # ─────────────────────────────────────────────────────────────────────────
    #  HTTP Client
    # ─────────────────────────────────────────────────────────────────────────

    def _http_request(self, method: str, url: str,
                       headers: Dict = None, body: Any = None,
                       timeout: float = 30.0,
                       follow_redirects: bool = True,
                       verify_ssl: bool = True) -> Dict:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        start     = time.monotonic()
        redirects = 0

        if self._requests:
            try:
                resp = self._requests.request(
                    method, url,
                    headers=headers or {},
                    data=body if isinstance(body, (str, bytes)) else None,
                    json=body if isinstance(body, dict) else None,
                    timeout=timeout,
                    allow_redirects=follow_redirects,
                    verify=verify_ssl,
                )
                elapsed    = (time.monotonic() - start) * 1000
                redirects  = len(resp.history)
                text       = resp.text[:100_000]
                self._log_http(method, url, resp.status_code, elapsed)
                return {
                    "success":    resp.ok,
                    "url":        resp.url,
                    "status":     resp.status_code,
                    "headers":    dict(resp.headers),
                    "body":       text,
                    "elapsed_ms": round(elapsed, 1),
                    "redirects":  redirects,
                    "ssl_valid":  True,
                    "encoding":   resp.encoding,
                    "content_type": resp.headers.get("Content-Type", ""),
                }
            except self._requests.exceptions.SSLError as e:
                return {"success": False, "error": f"SSL error: {e}", "url": url}
            except self._requests.exceptions.Timeout:
                return {"success": False, "error": f"Request timed out after {timeout}s"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # Fallback: urllib
        try:
            req = urllib.request.Request(url, method=method,
                                          headers=headers or {})
            if body:
                if isinstance(body, dict):
                    body = json.dumps(body).encode()
                    req.add_header("Content-Type", "application/json")
                req.data = body if isinstance(body, bytes) else body.encode()

            ctx = ssl._create_unverified_context() if not verify_ssl else None
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                elapsed  = (time.monotonic() - start) * 1000
                text     = resp.read(100_000).decode("utf-8", errors="replace")
                self._log_http(method, url, resp.status, elapsed)
                return {
                    "success":    True,
                    "url":        resp.url,
                    "status":     resp.status,
                    "headers":    dict(resp.headers),
                    "body":       text,
                    "elapsed_ms": round(elapsed, 1),
                    "redirects":  0,
                }
        except urllib.error.HTTPError as e:
            return {"success": False, "status": e.code, "error": str(e), "url": url}
        except Exception as e:
            return {"success": False, "error": str(e), "url": url}

    def http_get(self, url: str, headers: Dict = None,
                  params: Dict = None, timeout: float = 30.0,
                  verify_ssl: bool = True) -> Dict:
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        return self._http_request("GET", url, headers=headers,
                                   timeout=timeout, verify_ssl=verify_ssl)

    def http_post(self, url: str, body: Any = None,
                   headers: Dict = None, json_body: Dict = None,
                   timeout: float = 30.0) -> Dict:
        data = json_body or body
        h    = headers or {}
        if json_body and "Content-Type" not in h:
            h["Content-Type"] = "application/json"
        return self._http_request("POST", url, headers=h, body=data, timeout=timeout)

    def http_put(self, url: str, body: Any = None,
                  headers: Dict = None, timeout: float = 30.0) -> Dict:
        return self._http_request("PUT", url, headers=headers,
                                   body=body, timeout=timeout)

    def http_delete(self, url: str, headers: Dict = None,
                     timeout: float = 30.0) -> Dict:
        return self._http_request("DELETE", url, headers=headers, timeout=timeout)

    def http_head(self, url: str, headers: Dict = None,
                   timeout: float = 10.0) -> Dict:
        return self._http_request("HEAD", url, headers=headers, timeout=timeout)

    def check_url_accessible(self, url: str, timeout: float = 10.0) -> Dict:
        r = self.http_head(url, timeout=timeout)
        return {
            "success":    True,
            "url":        url,
            "accessible": r.get("success", False),
            "status":     r.get("status"),
            "elapsed_ms": r.get("elapsed_ms"),
        }

    def download_file(self, url: str, save_path: str = None,
                       chunk_size: int = 8192) -> Dict:
        """Download a file from URL to disk."""
        save_path = save_path or os.path.join(
            os.path.expanduser("~/Downloads"),
            url.rstrip("/").split("/")[-1] or "download"
        )
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        try:
            if self._requests:
                with self._requests.get(url, stream=True, timeout=60) as resp:
                    resp.raise_for_status()
                    total = 0
                    with open(save_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size):
                            f.write(chunk)
                            total += len(chunk)
            else:
                urllib.request.urlretrieve(url, save_path)
                total = Path(save_path).stat().st_size

            elapsed = time.monotonic() - start
            return {
                "success":   True,
                "url":       url,
                "saved_to":  save_path,
                "size_mb":   round(total / 1e6, 3),
                "speed_mbps": round((total / 1e6) / elapsed, 2) if elapsed > 0 else 0,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "url": url}

    def check_redirects(self, url: str) -> Dict:
        """Follow redirect chain and report all hops."""
        if self._requests:
            chain: List[Dict] = []
            try:
                resp = self._requests.get(url, allow_redirects=True, timeout=15)
                for r in resp.history:
                    chain.append({"url": r.url, "status": r.status_code})
                chain.append({"url": resp.url, "status": resp.status_code})
                return {"success": True, "redirects": len(resp.history),
                        "chain": chain, "final_url": resp.url}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "requests required for redirect tracing"}

    def check_http_status(self, url: str) -> Dict:
        r = self.http_head(url)
        code = r.get("status", 0)
        return {
            "success": True,
            "url":     url,
            "status":  code,
            "ok":      200 <= code < 400,
            "category": {
                2: "2xx OK",
                3: "3xx Redirect",
                4: "4xx Client Error",
                5: "5xx Server Error",
            }.get(code // 100, "Unknown"),
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  SSL / TLS
    # ─────────────────────────────────────────────────────────────────────────

    def check_ssl_certificate(self, host: str,
                                port: int = 443,
                                timeout: float = 5.0) -> Dict:
        """Check if SSL cert is valid and not expired."""
        try:
            ctx  = ssl.create_default_context()
            conn = ctx.wrap_socket(
                socket.create_connection((host, port), timeout=timeout),
                server_hostname=host,
            )
            cert = conn.getpeercert()
            conn.close()

            not_after  = ssl.cert_time_to_seconds(cert["notAfter"])
            not_before = ssl.cert_time_to_seconds(cert["notBefore"])
            now        = time.time()
            days_left  = int((not_after - now) / 86400)

            return {
                "success":    True,
                "host":       host,
                "valid":      True,
                "expires":    cert["notAfter"],
                "issued":     cert["notBefore"],
                "days_left":  days_left,
                "expired":    days_left < 0,
                "expiring_soon": 0 < days_left < 30,
                "issuer":     dict(x[0] for x in cert.get("issuer", [])),
                "subject":    dict(x[0] for x in cert.get("subject", [])),
                "san":        [v for t, v in cert.get("subjectAltName", [])
                               if t == "DNS"],
            }
        except ssl.SSLCertVerificationError as e:
            return {"success": True, "host": host, "valid": False,
                    "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e), "host": host}

    def get_ssl_details(self, host: str, port: int = 443) -> Dict:
        """Get extended SSL details including cipher suite and protocol."""
        try:
            ctx  = ssl.create_default_context()
            sock = ctx.wrap_socket(
                socket.create_connection((host, port), timeout=5),
                server_hostname=host,
            )
            cipher  = sock.cipher()
            version = sock.version()
            cert    = sock.getpeercert()
            sock.close()
            return {
                "success": True,
                "host":    host,
                "protocol": version,
                "cipher":   cipher[0] if cipher else "",
                "bits":     cipher[2] if cipher else 0,
                "cert":     {
                    "subject": dict(x[0] for x in cert.get("subject", [])),
                    "issuer":  dict(x[0] for x in cert.get("issuer", [])),
                    "expires": cert.get("notAfter"),
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────────────────────────────────────
    #  WiFi
    # ─────────────────────────────────────────────────────────────────────────

    def scan_wifi(self) -> Dict:
        """Scan for nearby WiFi networks."""
        def _scan_win():
            r = subprocess.run(
                ["netsh", "wlan", "show", "networks", "mode=Bssid"],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode != 0:
                return {"success": False, "error": r.stderr}

            networks: List[Dict] = []
            current: Dict        = {}
            
            _PREFIX_MAP = {
                "SSID": lambda v: current.update({"ssid": v.split(":", 1)[1].strip()}) if "BSSID" not in v else None,
                "Authentication": lambda v: current.update({"auth": v.split(":", 1)[1].strip()}),
                "Encryption":     lambda v: current.update({"encryption": v.split(":", 1)[1].strip()}),
                "Signal":         lambda v: current.update({"signal_pct": v.split(":", 1)[1].strip().rstrip("%")}),
                "BSSID":          lambda v: current.setdefault("bssids", []).append(v.split(":", 1)[1].strip()),
                "Channel":        lambda v: current.update({"channel": v.split(":", 1)[1].strip()}),
            }

            for line in r.stdout.splitlines():
                line = line.strip()
                if not line: continue
                
                # Check current switch
                if line.startswith("SSID") and "BSSID" not in line and current:
                    networks.append(current)
                    current = {}
                
                key = line.split(" ", 1)[0].replace(":", "")
                handler = _PREFIX_MAP.get(key)
                if handler: handler(line)
                
            if current: networks.append(current)
            return {"success": True, "networks": networks, "count": len(networks)}

        def _scan_linux():
            r = subprocess.run(
                ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,CHAN", "dev", "wifi"],
                capture_output=True, text=True, timeout=30,
            )
            networks = []
            for line in r.stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 4:
                    networks.append({
                        "ssid":       parts[0],
                        "signal_pct": parts[1],
                        "security":   parts[2],
                        "channel":    parts[3],
                    })
            return {"success": True, "networks": networks}

        _WIFI_DISPATCH = {
            "windows": _scan_win,
            "linux":   _scan_linux,
        }
        
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "unknown"
        handler = _WIFI_DISPATCH.get(platform_key)
        if not handler:
            return {"success": False, "error": f"WiFi scan not implemented for {platform_key}"}
        return handler()

    def get_wifi_profile(self, ssid: str = None) -> Dict:
        """Get details about a saved WiFi profile."""
        if not IS_WINDOWS:
            return {"success": False, "error": "Windows only"}
        cmd = (["netsh", "wlan", "show", "profile", f'name="{ssid}"', "key=clear"]
               if ssid else ["netsh", "wlan", "show", "profiles"])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {"success": r.returncode == 0, "output": r.stdout, "ssid": ssid}

    def connect_wifi(self, ssid: str, password: str = None) -> Dict:
        """Connect to a WiFi network via platform dispatch."""
        def _connect_win():
            if password:
                profile_xml = (f'<?xml version="1.0"?>\n<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">\n'
                    f'<name>{ssid}</name><SSIDConfig><SSID><name>{ssid}</name></SSID></SSIDConfig>\n'
                    f'<connectionType>ESS</connectionType><connectionMode>auto</connectionMode><MSM><security><authEncryption>\n'
                    f'<authentication>WPA2PSK</authentication><encryption>AES</encryption><useOneX>false</useOneX></authEncryption>\n'
                    f'<sharedKey><keyType>passPhrase</keyType><protected>false</protected><keyMaterial>{password}</keyMaterial></sharedKey>\n'
                    f'</security></MSM></WLANProfile>\n')
                import tempfile
                with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
                    f.write(profile_xml); tmp = f.name
                subprocess.run(["netsh", "wlan", "add", "profile", f"filename={tmp}"], capture_output=True, timeout=30)
                os.unlink(tmp)
            r = subprocess.run(["netsh", "wlan", "connect", f"name={ssid}"], capture_output=True, text=True, timeout=30)
            return {"success": r.returncode == 0, "ssid": ssid, "output": r.stdout}

        def _connect_linux():
            cmd = ["nmcli", "dev", "wifi", "connect", ssid]
            if password: cmd.extend(["password", password])
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return {"success": r.returncode == 0, "ssid": ssid, "output": r.stdout}

        _CONN_DISPATCH = {"windows": _connect_win, "linux": _connect_linux}
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "unknown"
        handler = _CONN_DISPATCH.get(platform_key)
        if not handler: return {"success": False, "error": "Not implemented"}
        return handler()

    def disconnect_wifi(self, interface: str = None) -> Dict:
        """Disconnect from WiFi via platform dispatch."""
        def _disc_win():
            r = subprocess.run(["netsh", "wlan", "disconnect"], capture_output=True, text=True, timeout=30)
            return {"success": r.returncode == 0, "output": r.stdout}

        def _disc_linux():
            iface = interface or "wlan0"
            r = subprocess.run(["nmcli", "dev", "disconnect", iface], capture_output=True, text=True, timeout=30)
            return {"success": r.returncode == 0}

        _DISC_DISPATCH = {"windows": _disc_win, "linux": _disc_linux}
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "unknown"
        handler = _DISC_DISPATCH.get(platform_key)
        if not handler: return {"success": False, "error": "Not implemented"}
        return handler()

    def get_saved_wifi_password(self, ssid: str) -> Dict:
        """Retrieve saved WiFi password (requires admin on Windows)."""
        if not IS_WINDOWS:
            return {"success": False, "error": "Windows only"}
        r = subprocess.run(
            ["netsh", "wlan", "show", "profile",
             f"name={ssid}", "key=clear"],
            capture_output=True, text=True, timeout=30,
        )
        m = re.search(r"Key Content\s*:\s*(.+)", r.stdout)
        if m:
            return {"success": True, "ssid": ssid, "password": m.group(1).strip()}
        return {"success": False, "error": "Password not found (may need admin)"}

    def forget_wifi_network(self, ssid: str) -> Dict:
        """Remove a saved WiFi profile via platform dispatch."""
        def _forget_win():
            r = subprocess.run(["netsh", "wlan", "delete", "profile", f"name={ssid}"], capture_output=True, text=True, timeout=10)
            return {"success": r.returncode == 0, "ssid": ssid}

        def _forget_linux():
            r = subprocess.run(["nmcli", "connection", "delete", ssid], capture_output=True, text=True, timeout=30)
            return {"success": r.returncode == 0}

        _FORGET_DISPATCH = {"windows": _forget_win, "linux": _forget_linux}
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "unknown"
        handler = _FORGET_DISPATCH.get(platform_key)
        if not handler: return {"success": False, "error": "Not implemented"}
        return handler()

    # ─────────────────────────────────────────────────────────────────────────
    #  IP / Geolocation
    # ─────────────────────────────────────────────────────────────────────────

    def get_public_ip(self) -> Dict:
        """Get external/public IP address."""
        services = [
            "https://api.ipify.org?format=json",
            "https://api.my-ip.io/ip.json",
            "https://httpbin.org/ip",
        ]
        for url in services:
            try:
                r = self.http_get(url, timeout=5)
                if r.get("success"):
                    body = json.loads(r["body"])
                    ip   = body.get("ip") or body.get("origin")
                    if ip:
                        return {"success": True, "public_ip": ip.strip(), "source": url}
            except Exception:
                continue
        return {"success": False, "error": "Could not get public IP"}

    def geolocate_ip(self, ip: str = None) -> Dict:
        """Geolocate an IP address using free ipapi.co."""
        target = ip or "me"
        r = self.http_get(f"https://ipapi.co/{target}/json/", timeout=10)
        if not r.get("success"):
            return r
        try:
            data = json.loads(r["body"])
            return {
                "success":    True,
                "ip":         data.get("ip"),
                "city":       data.get("city"),
                "region":     data.get("region"),
                "country":    data.get("country_name"),
                "country_code": data.get("country_code"),
                "latitude":   data.get("latitude"),
                "longitude":  data.get("longitude"),
                "org":        data.get("org"),
                "timezone":   data.get("timezone"),
                "isp":        data.get("org"),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_ip_info(self, ip: str) -> Dict:
        """Full IP info: geo, ASN, org, abuse contact."""
        r = self.http_get(f"https://ipinfo.io/{ip}/json", timeout=10)
        if not r.get("success"):
            return r
        try:
            data = json.loads(r["body"])
            return {"success": True, **data}
        except Exception:
            return {"success": True, "raw": r["body"]}

    def detect_vpn(self) -> Dict:
        """Heuristic: check if public IP is likely a VPN/proxy/datacenter."""
        geo_r = self.geolocate_ip()
        if not geo_r.get("success"):
            return geo_r
        org = geo_r.get("org", "").lower()
        vpn_keywords = ["vpn", "hosting", "proxy", "cloud", "datacenter",
                        "amazon", "digitalocean", "linode", "vultr", "ovh",
                        "azure", "google"]
        likely_vpn = any(kw in org for kw in vpn_keywords)
        return {
            "success":     True,
            "public_ip":   geo_r.get("ip"),
            "org":         geo_r.get("org"),
            "likely_vpn":  likely_vpn,
            "country":     geo_r.get("country"),
        }

    def check_ip_reputation(self, ip: str) -> Dict:
        """Check IP reputation using AbuseIPDB (no key) or local heuristic."""
        # Try ipqualityscore.com free endpoint (no key required for basic check)
        r = self.http_get(f"https://check.getipintel.net/check.php?ip={ip}&contact=novamind@local",
                           timeout=10)
        if r.get("success") and r.get("body"):
            try:
                score = float(r["body"].strip())
                return {
                    "success":    True,
                    "ip":         ip,
                    "fraud_score": score,
                    "suspicious": score > 0.9,
                }
            except Exception:
                pass
        return {"success": True, "ip": ip, "note": "Reputation check unavailable"}

    # ─────────────────────────────────────────────────────────────────────────
    #  Monitoring
    # ─────────────────────────────────────────────────────────────────────────

    def monitor_bandwidth(self, interval: float = 1.0,
                           duration: float = 5.0) -> Dict:
        """Measure real-time bandwidth over a period."""
        if not self._psutil:
            return {"success": False, "error": "psutil required"}
        import psutil

        samples: List[Dict] = []
        t0    = time.monotonic()
        prev  = psutil.net_io_counters()

        while (time.monotonic() - t0) < duration:
            time.sleep(interval)
            curr = psutil.net_io_counters()
            dt   = interval
            samples.append({
                "sent_mbps": round((curr.bytes_sent - prev.bytes_sent) / 1e6 / dt, 3),
                "recv_mbps": round((curr.bytes_recv - prev.bytes_recv) / 1e6 / dt, 3),
                "ts":        datetime.now().isoformat(),
            })
            prev = curr

        return {
            "success":     True,
            "samples":     samples,
            "avg_sent_mbps": round(sum(s["sent_mbps"] for s in samples) / len(samples), 3),
            "avg_recv_mbps": round(sum(s["recv_mbps"] for s in samples) / len(samples), 3),
            "duration_s":  duration,
        }

    def get_active_connections(self, kind: str = "tcp") -> Dict:
        """List all active network connections."""
        if self._psutil:
            import psutil
            conns = []
            for c in psutil.net_connections(kind=kind):
                conns.append({
                    "proto":  kind.upper(),
                    "laddr":  f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "",
                    "raddr":  f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else "",
                    "status": c.status,
                    "pid":    c.pid,
                })
            return {"success": True, "connections": conns, "count": len(conns)}
        cmd = ["netstat", "-ano"] if IS_WINDOWS else ["ss", "-antp"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return {"success": True, "output": r.stdout}

    def get_open_listening_ports(self) -> Dict:
        """List only listening TCP ports."""
        if self._psutil:
            import psutil
            ports = []
            for c in psutil.net_connections(kind="tcp"):
                if c.status == "LISTEN" or c.status == psutil.CONN_LISTEN:
                    ports.append({
                        "port":    c.laddr.port if c.laddr else None,
                        "address": c.laddr.ip   if c.laddr else "*",
                        "pid":     c.pid,
                        "service": self.SERVICE_MAP.get(c.laddr.port if c.laddr else 0, ""),
                    })
            return {"success": True, "ports": sorted(ports, key=lambda x: x["port"] or 0),
                    "count": len(ports)}
        if IS_WINDOWS:
            r = subprocess.run(["netstat", "-an"], capture_output=True, text=True, timeout=30)
            output = "\n".join(l for l in r.stdout.splitlines() if "LISTENING" in l)
        else:
            r = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=30)
            output = r.stdout
        return {"success": True, "output": output}

    def monitor_host_availability(self, host: str, interval: float = 5.0,
                                   duration: float = 60.0,
                                   port: int = None) -> Dict:
        """Monitor host availability for a period. Returns uptime %."""
        checks:   List[bool] = []
        t0 = time.monotonic()
        while (time.monotonic() - t0) < duration:
            if port:
                up = self._tcp_connect(host, port, timeout=2.0)
            else:
                up = self._is_alive(host)
            checks.append(up)
            time.sleep(interval)

        uptime_pct = round(sum(checks) / len(checks) * 100, 1) if checks else 0
        return {
            "success":    True,
            "host":       host,
            "checks":     len(checks),
            "up":         sum(checks),
            "down":       len(checks) - sum(checks),
            "uptime_pct": uptime_pct,
            "duration_s": duration,
        }

    def latency_test(self, host: str, count: int = 4,
                      port: int = None) -> Dict:
        """Measure TCP or ICMP latency to a host."""
        if port:
            # TCP latency
            times: List[float] = []
            for _ in range(count):
                t0 = time.monotonic()
                ok = self._tcp_connect(host, port, timeout=2.0)
                if ok:
                    times.append((time.monotonic() - t0) * 1000)
            if not times:
                return {"success": True, "host": host, "reachable": False}
            return {
                "success":   True,
                "host":      host,
                "reachable": True,
                "count":     count,
                "avg_ms":    round(sum(times) / len(times), 2),
                "min_ms":    round(min(times), 2),
                "max_ms":    round(max(times), 2),
                "method":    f"TCP:{port}",
            }

        # ICMP ping
        if IS_WINDOWS:
            cmd = ["ping", "-n", str(count), host]
        else:
            cmd = ["ping", "-c", str(count), host]

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        avg_m = re.search(r"[Aa]verage\s*[=:]\s*([\d.]+)|avg\s*[=:]\s*([\d.]+)", r.stdout)
        avg   = float(avg_m.group(1) or avg_m.group(2)) if avg_m else None
        return {
            "success":   True,
            "host":      host,
            "reachable": r.returncode == 0,
            "avg_ms":    avg,
            "output":    r.stdout[-500:],
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  Proxy
    # ─────────────────────────────────────────────────────────────────────────

    def set_system_proxy(self, http_proxy: str, https_proxy: str = None,
                          no_proxy: str = None) -> Dict:
        """Set system-wide proxy environment variables."""
        os.environ["HTTP_PROXY"]  = http_proxy
        os.environ["http_proxy"]  = http_proxy
        https = https_proxy or http_proxy
        os.environ["HTTPS_PROXY"] = https
        os.environ["https_proxy"] = https
        if no_proxy:
            os.environ["NO_PROXY"]  = no_proxy
            os.environ["no_proxy"]  = no_proxy

        if IS_WINDOWS:
            # Also set in Windows registry
            import winreg
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                      r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                                      0, winreg.KEY_WRITE)
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, http_proxy)
                winreg.CloseKey(key)
            except Exception:
                pass

        return {"success": True, "http": http_proxy, "https": https}

    def clear_system_proxy(self) -> Dict:
        """Remove all proxy settings."""
        for var in ["HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
                    "http_proxy", "https_proxy", "no_proxy"]:
            os.environ.pop(var, None)
        return {"success": True}

    def get_current_proxy(self) -> Dict:
        return {
            "success":    True,
            "http_proxy": os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy"),
            "https_proxy": os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"),
            "no_proxy":   os.environ.get("NO_PROXY"),
        }

    def test_proxy(self, proxy_url: str, test_url: str = "https://httpbin.org/ip") -> Dict:
        """Test if a proxy is working by routing a request through it."""
        if self._requests:
            proxies = {"http": proxy_url, "https": proxy_url}
            try:
                r = self._requests.get(test_url, proxies=proxies, timeout=10)
                return {
                    "success": r.ok,
                    "proxy":   proxy_url,
                    "status":  r.status_code,
                    "ip_via_proxy": r.json().get("origin") if r.ok else None,
                }
            except Exception as e:
                return {"success": False, "proxy": proxy_url, "error": str(e)}
        return {"success": False, "error": "requests required for proxy testing"}

    # ─────────────────────────────────────────────────────────────────────────
    #  Traceroute
    # ─────────────────────────────────────────────────────────────────────────

    def traceroute(self, host: str, max_hops: int = 30) -> Dict:
        """Trace the network path to a host."""
        if IS_WINDOWS:
            r = subprocess.run(["tracert", "-h", str(max_hops), host],
                                capture_output=True, text=True, timeout=30)
        else:
            cmd = shutil.which("traceroute") or shutil.which("tracepath")
            if not cmd:
                return {"success": False, "error": "traceroute not installed"}
            r = subprocess.run([cmd, "-m", str(max_hops), host],
                                capture_output=True, text=True, timeout=30)

        hops: List[Dict] = []
        for line in r.stdout.splitlines():
            m = re.search(r"(\d+)\s+(.+)", line)
            if m:
                hops.append({"hop": int(m.group(1)), "info": m.group(2).strip()})

        return {
            "success": True,
            "host":    host,
            "hops":    hops,
            "raw":     r.stdout[-3000:],
        }

    def mtr_trace(self, host: str, count: int = 5) -> Dict:
        """Run mtr (My TraceRoute) if available."""
        mtr = shutil.which("mtr")
        if not mtr:
            return self.traceroute(host)
        r = subprocess.run([mtr, "--report", "--report-cycles", str(count), host],
                            capture_output=True, text=True, timeout=30)
        return {"success": r.returncode == 0, "output": r.stdout, "host": host}

    # ─────────────────────────────────────────────────────────────────────────
    #  Misc
    # ─────────────────────────────────────────────────────────────────────────

    def whois_lookup(self, domain: str) -> Dict:
        """Run whois for a domain or IP."""
        whois_cmd = shutil.which("whois")
        if whois_cmd:
            r = subprocess.run([whois_cmd, domain],
                                capture_output=True, text=True, timeout=30)
            return {"success": True, "output": r.stdout[:5000], "domain": domain}
        # HTTP fallback
        r = self.http_get(f"https://www.whois.com/whois/{domain}", timeout=10)
        return {"success": r.get("success", False), "domain": domain,
                "note": "Parsed from HTML — use whois CLI for structured data"}

    def get_route_table(self) -> Dict:
        if IS_WINDOWS:
            r = subprocess.run(["route", "print"], capture_output=True,
                                text=True, timeout=30)
        else:
            r = subprocess.run(["ip", "route"], capture_output=True,
                                text=True, timeout=30)
        return {"success": r.returncode == 0, "output": r.stdout}

    def flush_arp_cache(self) -> Dict:
        """Flush ARP cache via platform dispatch."""
        _ARP_DISPATCH = {
            "windows": lambda: subprocess.run(["arp", "-d", "*"], capture_output=True, text=True, timeout=30),
            "linux":   lambda: subprocess.run(["ip", "neigh", "flush", "all"], capture_output=True, text=True, timeout=30),
        }
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "unknown"
        handler = _ARP_DISPATCH.get(platform_key)
        r = handler() if handler else subprocess.run(["arp", "-ad"], capture_output=True, text=True, timeout=30)
        return {"success": r.returncode == 0, "output": r.stdout + r.stderr}

    def get_arp_table(self) -> Dict:
        r = subprocess.run(["arp", "-a"], capture_output=True,
                            text=True, timeout=30)
        hosts: List[Dict] = []
        for line in r.stdout.splitlines():
            m = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+([\w:-]+)", line)
            if m:
                hosts.append({"ip": m.group(1), "mac": m.group(2)})
        return {"success": True, "hosts": hosts, "count": len(hosts), "raw": r.stdout}

    def netstat_summary(self) -> Dict:
        if IS_WINDOWS:
            r = subprocess.run(["netstat", "-ano"], capture_output=True,
                                text=True, timeout=30)
        else:
            r = subprocess.run(["ss", "-tnpu"], capture_output=True,
                                text=True, timeout=30)
        lines  = r.stdout.splitlines()
        listen = [l for l in lines if "LISTEN" in l]
        estab  = [l for l in lines if "ESTABLISH" in l or "ESTAB" in l]
        return {
            "success":       True,
            "listening":     len(listen),
            "established":   len(estab),
            "total_lines":   len(lines),
            "output":        r.stdout[:5000],
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  Internal Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _tcp_connect(self, host: str, port: int,
                      timeout: float = 1.0) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def _grab_banner(self, host: str, port: int,
                      timeout: float = 1.0) -> str:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            sock.send(b"HEAD / HTTP/1.0\r\n\r\n")
            banner = sock.recv(1024).decode("utf-8", errors="replace")
            sock.close()
            return banner.strip()[:200]
        except Exception:
            return ""

    def _is_alive(self, ip: str, timeout: float = 0.5) -> bool:
        """ICMP ping via OS command (fast, silent)."""
        if IS_WINDOWS:
            r = subprocess.run(
                ["ping", "-n", "1", "-w", str(int(timeout * 1000)), ip],
                capture_output=True, timeout=max(timeout * 2, 2),
            )
        else:
            r = subprocess.run(
                ["ping", "-c", "1", "-W", str(max(int(timeout), 1)), ip],
                capture_output=True, timeout=max(timeout * 2, 2),
            )
        return r.returncode == 0

    def _detect_local_subnet(self) -> Optional[str]:
        """Auto-detect local /24 subnet from default gateway."""
        try:
            if self._psutil:
                import psutil
                gws = psutil.net_if_addrs()
                for iface, addrs in gws.items():
                    for addr in addrs:
                        if (addr.family == socket.AF_INET and
                                not addr.address.startswith("127.")):
                            return addr.address
        except Exception:
            pass
        return None

    def _log_scan(self, host: str, ports: List[int], results: List[bool]):
        open_n = sum(results)
        self._scan_history.append({
            "ts":         datetime.now().isoformat(),
            "host":       host,
            "ports":      len(ports),
            "open":       open_n,
        })
        if len(self._scan_history) > 2000:
            self._scan_history = self._scan_history[-1000:]

    def _log_http(self, method: str, url: str, status: int, ms: float):
        self._http_history.append({
            "ts": datetime.now().isoformat(),
            "method": method, "url": url[:200],
            "status": status, "ms": ms,
        })
        if len(self._http_history) > 2000:
            self._http_history = self._http_history[-1000:]

    def _get_history(self, limit: int = 50) -> Dict:
        return {
            "success":      True,
            "scans":        self._scan_history[-limit:],
            "http_calls":   self._http_history[-limit:],
        }

    @staticmethod
    def _try_import(module_name: str):
        import importlib
        try:
            return importlib.import_module(module_name)
        except ImportError:
            return None
