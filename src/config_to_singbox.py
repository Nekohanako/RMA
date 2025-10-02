import json
import base64
import uuid
import time
import socket
import requests
import copy
import os
from typing import Dict, Optional, Tuple, List
from urllib.parse import urlparse, parse_qs

class ConfigToSingbox:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        self.location_cache = {}

    def get_location(self, address: str) -> tuple:
        if address in self.location_cache:
            return self.location_cache[address]
        
        try:
            ip = socket.gethostbyname(address)
            if ip in self.location_cache:
                return self.location_cache[ip]

            response = requests.get(f'http://ip-api.com/json/{ip}?fields=country,countryCode', headers=self.headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('countryCode'):
                    country_code = data['countryCode']
                    country = data['country']
                    flag = ''.join(chr(ord('🇦') + ord(c.upper()) - ord('A')) for c in country_code)
                    result = (f"{flag} {country}")
                    self.location_cache[address] = result
                    self.location_cache[ip] = result
                    return result
        except Exception:
            pass
            
        result = "🏳️ Unknown"
        self.location_cache[address] = result
        return result

    def decode_vmess(self, config: str) -> Optional[Dict]:
        try:
            encoded = config.replace('vmess://', '')
            decoded = base64.b64decode(encoded).decode('utf-8')
            return json.loads(decoded)
        except Exception:
            return None

    def parse_vless(self, config: str) -> Optional[Dict]:
        try:
            url = urlparse(config)
            if url.scheme.lower() != 'vless' or not url.hostname:
                return None
            netloc = url.netloc.split('@')[-1]
            address, port = netloc.split(':') if ':' in netloc else (netloc, '443')
            params = parse_qs(url.query)
            return {
                'uuid': url.username,
                'address': address,
                'port': int(port),
                'flow': params.get('flow', [''])[0],
                'security': params.get('security', ['none'])[0],
                'sni': params.get('sni', [address])[0],
                'fp': params.get('fp', [''])[0],
                'pbk': params.get('pbk', [''])[0],
                'sid': params.get('sid', [''])[0],
                'type': params.get('type', ['tcp'])[0],
                'path': params.get('path', [''])[0],
                'host': params.get('host', [''])[0]
            }
        except Exception:
            return None

    def convert_to_singbox(self, config: str, index: int) -> Optional[Dict]:
        try:
            config_lower = config.lower()
            tag_name = f"@Proxyfig-{index:02d}"

            if config_lower.startswith('vless://'):
                data = self.parse_vless(config)
                if not data: return None
                
                location_info = self.get_location(data['address'])
                full_tag = f"{tag_name} - {location_info}"

                singbox_config = {
                    "type": "vless",
                    "tag": full_tag,
                    "server": data['address'],
                    "server_port": data['port'],
                    "uuid": data['uuid'],
                    "flow": data['flow']
                }
                
                if data['security'] == 'reality':
                    singbox_config['tls'] = {
                        "enabled": True,
                        "reality": {"enabled": True, "public_key": data['pbk'], "short_id": data['sid']},
                        "server_name": data['sni'],
                        "utls": {"enabled": True, "fingerprint": data['fp']}
                    }
                elif data['security'] == 'tls':
                     singbox_config['tls'] = {
                        "enabled": True,
                        "server_name": data['sni'],
                        "insecure": True,
                        "utls": {"enabled": True, "fingerprint": data['fp']}
                    }

                if data['type'] == 'ws':
                    singbox_config['transport'] = {
                        "type": "ws",
                        "path": data['path'],
                        "headers": {"Host": data['host']}
                    }

                return singbox_config

            return None
        except Exception:
            return None

    def build_full_config(self, outbounds: List[Dict], use_fragment: bool) -> Dict:
        if use_fragment:
            for ob in outbounds:
                if ob['type'] == 'vless' and 'tls' in ob:
                    ob['tls']['fragment'] = {
                        "enabled": True,
                        "size": "10-100",
                        "sleep": "10-100"
                    }
        
        valid_tags = [ob['tag'] for ob in outbounds]
        
        base_config = {
            "log": {"level": "warn", "timestamp": True},
            "dns": {
                "servers": [
                    {"tag": "proxy-dns", "address": "https://1.1.1.1/dns-query", "detour": "PROXY"},
                    {"tag": "local-dns", "address": "https://8.8.8.8/dns-query", "detour": "DIRECT"}
                ],
                "rules": [
                    {"outbound": ["any"], "server": "local-dns"},
                    {"rule_set": ["geosite-ir"], "server": "local-dns"}
                ]
            },
            "inbounds": [
                {"type": "tun", "tag": "tun-in", "stack": "mixed", "sniff": True},
                {"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1:2080"}
            ],
            "outbounds": [
                {"type": "selector", "tag": "PROXY", "outbounds": ["♻️ Best Ping 🔥"] + valid_tags},
                {"type": "direct", "tag": "DIRECT"},
                {"type": "block", "tag": "BLOCK"},
                {"type": "urltest", "tag": "♻️ Best Ping 🔥", "outbounds": valid_tags, "url": "http://www.gstatic.com/generate_204"}
            ] + outbounds,
            "route": {
                "rules": [
                    {"rule_set": "geosite-ir", "outbound": "DIRECT"},
                    {"rule_set": "geosite-ads-all", "outbound": "BLOCK"}
                ],
                "rule_set": [
                    {"tag": "geosite-ir", "type": "remote", "format": "binary", "url": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-ir.srs"},
                    {"tag": "geosite-ads-all", "type": "remote", "format": "binary", "url": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-category-ads-all.srs"}
                ],
                "final": "PROXY"
            }
        }
        return base_config

    def process_and_save_configs(self):
        try:
            input_file = 'configs/proxy.txt'
            if not os.path.exists(input_file):
                print(f"Input file not found: {input_file}")
                return

            with open(input_file, 'r', encoding='utf-8') as f:
                configs = [line.strip() for line in f if line.strip() and not line.startswith('//')]
            
            outbounds = []
            for i, config_line in enumerate(configs):
                converted = self.convert_to_singbox(config_line, i + 1)
                if converted:
                    outbounds.append(converted)
            
            if not outbounds:
                print("No valid configs were converted to Sing-box format.")
                return

            standard_full_config = self.build_full_config(copy.deepcopy(outbounds), use_fragment=False)
            with open('configs/singbox_configs.json', 'w', encoding='utf-8') as f:
                json.dump(standard_full_config, f, indent=4, ensure_ascii=False)
            print("Successfully generated configs/singbox_configs.json")

            fragmented_full_config = self.build_full_config(copy.deepcopy(outbounds), use_fragment=True)
            with open('configs/singbox_frg_configs.json', 'w', encoding='utf-8') as f:
                json.dump(fragmented_full_config, f, indent=4, ensure_ascii=False)
            print("Successfully generated configs/singbox_frg_configs.json")

        except Exception as e:
            print(f"An error occurred: {e}")

def main():
    converter = ConfigToSingbox()
    converter.process_and_save_configs()

if __name__ == '__main__':
    main()
