"""
Network check module - passive and minimal active checks.
Only performs DNS lookups, WHOIS, and optional single-port check.
"""

import socket
import whois
import dns.resolver
from typing import Dict, List, Optional
from loguru import logger
import re
import requests

from modules.search_engines import SearchResult, _request_with_retry

def extract_domains_and_ips(text: str) -> Dict[str, List[str]]:
    """Extract domain names and IP addresses from text."""
    # IP pattern
    ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
    ips = list(set(re.findall(ip_pattern, text)))
    # Domain pattern (simple)
    domain_pattern = r'\b([a-zA-Z0-9][-a-zA-Z0-9]*\.)+[a-zA-Z]{2,}\b'
    domains = list(set(re.findall(domain_pattern, text)))
    return {"ips": ips, "domains": domains}

def dns_lookup(domain: str) -> Dict:
    """Perform DNS A record lookup."""
    try:
        answers = dns.resolver.resolve(domain, 'A')
        return {"domain": domain, "a_records": [str(r) for r in answers]}
    except Exception as e:
        return {"domain": domain, "error": str(e)}

def whois_lookup(domain: str) -> Dict:
    """Perform WHOIS lookup (public)."""
    try:
        w = whois.whois(domain)
        # Convert whois result to dict safely
        w_dict = {}
        if w:
            for k, v in w.items():
                w_dict[k] = str(v)
        return w_dict
    except Exception as e:
        return {"error": str(e)}

def check_port(host: str, port: int, timeout: float = 3) -> bool:
    """Check if a port is open (active, use with caution)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except:
        return False

def check_shodan_internetdb(ip: str) -> Dict:
    """Check Shodan InternetDB (Free, Passive API) for an IP address."""
    try:
        url = f"https://internetdb.shodan.io/{ip}"
        resp = _request_with_retry("GET", url)
        if resp and resp.status_code == 200:
            data = resp.json()
            return {
                "ip": ip,
                "ports": data.get("ports", []),
                "hostnames": data.get("hostnames", []),
                "cpes": data.get("cpes", []),
                "vulns": data.get("vulns", [])
            }
        return {"ip": ip, "error": f"HTTP {resp.status_code}" if resp else "timeout"}
    except Exception as e:
        return {"ip": ip, "error": str(e)}

def network_enrichment(results: List[SearchResult], active_ports: bool = False) -> Dict:
    """
    Main function to enrich results with network info.
    active_ports: if True, checks port 80/443 (requires permission).
    """
    # Collect all text from results
    all_text = ""
    for r in results:
        all_text += str(r.title) + ' ' + str(r.snippet) + ' ' + str(r.link) + ' '
        
    extracted = extract_domains_and_ips(all_text)
    enriched = {"extracted": extracted}
    
    logger.info("[NetworkCheck] Found {} unique IPs and {} unique Domains", 
                len(extracted['ips']), len(extracted['domains']))
    
    # DNS and WHOIS for domains
    domain_info = []
    # Limit number of lookups to prevent it from taking forever
    for domain in list(extracted['domains'])[:10]:
        logger.info("[NetworkCheck] Resolving domain: {}", domain)
        info = dns_lookup(domain)
        info['whois'] = whois_lookup(domain)
        if active_ports:
            info['port_80'] = check_port(domain, 80)
            info['port_443'] = check_port(domain, 443)
        domain_info.append(info)
        
    enriched['domains'] = domain_info
    
    # Basic IP info (reverse DNS + Shodan InternetDB)
    ip_info = []
    for ip in list(extracted['ips'])[:10]:
        logger.info("[NetworkCheck] Reverse lookup and IP check for: {}", ip)
        ip_details = {"ip": ip}
        
        # Reverse DNS
        try:
            hostname = socket.gethostbyaddr(ip)[0]
        except:
            hostname = None
        ip_details["hostname"] = hostname
        
        # Passive Shodan InternetDB
        internetdb_data = check_shodan_internetdb(ip)
        if "error" not in internetdb_data:
            ip_details["internetdb"] = internetdb_data
        else:
            ip_details["internetdb"] = {"error": internetdb_data["error"]}
            
        ip_info.append(ip_details)
        
    enriched['ips'] = ip_info
    
    return enriched
