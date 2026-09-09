"""
agents/scanner_agent.py — Web security scanner for Hermes.

Performs passive + semi-active checks on a target URL/domain:
  1. DNS resolution & IP info
  2. Port scan (common web ports)
  3. SSL/TLS certificate analysis
  4. HTTP security headers audit
  5. Cookie security flags check
  6. Server information disclosure
  7. Sensitive path discovery (/.git, /.env, /admin, /phpinfo.php, etc.)
  8. Basic content security checks (forms without CSRF, mixed content hints)

All checks use only httpx + stdlib (socket, ssl) — no external tools required.
Returns a structured ScanResult dict ready for LLM summarisation or direct display.

Usage:
    result = await scan_target("https://example.com")
    report = format_report(result)
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
import socket
import ssl
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

import config as _cfg

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────
SCAN_TIMEOUT    = 8       # seconds per request
PORT_TIMEOUT    = 2       # seconds per port probe
MAX_BODY_SCAN   = 50_000  # bytes to scan for content issues

COMMON_PORTS = [
    (21,   "FTP"),
    (22,   "SSH"),
    (23,   "Telnet"),
    (25,   "SMTP"),
    (80,   "HTTP"),
    (110,  "POP3"),
    (143,  "IMAP"),
    (443,  "HTTPS"),
    (445,  "SMB"),
    (3306, "MySQL"),
    (3389, "RDP"),
    (5432, "PostgreSQL"),
    (6379, "Redis"),
    (8080, "HTTP-Alt"),
    (8443, "HTTPS-Alt"),
    (8888, "HTTP-Dev"),
    (27017,"MongoDB"),
]

SENSITIVE_PATHS = [
    "/.git/HEAD",
    "/.git/config",
    "/.env",
    "/.env.backup",
    "/.env.local",
    "/phpinfo.php",
    "/info.php",
    "/server-info",
    "/server-status",
    "/admin",
    "/admin/",
    "/administrator",
    "/wp-admin/",
    "/wp-login.php",
    "/wp-config.php",
    "/backup.zip",
    "/backup.sql",
    "/dump.sql",
    "/database.sql",
    "/config.php",
    "/config.yaml",
    "/config.json",
    "/web.config",
    "/.htaccess",
    "/.htpasswd",
    "/robots.txt",
    "/sitemap.xml",
    "/crossdomain.xml",
    "/clientaccesspolicy.xml",
    "/api/v1/users",
    "/api/v1/admin",
    "/swagger.json",
    "/swagger-ui.html",
    "/openapi.json",
    "/actuator",
    "/actuator/env",
    "/actuator/health",
    "/.well-known/security.txt",
    # GraphQL
    "/graphql",
    "/api/graphql",
    "/graphiql",
    "/v1/graphql",
    # Laravel / PHP
    "/.env.example",
    "/storage/logs/laravel.log",
    "/public/storage",
    "/public/.env",
    # Django
    "/django-admin/",
    "/admin/login/",
    # Spring Boot extra actuators
    "/actuator/beans",
    "/actuator/mappings",
    "/actuator/info",
    "/actuator/metrics",
    "/actuator/loggers",
    # Jupyter Notebook
    "/jupyter/",
    "/api/kernels",
    "/tree",
    # Kubernetes / Docker metadata
    "/.dockerenv",
    "/api/v1/namespaces",
    # Server internals
    "/WEB-INF/web.xml",
    "/console",
    "/jmx-console/",
    # File leaks
    "/.DS_Store",
    "/.bash_history",
    "/.ssh/id_rsa",
    "/.git/logs/HEAD",
    # Common CI/CD
    "/.gitlab-ci.yml",
    "/.travis.yml",
    "/Jenkinsfile",
    "/.github/workflows",
    # Package files
    "/package.json",
    "/composer.json",
    "/Gemfile",
    "/requirements.txt",
]

# WAF/CDN signature detection — header name: (product, confidence)
WAF_SIGNATURES = {
    # Headers that indicate specific WAF/CDN products
    "cf-ray":                    ("Cloudflare", "HIGH"),
    "x-sucuri-id":               ("Sucuri WAF", "HIGH"),
    "x-sucuri-cache":            ("Sucuri WAF", "HIGH"),
    "x-fw-hash":                 ("Fastly WAF", "HIGH"),
    "x-cache-hits":              ("Fastly/CDN", "MEDIUM"),
    "x-akamai-transformed":      ("Akamai", "HIGH"),
    "x-akamai-session-id":       ("Akamai", "HIGH"),
    "x-amz-cf-id":               ("AWS CloudFront", "HIGH"),
    "x-amz-cf-pop":              ("AWS CloudFront", "HIGH"),
    "x-azure-ref":               ("Azure CDN/WAF", "HIGH"),
    "x-ms-ref":                  ("Azure Front Door", "HIGH"),
    "x-barracuda-connect":       ("Barracuda WAF", "HIGH"),
    "x-arequestid":              ("Incapsula/Imperva", "HIGH"),
    "x-iinfo":                   ("Incapsula/Imperva", "HIGH"),
    "x-cache":                   ("CDN Cache", "LOW"),
    "x-cdn":                     ("CDN", "MEDIUM"),
    "x-varnish":                 ("Varnish Cache", "MEDIUM"),
    "x-squid-error":             ("Squid Proxy", "MEDIUM"),
    "x-datadome-cid":            ("DataDome Bot Protection", "HIGH"),
    "x-distil-cs":               ("Distil Networks WAF", "HIGH"),
    "server-timing":             ("Performance monitoring", "LOW"),
}

# Server header patterns → WAF/product
WAF_SERVER_PATTERNS = [
    (r"cloudflare",    "Cloudflare"),
    (r"awselb",        "AWS ELB"),
    (r"sucuri",        "Sucuri"),
    (r"incapsula",     "Imperva Incapsula"),
    (r"imperva",       "Imperva"),
    (r"akamai",        "Akamai"),
    (r"fastly",        "Fastly"),
    (r"varnish",       "Varnish"),
    (r"nginx\s*/?\s*\d", "Nginx (versioned)"),
    (r"apache\s*/?\s*\d", "Apache (versioned)"),
    (r"microsoft-iis", "IIS"),
    (r"openresty",     "OpenResty/Nginx"),
]

# Tech fingerprint — cookie name → tech
TECH_COOKIE_MAP = {
    "PHPSESSID":           "PHP",
    "JSESSIONID":          "Java (Servlet)",
    "ASP.NET_SessionId":   "ASP.NET",
    "laravel_session":     "Laravel (PHP)",
    "ci_session":          "CodeIgniter (PHP)",
    "csrftoken":           "Django (Python)",
    "sessionid":           "Django (Python)",
    "_rails":              "Ruby on Rails",
    "rack.session":        "Ruby Rack",
    "__utma":              "Google Analytics",
    "_pk_id":              "Matomo Analytics",
    "wp-settings":         "WordPress",
}

# ── CMS Detection Signatures ─────────────────────────────────────────────
# body: list of regex patterns (any match = detected)
# headers: {header_name_lower: value_substring_or_None_for_presence_only}
# cookies: list of cookie name prefixes
# requires: parent CMS name (optional, e.g. WooCommerce requires WordPress)
CMS_SIGNATURES: dict[str, dict] = {
    "WordPress": {
        "body":    [r"wp-content|wp-includes|WordPress"],
        "headers": {"x-pingback": None},
        "cookies": ["wordpress_", "wp-settings-"],
    },
    "WooCommerce": {
        "body":    [r"woocommerce|wc-cart|add_to_cart_url|wc_checkout|woocommerce-page"],
        "headers": {},
        "cookies": ["woocommerce_"],
        "requires": "WordPress",
    },
    "Joomla": {
        "body":    [r"Joomla!|/media/jui/|/components/com_|option=com_|joomla\.js"],
        "headers": {"x-content-encoded-by": "Joomla"},
        "cookies": [],
    },
    "Drupal": {
        "body":    [r"Drupal\.settings|drupal\.js|/sites/default/|drupal/drupal"],
        "headers": {"x-generator": "Drupal", "x-drupal-cache": None, "x-drupal-dynamic-cache": None},
        "cookies": ["drupal_"],
    },
    "Magento": {
        "body":    [r"Mage\.Cookies|mage/cookies|skin/frontend/|Magento_[A-Z]|/pub/static/version|mageInit"],
        "headers": {"x-magento-cache-debug": None, "x-magento-vary": None},
        "cookies": ["frontend_cid", "mage-"],
    },
    "PrestaShop": {
        "body":    [r"window\.prestashop|PrestaShop|/modules/ps_|prestashop"],
        "headers": {"x-powered-by": "PrestaShop"},
        "cookies": ["PrestaShop-"],
    },
    "OpenCart": {
        "body":    [r"OpenCart|catalog/view/theme/|route=checkout/cart|route=product/product|opencart"],
        "headers": {},
        "cookies": [],
    },
    "Shopify": {
        "body":    [r"Shopify\.theme|shopify-features|cdn\.shopify\.com|myshopify\.com|Shopify\.shop"],
        "headers": {"x-shopify-stage": None, "x-shopid": None, "x-shopify-request-id": None},
        "cookies": ["_shopify_"],
    },
    "Wix": {
        "body":    [r"static\.wix\.com|wixsite\.com|wixstatic\.com|_wixCssContext|wix-warmup-data"],
        "headers": {"x-wix-request-id": None},
        "cookies": [],
    },
    "Squarespace": {
        "body":    [r"squarespace\.com|sqsp\.net|static1\.squarespace\.com|sqs-video"],
        "headers": {"server": "Squarespace"},
        "cookies": ["crumb_", "ss-"],
    },
}

# CMS-specific sensitive paths — probed only when that CMS is detected
CMS_PATHS: dict[str, list[str]] = {
    "WordPress": [
        "/wp-login.php",
        "/wp-admin/",
        "/wp-config.php",
        "/wp-config.php.bak",
        "/wp-config.php~",
        "/xmlrpc.php",
        "/wp-json/wp/v2/users",
        "/wp-content/debug.log",
        "/wp-content/uploads/",
        "/wp-includes/wlwmanifest.xml",
    ],
    "WooCommerce": [
        "/cart/",
        "/checkout/",
        "/wp-json/wc/v3/customers",
        "/wp-json/wc/v3/orders",
    ],
    "Joomla": [
        "/administrator/",
        "/administrator/index.php",
        "/administrator/manifests/files/joomla.xml",
        "/configuration.php~",
        "/configuration.php.bak",
        "/htaccess.txt",
        "/web.config.txt",
        "/LICENSE.txt",
        "/joomla.xml",
    ],
    "Drupal": [
        "/user/login",
        "/user/password",
        "/admin/",
        "/?q=user/login",
        "/CHANGELOG.txt",
        "/core/CHANGELOG.txt",
        "/INSTALL.txt",
        "/sites/default/settings.php",
        "/sites/default/files/",
    ],
    "Magento": [
        "/admin/",
        "/downloader/",
        "/app/etc/local.xml",
        "/app/etc/env.php",
        "/var/export/",
        "/var/log/system.log",
        "/magento_version",
        "/RELEASE_NOTES.txt",
        "/install.php",
    ],
    "PrestaShop": [
        "/config/config.inc.php",
        "/app/config/parameters.php",
        "/config/settings.inc.php",
        "/admin-dev/",
        "/modules/",
        "/INSTALL.txt",
        "/CHANGELOG",
    ],
    "OpenCart": [
        "/admin/",
        "/admin/index.php",
        "/config.php",
        "/admin/config.php",
        "/system/logs/",
        "/INSTALL.txt",
    ],
    "Shopify":     [],   # SaaS — no self-hosted paths
    "Wix":         [],   # SaaS — no self-hosted paths
    "Squarespace": [],   # SaaS — no self-hosted paths
}

# Exa search query templates per CMS
# "query": main search string; "type": "keyword" | "neural"
CMS_EXA_QUERIES: dict[str, dict] = {
    # All queries use neural search so Exa understands INTENT (real shop) not just keywords.
    # We target actual buyers/sellers — not CMS docs, theme stores, or dev blogs.
    "WordPress":   {
        "query": "real online store built with WordPress WooCommerce selling physical products buy checkout cart payment order",
        "type":  "neural",
    },
    "WooCommerce": {
        "query": "WooCommerce e-commerce store selling products add to cart checkout order payment customer",
        "type":  "neural",
    },
    "Joomla":      {
        "query": "online shop buy sell products cart checkout payment customer orders Joomla website",
        "type":  "neural",
    },
    "Drupal":      {
        "query": "online shop consumer store selling products cart checkout payment customer Drupal website",
        "type":  "neural",
    },
    "Magento":     {
        "query": "Magento consumer online retail store selling products cart checkout payment customer orders",
        "type":  "neural",
    },
    "PrestaShop":  {
        "query": "PrestaShop consumer store selling products cart checkout order payment delivery customer",
        "type":  "neural",
    },
    "OpenCart":    {
        "query": "OpenCart consumer online shop selling products cart checkout payment order customer",
        "type":  "neural",
    },
    "Shopify":     {
        "query": "Shopify online store selling physical products buy now checkout cart payment order fulfillment",
        "type":  "neural",
    },
    "Wix":         {
        "query": "Wix online store selling products shop buy checkout payment order customer",
        "type":  "neural",
    },
    "Squarespace": {
        "query": "Squarespace online store selling products checkout cart payment order buy",
        "type":  "neural",
    },
}

# Common subdomain wordlist for enumeration
SUBDOMAIN_WORDLIST = [
    # General
    "www", "mail", "ftp", "smtp", "pop", "imap", "ns1", "ns2", "mx",
    # Web services
    "api", "app", "apps", "mobile", "m", "wap", "web", "www2", "www3",
    # Admin / management
    "admin", "administrator", "panel", "cp", "cpanel", "whm", "webmail",
    "manage", "management", "dashboard", "control",
    # Dev / staging
    "dev", "development", "staging", "stage", "stg", "test", "testing",
    "beta", "alpha", "uat", "qa", "demo", "sandbox", "preview",
    # Auth / security
    "login", "auth", "sso", "oauth", "secure", "vpn", "remote",
    # Static / CDN
    "cdn", "static", "assets", "media", "images", "img", "files",
    "download", "downloads", "uploads", "storage", "s3",
    # Support / docs
    "support", "help", "docs", "documentation", "wiki",
    "blog", "forum", "community", "status", "monitor",
    # Backend infra
    "db", "database", "mysql", "postgres", "redis", "mongo",
    "elasticsearch", "kibana", "grafana", "prometheus",
    # DevOps / CI
    "jenkins", "gitlab", "ci", "cd", "git", "repo",
    "jira", "confluence", "sonar",
    # Business
    "shop", "store", "cart", "pay", "payment", "billing",
    "crm", "erp", "portal", "intranet", "extranet", "internal",
    # Backup / old
    "old", "backup", "bak", "archive", "legacy",
    # Email security
    "autodiscover", "autoconfig", "email",
]

# Subdomains that indicate higher risk if discovered
_RISKY_SUBS = {
    "dev", "development", "staging", "stage", "stg", "test", "testing",
    "beta", "alpha", "uat", "qa", "sandbox", "demo",
    "admin", "administrator", "panel", "cp", "cpanel", "whm",
    "db", "database", "mysql", "postgres", "redis", "mongo",
    "elasticsearch", "kibana", "grafana",
    "jenkins", "gitlab", "ci", "git",
    "old", "backup", "bak", "archive", "legacy",
    "internal", "intranet", "extranet",
    "vpn", "remote", "ssh",
    "jira", "confluence",
}

SECURITY_HEADERS = {
    "Strict-Transport-Security":    ("HSTS", "CRITICAL — Missing HSTS, vulnerable to SSL stripping"),
    "X-Content-Type-Options":       ("XCTO", "MEDIUM — Missing nosniff header, MIME sniffing risk"),
    "X-Frame-Options":              ("XFO",  "MEDIUM — Missing clickjacking protection"),
    "Content-Security-Policy":      ("CSP",  "HIGH — No CSP, XSS mitigation missing"),
    "X-XSS-Protection":             ("XXP",  "LOW — Legacy XSS filter header absent"),
    "Referrer-Policy":              ("RP",   "LOW — No referrer policy, info leakage risk"),
    "Permissions-Policy":           ("PP",   "LOW — No permissions policy"),
    "Cross-Origin-Opener-Policy":   ("COOP", "LOW — No COOP header"),
    "Cross-Origin-Resource-Policy": ("CORP", "LOW — No CORP header"),
}

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


# ── Helpers ───────────────────────────────────────────────────────────────

def _is_safe_target(host: str) -> bool:
    """Block scanning of private/loopback addresses."""
    try:
        ip = socket.gethostbyname(host)
        addr = ipaddress.ip_address(ip)
        return not (addr.is_private or addr.is_loopback or addr.is_reserved)
    except Exception:
        return True  # Allow if we can't resolve — httpx will handle failure


def _normalize_url(target: str) -> str:
    """Ensure target has a scheme."""
    if not target.startswith(("http://", "https://")):
        target = "https://" + target
    return target.rstrip("/")


# Known second-level TLDs (ccTLD+SLD) that require 3-part registrable domain
_KNOWN_SLD_TLDS: frozenset[str] = frozenset({
    # Indonesia
    "ac.id", "co.id", "go.id", "or.id", "net.id", "sch.id",
    "web.id", "my.id", "mil.id", "biz.id",
    # United Kingdom
    "co.uk", "org.uk", "me.uk", "net.uk", "ltd.uk", "plc.uk",
    "ac.uk", "gov.uk", "nhs.uk", "sch.uk",
    # Australia
    "com.au", "net.au", "org.au", "edu.au", "gov.au", "id.au", "asn.au",
    # Brazil
    "com.br", "org.br", "net.br", "gov.br", "edu.br", "mil.br",
    # Japan
    "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp", "ad.jp",
    # Malaysia
    "com.my", "net.my", "org.my", "gov.my", "edu.my", "mil.my",
    # Singapore
    "com.sg", "net.sg", "org.sg", "gov.sg", "edu.sg",
    # India
    "co.in", "net.in", "org.in", "gov.in", "ac.in", "edu.in",
    # New Zealand
    "co.nz", "net.nz", "org.nz", "govt.nz", "ac.nz",
    # South Africa
    "co.za", "net.za", "org.za", "gov.za", "ac.za",
    # Turkey
    "com.tr", "org.tr", "net.tr", "gov.tr", "edu.tr",
    # Argentina
    "com.ar", "org.ar", "net.ar", "gov.ar", "edu.ar",
})


def _extract_base_domain(host: str) -> str:
    """
    Extract the registrable base domain, correctly handling 2-level TLDs.
    Examples:
      ipb.ac.id        → ipb.ac.id   (not ac.id)
      unpak.ac.id      → unpak.ac.id (not ac.id)
      www.google.co.uk → google.co.uk
      sub.example.com  → example.com
    """
    parts = host.lower().split(".")
    if len(parts) >= 3:
        sld_candidate = ".".join(parts[-2:])
        if sld_candidate in _KNOWN_SLD_TLDS:
            return ".".join(parts[-3:])
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


async def _resolve_subdomain(sub: str, base_domain: str) -> dict | None:
    """Try DNS resolution for sub.base_domain. Returns info dict or None."""
    fqdn = f"{sub}.{base_domain}"
    try:
        ip = await asyncio.get_event_loop().run_in_executor(
            None, socket.gethostbyname, fqdn
        )
        addr = ipaddress.ip_address(ip)
        if addr.is_private or addr.is_loopback:
            return None
        return {"subdomain": fqdn, "sub": sub, "ip": ip}
    except Exception:
        return None


async def _enum_subdomains_passive(domain: str) -> list[dict]:
    """
    Passive subdomain enumeration from multiple free public sources:
      - crt.sh  (certificate transparency, no key)
      - HackerTarget  (free tier, no key)
      - AlienVault OTX  (no key for basic)
      - SecurityTrails  (optional API key from .env)
      - VirusTotal  (optional API key from .env)
    Returns list of {subdomain, ip, source} dicts.
    """
    found: dict[str, dict] = {}  # fqdn -> info
    headers = {"User-Agent": "Mozilla/5.0 (SecurityAudit/Hermes)"}

    async with httpx.AsyncClient(timeout=15, headers=headers, verify=False) as client:

        # ── 1. crt.sh  (certificate transparency logs) ─────────────────
        try:
            r = await client.get(
                f"https://crt.sh/?q=%25.{domain}&output=json",
                follow_redirects=True,
            )
            if r.status_code == 200:
                for entry in r.json():
                    names = entry.get("name_value", "")
                    for n in names.splitlines():
                        n = n.strip().lower().lstrip("*.").rstrip(".")
                        if n.endswith(f".{domain}") or n == domain:
                            found.setdefault(n, {"subdomain": n, "sources": []})
                            if "crt.sh" not in found[n]["sources"]:
                                found[n]["sources"].append("crt.sh")
        except Exception as e:
            logger.debug(f"crt.sh error: {e}")

        # ── 2. HackerTarget ────────────────────────────────────────────
        try:
            r = await client.get(
                f"https://api.hackertarget.com/hostsearch/?q={domain}",
                follow_redirects=True,
            )
            if r.status_code == 200 and "API count exceeded" not in r.text:
                for line in r.text.splitlines():
                    parts = line.split(",")
                    if len(parts) >= 1:
                        n = parts[0].strip().lower()
                        if n.endswith(f".{domain}") or n == domain:
                            found.setdefault(n, {"subdomain": n, "sources": []})
                            if "hackertarget" not in found[n]["sources"]:
                                found[n]["sources"].append("hackertarget")
                            if len(parts) >= 2:
                                found[n]["ip"] = parts[1].strip()
        except Exception as e:
            logger.debug(f"HackerTarget error: {e}")

        # ── 3. AlienVault OTX ─────────────────────────────────────────
        try:
            r = await client.get(
                f"https://otx.alienvault.com/api/v1/indicators/domain/{domain}/passive_dns",
                follow_redirects=True,
            )
            if r.status_code == 200:
                for entry in r.json().get("passive_dns", []):
                    n = entry.get("hostname", "").strip().lower()
                    if n.endswith(f".{domain}") or n == domain:
                        found.setdefault(n, {"subdomain": n, "sources": []})
                        if "alienvault" not in found[n]["sources"]:
                            found[n]["sources"].append("alienvault")
                        if entry.get("address") and not found[n].get("ip"):
                            found[n]["ip"] = entry["address"]
        except Exception as e:
            logger.debug(f"AlienVault OTX error: {e}")

        # ── 4. SecurityTrails (optional API key) ───────────────────────
        st_key = getattr(_cfg, "SECURITYTRAILS_API_KEY", "")
        if st_key:
            try:
                r = await client.get(
                    f"https://api.securitytrails.com/v1/domain/{domain}/subdomains",
                    headers={**headers, "APIKEY": st_key},
                    follow_redirects=True,
                )
                if r.status_code == 200:
                    for sub in r.json().get("subdomains", []):
                        n = f"{sub}.{domain}"
                        found.setdefault(n, {"subdomain": n, "sources": []})
                        if "securitytrails" not in found[n]["sources"]:
                            found[n]["sources"].append("securitytrails")
            except Exception as e:
                logger.debug(f"SecurityTrails error: {e}")

        # ── 5. VirusTotal (optional API key) ───────────────────────────
        vt_key = getattr(_cfg, "VIRUSTOTAL_API_KEY", "")
        if vt_key:
            try:
                r = await client.get(
                    f"https://www.virustotal.com/api/v3/domains/{domain}/subdomains",
                    headers={**headers, "x-apikey": vt_key},
                    follow_redirects=True,
                )
                if r.status_code == 200:
                    for item in r.json().get("data", []):
                        n = item.get("id", "").strip().lower()
                        if n.endswith(f".{domain}") or n == domain:
                            found.setdefault(n, {"subdomain": n, "sources": []})
                            if "virustotal" not in found[n]["sources"]:
                                found[n]["sources"].append("virustotal")
            except Exception as e:
                logger.debug(f"VirusTotal error: {e}")

    # ── DNS verify all found subdomains (resolve to confirm alive) ─────
    async def _verify(info: dict) -> dict | None:
        if info.get("ip"):  # already have IP from API
            try:
                addr = ipaddress.ip_address(info["ip"])
                if addr.is_private or addr.is_loopback:
                    return None
            except Exception:
                pass
            return info
        # Try DNS resolve
        fqdn = info["subdomain"]
        try:
            ip = await asyncio.get_event_loop().run_in_executor(
                None, socket.gethostbyname, fqdn
            )
            addr = ipaddress.ip_address(ip)
            if addr.is_private or addr.is_loopback:
                return None
            info["ip"] = ip
            return info
        except Exception:
            return None

    tasks = [_verify(v) for v in found.values()]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    verified = [
        r for r in results
        if r and not isinstance(r, Exception)
    ]
    # Sort: risky first, then alphabetically
    verified.sort(key=lambda x: (
        0 if x["subdomain"].split(".")[0] in _RISKY_SUBS else 1,
        x["subdomain"]
    ))
    return verified


async def _probe_port(host: str, port: int) -> bool:
    """Try TCP connect to host:port. Returns True if open."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=PORT_TIMEOUT
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


def _check_ssl_cert(host: str, port: int = 443) -> dict:
    """Retrieve SSL certificate info synchronously."""
    result: dict[str, Any] = {"error": None, "valid": False}
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(
            socket.create_connection((host, port), timeout=SCAN_TIMEOUT),
            server_hostname=host,
        ) as ssock:
            cert = ssock.getpeercert()
            cipher = ssock.cipher()
            proto  = ssock.version()

            not_after = datetime.strptime(
                cert["notAfter"], "%b %d %H:%M:%S %Y %Z"
            ).replace(tzinfo=timezone.utc)
            days_left = (not_after - datetime.now(timezone.utc)).days

            result = {
                "valid":        True,
                "subject":      dict(x[0] for x in cert.get("subject", [])),
                "issuer":       dict(x[0] for x in cert.get("issuer", [])),
                "not_after":    not_after.strftime("%Y-%m-%d"),
                "days_left":    days_left,
                "protocol":     proto,
                "cipher":       cipher[0] if cipher else "unknown",
                "san":          [v for _, v in cert.get("subjectAltName", [])],
                "error":        None,
            }

            # Warn if expiring soon
            if days_left < 0:
                result["expired"] = True
            elif days_left < 30:
                result["expiring_soon"] = True

            # Warn on old protocol
            if proto in ("SSLv2", "SSLv3", "TLSv1", "TLSv1.1"):
                result["weak_protocol"] = True

    except ssl.SSLCertVerificationError as e:
        result = {"valid": False, "error": f"Certificate verification failed: {e}"}
    except Exception as e:
        result = {"valid": False, "error": str(e)}
    return result


# ── LLM-Guided Path Generation ───────────────────────────────────────────

async def _llm_generate_paths(
    tech_info: dict,
    already_found: list | None = None,
    context: str = "path",   # "path" | "api"
    max_paths: int = 25,
) -> list:
    """
    Ask the LLM to generate targeted probe paths based on tech fingerprint.
    Uses Groq (free/fast) via LLMClient — short prompt to save tokens.
    Returns list of /paths. Empty list on any failure.
    """
    try:
        from llm.client import LLMClient   # lazy import to avoid circular dep
        _llm = LLMClient()
    except Exception:
        return []

    tech   = ", ".join(tech_info.get("tech_stack", [])) or "unknown"
    server = tech_info.get("server", "unknown")
    waf    = ", ".join(tech_info.get("waf_cdn", [])) or "none"
    found  = ", ".join((already_found or [])[:8]) or "none"

    if context == "api":
        task = (
            f"Generate up to {max_paths} URL paths for API endpoints, auth, "
            "docs (OpenAPI/Swagger/GraphQL) specific to this stack."
        )
    else:
        task = (
            f"Generate up to {max_paths} URL paths to probe for security issues "
            "(config files, admin panels, debug endpoints, backup files, "
            "framework-specific sensitive paths) for this stack."
        )

    prompt = (
        f"Tech: {tech}\nServer: {server}\nWAF/CDN: {waf}\n"
        f"Already found: {found}\n\n{task}\n"
        "Output ONLY a JSON array like [\"/path1\",\"/path2\"]. No explanation."
    )
    try:
        resp = await _llm.chat(
            [{"role": "user", "content": prompt}],
            system=(
                "You are a web security scanner. "
                "Respond only with a valid JSON array of URL paths starting with /."
            ),
        )
        m = re.search(r"\[[\s\S]*?\]", resp)
        if m:
            # Strip literal control chars that Groq sometimes embeds in strings
            clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', m.group(0))
            clean = clean.replace('\n', '\\n').replace('\r', '')
            # Try greedy match in case non-greedy cut off the array
            m2 = re.search(r"\[[\s\S]*\]", resp)
            if m2:
                clean2 = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', m2.group(0))
                clean2 = clean2.replace('\n', '\\n').replace('\r', '')
                try:
                    raw = json.loads(clean2)
                except Exception:
                    raw = None
                if not raw:
                    try:
                        raw = json.loads(clean)
                    except Exception:
                        raw = None
            else:
                try:
                    raw = json.loads(clean)
                except Exception:
                    raw = None
            if raw:
                return [
                    re.sub(r'\\n.*', '', p).rstrip("?&#").strip()
                    for p in raw
                    if isinstance(p, str) and p.startswith("/") and len(p) > 1
                ][:max_paths]
    except Exception as e:
        logger.warning(f"LLM path generation error: {e}")
    return []


def _guess_severity(path: str, status: int) -> str:
    """Guess finding severity based on path name."""
    pl = path.lower()
    if any(x in pl for x in [".env", ".git", "passwd", "shadow", "credentials",
                               "secret", "private_key", ".pem", ".key"]):
        return "CRITICAL"
    if any(x in pl for x in ["phpinfo", "config", "backup", "dump", ".sql",
                               "wp-config", "actuator/env", "admin", "shell"]):
        return "HIGH"
    return "MEDIUM" if status == 200 else "LOW"


def _detect_cms(body: str, resp_headers_lower: dict, cookies) -> list[str]:
    """
    Detect CMS/platform from page body, HTTP headers, and cookies.
    Returns list of detected CMS names in detection order.
    """
    detected: list[str] = []
    for cms, sig in CMS_SIGNATURES.items():
        # Skip if this CMS requires a parent that hasn't been detected yet
        required = sig.get("requires")
        if required and required not in detected:
            continue

        matched = False
        # Body pattern check
        for pattern in sig.get("body", []):
            if re.search(pattern, body, re.IGNORECASE):
                matched = True
                break
        # Header presence/value check
        if not matched:
            for hdr_name, hdr_val in sig.get("headers", {}).items():
                actual = resp_headers_lower.get(hdr_name, "")
                if actual:
                    if hdr_val is None or hdr_val.lower() in actual.lower():
                        matched = True
                        break
        # Cookie name prefix check
        if not matched:
            cookie_names = [c.name for c in cookies]
            for prefix in sig.get("cookies", []):
                if any(cn.startswith(prefix) for cn in cookie_names):
                    matched = True
                    break
        if matched:
            detected.append(cms)
    return detected


# ── DNS-only Lookup ───────────────────────────────────────────────────────

async def dns_lookup(target: str) -> str:
    """
    Query DNS records for a domain: A, AAAA, MX, NS, TXT (SPF), CNAME, DMARC.
    Returns a formatted plain-text report. No HTTP scan, no port scan.
    """
    import urllib.parse

    # Normalise: strip scheme/path
    host = target.strip()
    for scheme in ("https://", "http://"):
        if host.startswith(scheme):
            host = host[len(scheme):]
    host = host.split("/")[0].split("?")[0].lower()

    base_domain = _extract_base_domain(host)
    doh = "https://cloudflare-dns.com/dns-query"
    headers = {"Accept": "application/dns-json", "User-Agent": "Mozilla/5.0"}
    result: dict[str, list[str]] = {}

    RECORD_TYPES = ["A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA"]

    async with httpx.AsyncClient(timeout=10, headers=headers) as client:
        # Standard record types for the target host
        for rtype in RECORD_TYPES:
            name = host if rtype not in ("MX", "NS", "SOA") else base_domain
            try:
                r = await client.get(doh, params={"name": name, "type": rtype})
                if r.status_code == 200:
                    answers = r.json().get("Answer", [])
                    vals = [a.get("data", "").strip('"') for a in answers]
                    if vals:
                        result[rtype] = vals
            except Exception as e:
                logger.debug(f"DNS {rtype} query error: {e}")

        # DMARC — always query base domain
        try:
            r = await client.get(doh, params={"name": f"_dmarc.{base_domain}", "type": "TXT"})
            if r.status_code == 200:
                vals = [
                    a.get("data", "").strip('"')
                    for a in r.json().get("Answer", [])
                    if a.get("data", "").startswith("v=DMARC1")
                ]
                if vals:
                    result["DMARC"] = vals
        except Exception as e:
            logger.debug(f"DMARC query error: {e}")

    # ── Format output ─────────────────────────────────────────────────────
    lines = [
        f"DNS Lookup: {host}",
        f"Base domain: {base_domain}",
        "=" * 48,
    ]

    if not result:
        lines.append("Tidak ada DNS record ditemukan.")
        return "\n".join(lines)

    order = ["A", "AAAA", "CNAME", "MX", "NS", "SOA", "TXT", "DMARC"]
    shown = set()
    for rtype in order:
        if rtype in result:
            shown.add(rtype)
            lines.append(f"\n[{rtype}]")
            for v in result[rtype]:
                lines.append(f"  {v}")

    # Any remaining types not in order
    for rtype, vals in result.items():
        if rtype not in shown:
            lines.append(f"\n[{rtype}]")
            for v in vals:
                lines.append(f"  {v}")

    # ── Security notes ────────────────────────────────────────────────────
    notes = []
    spf_vals = [v for v in result.get("TXT", []) if v.startswith("v=spf1")]
    if not spf_vals:
        notes.append("  WARNING: Tidak ada SPF record — rentan email spoofing")
    else:
        spf = spf_vals[0]
        if "+all" in spf:
            notes.append("  CRITICAL: SPF '+all' — siapapun bisa spoof email domain ini!")
        elif "?all" in spf:
            notes.append("  MEDIUM: SPF '?all' — tidak memproteksi spoofing, gunakan -all")
    if "DMARC" not in result:
        notes.append("  WARNING: Tidak ada DMARC record — email fraud tidak terproteksi")
    else:
        dmarc_val = result["DMARC"][0]
        m = re.search(r'p=(\w+)', dmarc_val)
        if m and m.group(1).lower() == "none":
            notes.append("  MEDIUM: DMARC p=none — tidak ada enforcement, ubah ke quarantine/reject")

    if notes:
        lines.append("\n-- Catatan Keamanan --")
        lines.extend(notes)

    return "\n".join(lines)


# ── Main Scanner ──────────────────────────────────────────────────────────

async def scan_target(target: str) -> dict:
    """
    Run full security scan on target.
    Returns a structured dict with all findings.
    """
    url    = _normalize_url(target)
    parsed = urlparse(url)
    host   = parsed.hostname or target
    scheme = parsed.scheme

    findings: list[dict] = []
    info: dict[str, Any] = {
        "target":   target,
        "url":      url,
        "host":     host,
        "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # ── 1. DNS Resolution ─────────────────────────────────────────────────
    try:
        ip = socket.gethostbyname(host)
        info["ip"] = ip
        addr = ipaddress.ip_address(ip)
        if addr.is_private or addr.is_loopback:
            return {
                "error": f"Target {host} resolves to private/loopback IP ({ip}). Scan aborted.",
                "info": info,
                "findings": [],
            }
    except socket.gaierror as e:
        return {
            "error": f"DNS resolution failed for {host}: {e}",
            "info": info,
            "findings": [],
        }

    # ── 2. Port Scan ──────────────────────────────────────────────────────
    open_ports = []
    tasks = [_probe_port(host, port) for port, _ in COMMON_PORTS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for (port, service), is_open in zip(COMMON_PORTS, results):
        if is_open is True:
            open_ports.append((port, service))
            # Flag dangerous open ports
            if port in (21, 23, 445, 3306, 5432, 6379, 27017, 3389):
                severity = "HIGH" if port in (3389, 445) else "MEDIUM"
                findings.append({
                    "category": "Open Port",
                    "severity": severity,
                    "title":    f"Port {port}/{service} terbuka",
                    "detail":   f"Port {port} ({service}) accessible dari internet. "
                                f"Pertimbangkan firewall rule untuk membatasi akses.",
                })
    info["open_ports"] = [f"{p}/{s}" for p, s in open_ports]

    # ── 3. SSL/TLS Check ─────────────────────────────────────────────────
    if scheme == "https" or any(p == 443 for p, _ in open_ports):
        ssl_info = await asyncio.get_event_loop().run_in_executor(
            None, _check_ssl_cert, host, 443
        )
        info["ssl"] = ssl_info
        if ssl_info.get("error"):
            findings.append({
                "category": "SSL/TLS",
                "severity": "CRITICAL",
                "title":    "SSL certificate error",
                "detail":   ssl_info["error"],
            })
        elif ssl_info.get("expired"):
            findings.append({
                "category": "SSL/TLS",
                "severity": "CRITICAL",
                "title":    "Sertifikat SSL sudah kedaluwarsa",
                "detail":   f"Expired pada {ssl_info['not_after']}. Pengguna akan mendapat peringatan browser.",
            })
        elif ssl_info.get("expiring_soon"):
            findings.append({
                "category": "SSL/TLS",
                "severity": "MEDIUM",
                "title":    f"Sertifikat SSL akan kedaluwarsa dalam {ssl_info['days_left']} hari",
                "detail":   f"Perbarui sertifikat sebelum {ssl_info['not_after']}.",
            })
        if ssl_info.get("weak_protocol"):
            findings.append({
                "category": "SSL/TLS",
                "severity": "HIGH",
                "title":    f"Protokol lama digunakan: {ssl_info.get('protocol')}",
                "detail":   "TLS 1.0/1.1 sudah deprecated. Gunakan TLS 1.2+ (TLS 1.3 disarankan).",
            })

    # Check HTTP → HTTPS redirect
    if scheme == "https":
        try:
            async with httpx.AsyncClient(
                follow_redirects=False, timeout=SCAN_TIMEOUT,
                verify=False
            ) as client:
                http_url = url.replace("https://", "http://", 1)
                resp = await client.get(http_url)
                if resp.status_code not in (301, 302, 307, 308) or \
                   "https" not in resp.headers.get("location", "").lower():
                    findings.append({
                        "category": "SSL/TLS",
                        "severity": "HIGH",
                        "title":    "HTTP tidak redirect ke HTTPS",
                        "detail":   f"Akses via HTTP tidak otomatis dialihkan ke HTTPS. "
                                    f"HTTP status: {resp.status_code}",
                    })
        except Exception:
            pass

    # ── 4. HTTP Headers & Content Analysis ───────────────────────────────
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=SCAN_TIMEOUT,
            verify=False,
            headers={"User-Agent": "Mozilla/5.0 (SecurityAudit/Hermes)"},
        ) as client:
            resp = await client.get(url)

        info["http_status"]  = resp.status_code
        info["final_url"]    = str(resp.url)
        info["server"]       = resp.headers.get("server", "")
        info["x_powered_by"] = resp.headers.get("x-powered-by", "")
        body = resp.text[:MAX_BODY_SCAN]

        # ── 4a. Security headers ─────────────────────────────────────────
        missing_headers = []
        for header, (short, detail) in SECURITY_HEADERS.items():
            if header.lower() not in {k.lower() for k in resp.headers.keys()}:
                severity = detail.split(" — ")[0]
                missing_headers.append((header, severity, detail))
                findings.append({
                    "category": "Security Header",
                    "severity": severity,
                    "title":    f"Header {header} tidak ada",
                    "detail":   detail,
                })
        info["missing_headers"] = [h for h, _, _ in missing_headers]

        # ── 4b. Server info leakage ──────────────────────────────────────
        server_val = resp.headers.get("server", "")
        xpb_val    = resp.headers.get("x-powered-by", "")
        if server_val and re.search(r'[\d.]', server_val):
            findings.append({
                "category": "Information Disclosure",
                "severity": "LOW",
                "title":    f"Server header mengungkap versi: {server_val}",
                "detail":   "Versi software server terekspos di header. Attacker bisa mencari CVE spesifik.",
            })
        if xpb_val:
            findings.append({
                "category": "Information Disclosure",
                "severity": "LOW",
                "title":    f"X-Powered-By mengekspos teknologi: {xpb_val}",
                "detail":   "Header X-Powered-By mengungkap teknologi backend. Sebaiknya dihilangkan.",
            })

        # ── 4c. Cookie flags ─────────────────────────────────────────────
        for cookie in resp.cookies.jar:
            issues = []
            if not getattr(cookie, "_rest", {}).get("HttpOnly") and "httponly" not in str(cookie).lower():
                issues.append("HttpOnly flag tidak ada (XSS bisa mencuri cookie)")
            if not cookie.secure:
                issues.append("Secure flag tidak ada (cookie bisa dikirim lewat HTTP)")
            if "samesite" not in str(cookie).lower():
                issues.append("SameSite tidak di-set (rentan CSRF)")
            if issues:
                findings.append({
                    "category": "Cookie Security",
                    "severity": "MEDIUM",
                    "title":    f"Cookie '{cookie.name}' tidak aman",
                    "detail":   " | ".join(issues),
                })

        # ── 4d. Content checks ───────────────────────────────────────────
        # Check for forms without CSRF token hint
        forms = re.findall(r'<form[^>]*method=["\']post["\'][^>]*>', body, re.IGNORECASE)
        csrf_tokens = re.findall(r'csrf|_token|nonce', body, re.IGNORECASE)
        if forms and not csrf_tokens:
            findings.append({
                "category": "CSRF",
                "severity": "HIGH",
                "title":    f"Ditemukan {len(forms)} form POST tanpa indikasi CSRF token",
                "detail":   "Form tanpa CSRF protection rentan terhadap Cross-Site Request Forgery.",
            })

        # Mixed content check
        if scheme == "https" and re.search(r'src=["\']http://', body):
            findings.append({
                "category": "Mixed Content",
                "severity": "MEDIUM",
                "title":    "Mixed content detected (HTTP resource dalam halaman HTTPS)",
                "detail":   "Resource HTTP di-load dalam halaman HTTPS. Browser modern memblokir ini.",
            })

        # HTML comment leakage
        comments = re.findall(r'<!--(.*?)-->', body, re.DOTALL)
        for c in comments:
            if any(kw in c.lower() for kw in ["password", "pass:", "secret", "key", "token", "todo", "fixme", "hack", "debug"]):
                findings.append({
                    "category": "Information Disclosure",
                    "severity": "MEDIUM",
                    "title":    "HTML comment berisi informasi sensitif",
                    "detail":   f"Ditemukan komentar HTML mencurigakan: {c[:120].strip()!r}",
                })
                break

        # ── 4e. WAF / CDN Detection ──────────────────────────────────────
        detected_waf: list[str] = []
        resp_headers_lower = {k.lower(): v for k, v in resp.headers.items()}
        for hdr, (product, conf) in WAF_SIGNATURES.items():
            if hdr in resp_headers_lower:
                if product not in detected_waf:
                    detected_waf.append(product)
        # Check server header against patterns
        for pattern, product in WAF_SERVER_PATTERNS:
            if re.search(pattern, resp_headers_lower.get("server", ""), re.IGNORECASE):
                if product not in detected_waf:
                    detected_waf.append(product)
        info["waf_cdn"] = detected_waf
        if detected_waf:
            findings.append({
                "category": "WAF/CDN",
                "severity": "INFO",
                "title":    f"Detected: {', '.join(detected_waf)}",
                "detail":   "WAF/CDN terdeteksi. Perlu teknik bypass WAF untuk pentest lebih lanjut.",
            })

        # ── 4f. Technology Fingerprinting ───────────────────────────────
        tech_stack: list[str] = []

        # From headers
        xpb = resp_headers_lower.get("x-powered-by", "")
        if xpb:
            tech_stack.append(xpb)
        if resp_headers_lower.get("x-aspnet-version"):
            tech_stack.append(f"ASP.NET {resp_headers_lower['x-aspnet-version']}")
        if resp_headers_lower.get("x-generator"):
            tech_stack.append(resp_headers_lower["x-generator"])

        # From cookies
        for cookie in resp.cookies.jar:
            mapped = TECH_COOKIE_MAP.get(cookie.name)
            if mapped and mapped not in tech_stack:
                tech_stack.append(mapped)

        # From body meta/generator
        meta_gen = re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)["\']',
                             body, re.IGNORECASE)
        if meta_gen and meta_gen.group(1).strip():
            gen_val = meta_gen.group(1).strip()
            if gen_val not in tech_stack:
                tech_stack.append(gen_val)

        # CMS Detection — comprehensive fingerprinting (body + headers + cookies)
        detected_cms = _detect_cms(body, resp_headers_lower, resp.cookies.jar)
        for cms_name in detected_cms:
            if cms_name not in tech_stack:
                tech_stack.append(cms_name)

        # Django (Python) — CSRF token pattern
        if re.search(r'<input[^>]+name="csrfmiddlewaretoken"', body):
            if "Django (Python)" not in tech_stack:
                tech_stack.append("Django (Python)")

        # Frontend frameworks
        if re.search(r'ng-version|angular\.min\.js|Angular', body):
            if "Angular" not in tech_stack:
                tech_stack.append("Angular")
        if re.search(r'__NEXT_DATA__|_next/static', body):
            if "Next.js" not in tech_stack:
                tech_stack.append("Next.js")
        if re.search(r'react\.development|react\.production|__reactFiber', body):
            if "React" not in tech_stack:
                tech_stack.append("React")
        if re.search(r'vue\.min\.js|vue\.runtime|__vue', body, re.IGNORECASE):
            if "Vue.js" not in tech_stack:
                tech_stack.append("Vue.js")

        info["tech_stack"]  = tech_stack
        info["detected_cms"] = detected_cms

        # Flag SaaS/hosted platforms
        _saas_cms = {"Shopify", "Wix", "Squarespace"}
        _hosted_detected = [c for c in detected_cms if c in _saas_cms]
        if _hosted_detected:
            findings.append({
                "category": "CMS",
                "severity": "INFO",
                "title":    f"Platform SaaS/Hosted terdeteksi: {', '.join(_hosted_detected)}",
                "detail":   "Platform hosted — tidak ada self-hosted vulnerability path. "
                            "Fokus audit pada konfigurasi toko, CSP, third-party scripts, dan data exposure.",
            })

    except httpx.ConnectError:
        findings.append({
            "category": "Connectivity",
            "severity": "INFO",
            "title":    "Tidak bisa connect ke target",
            "detail":   f"Tidak bisa terhubung ke {url}. Host mungkin down atau memblokir scanner.",
        })
    except Exception as e:
        logger.warning(f"HTTP analysis error for {url}: {e}")

    # ── 5. Sensitive Path Discovery (HEAD — efficient, no body download) ─────
    found_paths = []
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=SCAN_TIMEOUT,
        verify=False,
        headers={"User-Agent": "Mozilla/5.0 (SecurityAudit/Hermes)"},
    ) as client:
        path_tasks = []
        for path in SENSITIVE_PATHS:
            path_tasks.append(client.head(f"{url}{path}"))

        path_results = await asyncio.gather(*path_tasks, return_exceptions=True)

    for path, result in zip(SENSITIVE_PATHS, path_results):
        if isinstance(result, Exception):
            continue
        status = result.status_code
        # 405 = server doesn't support HEAD for this path → fall back interpretation
        if status in (200, 403):
            severity = "CRITICAL" if path in ("/.git/HEAD", "/.env", "/.htpasswd", "/backup.sql", "/dump.sql") \
                       else "HIGH" if path in ("/.git/config", "/phpinfo.php", "/wp-config.php", "/actuator/env") \
                       else "MEDIUM"
            label = "terekspos" if status == 200 else "ada (tapi akses diblokir 403)"
            found_paths.append(path)
            findings.append({
                "category": "Sensitive Path",
                "severity": severity,
                "title":    f"{path} {label} (HEAD {status})",
                "detail":   _sensitive_path_detail(path, status),
            })

    info["found_paths"] = found_paths

    # ── 5b. LLM-guided paths — AI generates targeted probes from fingerprint ──
    try:
        _llm_probe_paths = await _llm_generate_paths(
            {
                "tech_stack": info.get("tech_stack", []),
                "server":     info.get("server", ""),
                "waf_cdn":    info.get("waf_cdn", []),
            },
            already_found=found_paths,
            context="path",
            max_paths=25,
        )
        if _llm_probe_paths:
            info["llm_probed"] = len(_llm_probe_paths)
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=SCAN_TIMEOUT,
                verify=False,
                headers={"User-Agent": "Mozilla/5.0 (SecurityAudit/Hermes)"},
            ) as _llm_client:
                _llm_tasks = [_llm_client.head(f"{url}{p}") for p in _llm_probe_paths]
                _llm_results = await asyncio.gather(*_llm_tasks, return_exceptions=True)
            for _p, _r in zip(_llm_probe_paths, _llm_results):
                if isinstance(_r, Exception):
                    continue
                if _r.status_code in (200, 403):
                    _sev = _guess_severity(_p, _r.status_code)
                    _label = "terekspos" if _r.status_code == 200 else "ada tapi diblokir (403)"
                    findings.append({
                        "category": "AI-Discovered Path",
                        "severity": _sev,
                        "title":    f"[AI] {_p} {_label} ({_r.status_code})",
                        "detail":   f"Path ditemukan oleh AI probe berdasarkan fingerprint stack. "
                                    f"Verifikasi manual disarankan.",
                    })
                    if _p not in found_paths:
                        found_paths.append(_p)
    except Exception as _e:
        logger.debug(f"LLM probe phase error: {_e}")

    # ── 5c. CMS-Specific Path Probing ─────────────────────────────────────────
    _cms_probe_paths: list[str] = []
    for _cms_name in info.get("detected_cms", []):
        for _cms_p in CMS_PATHS.get(_cms_name, []):
            if _cms_p not in SENSITIVE_PATHS and _cms_p not in found_paths and _cms_p not in _cms_probe_paths:
                _cms_probe_paths.append(_cms_p)

    if _cms_probe_paths:
        async with httpx.AsyncClient(
            follow_redirects=False, timeout=SCAN_TIMEOUT, verify=False,
            headers={"User-Agent": "Mozilla/5.0 (SecurityAudit/Hermes)"},
        ) as _cms_client:
            _cms_tasks   = [_cms_client.head(f"{url}{_cp}") for _cp in _cms_probe_paths]
            _cms_results = await asyncio.gather(*_cms_tasks, return_exceptions=True)
        for _cp, _cr in zip(_cms_probe_paths, _cms_results):
            if isinstance(_cr, Exception):
                continue
            if _cr.status_code in (200, 403):
                _sev = _guess_severity(_cp, _cr.status_code)
                # Escalate severity for credential-containing files
                if _cp in ("/wp-config.php", "/wp-config.php.bak", "/wp-config.php~",
                            "/app/etc/local.xml", "/app/etc/env.php",
                            "/config/config.inc.php", "/config/settings.inc.php",
                            "/sites/default/settings.php", "/app/config/parameters.php",
                            "/admin/config.php", "/config.php"):
                    _sev = "CRITICAL"
                elif _cp in ("/xmlrpc.php", "/wp-login.php", "/wp-admin/",
                              "/administrator/", "/administrator/index.php",
                              "/downloader/", "/wp-json/wp/v2/users",
                              "/wp-content/debug.log", "/wp-json/wc/v3/orders",
                              "/wp-json/wc/v3/customers", "/var/export/"):
                    _sev = "HIGH"
                _label = "terekspos" if _cr.status_code == 200 else "ada tapi diblokir (403)"
                findings.append({
                    "category": "CMS Path",
                    "severity": _sev,
                    "title":    f"[CMS] {_cp} {_label} ({_cr.status_code})",
                    "detail":   _cms_path_detail(_cp, _cr.status_code),
                })
                if _cp not in found_paths:
                    found_paths.append(_cp)

    # ── 5b. HTTP Methods Audit ───────────────────────────────────────────────
    # Tests: GET HEAD POST PUT DELETE PATCH TRACE OPTIONS
    info["allowed_methods"] = []
    info["method_checks"]   = {}   # {METHOD: status_code or "ERR"}
    test_path = f"/hermes-probe-{int(datetime.now().timestamp())}.txt"
    try:
        async with httpx.AsyncClient(
            follow_redirects=False, timeout=SCAN_TIMEOUT, verify=False,
            headers={"User-Agent": "Mozilla/5.0 (SecurityAudit/Hermes)"},
        ) as mc:

            # GET
            try:
                _gr = await mc.get(url)
                info["method_checks"]["GET"] = _gr.status_code
            except Exception as e:
                info["method_checks"]["GET"] = "ERR"
                logger.debug(f"GET check failed: {e}")

            # HEAD
            try:
                _hr = await mc.head(url)
                info["method_checks"]["HEAD"] = _hr.status_code
            except Exception as e:
                info["method_checks"]["HEAD"] = "ERR"
                logger.debug(f"HEAD check failed: {e}")

            # OPTIONS — enumerate allowed methods
            try:
                opt = await mc.options(url)
                info["method_checks"]["OPTIONS"] = opt.status_code
                raw = opt.headers.get("Allow", "") or \
                      opt.headers.get("Access-Control-Allow-Methods", "")
                allowed: set[str] = {
                    m.strip().upper()
                    for m in re.split(r"[,\s]+", raw)
                    if m.strip()
                } if raw else set()
                info["allowed_methods"] = sorted(allowed)
                dangerous = {"PUT", "DELETE", "TRACE", "CONNECT", "DEBUG"} & allowed
                if dangerous:
                    findings.append({
                        "category": "HTTP Methods",
                        "severity": "HIGH",
                        "title":    f"Method berbahaya dilaporkan OPTIONS: {', '.join(sorted(dangerous))}",
                        "detail":   "PUT/DELETE bisa dipakai untuk modifikasi file; "
                                    "TRACE rentan Cross-Site Tracing (XST); "
                                    "DEBUG dapat mengekspos diagnostik internal.",
                    })
            except Exception as e:
                info["method_checks"]["OPTIONS"] = "ERR"
                logger.debug(f"OPTIONS check failed: {e}")

            # POST + null Origin — CORS misconfiguration
            try:
                post_r = await mc.post(
                    url,
                    headers={
                        "Origin": "null",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    content=b"hermes=probe",
                )
                info["method_checks"]["POST"] = post_r.status_code
                acao = post_r.headers.get("Access-Control-Allow-Origin", "")
                acac = post_r.headers.get("Access-Control-Allow-Credentials", "").lower()
                if acao in ("*", "null"):
                    sev = "HIGH" if acac == "true" else "MEDIUM"
                    findings.append({
                        "category": "CORS",
                        "severity": sev,
                        "title":    f"CORS misconfiguration: ACAO={acao}"
                                    + (" + Credentials=true" if acac == "true" else ""),
                        "detail":   "Origin wildcard atau null diizinkan. " +
                                    ("Credentials juga diizinkan — sangat berbahaya, "
                                     "memungkinkan cross-origin request dengan session korban!"
                                     if acac == "true" else
                                     "Bisa dieksploitasi untuk cross-origin data theft."),
                    })
            except Exception as e:
                info["method_checks"]["POST"] = "ERR"
                logger.debug(f"CORS POST check failed: {e}")

            # PUT — arbitrary file upload check
            try:
                put_r = await mc.put(f"{url}{test_path}", content=b"hermes-security-test")
                info["method_checks"]["PUT"] = put_r.status_code
                if put_r.status_code in (200, 201, 204):
                    findings.append({
                        "category": "HTTP Methods",
                        "severity": "CRITICAL",
                        "title":    "HTTP PUT tidak terproteksi — arbitrary file upload!",
                        "detail":   f"PUT {test_path} berhasil ({put_r.status_code}). "
                                    "Attacker bisa meng-upload web shell atau file berbahaya ke server.",
                    })
            except Exception as e:
                info["method_checks"]["PUT"] = "ERR"
                logger.debug(f"PUT check failed: {e}")

            # DELETE — unauthorized delete check
            try:
                del_r = await mc.delete(f"{url}{test_path}")
                info["method_checks"]["DELETE"] = del_r.status_code
                if del_r.status_code in (200, 204):
                    findings.append({
                        "category": "HTTP Methods",
                        "severity": "CRITICAL",
                        "title":    "HTTP DELETE tidak terproteksi — arbitrary file delete!",
                        "detail":   f"DELETE {test_path} berhasil ({del_r.status_code}). "
                                    "Attacker bisa menghapus file di server tanpa autentikasi.",
                    })
            except Exception as e:
                info["method_checks"]["DELETE"] = "ERR"
                logger.debug(f"DELETE check failed: {e}")

            # PATCH — check if allowed
            try:
                patch_r = await mc.patch(
                    f"{url}{test_path}",
                    content=b"hermes=patch-probe",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                info["method_checks"]["PATCH"] = patch_r.status_code
                if patch_r.status_code in (200, 204):
                    findings.append({
                        "category": "HTTP Methods",
                        "severity": "HIGH",
                        "title":    f"HTTP PATCH diterima ({patch_r.status_code}) — modifikasi resource tanpa auth!",
                        "detail":   "PATCH method diizinkan tanpa autentikasi. Attacker bisa memodifikasi resource.",
                    })
            except Exception as e:
                info["method_checks"]["PATCH"] = "ERR"
                logger.debug(f"PATCH check failed: {e}")

            # TRACE — Cross-Site Tracing (XST)
            try:
                tr = await mc.request("TRACE", url)
                info["method_checks"]["TRACE"] = tr.status_code
                if tr.status_code == 200:
                    findings.append({
                        "category": "HTTP Methods",
                        "severity": "HIGH",
                        "title":    "HTTP TRACE aktif — rentan Cross-Site Tracing (XST)",
                        "detail":   "TRACE method aktif. Bisa dipakai untuk membaca header sensitif "
                                    "(termasuk cookies) via XST attack di browser korban.",
                    })
            except Exception as e:
                info["method_checks"]["TRACE"] = "ERR"
                logger.debug(f"TRACE check failed: {e}")

    except Exception as e:
        logger.warning(f"HTTP methods audit error: {e}")

    # ── 7. DNS Email Security (SPF / DMARC / DKIM) via DoH ───────────────
    # Strip to registrable base domain (handles ac.id, co.uk, etc.)
    base_domain = _extract_base_domain(host)
    info["base_domain"] = base_domain
    info["dns_email"] = {}
    try:
        doh_headers = {
            "Accept": "application/dns-json",
            "User-Agent": "Mozilla/5.0 (SecurityAudit/Hermes)",
        }
        async with httpx.AsyncClient(timeout=10, headers=doh_headers) as doh:
            # SPF — query TXT records on the root domain
            spf_found = False
            dmarc_found = False
            dmarc_policy = ""
            try:
                r = await doh.get(
                    f"https://cloudflare-dns.com/dns-query?name={base_domain}&type=TXT"
                )
                if r.status_code == 200:
                    for ans in r.json().get("Answer", []):
                        val = ans.get("data", "").strip('"')
                        if val.startswith("v=spf1"):
                            spf_found = True
                            info["dns_email"]["spf"] = val[:200]
                            # Check for overly permissive SPF
                            if "+all" in val:
                                findings.append({
                                    "category": "Email Security",
                                    "severity": "CRITICAL",
                                    "title":    "SPF record menggunakan '+all' — siapapun bisa spoof email!",
                                    "detail":   f"SPF: {val[:100]}. '+all' artinya semua server diizinkan kirim email atas nama domain ini.",
                                })
                            elif "?all" in val:
                                findings.append({
                                    "category": "Email Security",
                                    "severity": "MEDIUM",
                                    "title":    "SPF record menggunakan '?all' (neutral) — tidak memproteksi spoofing",
                                    "detail":   f"SPF: {val[:100]}. Gunakan '-all' (fail) atau '~all' (softfail).",
                                })
            except Exception as e:
                logger.debug(f"SPF DoH query error: {e}")

            if not spf_found:
                findings.append({
                    "category": "Email Security",
                    "severity": "HIGH",
                    "title":    "Tidak ada SPF record — domain rentan email spoofing",
                    "detail":   f"Tidak ditemukan SPF TXT record untuk {base_domain}. Attacker bisa kirim email palsu mengatasnamakan domain ini.",
                })

            # DMARC — query _dmarc.{domain}
            try:
                r = await doh.get(
                    f"https://cloudflare-dns.com/dns-query?name=_dmarc.{base_domain}&type=TXT"
                )
                if r.status_code == 200:
                    for ans in r.json().get("Answer", []):
                        val = ans.get("data", "").strip('"')
                        if val.startswith("v=DMARC1"):
                            dmarc_found = True
                            info["dns_email"]["dmarc"] = val[:300]
                            # Check policy
                            policy_match = re.search(r'p=(\w+)', val)
                            if policy_match:
                                dmarc_policy = policy_match.group(1).lower()
                            if dmarc_policy == "none":
                                findings.append({
                                    "category": "Email Security",
                                    "severity": "MEDIUM",
                                    "title":    "DMARC policy = none — tidak ada enforcement",
                                    "detail":   f"DMARC ada tapi p=none tidak memblokir spoofed email. Ubah ke p=quarantine atau p=reject.",
                                })
            except Exception as e:
                logger.debug(f"DMARC DoH query error: {e}")

            if not dmarc_found:
                findings.append({
                    "category": "Email Security",
                    "severity": "HIGH",
                    "title":    "Tidak ada DMARC record — email fraud tidak terproteksi",
                    "detail":   f"Tidak ditemukan _dmarc.{base_domain}. DMARC mencegah phishing/spoofing yang menggunakan domain ini.",
                })

    except Exception as e:
        logger.warning(f"DNS email security check error: {e}")

    # ── 6. Passive Subdomain Enumeration ──────────────────────────────────
    info["subdomains"] = []
    try:
        subs = await _enum_subdomains_passive(base_domain)
        info["subdomains"] = subs
        for s in subs:
            sub_label = s["subdomain"].split(".")[0]
            if sub_label in _RISKY_SUBS:
                findings.append({
                    "category": "Subdomain",
                    "severity": "HIGH",
                    "title":    f"Subdomain berisiko ditemukan: {s['subdomain']} ({s.get('ip', '?')})",
                    "detail":   f"Subdomain environment berisiko ({sub_label}) terekspos publik. "
                                f"Sumber: {', '.join(s.get('sources', []))}. "
                                f"Environment dev/staging/admin sering tidak se-hardened produksi.",
                })
    except Exception as e:
        logger.warning(f"Subdomain enumeration error: {e}")

    # ── Sort findings by severity ─────────────────────────────────────────
    findings.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 99))

    # ── Summary stats ─────────────────────────────────────────────────────
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
    for f in findings:
        counts[f.get("severity", "INFO")] = counts.get(f.get("severity", "INFO"), 0) + 1

    risk_score = (
        counts["CRITICAL"] * 10 +
        counts["HIGH"]     * 5  +
        counts["MEDIUM"]   * 2  +
        counts["LOW"]      * 1
    )
    if risk_score >= 30:
        risk_level = "KRITIS"
    elif risk_score >= 15:
        risk_level = "TINGGI"
    elif risk_score >= 5:
        risk_level = "SEDANG"
    else:
        risk_level = "RENDAH"

    return {
        "info":       info,
        "findings":   findings,
        "counts":     counts,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "error":      None,
    }


def _cms_path_detail(path: str, status: int) -> str:
    """Return a human-readable description for CMS-specific sensitive path findings."""
    details = {
        # WordPress
        "/wp-login.php":                        "Halaman login WordPress publik — rentan brute-force attack.",
        "/wp-admin/":                           "Panel admin WordPress terekspos publik.",
        "/wp-config.php":                       "KRITIS: wp-config.php berisi DB credentials dan secret keys!",
        "/wp-config.php.bak":                   "Backup wp-config.php terekspos — berisi DB credentials.",
        "/wp-config.php~":                      "Backup temp wp-config.php terekspos — berisi DB credentials.",
        "/xmlrpc.php":                          "XML-RPC aktif — rentan brute-force amplification dan DDoS.",
        "/wp-json/wp/v2/users":                 "WordPress REST API mengekspos daftar user (user enumeration).",
        "/wp-content/debug.log":                "Debug log WordPress terekspos — dapat mengandung stack trace dan path sensitif.",
        "/wp-includes/wlwmanifest.xml":         "Windows Live Writer manifest terekspos — mengungkap endpoint WordPress.",
        # WooCommerce
        "/wp-json/wc/v3/orders":                "WooCommerce REST API orders terekspos — data transaksi pelanggan!",
        "/wp-json/wc/v3/customers":             "WooCommerce REST API customers terekspos — data PII pelanggan!",
        # Joomla
        "/administrator/":                      "Panel administrator Joomla terekspos — rentan brute-force.",
        "/administrator/index.php":             "Halaman login admin Joomla terekspos.",
        "/administrator/manifests/files/joomla.xml": "Manifest Joomla mengekspos versi instalasi.",
        "/configuration.php~":                  "Backup konfigurasi Joomla — kemungkinan berisi DB credentials.",
        "/configuration.php.bak":               "Backup konfigurasi Joomla — kemungkinan berisi DB credentials.",
        "/htaccess.txt":                        "File htaccess sample Joomla terekspos — mengungkap konfigurasi server.",
        "/joomla.xml":                          "Manifest Joomla mengekspos versi instalasi.",
        # Drupal
        "/user/login":                          "Halaman login Drupal terekspos publik.",
        "/user/password":                       "Endpoint reset password Drupal terekspos.",
        "/CHANGELOG.txt":                       "Changelog Drupal mengekspos versi instalasi — membantu attacker menargetkan CVE.",
        "/core/CHANGELOG.txt":                  "Changelog Drupal 8+ mengekspos versi instalasi.",
        "/INSTALL.txt":                         "File instalasi terekspos — mengungkap versi CMS.",
        "/sites/default/settings.php":          "KRITIS: settings.php Drupal berisi DB credentials!",
        "/sites/default/files/":                "Direktori file upload Drupal terekspos.",
        # Magento
        "/downloader/":                         "Magento Connect Downloader terekspos — rentan RCE!",
        "/app/etc/local.xml":                   "KRITIS: local.xml Magento 1 berisi DB credentials dan encryption key!",
        "/app/etc/env.php":                     "KRITIS: env.php Magento 2 berisi DB credentials dan encryption key!",
        "/var/export/":                         "Direktori export Magento terekspos — mungkin berisi data pelanggan.",
        "/var/log/system.log":                  "System log Magento terekspos — berisi informasi error dan path internal.",
        "/magento_version":                     "File versi Magento terekspos.",
        "/RELEASE_NOTES.txt":                   "Release notes Magento mengekspos versi instalasi.",
        "/install.php":                         "Script instalasi Magento terekspos — harus dihapus setelah install.",
        # PrestaShop
        "/config/config.inc.php":               "KRITIS: config.inc.php PrestaShop berisi DB credentials!",
        "/app/config/parameters.php":           "KRITIS: parameters.php PrestaShop berisi DB credentials!",
        "/config/settings.inc.php":             "KRITIS: settings.inc.php PrestaShop berisi DB credentials!",
        "/admin-dev/":                          "Panel admin PrestaShop (dev) terekspos.",
        # OpenCart
        "/config.php":                          "config.php OpenCart berisi DB credentials dan secret key.",
        "/admin/config.php":                    "Admin config OpenCart berisi credentials — harus diproteksi!",
        "/system/logs/":                        "Direktori logs OpenCart terekspos — berisi informasi error.",
    }
    base = details.get(path, f"Path CMS sensitif {path} ditemukan.")
    if status == 403:
        base += " (Akses diblokir 403 — resource ada tapi terproteksi; pertimbangkan menghapusnya.)"
    return base


def _sensitive_path_detail(path: str, status: int) -> str:
    details = {
        "/.git/HEAD":       "Repository Git terekspos! Source code, history, dan credential bisa diunduh.",
        "/.git/config":     "Konfigurasi Git terekspos. Bisa mengandung credential repository.",
        "/.env":            "File .env terekspos! Kemungkinan berisi DB password, API key, secret key.",
        "/.htpasswd":       "File htpasswd terekspos. Berisi username dan password hash.",
        "/phpinfo.php":     "phpinfo() terekspos — mengungkap konfigurasi PHP, path, dan environment variable.",
        "/wp-config.php":   "wp-config.php WordPress berisi kredensial database.",
        "/backup.sql":      "File backup database SQL dapat diunduh — data breach potensial!",
        "/dump.sql":        "SQL dump terekspos — data breach potensial!",
        "/actuator/env":    "Spring Boot Actuator env endpoint — mengekspos konfigurasi aplikasi.",
        "/swagger.json":    "API documentation terekspos — semua endpoint terdokumentasi untuk attacker.",
        "/swagger-ui.html": "Swagger UI terekspos — API documentation dan testing interface public.",
    }
    base = details.get(path, f"Path sensitif {path} dapat diakses.")
    if status == 403:
        base += " (Akses diblokir tapi resource ada — pertimbangkan menghapusnya.)"
    return base


# ── Report Formatter ──────────────────────────────────────────────────────

def _md_escape(text: str) -> str:
    """Escape characters that break Telegram MarkdownV1 in plain text spans."""
    # Only escape chars that are special outside of code/bold/italic spans
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text


def format_report(result: dict) -> str:
    """Format scan result as plain text (no Markdown) to avoid Telegram parse errors."""
    if result.get("error") and not result.get("findings"):
        return f"Scan gagal: {result['error']}"

    info     = result["info"]
    findings = result["findings"]
    counts   = result["counts"]
    risk     = result["risk_level"]

    risk_emoji = {"KRITIS": "🔴", "TINGGI": "🟠", "SEDANG": "🟡", "RENDAH": "🟢"}.get(risk, "⚪")

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "🔍 SECURITY SCAN REPORT",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Target  : {info['target']}",
        f"IP      : {info.get('ip', 'N/A')}",
        f"Waktu   : {info['scan_time']}",
        "",
        f"Risk Level: {risk_emoji} {risk}",
        f"🔴 Critical: {counts['CRITICAL']}  🟠 High: {counts['HIGH']}  🟡 Medium: {counts['MEDIUM']}  🔵 Low: {counts['LOW']}",
        "",
    ]

    # SSL info
    ssl_info = info.get("ssl", {})
    if ssl_info and not ssl_info.get("error"):
        issuer = ssl_info.get('issuer', {}).get('organizationName', '?')
        lines.append("🔒 SSL/TLS")
        lines.append(f"  Issuer  : {issuer}")
        lines.append(f"  Expires : {ssl_info.get('not_after', '?')} ({ssl_info.get('days_left', '?')} hari lagi)")
        lines.append(f"  Protocol: {ssl_info.get('protocol', '?')} / {ssl_info.get('cipher', '?')}")
        lines.append("")
    elif ssl_info and ssl_info.get("error"):
        lines.append(f"🔒 SSL/TLS ERROR: {ssl_info['error']}")
        lines.append("")

    # Open ports
    if info.get("open_ports"):
        lines.append(f"🔌 Open Ports: {', '.join(info['open_ports'])}")
        lines.append("")

    # WAF/CDN
    if info.get("waf_cdn"):
        lines.append(f"🛡️  WAF/CDN  : {', '.join(info['waf_cdn'])}")
        lines.append("")

    # Tech Stack
    if info.get("tech_stack"):
        lines.append(f"⚙️  Tech Stack: {', '.join(info['tech_stack'])}")
        lines.append("")

    # Detected CMS
    if info.get("detected_cms"):
        _saas_r = {"Shopify", "Wix", "Squarespace"}
        _cms_labels = [f"{c} (SaaS)" if c in _saas_r else c for c in info["detected_cms"]]
        lines.append(f"🏪 CMS      : {', '.join(_cms_labels)}")
        lines.append("")

    # DNS Email Security
    dns_email = info.get("dns_email", {})
    spf_val   = dns_email.get("spf", "")
    dmarc_val = dns_email.get("dmarc", "")
    if spf_val or dmarc_val:
        lines.append("📧 DNS Email Security")
        lines.append(f"  SPF  : {spf_val[:80] if spf_val else 'TIDAK ADA'}")
        lines.append(f"  DMARC: {dmarc_val[:80] if dmarc_val else 'TIDAK ADA'}")
        lines.append("")

    # HTTP Method Checks
    mc = info.get("method_checks", {})
    if mc:
        def _mstatus(code) -> str:
            if code == "ERR":
                return "ERR"
            c = int(code)
            if c in (200, 201, 204):
                return f"{c} ✓ ALLOWED"
            elif c == 403:
                return f"{c} 🚫 FORBIDDEN"
            elif c in (405, 501):
                return f"{c} ✗ NOT ALLOWED"
            elif c == 301 or c == 302:
                return f"{c} → REDIRECT"
            else:
                return str(c)
        lines.append("🔧 HTTP Method Checks:")
        for _method in ["GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "TRACE", "OPTIONS"]:
            if _method in mc:
                lines.append(f"  {_method:<8}: {_mstatus(mc[_method])}")
        _am = info.get("allowed_methods", [])
        if _am:
            lines.append(f"  OPTIONS Allow header: {', '.join(_am)}")
        lines.append("")

    # Subdomains
    subs = info.get("subdomains", [])
    if subs:
        risky  = [s for s in subs if s["subdomain"].split(".")[0] in _RISKY_SUBS]
        normal = [s for s in subs if s not in risky]
        lines.append(f"\U0001f310 Subdomains ({len(subs)} ditemukan):")
        if risky:
            lines.append(f"  \u26a0\ufe0f  BERISIKO ({len(risky)}):")
            for s in risky[:15]:
                src = ','.join(s.get('sources', []))
                lines.append(f"    \u2022 {s['subdomain']}  [{s.get('ip','?')}]  (src:{src})")
        if normal:
            lines.append(f"  \u2139\ufe0f  Lainnya ({len(normal)}):")
            for s in normal[:20]:
                src = ','.join(s.get('sources', []))
                lines.append(f"    \u2022 {s['subdomain']}  [{s.get('ip','?')}]  (src:{src})")
            if len(normal) > 20:
                lines.append(f"    ... dan {len(normal)-20} subdomain lainnya (lihat file .json)")
        lines.append("")

    # Findings
    if not findings:
        lines.append("✅ Tidak ditemukan kerentanan signifikan.")
    else:
        severity_emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "⚪"}
        current_sev = None
        for f in findings:
            sev = f["severity"]
            if current_sev != sev:
                current_sev = sev
                lines.append(f"\n{severity_emoji.get(sev, '•')} {sev} FINDINGS:")
            lines.append(f"  [{sev}] {f['title']}")
            lines.append(f"  → {f['detail']}")

    lines.append("")
    lines.append(f"Scan: Hermes Security Scanner • {info['scan_time']}")
    lines.append("⚠️  Gunakan hanya pada sistem yang berwenang.")

    return "\n".join(lines)


# ── Directory Scanner ─────────────────────────────────────────────────────

# Wordlists — paths probed concurrently via HEAD requests
_WORDLIST_STANDARD: list[str] = [
    # Common dirs
    "/admin", "/admin/", "/administrator", "/administration",
    "/api", "/api/v1", "/api/v2", "/api/v3",
    "/backup", "/backups", "/bak",
    "/bin", "/cgi-bin",
    "/config", "/configs", "/configuration",
    "/dashboard", "/db", "/database",
    "/data", "/debug",
    "/dev", "/developer", "/docs", "/documentation",
    "/download", "/downloads",
    "/files", "/file", "/filemanager",
    "/images", "/img", "/assets", "/static", "/media",
    "/include", "/includes", "/inc",
    "/install", "/installer", "/setup",
    "/js", "/javascript", "/css",
    "/lib", "/libs", "/library",
    "/login", "/logout", "/signin", "/signup", "/register",
    "/logs", "/log",
    "/manage", "/management", "/manager",
    "/panel", "/controlpanel", "/cpanel",
    "/private", "/secret", "/secure",
    "/portal", "/public",
    "/scripts", "/script",
    "/server", "/services",
    "/src", "/source",
    "/temp", "/tmp", "/test",
    "/tools", "/util", "/utils",
    "/upload", "/uploads", "/uploader",
    "/user", "/users", "/account", "/accounts",
    "/wp-admin", "/wp-content", "/wp-includes",
    "/xmlrpc.php", "/wp-login.php",
    # API patterns
    "/graphql", "/graphiql", "/api/graphql",
    "/swagger", "/swagger-ui", "/swagger-ui.html", "/swagger.json",
    "/openapi.json", "/openapi.yaml", "/api-docs",
    "/redoc", "/v1", "/v2", "/v3",
    # Sensitive files
    "/.env", "/.env.local", "/.env.backup", "/.env.example",
    "/.git/HEAD", "/.git/config",
    "/.htaccess", "/.htpasswd",
    "/robots.txt", "/sitemap.xml",
    "/phpinfo.php", "/info.php",
    "/server-status", "/server-info",
    "/actuator", "/actuator/health", "/actuator/env",
    "/console", "/h2-console",
    "/.DS_Store", "/.bash_history",
    "/config.php", "/config.json", "/config.yaml", "/web.config",
    "/backup.sql", "/dump.sql", "/database.sql",
    "/backup.zip", "/backup.tar.gz",
    "/package.json", "/composer.json", "/requirements.txt",
    "/Dockerfile", "/docker-compose.yml",
    "/.gitlab-ci.yml", "/.travis.yml", "/Jenkinsfile",
    # Storage
    "/storage", "/storage/logs", "/storage/app",
    "/var", "/var/log",
    # Auth
    "/auth", "/oauth", "/oauth2", "/token",
    "/sso", "/saml", "/oidc",
]

_WORDLIST_API: list[str] = [
    "/api", "/api/v1", "/api/v2", "/api/v3", "/api/v4",
    "/api/v1/users", "/api/v1/user", "/api/v1/auth", "/api/v1/login",
    "/api/v1/admin", "/api/v1/config", "/api/v1/status", "/api/v1/health",
    "/api/v1/products", "/api/v1/items", "/api/v1/orders",
    "/api/v2/users", "/api/v2/auth", "/api/v2/admin",
    "/api/v3/users", "/api/v3/auth",
    "/api/auth", "/api/login", "/api/logout", "/api/register",
    "/api/user", "/api/users", "/api/profile",
    "/api/admin", "/api/config", "/api/settings",
    "/api/data", "/api/export", "/api/import",
    "/api/health", "/api/status", "/api/ping", "/api/version",
    "/api/search", "/api/upload", "/api/download",
    "/api/public", "/api/private",
    "/api/graphql", "/graphql", "/graphiql",
    "/swagger.json", "/swagger-ui.html", "/swagger-ui/",
    "/openapi.json", "/openapi.yaml", "/api-docs", "/api-docs.json",
    "/redoc", "/.well-known/openapi.json",
    "/v1", "/v2", "/v3", "/v4",
    "/v1/api", "/v2/api",
    "/rest", "/rest/v1", "/rest/v2",
    "/rpc", "/jsonrpc", "/xml-rpc", "/xmlrpc.php",
    "/actuator", "/actuator/health", "/actuator/env",
    "/actuator/beans", "/actuator/mappings", "/actuator/info",
    "/health", "/healthz", "/ping", "/status", "/version", "/info",
    "/metrics", "/prometheus",
    "/auth", "/oauth", "/oauth2", "/token", "/authorize",
    "/sso", "/saml", "/oidc", "/callback",
]

_WORDLIST_DEEP: list[str] = _WORDLIST_STANDARD + [
    # More admin panels
    "/phpmyadmin", "/phpmyadmin/", "/pma", "/myadmin",
    "/adminer.php", "/adminer",
    "/webmail", "/mail", "/roundcube", "/squirrelmail",
    "/wp-json", "/wp-json/wp/v2",
    "/xmlrpc",
    "/magento", "/app", "/app/etc", "/var/export",
    "/shell", "/webshell", "/backdoor",
    "/old", "/new", "/bak", "/backup2", "/backup_old",
    "/test2", "/testing", "/staging", "/demo", "/sandbox",
    "/beta", "/alpha", "/qa", "/uat", "/prod", "/production",
    "/error", "/errors", "/error_log",
    "/laravel", "/laravel/public",
    "/django", "/flask", "/rails",
    "/vendor", "/node_modules", "/bower_components",
    "/cache", "/caches", "/tmp", "/temp",
    "/sess", "/session", "/sessions",
    "/socket.io", "/ws", "/websocket",
    "/feed", "/rss", "/atom", "/rss.xml",
    "/cms", "/drupal", "/joomla", "/magento",
    "/.well-known", "/.well-known/security.txt",
    "/security.txt",
    "/crossdomain.xml", "/clientaccesspolicy.xml",
    "/apple-app-site-association",
    "/assetlinks.json",
    "/.ssh", "/.ssh/id_rsa", "/.ssh/id_rsa.pub",
    "/id_rsa", "/id_rsa.pub",
    "/.aws/credentials", "/.aws/config",
    "/wp-content/uploads", "/wp-content/plugins",
    "/wp-content/themes",
    "/administrator/components",
    "/administrator/modules",
    # Backup file variants
    "/index.php.bak", "/index.html.bak", "/config.php.bak",
    "/login.php.bak",
    # Logs
    "/error.log", "/access.log", "/debug.log", "/app.log",
    "/application.log", "/laravel.log",
    "/storage/logs/laravel.log",
]


async def dirscan_target(
    target: str,
    *,
    mode: str = "standard",   # "standard" | "api" | "deep"
    concurrency: int = 30,
    timeout: float = 6.0,
) -> str:
    """
    Directory/path enumeration against target.
    Sends HEAD requests concurrently to a wordlist of paths.
    Returns formatted plain-text report.

    mode:
      "standard" — ~150 common paths
      "api"      — ~90 API-focused paths
      "deep"     — ~300+ paths (standard + extras)
    """
    # Normalise target
    if not target.startswith(("http://", "https://")):
        target = "https://" + target
    parsed = urlparse(target)
    base = f"{parsed.scheme}://{parsed.netloc}"

    wordlist = {
        "api":      _WORDLIST_API,
        "deep":     _WORDLIST_DEEP,
    }.get(mode, _WORDLIST_STANDARD)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }

    found:   list[dict] = []   # {"path", "status", "size", "ct"}
    blocked: list[str]  = []   # 403
    errors:  int        = 0

    sem = asyncio.Semaphore(concurrency)

    async def probe(client: httpx.AsyncClient, path: str) -> None:
        nonlocal errors
        url = base + path
        async with sem:
            try:
                r = await client.head(url, follow_redirects=True)
                status = r.status_code
                if status in (200, 201, 204):
                    ct   = r.headers.get("content-type", "")[:40]
                    size = r.headers.get("content-length", "?")
                    found.append({"path": path, "status": status, "size": size, "ct": ct})
                elif status == 403:
                    blocked.append(path)
                elif status in (301, 302, 307, 308):
                    loc = r.headers.get("location", "")[:60]
                    found.append({"path": path, "status": status, "size": "?", "ct": f"→ {loc}"})
            except Exception:
                errors += 1

    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
        await asyncio.gather(*(probe(client, p) for p in wordlist))

    # Sort found by path
    found.sort(key=lambda x: x["path"])
    blocked.sort()

    # ── Format report ──────────────────────────────────────────────────────
    mode_label = {"api": "API Mode", "deep": "Deep Mode"}.get(mode, "Standard Mode")
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "📂 DIRECTORY SCAN REPORT",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Target : {base}",
        f"Mode   : {mode_label} ({len(wordlist)} paths)",
        f"Waktu  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"✅ Ditemukan  : {len(found)} path",
        f"🚫 Diblokir  : {len(blocked)} path (403)",
        f"⚠️  Error      : {errors}",
        "",
    ]

    if found:
        lines.append("── ACCESSIBLE PATHS ──────────────────────────────")
        for f in found:
            status_icon = "🟢" if f["status"] == 200 else "🔀"
            lines.append(f"  {status_icon} [{f['status']}] {f['path']}")
            if f["ct"]:
                lines.append(f"         {f['ct']}")
        lines.append("")

    if blocked:
        lines.append(f"── BLOCKED (403) — {len(blocked)} paths ──────────────")
        for p in blocked[:40]:
            lines.append(f"  🔴 {p}")
        if len(blocked) > 40:
            lines.append(f"  ... dan {len(blocked)-40} lainnya")
        lines.append("")

    lines.append("⚠️  Gunakan hanya pada sistem yang berwenang.")
    return "\n".join(lines)


# ── API Type Scanner ──────────────────────────────────────────────────────

# GraphQL: endpoints to probe + introspection payload
_GQL_ENDPOINTS = [
    "/graphql",
    "/api/graphql",
    "/graphiql",
    "/v1/graphql",
    "/v2/graphql",
    "/query",
    "/api/query",
    "/gql",
]
_GQL_INTROSPECTION = '{"query":"{__typename}"}'
_GQL_DEEP_INTROSPECTION = (
    '{"query":"query IntrospectionQuery{__schema{queryType{name}'
    ' mutationType{name} subscriptionType{name}}}"}'
)

# SOAP: paths that typically expose WSDL
_WSDL_PROBES = [
    "/?wsdl", "/?WSDL",
    "/service?wsdl", "/Service?wsdl",
    "/ws?wsdl", "/webservice?wsdl",
    "/api?wsdl", "/soap?wsdl",
    "/services?wsdl",
]

# JSON-RPC: common mount points
_JSONRPC_ENDPOINTS = [
    "/jsonrpc", "/json-rpc", "/rpc", "/api/rpc",
    "/api/jsonrpc", "/json_rpc",
]
_JSONRPC_PROBE = b'{"jsonrpc":"2.0","method":"system.listMethods","id":1}'

# OData: metadata endpoint is always `/$metadata`
_ODATA_PROBES = [
    "/$metadata",
    "/odata/$metadata",
    "/api/$metadata",
    "/api/odata/$metadata",
]

# WebSocket upgrade paths
_WS_PROBES = [
    "/ws", "/websocket", "/socket.io", "/socket.io/",
    "/ws/", "/live", "/realtime",
]

# OpenAPI / Swagger discovery paths
_OPENAPI_PROBES = [
    "/swagger.json", "/swagger.yaml",
    "/swagger-ui.html", "/swagger-ui/",
    "/swagger/",
    "/openapi.json", "/openapi.yaml",
    "/api-docs", "/api-docs.json", "/api-docs.yaml",
    "/docs", "/docs/", "/redoc",
    "/.well-known/openapi.json",
    "/v1/swagger.json", "/v2/swagger.json", "/v3/swagger.json",
    "/v1/openapi.json", "/v2/openapi.json",
]

# gRPC health check paths (gRPC-Web / gRPC-Gateway style)
_GRPC_PROBES = [
    "/grpc.health.v1.Health/Check",
    "/grpc/health",
]


async def _discover_api_paths(base: str, client: httpx.AsyncClient, headers_common: dict) -> dict[str, list[str]]:
    """
    Phase 0 — Crawl homepage + JS bundles to discover real API paths.
    Crawls up to MAX_CRAWL_DEPTH=5 levels deep, following same-origin HTML links.

    Returns dict with extra discovered endpoints per category:
      {"graphql": [...], "rest": [...], "websocket": [...], "generic": [...]}
    """
    MAX_CRAWL_DEPTH  = 5
    MAX_PAGES        = 50   # max HTML pages to crawl total
    MAX_JS_PER_PAGE  = 100  # max JS bundles per page

    discovered: dict[str, list[str]] = {"graphql": [], "rest": [], "websocket": [], "generic": []}

    # Regex patterns to mine from JS/HTML
    _re_gql_uri  = re.compile(
        r"""(?:uri|graphqlUrl|graphqlEndpoint|graphql_url|GRAPHQL_URL|gqlUrl)\s*[=:]\s*['"`]([^'"`\s]{3,120})['"`]""",
        re.IGNORECASE,
    )
    _re_gql_kw   = re.compile(r"/graphql|/gql\b|graphiql|apollo[-_]?client", re.IGNORECASE)
    _re_api_url  = re.compile(
        r"""(?:apiUrl|api_url|baseUrl|base_url|apiBase|API_BASE|API_URL|apiEndpoint|endpoint)\s*[=:]\s*['"`]([^'"`\s]{3,120})['"`]""",
        re.IGNORECASE,
    )
    _re_fetch    = re.compile(
        r"""(?:fetch|axios\.(?:get|post|put|patch|delete))\s*\(\s*['"`]([^'"`\s?#]{3,120})['"`]""",
        re.IGNORECASE,
    )
    _re_ws_uri   = re.compile(
        r"""(?:wsUrl|ws_url|socketUrl|socket_url|WS_URL|wss?://[^\s'"`]{3,80})""",
        re.IGNORECASE,
    )
    _re_script   = re.compile(r'<script[^>]+src=["\']([^"\']{3,200})["\']', re.IGNORECASE)
    _re_link_api = re.compile(r'href=["\']([^"\']{2,}?(?:/api/|/graphql|/rest/|/v\d+/)[^"\']*)["\']', re.IGNORECASE)
    _re_link_all = re.compile(r'href=["\']([^"\'#?]{2,200})["\']', re.IGNORECASE)

    def _normalise(url: str) -> str | None:
        """Convert relative → absolute, reject external."""
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith("/"):
            return base + url
        if url.startswith(base):
            return url
        return None

    def _to_path(url: str) -> str | None:
        """Strip base → return just the path."""
        n = _normalise(url)
        if not n:
            return None
        p = urlparse(n).path
        return p if p and p != "/" else None

    async def _get_text(url: str) -> str:
        try:
            r = await client.get(url, headers=headers_common)
            if r.status_code == 200:
                ct = r.headers.get("content-type", "")
                if "html" in ct or "javascript" in ct or "text" in ct or not ct:
                    return r.text[:80_000]
        except Exception:
            pass
        return ""

    # ── BFS crawl: HTML pages up to MAX_CRAWL_DEPTH ───────────────────────
    visited_pages: set[str] = set()
    queue: list[tuple[str, int]] = [(base, 0), (base + "/", 0)]
    all_content = ""   # all HTML + JS text to mine

    while queue and len(visited_pages) < MAX_PAGES:
        page_url, depth = queue.pop(0)
        if page_url in visited_pages:
            continue
        visited_pages.add(page_url)

        html = await _get_text(page_url)
        if not html:
            continue
        all_content += "\n" + html

        # Mine API links from this page
        for m in _re_link_api.finditer(html):
            p = _to_path(m.group(1))
            if p and p not in discovered["generic"]:
                discovered["generic"].append(p)

        # Extract JS bundles from this page and fetch them
        script_urls: list[str] = []
        for src in _re_script.findall(html):
            n = _normalise(src)
            if n and n not in visited_pages:
                script_urls.append(n)
        for js_url in script_urls[:MAX_JS_PER_PAGE]:
            if js_url not in visited_pages:
                visited_pages.add(js_url)
                js = await _get_text(js_url)
                if js:
                    all_content += "\n" + js

        # Follow same-origin HTML links for next depth level
        if depth < MAX_CRAWL_DEPTH:
            for m in _re_link_all.finditer(html):
                href = m.group(1).strip()
                abs_url = _normalise(href)
                if abs_url and abs_url not in visited_pages:
                    # Skip binary/media/style files
                    if not re.search(r'\.(css|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot|pdf|zip|gz|mp4|mp3)$',
                                     abs_url, re.IGNORECASE):
                        queue.append((abs_url, depth + 1))

    all_js = all_content  # alias for mining below

    # GraphQL URI patterns
    for m in _re_gql_uri.finditer(all_js):
        val = m.group(1)
        p = _to_path(val)
        if p and p not in discovered["graphql"]:
            discovered["graphql"].append(p)
        elif val and val not in discovered["graphql"]:
            # Maybe it's a full URL on same origin
            if base in val:
                p2 = urlparse(val).path
                if p2 and p2 not in discovered["graphql"]:
                    discovered["graphql"].append(p2)

    # If JS contains graphql keyword → add common paths not already in static list
    if _re_gql_kw.search(all_js):
        for candidate in ["/graphql", "/api/graphql", "/v1/graphql", "/query", "/gql"]:
            if candidate not in discovered["graphql"] and candidate not in _GQL_ENDPOINTS:
                discovered["graphql"].append(candidate)

    # API base URL patterns → extract the path
    for m in _re_api_url.finditer(all_js):
        val = m.group(1)
        p = _to_path(val) if (val.startswith("/") or val.startswith("http")) else ("/" + val.lstrip("/"))
        if p and len(p) > 1 and p not in discovered["rest"] and p not in _OPENAPI_PROBES:
            # Add swagger/openapi probes relative to that base
            for suffix in ["/swagger.json", "/openapi.json", "/docs"]:
                ep = p.rstrip("/") + suffix
                if ep not in discovered["rest"]:
                    discovered["rest"].append(ep)
            if p not in discovered["generic"]:
                discovered["generic"].append(p)

    # fetch/axios calls
    for m in _re_fetch.finditer(all_js):
        val = m.group(1)
        p = _to_path(val) if (val.startswith("/") or val.startswith("http")) else ("/" + val.lstrip("/"))
        if p and len(p) > 1:
            if any(x in p for x in ["graphql", "gql", "query"]) and p not in discovered["graphql"]:
                discovered["graphql"].append(p)
            elif any(x in p for x in ["/api/", "/v1/", "/v2/", "/rest/"]) and p not in discovered["rest"]:
                discovered["rest"].append(p[:p.rfind("/") + 1] if "/" in p[1:] else p)
            elif p not in discovered["generic"]:
                discovered["generic"].append(p)

    # WebSocket patterns
    for m in _re_ws_uri.finditer(all_js):
        val = m.group(0)
        # wss?://... pattern → extract path
        ws_m = re.search(r"wss?://[^/\s'\"]+(/[^\s'\"]*)", val)
        if ws_m:
            p = ws_m.group(1).rstrip("/") or "/"
            if p and p not in discovered["websocket"]:
                discovered["websocket"].append(p)
        elif "wsUrl" in val or "socketUrl" in val:
            # Try to find the actual value nearby
            pass

    # De-dup and trim
    for k in discovered:
        seen: set[str] = set()
        clean = []
        for v in discovered[k]:
            if v not in seen:
                seen.add(v)
                clean.append(v)
        discovered[k] = clean[:20]

    return discovered


async def api_scan(target: str) -> str:
    """
    Deteksi jenis API yang digunakan oleh sebuah target:
      - GraphQL  (introspection probe, playground check)
      - REST     (swagger/openapi discovery, JSON endpoint check)
      - SOAP     (WSDL endpoint probe)
      - JSON-RPC (method probe)
      - gRPC     (content-type + HTTP/2 header check)
      - OData    ($metadata endpoint probe)
      - WebSocket (Upgrade header, socket.io)

    Phase 0: Crawl homepage + JS bundles untuk discover endpoint nyata.
    Phase 1+: Probe static + discovered endpoints.

    Returns formatted plain-text report.
    """
    if not target.startswith(("http://", "https://")):
        target = "https://" + target
    parsed  = urlparse(target)
    base    = f"{parsed.scheme}://{parsed.netloc}"
    host    = parsed.hostname or ""

    headers_common = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept":     "application/json, text/html, */*",
    }
    timeout = httpx.Timeout(connect=8.0, read=15.0, write=8.0, pool=5.0)

    results: dict[str, list[dict]] = {
        "GraphQL":  [],
        "REST":     [],
        "SOAP":     [],
        "JSON-RPC": [],
        "gRPC":     [],
        "OData":    [],
        "WebSocket":[],
    }

    # ── helpers ────────────────────────────────────────────────────────────

    def _is_json(text: str) -> bool:
        try:
            json.loads(text)
            return True
        except Exception:
            return False

    def _is_graphql_response(body: str) -> bool:
        """True if response looks like a GraphQL response."""
        try:
            d = json.loads(body)
            return "data" in d or "errors" in d
        except Exception:
            return False

    def _is_graphql_errors(body: str) -> bool:
        """True if response has GraphQL-style error array with locations."""
        try:
            d = json.loads(body)
            errs = d.get("errors", [])
            if not errs or not isinstance(errs, list):
                return False
            return any("locations" in e or "path" in e for e in errs)
        except Exception:
            return False

    def _has_gql_playground(body: str) -> bool:
        return bool(re.search(
            r"GraphiQL|graphql-playground|apollo-sandbox|ApolloExplorer"
            r"|graphql-voyager|GraphQL\s+IDE",
            body, re.IGNORECASE
        ))

    def _is_wsdl(body: str, ct: str) -> bool:
        return (
            "wsdl:definitions" in body
            or "<definitions" in body
            or "xmlns:wsdl" in body
            or "application/wsdl" in ct
            or ("text/xml" in ct and ("<wsdl" in body or "<definitions" in body))
        )

    def _is_jsonrpc_response(body: str) -> bool:
        try:
            d = json.loads(body)
            return "jsonrpc" in d or (
                isinstance(d, dict)
                and "error" in d
                and isinstance(d["error"], dict)
                and "code" in d["error"]
            )
        except Exception:
            return False

    def _is_odata(body: str, ct: str) -> bool:
        return (
            "odata.context" in body
            or "@odata.context" in body
            or "odata.metadata" in ct
            or "<edmx:Edmx" in body
            or "http://schemas.microsoft.com/ado/2007/06/edmx" in body
        )

    async with httpx.AsyncClient(
        headers=headers_common,
        timeout=timeout,
        follow_redirects=True,
        verify=False,
    ) as client:

        # ── Phase 0: JS/HTML crawl to discover real API endpoints ──────────
        discovered = await _discover_api_paths(base, client, headers_common)

        # ── Phase 0b: LLM-guided API path generation ─────────────────────
        # Fingerprint from homepage response
        _api_fp: dict = {"tech_stack": [], "server": "", "waf_cdn": []}
        try:
            _fp_resp = await client.get(base, headers=headers_common)
            _api_fp["server"] = _fp_resp.headers.get("server", "")
            _fp_body = _fp_resp.text[:30_000]
            _fp_tech = []
            for _pat, _tname in [
                (r"wp-content|WordPress", "WordPress"),
                (r"__NEXT_DATA__|_next/static", "Next.js"),
                (r"react\.production|__reactFiber", "React"),
                (r"vue\.min\.js|__vue", "Vue.js"),
                (r"laravel_session", "Laravel"),
                (r"ng-version", "Angular"),
                (r"csrfmiddlewaretoken", "Django"),
                (r"x-powered-by", _fp_resp.headers.get("x-powered-by", "")),
            ]:
                if _tname and re.search(_pat, _fp_body, re.IGNORECASE):
                    _fp_tech.append(_tname)
            _api_fp["tech_stack"] = _fp_tech
            for _hdr, (_prod, _) in WAF_SIGNATURES.items():
                if _hdr in {k.lower() for k in _fp_resp.headers}:
                    _api_fp["waf_cdn"].append(_prod)
        except Exception:
            pass

        _llm_api_paths = await _llm_generate_paths(
            _api_fp,
            already_found=list(discovered["graphql"] + discovered["rest"] + discovered["generic"]),
            context="api",
            max_paths=20,
        )
        # Merge LLM-suggested API paths into discovered
        for _p in _llm_api_paths:
            if any(x in _p.lower() for x in ["graphql", "gql", "query"]):
                if _p not in discovered["graphql"]:
                    discovered["graphql"].append(_p)
            else:
                if _p not in discovered["rest"] and _p not in discovered["generic"]:
                    discovered["generic"].append(_p)

        # Merge discovered into probe lists (prepend so they're probed first)
        gql_endpoints   = list(dict.fromkeys(discovered["graphql"] + _GQL_ENDPOINTS))
        openapi_probes  = list(dict.fromkeys(discovered["rest"] + _OPENAPI_PROBES))
        ws_probes       = list(dict.fromkeys(discovered["websocket"] + _WS_PROBES))
        # generic discovered paths — also try GraphQL + REST probes against them
        _generic_bases  = discovered["generic"]

        # ── 1. GraphQL ─────────────────────────────────────────────────────
        for path in gql_endpoints:
            url = base + path
            try:
                # POST introspection
                r = await client.post(
                    url,
                    content=_GQL_INTROSPECTION.encode(),
                    headers={**headers_common, "Content-Type": "application/json"},
                )
                body = r.text[:4000]
                ct   = r.headers.get("content-type", "")

                if r.status_code in (200, 400, 422):
                    if _is_graphql_response(body):
                        # Confirmed — check if introspection is enabled
                        introspection_on = '"__typename"' in body or '"queryType"' in body
                        results["GraphQL"].append({
                            "path":    path,
                            "status":  r.status_code,
                            "note":    "Introspection AKTIF ✓" if introspection_on else "GraphQL endpoint (introspection off)",
                            "confirm": True,
                        })
                        continue
                    if _is_graphql_errors(body):
                        results["GraphQL"].append({
                            "path":   path,
                            "status": r.status_code,
                            "note":   "GraphQL error format terdeteksi",
                            "confirm": True,
                        })
                        continue

                # GET playground check (GraphiQL / Apollo Sandbox)
                r2 = await client.get(url, headers={**headers_common, "Accept": "text/html"})
                if r2.status_code == 200 and _has_gql_playground(r2.text[:8000]):
                    results["GraphQL"].append({
                        "path":    path,
                        "status":  200,
                        "note":    "GraphQL Playground / GraphiQL UI ditemukan",
                        "confirm": True,
                    })

            except Exception:
                pass

        # ── 2. REST (OpenAPI/Swagger) ──────────────────────────────────────
        for path in openapi_probes:
            url = base + path
            try:
                r = await client.get(url)
                if r.status_code not in (200, 206):
                    continue
                body = r.text[:6000]
                ct   = r.headers.get("content-type", "")

                # Swagger JSON/YAML detection
                is_swagger = (
                    '"swagger"' in body
                    or '"openapi"' in body
                    or "openapi:" in body
                    or "swagger:" in body
                    or "Swagger UI" in body
                    or "SwaggerUIBundle" in body
                    or "ReDoc" in body
                    or "redoc" in body.lower()
                )
                if is_swagger:
                    # Try to extract API title
                    title = ""
                    m = re.search(r'"title"\s*:\s*"([^"]{1,60})"', body)
                    if m:
                        title = m.group(1)
                    note = f'Swagger/OpenAPI docs: "{title}"' if title else "Swagger/OpenAPI ditemukan"
                    results["REST"].append({
                        "path":   path,
                        "status": r.status_code,
                        "note":   note,
                    })

            except Exception:
                pass

        # Also check if main path returns JSON with API-like structure
        try:
            api_candidates = ["/api", "/api/v1", "/api/v2", "/v1", "/v2"] + _generic_bases
            seen_rest: set[str] = set()
            for api_path in api_candidates:
                if api_path in seen_rest:
                    continue
                seen_rest.add(api_path)
                r = await client.get(base + api_path)
                if r.status_code == 200 and _is_json(r.text[:2000]):
                    ct = r.headers.get("content-type", "")
                    if "json" in ct:
                        results["REST"].append({
                            "path":   api_path,
                            "status": 200,
                            "note":   f"JSON API endpoint aktif (ct: {ct[:40]})",
                        })
        except Exception:
            pass

        # ── 3. SOAP / WSDL ────────────────────────────────────────────────
        for path in _WSDL_PROBES:
            url = base + path
            try:
                r = await client.get(url)
                if r.status_code not in (200, 206):
                    continue
                ct   = r.headers.get("content-type", "")
                body = r.text[:5000]
                if _is_wsdl(body, ct):
                    # Extract service name if possible
                    svc = ""
                    m = re.search(r'name=["\']([^"\']{1,40})["\']', body)
                    if m:
                        svc = m.group(1)
                    results["SOAP"].append({
                        "path":   path,
                        "status": r.status_code,
                        "note":   f'WSDL ditemukan — service: "{svc}"' if svc else "WSDL ditemukan",
                    })
            except Exception:
                pass

        # ── 4. JSON-RPC ────────────────────────────────────────────────────
        for path in _JSONRPC_ENDPOINTS:
            url = base + path
            try:
                r = await client.post(
                    url,
                    content=_JSONRPC_PROBE,
                    headers={**headers_common, "Content-Type": "application/json"},
                )
                body = r.text[:2000]
                if r.status_code in (200, 400, 404):
                    if _is_jsonrpc_response(body):
                        results["JSON-RPC"].append({
                            "path":   path,
                            "status": r.status_code,
                            "note":   "JSON-RPC response format terdeteksi",
                        })
            except Exception:
                pass

        # ── 5. gRPC ────────────────────────────────────────────────────────
        try:
            # Check if server speaks gRPC via headers
            r = await client.get(base)
            ct = r.headers.get("content-type", "").lower()
            if "application/grpc" in ct:
                results["gRPC"].append({
                    "path":   "/",
                    "status": r.status_code,
                    "note":   "Content-Type: application/grpc terdeteksi",
                })
            # gRPC-Web trailers
            if r.headers.get("grpc-status") or r.headers.get("grpc-message"):
                results["gRPC"].append({
                    "path":   "/",
                    "status": r.status_code,
                    "note":   "gRPC trailer headers (grpc-status / grpc-message) terdeteksi",
                })
        except Exception:
            pass

        # Probe gRPC health endpoints
        for path in _GRPC_PROBES:
            url = base + path
            try:
                r = await client.post(
                    url,
                    content=b"\x00\x00\x00\x00\x00",  # empty gRPC frame
                    headers={**headers_common, "Content-Type": "application/grpc"},
                )
                ct = r.headers.get("content-type", "")
                if "grpc" in ct.lower() or r.headers.get("grpc-status"):
                    results["gRPC"].append({
                        "path":   path,
                        "status": r.status_code,
                        "note":   "gRPC endpoint merespons",
                    })
            except Exception:
                pass

        # ── 6. OData ──────────────────────────────────────────────────────
        for path in _ODATA_PROBES:
            url = base + path
            try:
                r = await client.get(url)
                if r.status_code not in (200, 206):
                    continue
                ct   = r.headers.get("content-type", "")
                body = r.text[:5000]
                if _is_odata(body, ct):
                    # Try to grab EntityContainer name
                    svc = ""
                    m = re.search(r'EntityContainer[^N]*Name=["\']([^"\']{1,40})["\']', body)
                    if m:
                        svc = m.group(1)
                    results["OData"].append({
                        "path":   path,
                        "status": r.status_code,
                        "note":   f"OData $metadata endpoint: {svc}" if svc else "OData $metadata ditemukan",
                    })
            except Exception:
                pass

        # ── 7. WebSocket ──────────────────────────────────────────────────
        for path in ws_probes:
            url = base + path
            try:
                # Send a WebSocket upgrade request manually via HTTP/1.1
                import secrets
                ws_key = secrets.token_bytes(16)
                import base64 as _b64
                ws_key_b64 = _b64.b64encode(ws_key).decode()
                r = await client.get(
                    url,
                    headers={
                        **headers_common,
                        "Upgrade":               "websocket",
                        "Connection":            "Upgrade",
                        "Sec-WebSocket-Key":     ws_key_b64,
                        "Sec-WebSocket-Version": "13",
                    },
                )
                # 101 = Switching Protocols = WebSocket confirmed
                if r.status_code == 101:
                    results["WebSocket"].append({
                        "path":   path,
                        "status": 101,
                        "note":   "WebSocket handshake berhasil (101 Switching Protocols)",
                    })
                elif r.status_code in (200, 400):
                    # socket.io sends 200 with JSON on bare GET
                    body = r.text[:800]
                    if "socket.io" in body.lower() or "websocket" in r.headers.get("upgrade", "").lower():
                        results["WebSocket"].append({
                            "path":   path,
                            "status": r.status_code,
                            "note":   "Socket.IO / WebSocket endpoint terdeteksi",
                        })
            except Exception:
                pass

    # ── Format report ─────────────────────────────────────────────────────
    detected = [k for k, v in results.items() if v]
    total    = sum(len(v) for v in results.values())
    n_discovered = sum(len(v) for v in discovered.values())
    n_static     = (len(_GQL_ENDPOINTS) + len(_OPENAPI_PROBES) + len(_WSDL_PROBES)
                    + len(_JSONRPC_ENDPOINTS) + len(_GRPC_PROBES) + len(_ODATA_PROBES) + len(_WS_PROBES))
    n_probed     = len(gql_endpoints) + len(openapi_probes) + len(_WSDL_PROBES) + len(_JSONRPC_ENDPOINTS) + len(_GRPC_PROBES) + len(_ODATA_PROBES) + len(ws_probes)

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "🔌 API TYPE SCAN REPORT",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Target    : {base}",
        f"Waktu     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Discovery : {n_discovered} endpoint ditemukan dari HTML/JS crawl",
        f"Probe     : {n_probed} total ({n_static} static + {max(0, n_probed - n_static)} discovered)",
        "",
    ]

    if not detected:
        lines.append("Tidak ada API type yang terdeteksi.")
        lines.append("Kemungkinan: bukan API server, semua endpoint diblokir, atau pakai auth.")
    else:
        lines.append(f"✅ Terdeteksi {len(detected)} jenis API: {', '.join(detected)}")
        lines.append("")

        # Emoji per type
        _icons = {
            "GraphQL":   "🔮",
            "REST":      "📡",
            "SOAP":      "🧼",
            "JSON-RPC":  "🔧",
            "gRPC":      "⚡",
            "OData":     "📊",
            "WebSocket": "🔄",
        }
        # Risk notes per type
        _risk = {
            "GraphQL":  "Cek: introspection aktif? Bisa dump semua schema!",
            "REST":     "Cek: auth, rate limiting, IDOR, BOLA, exposed debug endpoints",
            "SOAP":     "Cek: XXE injection, WSDL mencantumkan semua operasi",
            "JSON-RPC": "Cek: method enumeration, unauthorized calls",
            "gRPC":     "Cek: reflection service enabled? Bisa dump semua service",
            "OData":    "Cek: $filter injection, excessive data exposure, $expand abuse",
            "WebSocket":"Cek: auth saat handshake, injection via WS message",
        }

        for api_type, findings in results.items():
            if not findings:
                continue
            icon = _icons.get(api_type, "•")
            lines.append(f"{icon} {api_type}")
            for f in findings:
                lines.append(f"  [{f['status']}] {f['path']}")
                lines.append(f"       {f['note']}")
            risk = _risk.get(api_type, "")
            if risk:
                lines.append(f"  ⚠️  {risk}")
            lines.append("")

    lines.append("⚠️  Gunakan hanya pada sistem yang berwenang.")
    return "\n".join(lines)


# ── AI-Guided Iterative Scanner ───────────────────────────────────────────

async def aiscan_target(target: str, rounds: int = 2) -> str:
    """
    Full scan (scan_target) + AI-guided iterative path probing.

    Phase 1: Full scan — ports, SSL, headers, DNS, subdomains, sensitive paths
    Phase 2: LLM generates targeted probe paths from full scan fingerprint
    Phase 3: Round 2 — feed hits back to LLM for deeper probing
    """
    url    = _normalize_url(target)
    parsed = urlparse(url)
    base   = f"{parsed.scheme}://{parsed.netloc}"
    _hdr   = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # ── Phase 1: Full scan (same as /scan) ───────────────────────────────
    full_result = await scan_target(target)
    base_report = format_report(full_result)

    # Build tech_info from full scan result for LLM context
    _info = full_result.get("info", {})
    tech_info = {
        "tech_stack": _info.get("tech_stack", []),
        "server":     _info.get("server", ""),
        "waf_cdn":    _info.get("waf_cdn", []),
        "found_paths": _info.get("found_paths", []),
    }
    # Add subdomain count and open ports to server string for richer LLM context
    _ports = _info.get("open_ports", [])
    if _ports:
        tech_info["server"] = (tech_info["server"] or "") + f" ports:{','.join(_ports[:6])}"
    _subs = _info.get("subdomains", [])
    if _subs:
        tech_info["tech_stack"] = list(tech_info["tech_stack"]) + [f"subdomains:{len(_subs)}"]

    all_hits:   list[dict] = []
    round_logs: list[str]  = []
    total_probed = 0

    # ── Phase 2 & 3: AI-guided probing rounds ────────────────────────────
    for _round in range(1, rounds + 1):
        _already = _info.get("found_paths", []) + [h["path"] for h in all_hits]

        _llm_paths = await _llm_generate_paths(
            tech_info,
            already_found=_already,
            context="path",
            max_paths=30 if _round == 1 else 20,
        )
        if not _llm_paths:
            round_logs.append(f"Round {_round}: LLM tidak menghasilkan path.")
            break

        total_probed += len(_llm_paths)
        _sem = asyncio.Semaphore(20)

        async def _probe_one(p: str) -> dict | None:
            async with _sem:
                try:
                    async with httpx.AsyncClient(
                        follow_redirects=False, timeout=7, verify=False, headers=_hdr
                    ) as _pc:
                        _pr = await _pc.head(f"{base}{p}")
                    if _pr.status_code in (200, 403):
                        return {
                            "path":     p,
                            "status":   _pr.status_code,
                            "severity": _guess_severity(p, _pr.status_code),
                            "ct":       _pr.headers.get("content-type", "")[:40],
                        }
                except Exception:
                    pass
                return None

        _prs = await asyncio.gather(*[_probe_one(p) for p in _llm_paths])
        _round_hits = [r for r in _prs if r]
        all_hits.extend(_round_hits)
        tech_info["found_paths"] = _already + [h["path"] for h in all_hits]

        _probed_str = "  " + "\n  ".join(_llm_paths)
        if _round_hits:
            _hits_str = "\n".join(
                f"  [{h['status']}] {h['path']}  ({h['severity']})" for h in _round_hits[:15]
            )
            round_logs.append(
                f"Round {_round}: {len(_llm_paths)} paths probed:\n{_probed_str}\n\n→ {len(_round_hits)} hit:\n{_hits_str}"
            )
        else:
            round_logs.append(f"Round {_round}: {len(_llm_paths)} paths probed:\n{_probed_str}\n\n→ 0 hit")

    # ── Format combined report ─────────────────────────────────────────────
    ai_lines = [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🤖 AI-GUIDED PROBE (PHASE 2)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"AI Probe : {total_probed} paths ({rounds} round)",
        f"Total Hit: {len(all_hits)} paths",
        "",
    ]
    for rlog in round_logs:
        ai_lines.append(rlog)
        ai_lines.append("")

    if all_hits:
        ai_lines.append("📌 AI-Discovered Findings:")
        for _sev, _emoji in [("CRITICAL","🔴"), ("HIGH","🟠"), ("MEDIUM","🟡"), ("LOW","🔵")]:
            _grp = [h for h in all_hits if h["severity"] == _sev]
            if _grp:
                ai_lines.append(f"{_emoji} {_sev}:")
                for h in _grp:
                    ai_lines.append(f"  [{h['status']}] {h['path']}")
        ai_lines.append("")
    else:
        ai_lines.append("✅ Tidak ada path tambahan ditemukan via AI probe.")
        ai_lines.append("")

    return base_report + "\n" + "\n".join(ai_lines)


# ── Helpers for Exa functions ─────────────────────────────────────────────────

# Official / vendor / documentation sites — never targets, always excluded
_CMS_VENDOR_DOMAINS: set[str] = {
    # WordPress / WooCommerce
    "wordpress.org", "wordpress.com", "woocommerce.com",
    "wp.org", "wpengine.com", "wordpress.tv", "wp-cli.org",
    # Joomla
    "joomla.org", "joomlacode.org", "joomla.com", "deepwiki.com",
    # Drupal
    "drupal.org", "drupal.com",
    # Magento / Adobe Commerce
    "magento.com", "adobe.com", "mage-os.org",
    # PrestaShop
    "prestashop.com", "prestashop.org",
    # OpenCart
    "opencart.com",
    # Shopify
    "shopify.com", "shopify.dev", "shopify.io",
    # Wix
    "wix.com", "wixsite.com",
    # Squarespace
    "squarespace.com",
    # Generic dev/doc noise
    "github.com", "github.io",
    "stackoverflow.com", "stackexchange.com",
    "w3schools.com", "tutorialspoint.com", "geeksforgeeks.org",
    "medium.com", "dev.to", "hackernoon.com", "hashnode.dev",
    "reddit.com", "youtube.com", "wikipedia.org",
    "docs.com", "gitbook.io",
    # Major news & media outlets
    "cnn.com", "bbc.com", "bbc.co.uk", "theguardian.com",
    "nytimes.com", "washingtonpost.com", "reuters.com", "apnews.com",
    "forbes.com", "businessinsider.com", "techcrunch.com",
    "theverge.com", "wired.com", "arstechnica.com", "engadget.com",
    "zdnet.com", "cnet.com", "pcmag.com", "tomsguide.com",
    "bleepingcomputer.com", "theregister.com", "securityweek.com",
    "darkreading.com", "krebsonsecurity.com", "redpacketsecurity.com",
    "mashable.com", "gizmodo.com", "lifehacker.com",
    "huffpost.com", "buzzfeed.com", "vice.com",
    "nbcnews.com", "cbsnews.com", "abcnews.go.com", "foxnews.com",
    "msn.com", "news.yahoo.com", "news.google.com",
    # Blog / publishing platforms
    "blogger.com", "blogspot.com", "tumblr.com",
    "substack.com", "ghost.io", "typepad.com",
    "livejournal.com", "weebly.com", "webnode.com",
    "blogarama.com", "archynewsy.com",
    # Security / infosec sites
    "joomlaxtc.com", "cyberscoop.com", "rescana.com", "securityaffairs.com",
    "threatpost.com", "hackread.com", "infosecurity-magazine.com",
    "securitymagazine.com", "cybersecuritynews.com",
    # Theme / plugin / template marketplaces
    "themeforest.net", "codecanyon.net", "envato.com", "envato.market",
    "templatemonster.com", "elegantthemes.com", "themeisle.com",
    "mythemeshop.com", "themify.me", "joomshaper.com", "yootheme.com",
    "rockettheme.com", "joomlashack.com", "shape5.com", "gavick.com",
    "prothemedesign.com", "mojo-themes.com", "visualcomposer.com",
    "avada.io", "wpbakery.com", "elementor.com", "divi.net",
    "wplook.com", "wpzoom.com", "wpmudev.org", "wpbeginner.com",
    "yoast.com", "woothemes.com", "storefront.com",
    "magentocommerce.com", "magesolution.com", "magenest.com",
    "addons.prestashop.com", "prestashop.org",
    "extensions.joomla.org", "joomlaextensions.com",
    # Joomla extension official sites
    "hikashop.com", "hikamarket.com", "virtuemart.net", "virtuemart.org",
    "j2store.org", "mijoshop.com", "eshop.com", "redshop.dk",
    # Magento extension sites
    "mgt-commerce.com",
    # ── Major e-commerce marketplaces & retail giants ──────────────────────
    # North America
    "amazon.com", "amazon.ca", "amazon.co.uk", "amazon.de", "amazon.fr",
    "amazon.co.jp", "amazon.com.au", "amazon.com.br", "amazon.com.mx",
    "amazon.in", "amazon.it", "amazon.es", "amazon.nl", "amazon.se",
    "amazon.sg", "amazon.ae", "amazon.sa", "amazon.pl", "amazon.tr",
    "ebay.com", "ebay.co.uk", "ebay.de", "ebay.fr", "ebay.it",
    "ebay.es", "ebay.com.au", "ebay.ca", "ebay.at", "ebay.nl",
    "walmart.com", "walmart.ca", "walmart.com.mx",
    "target.com",
    "bestbuy.com", "bestbuy.ca",
    "costco.com", "costco.ca", "costco.co.uk",
    "homedepot.com", "homedepot.ca",
    "lowes.com",
    "kroger.com",
    "macys.com", "bloomingdales.com", "nordstrom.com", "nordstromrack.com",
    "gap.com", "oldnavy.com", "bananarepublic.com",
    "kohls.com", "jcpenney.com", "sears.com",
    "wayfair.com", "overstock.com", "chewy.com",
    "newegg.com",
    "etsy.com",
    # Latin America
    "mercadolibre.com", "mercadolibre.com.ar", "mercadolibre.com.br",
    "mercadolibre.com.mx", "mercadolibre.com.co", "mercadolibre.com.cl",
    "mercadolibre.com.pe", "mercadolibre.com.ve",
    "mercadopago.com",
    "americanas.com.br", "submarino.com.br", "shoptime.com.br",
    "magazineluiza.com.br", "magalu.com.br",
    "casasbahia.com.br", "pontofrio.com.br", "extra.com.br",
    "shopee.com.br",
    # Europe
    "otto.de", "zalando.com", "zalando.de", "zalando.fr",
    "cdiscount.com", "fnac.com",
    "asos.com", "boohoo.com",
    "allegro.pl",
    "bol.com",
    "coolblue.nl",
    "mediamarkt.de", "mediamarkt.nl",
    # Asia / Global
    "alibaba.com", "aliexpress.com", "aliexpress.ru", "surecart.com","https://peachpay.app",
    "taobao.com", "tmall.com", "jd.com", "pinduoduo.com",
    "shopee.com", "shopee.sg", "shopee.ph", "shopee.co.th",
    "lazada.com", "lazada.sg", "lazada.co.th", "lazada.com.my",
    "flipkart.com", "snapdeal.com", "myntra.com",
    "rakuten.com", "rakuten.co.jp",
    "coupang.com",
    # Australia / NZ
    "kogan.com", "catch.com.au", "bigw.com.au", "myer.com.au",
    # Global fashion
    "zara.com", "hm.com", "uniqlo.com", "shein.com", "temu.com",
    # Payments / checkout (not shops but flood results)
    "paypal.com", "stripe.com", "square.com", "klarna.com",
    "afterpay.com", "affirm.com",
}

# Regex to catch generic news/blog/media domains by keyword in the apex label.
# Matches if the label STARTS WITH or ENDS WITH a news/blog keyword:
#   "newsroom.com"  → starts with "news"     → filtered
#   "technews.com"  → ends with "news"        → filtered
#   "myblog.net"    → ends with "blog"        → filtered
#   "dailypress.org"→ starts with "daily"     → filtered
#   "realshop.com"  → no keyword match        → allowed
_NEWS_BLOG_APEX_RE = re.compile(
    r"^(?:news|blog|blogs|press|media|magazine|mag|journal|"
    r"daily|weekly|herald|tribune|gazette|post|times|chronicle|"
    r"report|reporter|dispatch|bulletin|digest|review|observer|"
    r"insider|feed|feeds|rss|wire|newswire|"
    r"security|cyber|hacking|infosec|malware|vuln|exploit|"
    r"theme|themes|template|templates|plugin|plugins|addon|addons|"
    r"extension|extensions|themeforest|marketplace|download|"
    r"wordpress|woocommerce|joomla|drupal|magento|prestashop|opencart|"
    r"virtuemart|hikashop|j2store|opencart|shopify|squarespace)"
    r"|(?:news|newsy|blog|press|media|journal|daily|weekly|times|wire|"
    r"post|feed|feeds|gazette|tribune|herald|magazine|review|digest|"
    r"security|cyber|hacking|infosec|themes|plugins|addons|extensions|"
    r"theme|plugin|addon|extension)$",
    re.IGNORECASE,
)

_PRIVATE_IP_RE = re.compile(
    r"^(?:127\.|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.|::1|localhost)",
    re.IGNORECASE,
)

def _is_safe_url(url: str) -> bool:
    """Return True if url is a public HTTP/HTTPS URL (not private IP, not localhost)."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False
        host = p.hostname or ""
        if not host:
            return False
        if _PRIVATE_IP_RE.match(host):
            return False
        # Block raw IPv4 private ranges via ipaddress
        try:
            addr = ipaddress.ip_address(host)
            if addr.is_private or addr.is_loopback or addr.is_reserved:
                return False
        except ValueError:
            pass  # hostname, not an IP — fine
        return True
    except Exception:
        return False


# WAF fingerprints: header-name → (substring-to-match, display-name)
_WAF_SIGNATURES: list[tuple[str, str, str]] = [
    # (header_name, value_substring_lower, display_name)
    ("cf-ray",              "",               "Cloudflare"),
    ("cf-cache-status",     "",               "Cloudflare"),
    ("server",              "cloudflare",     "Cloudflare"),
    ("x-amz-cf-id",        "",               "AWS CloudFront"),
    ("x-amz-cf-pop",       "",               "AWS CloudFront"),
    ("x-azure-ref",        "",               "Azure Front Door"),
    ("x-akamai-request-id","",               "Akamai"),
    ("akamai-grn",         "",               "Akamai"),
    ("x-sucuri-id",        "",               "Sucuri WAF"),
    ("x-sucuri-cache",     "",               "Sucuri WAF"),
    ("x-cdn",              "incapsula",      "Imperva Incapsula"),
    ("x-iinfo",            "",               "Imperva Incapsula"),
    ("x-wa-info",          "",               "F5 BIG-IP"),
    ("x-fw-hash",          "",               "Fortinet FortiWeb"),
    ("x-protected-by",     "",               "WAF"),
]


async def _is_behind_waf(url: str, timeout: float = 6.0) -> tuple[bool, str]:
    """
    Quick WAF detection: HEAD request + header fingerprinting.
    Returns (is_waf: bool, waf_name: str).
    """
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"},
        ) as client:
            resp = await client.head(url)
            hdrs = {k.lower(): v.lower() for k, v in resp.headers.items()}

        for hdr, val_sub, name in _WAF_SIGNATURES:
            if hdr in hdrs:
                if not val_sub or val_sub in hdrs[hdr]:
                    return True, name

        return False, ""
    except Exception:
        return False, ""


# ── Exa CMS Site Discovery ────────────────────────────────────────────────────

async def exa_find_cms_sites(
    cms_name: str,
    max_results: int = 10,
    save_dir: str | None = None,
    topic: str = "",
    country: str = "",
) -> tuple[list[str], str]:
    """
    Use Exa to discover live websites running a specific CMS.

    Args:
        cms_name:    CMS name (case-insensitive). Must be in CMS_SIGNATURES.
        max_results: How many unique domains to collect.
        save_dir:    Directory to auto-save the domain list. Defaults to
                     <OUTPUT_DIR>/scans/cms_targets/.
        topic:       Optional product/niche keyword, e.g. "shoes" or "electronics".
        country:     Optional target country name/code, e.g. "Indonesia" or "Brazil".

    Returns:
        (domains, saved_path)
        domains    — list of base URLs, e.g. ["https://example.com", ...]
        saved_path — absolute path of the .txt file written to disk
    """
    # Normalise CMS name
    cms_key = next((k for k in CMS_SIGNATURES if k.lower() == cms_name.lower()), None)
    if not cms_key:
        raise ValueError(
            f"CMS tidak dikenal: '{cms_name}'. "
            f"Pilihan: {', '.join(CMS_SIGNATURES)}"
        )

    if not _cfg.EXA_API_KEY:
        raise RuntimeError("EXA_API_KEY tidak di-set di .env — tidak bisa gunakan Exa search.")

    sig = CMS_EXA_QUERIES.get(cms_key, {})
    query       = sig.get("query", f"{cms_key} CMS website")
    search_type = sig.get("type", "neural")

    # Append topic keyword if provided (e.g. "shoes", "electronics")
    if topic:
        query = f"{query} selling {topic.strip()}"

    # Append country targeting if provided
    if country:
        query = f"{query} from {country.strip()} {country.strip()} website"

    from exa_py import Exa  # type: ignore
    exa = Exa(api_key=_cfg.EXA_API_KEY)

    # exa.search() is synchronous — run in executor so it doesn't block the event loop
    _num = min(max_results * 3, 100)
    _loop = asyncio.get_event_loop()
    response = await _loop.run_in_executor(
        None,
        lambda: exa.search(
            query,
            type=search_type,
            num_results=_num,
            category="company",
            exclude_domains=list(_CMS_VENDOR_DOMAINS),
        ),
    )

    seen_apex: set[str] = set()   # dedup by apex domain (e.g. "example.com")
    domains:   list[str] = []

    for r in response.results:
        raw_url = r.url or ""
        try:
            parsed  = urlparse(raw_url)
            netloc  = parsed.netloc.lower()
            if not netloc:
                continue

            # Apex domain = last 2 parts (covers most TLDs sufficiently)
            parts = netloc.split(".")
            apex  = ".".join(parts[-2:]) if len(parts) >= 2 else netloc

            # Post-filter: skip vendor/official domains even if Exa missed them
            if any(apex == vd or apex.endswith("." + vd)
                   for vd in _CMS_VENDOR_DOMAINS):
                continue

            # Skip generic news / blog domains by keyword in apex label
            apex_label = apex.split(".")[0]   # e.g. "technews" from "technews.com"
            if _NEWS_BLOG_APEX_RE.search(apex_label):
                continue

            # Skip URLs whose subdomain itself is a news/blog keyword
            # e.g. blog.example.com, news.store.com, journal.shop.net
            _SUBDOMAIN_IGNORE = frozenset({
                "blog", "blogs", "news", "journal", "journals", "press",
                "media", "forum", "forums", "feed", "feeds", "rss",
                "magazine", "mag", "digest", "review", "reviews",
                "article", "articles", "post", "posts", "editorial",
                "community", "discuss", "discussion", "support",
                "docs", "documentation", "help", "wiki",
                "security", "cyber", "infosec",
            })
            sub_labels = parts[:-2]  # labels before the apex domain
            if any(sl in _SUBDOMAIN_IGNORE for sl in sub_labels):
                continue

            base_url = f"{parsed.scheme}://{netloc}"
            if apex and apex not in seen_apex and _is_safe_url(base_url):
                seen_apex.add(apex)
                domains.append(base_url)
        except Exception:
            continue
        if len(domains) >= max_results:
            break

    # Auto-save domain list
    if save_dir is None:
        save_dir = os.path.join(str(_cfg.OUTPUT_DIR), "scans", "cms_targets")
    os.makedirs(save_dir, exist_ok=True)

    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    _cc_slug = f"_{country.lower().replace(' ', '_')}" if country else ""
    filename = os.path.join(save_dir, f"exa_{cms_key.lower()}{_cc_slug}_{ts}.txt")

    with open(filename, "w", encoding="utf-8") as f:
        _meta_country = f" | Country: {country}" if country else ""
        f.write(
            f"# Exa CMS Search | CMS: {cms_key} | "
            f"{datetime.now():%Y-%m-%d %H:%M:%S}{_meta_country} | {len(domains)} domain(s)\n"
        )
        for d in domains:
            f.write(d + "\n")

    logger.info(f"exa_find_cms_sites: {len(domains)} domains saved → {filename}")
    return domains, filename


# ── Auto CMS Scan (Exa → find → scan all) ────────────────────────────────────

async def auto_scan_cms(
    cms_name: str,
    max_sites: int = 5,
    save_dir: str | None = None,
    progress_cb=None,
    topic: str = "",
    country: str = "",
) -> dict:
    """
    Full auto-pipeline: Exa search → domain list → scan each → save results.

    Args:
        cms_name:    Target CMS (case-insensitive)
        max_sites:   Max sites to find and scan (capped at 20)
        save_dir:    Output directory (default: <OUTPUT_DIR>/scans/cms_autoscan)
        progress_cb: Optional async callable(msg: str) for real-time progress
        topic:       Optional product/niche keyword (e.g. "shoes")
        country:     Optional target country (e.g. "Indonesia", "Brazil")

    Returns dict with keys:
        cms, domains_file, domains, scan_results, summary_file, error (optional)
    """
    max_sites = min(max_sites, 20)

    if save_dir is None:
        save_dir = os.path.join(str(_cfg.OUTPUT_DIR), "scans", "cms_autoscan")
    os.makedirs(save_dir, exist_ok=True)

    async def _prog(msg: str) -> None:
        logger.info(msg)
        if progress_cb:
            try:
                await progress_cb(msg)
            except Exception:
                pass

    # ── Step 1: Find CMS sites via Exa ──────────────────────────────────
    _topic_label   = f" [{topic}]" if topic else ""
    _country_label = f" @{country}" if country else ""
    await _prog(f"🔍 Mencari {cms_name}{_topic_label}{_country_label} sites via Exa ({max_sites} target)…")
    try:
        domains, domains_file = await exa_find_cms_sites(
            cms_name, max_sites, save_dir, topic=topic, country=country
        )
    except Exception as e:
        return {
            "cms": cms_name, "domains_file": "", "domains": [],
            "scan_results": [], "summary_file": "", "error": str(e),
        }

    if not domains:
        return {
            "cms": cms_name, "domains_file": domains_file, "domains": [],
            "scan_results": [], "summary_file": "",
            "error": "Tidak ada domain ditemukan oleh Exa untuk CMS ini.",
        }

    await _prog(f"✅ {len(domains)} domain ditemukan. Mulai scanning…")

    # ── Step 2: Scan each domain ─────────────────────────────────────────
    cms_key      = next((k for k in CMS_SIGNATURES if k.lower() == cms_name.lower()), cms_name)
    ts           = datetime.now().strftime("%Y%m%d_%H%M%S")
    scan_results: list[dict] = []

    for i, domain_url in enumerate(domains, 1):
        await _prog(f"[{i}/{len(domains)}] Scanning: {domain_url}")
        try:
            # Detect WAF before scanning — note it but still scan
            waf_hit, waf_name = await _is_behind_waf(domain_url)
            if waf_hit:
                await _prog(f"  ⚠ Dilindungi {waf_name} — tetap scan…")

            result = await scan_target(domain_url)
            if waf_hit:
                result["waf"] = waf_name
            result["_source_domain"] = domain_url

            # Save individual scan as JSON
            safe_name  = re.sub(r"[^\w.-]", "_", domain_url.replace("://", "_"))
            scan_file  = os.path.join(save_dir, f"scan_{safe_name}_{ts}.json")
            with open(scan_file, "w", encoding="utf-8") as fout:
                json.dump(result, fout, ensure_ascii=False, indent=2, default=str)
            result["_json_path"] = scan_file

            risk   = result.get("risk_level", "?")
            counts = result.get("counts", {})
            await _prog(
                f"  → {risk} "
                f"C:{counts.get('CRITICAL',0)} "
                f"H:{counts.get('HIGH',0)} "
                f"M:{counts.get('MEDIUM',0)} "
                f"L:{counts.get('LOW',0)}"
            )
            scan_results.append(result)

        except Exception as e:
            logger.warning(f"Scan failed for {domain_url}: {e}")
            await _prog(f"  → GAGAL: {e}")
            scan_results.append({
                "_source_domain": domain_url,
                "error": str(e),
                "info": {"target": domain_url},
                "findings": [], "counts": {}, "risk_level": "?",
            })

    # ── Step 3: Save combined summary ────────────────────────────────────
    summary_file = os.path.join(save_dir, f"summary_{cms_key.lower()}_{ts}.txt")
    with open(summary_file, "w", encoding="utf-8") as f:
        f.write(f"CMS Auto-Scan Summary\n")
        f.write(f"CMS    : {cms_key}\n")
        f.write(f"Date   : {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        f.write(f"Found  : {len(domains)} sites\n")
        f.write(f"Scanned: {len(scan_results)} sites\n")
        f.write("=" * 60 + "\n\n")
        for r in scan_results:
            info   = r.get("info", {})
            counts = r.get("counts", {})
            risk   = r.get("risk_level", "?")
            src    = r.get("_source_domain", info.get("target", "?"))
            if r.get("error") and not r.get("findings"):
                f.write(f"[ERROR] {src}: {r['error']}\n\n")
            else:
                f.write(f"{src}\n")
                f.write(f"  Risk   : {risk}\n")
                f.write(
                    f"  Counts : CRITICAL={counts.get('CRITICAL',0)}  "
                    f"HIGH={counts.get('HIGH',0)}  "
                    f"MEDIUM={counts.get('MEDIUM',0)}  "
                    f"LOW={counts.get('LOW',0)}\n"
                )
                if r.get("waf"):
                    f.write(f"  WAF    : {r['waf']}\n")
                f.write(f"  CMS    : {', '.join(info.get('detected_cms', []))}\n")
                f.write(f"  IP     : {info.get('ip','?')}\n")
                f.write(f"  Server : {info.get('server','?')}\n")
                fp = info.get("found_paths", [])
                if fp:
                    f.write(f"  Paths  : {', '.join(fp)}\n")
                f.write("\n")

    await _prog(f"✅ Selesai! Summary → {summary_file}")

    return {
        "cms":          cms_key,
        "domains_file": domains_file,
        "domains":      domains,
        "scan_results": scan_results,
        "summary_file": summary_file,
    }
