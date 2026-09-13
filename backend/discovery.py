"""
OmniSight-NVR - Camera Discovery Engine
Performs ONVIF WS-Discovery probes and LAN port scanning to locate
Hikvision, Dahua, Xiongmai, and generic ONVIF/RTSP surveillance devices.
"""

import socket
import struct
import uuid
import re
import time
import threading
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor
try:
    from .vendor_presets import detect_vendor_by_ports, VENDOR_PRESETS
except (ImportError, ValueError):
    from vendor_presets import detect_vendor_by_ports, VENDOR_PRESETS

WS_DISCOVERY_PROBE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <e:Header>
    <w:MessageID>uuid:{msg_id}</w:MessageID>
    <w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe>
      <d:Types>dn:NetworkVideoTransmitter</d:Types>
    </d:Probe>
  </e:Body>
</e:Envelope>"""

COMMON_CAMERA_PORTS = [554, 34567, 37777, 8000, 8899, 2020, 5000, 80, 8080]


def get_local_ip() -> str:
    """Discovers the active primary local IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not actually connect externally, merely selects outbound interface
        s.connect(('10.255.255.255', 1))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = '127.0.0.1'
    finally:
        s.close()
    return local_ip


def run_onvif_discovery(timeout: float = 2.5) -> List[Dict[str, Any]]:
    """Sends multicast WS-Discovery probe and gathers responding ONVIF devices."""
    devices = []
    seen_ips = set()
    msg_id = str(uuid.uuid4())
    probe_msg = WS_DISCOVERY_PROBE_XML.format(msg_id=msg_id).encode("utf-8")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)

    # Set multicast TTL and loopback
    ttl = struct.pack('b', 4)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

    try:
        sock.sendto(probe_msg, ('239.255.255.250', 3702))
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                data, addr = sock.recvfrom(65535)
                ip = addr[0]
                if ip in seen_ips:
                    continue
                seen_ips.add(ip)

                xml_str = data.decode("utf-8", errors="ignore")
                
                # Extract XAddrs or endpoint reference
                xaddrs_match = re.search(r'<[^:]*:XAddrs>([^<]+)</[^:]*:XAddrs>', xml_str)
                xaddrs = xaddrs_match.group(1).strip() if xaddrs_match else f"http://{ip}/onvif/device_service"

                # Extract hardware / scopes if available
                scopes_match = re.search(r'<[^:]*:Scopes>([^<]+)</[^:]*:Scopes>', xml_str)
                scopes = scopes_match.group(1) if scopes_match else ""

                # Guess vendor from scopes or text
                vendor_guess = "generic_onvif"
                lower_xml = xml_str.lower()
                if "hikvision" in lower_xml or "hik" in lower_xml:
                    vendor_guess = "hikvision"
                elif "dahua" in lower_xml or "imou" in lower_xml:
                    vendor_guess = "dahua"
                elif "xiongmai" in lower_xml or "xm" in lower_xml:
                    vendor_guess = "xiongmai"
                elif "reolink" in lower_xml:
                    vendor_guess = "reolink"
                elif "tapo" in lower_xml or "tp-link" in lower_xml:
                    vendor_guess = "tapo"

                devices.append({
                    "ip": ip,
                    "type": "ONVIF",
                    "xaddrs": xaddrs,
                    "vendor_preset": vendor_guess,
                    "vendor_name": VENDOR_PRESETS.get(vendor_guess, {}).get("name", "Generic ONVIF"),
                    "details": f"ONVIF Device responded at {ip}"
                })
            except socket.timeout:
                break
            except Exception:
                continue
    except Exception as e:
        print(f"[Discovery] ONVIF multicast error: {e}")
    finally:
        sock.close()

    return devices


def test_single_port(ip: str, port: int, timeout: float = 0.3) -> bool:
    """Tests if a single TCP port is listening on the host."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        res = s.connect_ex((ip, port))
        return res == 0
    except Exception:
        return False
    finally:
        s.close()


def scan_host_camera_ports(ip: str) -> List[int]:
    """Tests all standard camera ports on a single host."""
    open_ports = []
    for p in COMMON_CAMERA_PORTS:
        if test_single_port(ip, p):
            open_ports.append(p)
    return open_ports


def scan_lan_subnet(subnet_base: str = "", max_hosts: int = 40) -> List[Dict[str, Any]]:
    """Scans the local subnet for cameras with open RTSP or surveillance ports."""
    if not subnet_base:
        local_ip = get_local_ip()
        parts = local_ip.split(".")
        if len(parts) == 4 and parts[0] != "127":
            subnet_base = f"{parts[0]}.{parts[1]}.{parts[2]}"
        else:
            subnet_base = "192.168.1"

    results = []
    ips_to_scan = [f"{subnet_base}.{i}" for i in range(1, min(max_hosts + 1, 255))]

    def check_ip(ip):
        ports = scan_host_camera_ports(ip)
        if ports:
            vendor_info = detect_vendor_by_ports(ports)
            preset_id = vendor_info["preset_id"]
            return {
                "ip": ip,
                "type": "TCP Port Scan",
                "open_ports": ports,
                "vendor_preset": preset_id,
                "vendor_name": VENDOR_PRESETS.get(preset_id, {}).get("name", "Unknown"),
                "confidence": vendor_info["confidence"],
                "reason": vendor_info["reason"]
            }
        return None

    with ThreadPoolExecutor(max_workers=25) as executor:
        scan_results = executor.map(check_ip, ips_to_scan)
        for res in scan_results:
            if res:
                results.append(res)

    return results


def run_full_discovery() -> Dict[str, Any]:
    """Combines ONVIF discovery and LAN scanning."""
    onvif_devices = run_onvif_discovery(timeout=2.0)
    seen_ips = {d["ip"] for d in onvif_devices}

    # Add simulated test camera indicator
    devices = list(onvif_devices)

    # Fast scan near local IP
    lan_devices = scan_lan_subnet(max_hosts=30)
    for dev in lan_devices:
        if dev["ip"] not in seen_ips:
            devices.append(dev)

    # Always ensure simulated templates are discoverable for instant preview
    devices.append({
        "ip": "127.0.0.1",
        "type": "OmniSight Virtual Generator",
        "vendor_preset": "simulated",
        "vendor_name": "OmniSight Virtual CCTV Engine",
        "open_ports": [8000],
        "confidence": "High",
        "reason": "Internal high-speed surveillance generator ready for zero-hardware testing."
    })

    return {
        "timestamp": time.time(),
        "device_count": len(devices),
        "devices": devices
    }
