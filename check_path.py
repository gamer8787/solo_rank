"""Data Dragon CDN 연결 및 패치 일정 기준 버전 확인."""
import urllib.request

from env import DDRAGON_USER_AGENT, ddragon_versioned_cdn_root, get_data_dragon_version

v = get_data_dragon_version()
root = ddragon_versioned_cdn_root()
test_url = f"{root}/data/ko_KR/champion.json"

print("---------------------------------------------------")
print(f"[version] Data Dragon: {v}")
print(f"[CDN]  {root}")
print("---------------------------------------------------")

try:
    req = urllib.request.Request(test_url, headers={"User-Agent": DDRAGON_USER_AGENT})
    with urllib.request.urlopen(req, timeout=25) as resp:
        print(f"[OK] CDN HTTP {resp.status} champion.json")
except Exception as e:
    print(f"[FAIL] CDN: {e}")
    print("   Check network / firewall / User-Agent blocking.")

print("---------------------------------------------------")
