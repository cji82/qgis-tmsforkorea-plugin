#!/usr/bin/env python
# -*- coding: utf-8 -*-

import requests
import json
import re
import hashlib
from urllib.parse import urlparse, quote
import ssl
import time
import urllib3
import urllib.request
import urllib.error

# SSL 경고 무시
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# QGIS 환경인지 확인하고 조건부로 import
try:
    from qgis.core import QgsMessageLog
    QGIS_AVAILABLE = True
except ImportError:
    # QGIS 환경이 아닐 때는 print 사용
    class QgsMessageLog:
        @staticmethod
        def logMessage(message, tag="", level=None):
            print(f"[{tag}] {message}")
    QGIS_AVAILABLE = False

def _extract_kakao_uri_func_inner(js_text):
    """카카오 SDK JS에서 e.URI_FUNC={ ... },e.VERSION 앞까지 본문 추출 (Java 정규식과 동일 목적)."""
    for prefix in ("e.URI_FUNC={", "URI_FUNC={"):
        p = js_text.find(prefix)
        if p == -1:
            continue
        open_brace = p + len(prefix) - 1  # '{' 위치
        depth = 0
        for j in range(open_brace, len(js_text)):
            c = js_text[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return js_text[open_brace + 1 : j]
    return None


def _kakao_return_url_for_keys(inner, keys):
    """URI_FUNC 본문에서 keys 순서대로 function(){return\"...\"} 패턴으로 URL 추출."""
    for key in keys:
        pat_double = re.compile(
            rf"{re.escape(key)}:function\([^)]*\)\{{\s*return\s*\"([^\"]+)\"",
            re.DOTALL,
        )
        m = pat_double.search(inner)
        if m:
            return m.group(1).strip()
        pat_single = re.compile(
            rf"{re.escape(key)}:function\([^)]*\)\{{\s*return\s*'([^']+)'",
            re.DOTALL,
        )
        m = pat_single.search(inner)
        if m:
            return m.group(1).strip()
    return None


def _normalize_kakao_mts_url(raw_fragment):
    """
    SDK return 조각에서 mts .../latest/... 형만 추출해 map_services와 동일하게
    https?://.../latest/{z}/{x}/{y}.png 로 정규화 (좌표 순서 z,x,y).
    """
    if not raw_fragment:
        return None
    s = raw_fragment.strip()
    low = s.lower()
    i = low.find("http://")
    if i == -1:
        i = low.find("https://")
    if i == -1:
        return None
    s = s[i:]
    j = s.find("latest/")
    if j == -1:
        return None
    base = s[: j + len("latest/")].rstrip("/")
    if base.startswith("//"):
        base = "http:" + base
    elif not base.startswith("http"):
        return None
    return base + "/{z}/{x}/{y}.png"


def _kakao_tile_version_from_url(url):
    """
    mts 타일 팩 버전만 추출 (경로의 .../v숫자_코드/latest/ ...).
    첫 /v.../ 매칭은 PNG 종류 등으로 오인될 수 있어 latest 직전만 본다.
    """
    if not url:
        return ""
    m = re.search(r"/v(\d+_[a-z0-9]+)/latest/", url, re.I)
    if m:
        return m.group(1)
    return ""


def _kakao_sdk_e_version(js_text):
    """SDK 전역 e.VERSION (타일 v코드와 별개)."""
    m = re.search(r'e\.VERSION\s*=\s*["\']([^"\']+)["\']', js_text)
    return m.group(1).strip() if m else ""


def _tile_probe_http_fallback_hosts(low_url):
    """https 타일 가용성 테스트가 SSL로만 실패할 때 http 재시도할 호스트(저장 URL은 그대로)."""
    return (
        "mts.daumcdn.net" in low_url
        or "map.pstatic.net" in low_url
        or "map_skyview" in low_url
        or "xdworld.vworld.kr" in low_url
        or (".daumcdn.net" in low_url and "map" in low_url)
    )


class MapServiceURLUpdater:
    """지도 서비스의 최신 URL을 자동으로 가져오는 클래스"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        # SSL 검증 비활성화
        self.session.verify = False
        self._proxy_cfg = {}
        self._urllib_opener = None
        
        # 카카오 API 키(사용자 입력값만 사용)
        self.kakao_api_key = ""
        
        # 허용된 도메인
        self.allowed_domains = {
            "r.maps.daum-img.net", "t1.daumcdn.net", "map1.daumcdn.net", 
            "map2.daumcdn.net", "map3.daumcdn.net", "map4.daumcdn.net", 
            "map.pstatic.net", "mts.daumcdn.net", "map.daumcdn.net"
        }

    def set_kakao_api_key(self, api_key):
        """카카오 SDK appkey 설정."""
        self.kakao_api_key = (api_key or "").strip()

    def configure_proxies(self, cfg=None):
        """설정 관리의 프록시를 requests/urllib에 반영.
        mode: http_host — IP:포트 HTTP 프록시 | url_get — 요청 URL을 템플릿에 넣어 GET
        """
        self._proxy_cfg = dict(cfg) if cfg else {}
        self._urllib_opener = None
        if not self._proxy_cfg.get("enabled"):
            self.session.proxies.clear()
            self.session.trust_env = True
            return
        self.session.trust_env = False
        mode = self._proxy_cfg.get("mode") or "http_host"
        if mode == "http_host":
            host = (self._proxy_cfg.get("http_host") or "").strip()
            try:
                port = int(self._proxy_cfg.get("http_port") or 0)
            except (TypeError, ValueError):
                port = 0
            if not host or port <= 0:
                self.session.proxies.clear()
                return
            user = (self._proxy_cfg.get("http_user") or "").strip()
            pwd = (self._proxy_cfg.get("http_password") or "").strip()
            if user:
                auth = quote(user, safe="") + ":" + quote(pwd, safe="") + "@"
            else:
                auth = ""
            base = "http://%s%s:%d" % (auth, host, port)
            self.session.proxies = {"http": base, "https": base}
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ph = urllib.request.ProxyHandler({"http": base, "https": base})
            https_h = urllib.request.HTTPSHandler(context=ctx)
            self._urllib_opener = urllib.request.build_opener(ph, https_h)
        else:
            self.session.proxies.clear()

    def _effective_url(self, url):
        if not url or not self._proxy_cfg.get("enabled"):
            return url
        if (self._proxy_cfg.get("mode") or "http_host") != "url_get":
            return url
        tpl = (self._proxy_cfg.get("url_get_template") or "").strip()
        if not tpl:
            return url
        q = quote(url, safe="")
        return tpl.replace("{target_url}", q).replace("{url}", q)

    def _session_get(self, url, **kwargs):
        return self.session.get(self._effective_url(url), **kwargs)

    def _session_get_tile_test(self, url, **kwargs):
        """타일 URL 가용성 테스트용. QGIS 번들 환경에서 https SSL 실패 시 http로 1회 재시도(저장 URL은 변경하지 않음)."""
        eff = self._effective_url(url)
        kw = dict(kwargs)
        kw.setdefault("verify", False)
        try:
            return self.session.get(eff, **kw)
        except requests.exceptions.SSLError:
            if self._proxy_cfg.get("enabled") and (self._proxy_cfg.get("mode") or "http_host") == "url_get":
                raise
            low = eff.lower()
            if low.startswith("https://") and _tile_probe_http_fallback_hosts(low):
                return self.session.get("http://" + eff[8:], **kw)
            raise

    def _urlopen(self, url, timeout=20):
        u = self._effective_url(url)
        if self._urllib_opener is not None:
            return self._urllib_opener.open(u, timeout=timeout)
        return urllib.request.urlopen(u, timeout=timeout)
    
    def get_kakao_latest_urls(self):
        """카카오 SDK의 URI_FUNC와 동일 소스에서 타일 URL 추출 (mts latest → {z}/{x}/{y})."""
        # SDK 키 우선순위: HD/구버전 병행 (Java 쪽과 유사)
        layer_key_groups = {
            "street": ["ROADMAP_HD", "ROADMAP"],
            "hybrid": ["HYBRID_HD", "HYBRID"],
            "physical": ["ROADMAP", "ROADMAP_HD"],
            "cadastral": ["USE_DISTRICT_HD", "USE_DISTRICT"],
        }
        satellite_overlay_url = "https://map{0-3}.daumcdn.net/map_skyview/L{z}/{x}/{y}.jpg?v=160114"

        try:
            kakao_api_url = f"http://dapi.kakao.com/v2/maps/sdk.js?appkey={self.kakao_api_key}"
            with self._urlopen(kakao_api_url, timeout=20) as response:
                js_text = response.read().decode("utf-8", errors="replace")

            inner = _extract_kakao_uri_func_inner(js_text)
            if not inner:
                QgsMessageLog.logMessage(
                    "카카오 SDK에서 URI_FUNC 본문을 찾지 못했습니다. 기본 URL로 폴백합니다.",
                    "TMS for Korea",
                )
                return self._kakao_fallback_layer_results()

            kakao_urls = {}
            for layer_name, keys in layer_key_groups.items():
                raw = _kakao_return_url_for_keys(inner, keys)
                if not raw:
                    continue
                norm = _normalize_kakao_mts_url(raw)
                if norm:
                    kakao_urls[layer_name] = norm
                    QgsMessageLog.logMessage(
                        "카카오 %s URL: %s" % (layer_name, norm), "TMS for Korea"
                    )

            kakao_urls["satellite"] = satellite_overlay_url

            if not kakao_urls or len(kakao_urls) < 2:
                return self._kakao_fallback_layer_results()

            sdk_ev = _kakao_sdk_e_version(js_text)
            if sdk_ev:
                QgsMessageLog.logMessage(
                    "카카오 SDK e.VERSION=%s (타일 경로의 v*_*/latest 와는 별개일 수 있음)"
                    % sdk_ev,
                    "TMS for Korea",
                )

            attr = (
                '<a target="_blank" href="http://map.kakao.com/" title="Kakao 지도로 보시려면 클릭하세요." '
                'style="float: left; width: 32px; height: 10px;">'
                '<img style="float: left; width: 32px; height: 10px; border: medium none;" '
                'src="https://t1.daumcdn.net/mapjsapi/images/2x/m_bi_b.png" alt="Kakao 지도로 이동"></a>'
            )

            layer_results = {}
            for layer_type in ("street", "hybrid", "physical", "cadastral", "satellite"):
                if layer_type not in kakao_urls:
                    continue
                u = kakao_urls[layer_type]
                tile_ver = _kakao_tile_version_from_url(u)
                msg = "카카오 SDK URI_FUNC에서 URL을 갱신했습니다."
                if tile_ver:
                    msg += " (타일 v%s)" % tile_ver
                if sdk_ev:
                    msg += " [SDK e.VERSION=%s]" % sdk_ev
                layer_results[layer_type] = {
                    "urls": [u],
                    "version": tile_ver or ("latest" if layer_type != "satellite" else ""),
                    "attribution": attr,
                    "status": "success",
                    "message": msg,
                }
            return layer_results

        except Exception as e:
            QgsMessageLog.logMessage("카카오 URL 갱신 오류: %s" % str(e), "TMS for Korea")
            return self._kakao_fallback_layer_results()

    def _kakao_fallback_layer_results(self):
        default_urls = {
            "street": "http://mts.daumcdn.net/api/v1/tile/PNG02/v17_8uj6w/latest/{z}/{x}/{y}.png",
            "hybrid": "http://mts.daumcdn.net/api/v1/tile/PNG_SKYH02/v17_kdqve/latest/{z}/{x}/{y}.png",
            "physical": "http://mts.daumcdn.net/api/v1/tile/PNG02/v17_8uj6w/latest/{z}/{x}/{y}.png",
            "cadastral": "http://mts.daumcdn.net/api/v1/tile/PNG_CAD02/v14_i1vtt/latest/{z}/{x}/{y}.png",
            "satellite": "https://map{0-3}.daumcdn.net/map_skyview/L{z}/{x}/{y}.jpg?v=160114",
        }
        attr = (
            '<a target="_blank" href="http://map.kakao.com/" title="Kakao 지도로 보시려면 클릭하세요." '
            'style="float: left; width: 32px; height: 10px;">'
            '<img style="float: left; width: 32px; height: 10px; border: medium none;" '
            'src="https://t1.daumcdn.net/mapjsapi/images/2x/m_bi_b.png" alt="Kakao 지도로 이동"></a>'
        )
        out = {}
        for layer_type, url in default_urls.items():
            out[layer_type] = {
                "urls": [url],
                "version": "17_8uj6w",
                "attribution": attr,
                "status": "fallback",
                "message": "카카오 %s 기본 URL을 사용합니다." % layer_type,
            }
        return out
    
    def get_naver_latest_urls(self):
        """네이버 styles JSON에서 tiles[0]·version 사용 (Java regex 파싱과 동등한 정보)."""
        # fmt=jpg: png 템플릿은 200이어도 극소 PNG(빈 타일)만 오는 경우가 많음 → QGIS XYZ는 jpg 사용
        naver_apis = {
            "basic": "http://nrb.map.naver.net/styles/basic.json?fmt=jpg",
            "satellite": "http://nrb.map.naver.net/styles/satellite.json?fmt=jpg",
            "terrain": "http://nrb.map.naver.net/styles/terrain.json?fmt=jpg",
        }

        def _norm_template(u):
            if not u:
                return u
            t = u.strip()
            # map_services / OpenLayers 네이버 레이어는 ${z} 형 사용
            t = t.replace("{z}", "${z}").replace("{x}", "${x}").replace("{y}", "${y}")
            return t

        def _with_mt(base, mt_val):
            if "mt=" in base:
                return base
            sep = "&" if "?" in base else "?"
            return base + sep + mt_val

        try:
            naver_urls = {}
            versions = {}

            for map_type, api_url in naver_apis.items():
                try:
                    response = self._session_get(api_url, timeout=15)
                    response.raise_for_status()
                    data = response.json()
                except Exception as e:
                    QgsMessageLog.logMessage(
                        "네이버 %s JSON 실패: %s" % (map_type, str(e)), "TMS for Korea"
                    )
                    continue

                if not isinstance(data, dict) or "tiles" not in data or not data["tiles"]:
                    continue
                tile0 = data["tiles"][0]
                if not isinstance(tile0, str):
                    continue
                tile_url = _norm_template(tile0)
                naver_urls[map_type] = tile_url
                # TileJSON 최상위 version (타일 URL 경로의 숫자 폴더와 동일)
                versions[map_type] = str(data.get("version", ""))

            if not naver_urls:
                return self._naver_fallback()

            layer_results = {}

            if "basic" in naver_urls:
                b = _with_mt(naver_urls["basic"], "mt=bg.ol.ts.lko")
                layer_results["street"] = {
                    "urls": [b],
                    "version": versions.get("basic", ""),
                    "attribution": '<a target="_blank" href="https://map.naver.com/" title="네이버 지도로 이동">네이버 지도</a>',
                    "status": "success",
                    "message": "네이버 basic.json에서 street URL을 갱신했습니다.",
                }
                cad = _with_mt(naver_urls["basic"].split("?")[0], "mt=bg.ol.ts.lp")
                layer_results["cadastral"] = {
                    "urls": [cad],
                    "version": versions.get("basic", ""),
                    "attribution": '<a target="_blank" href="https://map.naver.com/" title="네이버 지도로 이동">네이버 지도</a>',
                    "status": "success",
                    "message": "네이버 basic.json에서 cadastral URL을 갱신했습니다.",
                }

            if "satellite" in naver_urls:
                sat = _with_mt(naver_urls["satellite"], "mt=bg.ol.ts")
                layer_results["satellite"] = {
                    "urls": [sat],
                    "version": versions.get("satellite", ""),
                    "attribution": '<a target="_blank" href="https://map.naver.com/" title="네이버 지도로 이동">네이버 지도</a>',
                    "status": "success",
                    "message": "네이버 satellite.json에서 satellite URL을 갱신했습니다.",
                }
                base_sat = naver_urls["satellite"].split("?")[0]
                hyb = _with_mt(base_sat, "mt=bg.ol.ts.lko")
                layer_results["hybrid"] = {
                    "urls": [hyb],
                    "version": versions.get("satellite", ""),
                    "attribution": '<a target="_blank" href="https://map.naver.com/" title="네이버 지도로 이동">네이버 지도</a>',
                    "status": "success",
                    "message": "네이버 satellite.json에서 hybrid URL을 갱신했습니다.",
                }

            if "terrain" in naver_urls:
                phy = _with_mt(naver_urls["terrain"], "mt=bg.ol.ts.lko")
                layer_results["physical"] = {
                    "urls": [phy],
                    "version": versions.get("terrain", ""),
                    "attribution": '<a target="_blank" href="https://map.naver.com/" title="네이버 지도로 이동">네이버 지도</a>',
                    "status": "success",
                    "message": "네이버 terrain.json에서 physical URL을 갱신했습니다.",
                }

            if layer_results:
                return layer_results
            return self._naver_fallback()

        except Exception as e:
            QgsMessageLog.logMessage("네이버 URL 갱신 오류: %s" % str(e), "TMS for Korea")
            return self._naver_fallback()

    def _naver_fallback(self):
        # JSON 요청 전부 실패 시에만 사용. 주기적으로 만료되므로 가능하면 URL 최신화로 갱신할 것.
        v = "1778232861"
        attr = '<a target="_blank" href="https://map.naver.com/" title="네이버 지도로 이동">네이버 지도</a>'
        return {
            "street": {
                "urls": [
                    "https://map.pstatic.net/nrb/styles/basic/%s/${z}/${x}/${y}.jpg?mt=bg.ol.ts.lko" % v
                ],
                "version": v,
                "attribution": attr,
                "status": "fallback",
                "message": "네이버 street 기본 URL",
            },
            "satellite": {
                "urls": [
                    "https://map.pstatic.net/nrb/styles/satellite/%s/${z}/${x}/${y}.jpg?mt=bg.ol.ts" % v
                ],
                "version": v,
                "attribution": attr,
                "status": "fallback",
                "message": "네이버 satellite 기본 URL",
            },
            "hybrid": {
                "urls": [
                    "https://map.pstatic.net/nrb/styles/satellite/%s/${z}/${x}/${y}.jpg?mt=bg.ol.ts.lko" % v
                ],
                "version": v,
                "attribution": attr,
                "status": "fallback",
                "message": "네이버 hybrid 기본 URL",
            },
            "physical": {
                "urls": [
                    "https://map.pstatic.net/nrb/styles/terrain/%s/${z}/${x}/${y}.jpg?mt=bg.ol.ts.lko" % v
                ],
                "version": v,
                "attribution": attr,
                "status": "fallback",
                "message": "네이버 physical 기본 URL",
            },
            "cadastral": {
                "urls": [
                    "https://map.pstatic.net/nrb/styles/basic/%s/${z}/${x}/${y}.jpg?mt=bg.ol.ts.lp" % v
                ],
                "version": v,
                "attribution": attr,
                "status": "fallback",
                "message": "네이버 cadastral 기본 URL",
            },
        }
    
    def get_vworld_latest_urls(self):
        """VWorld 지도의 최신 URL을 가져옵니다"""
        try:
            # VWorld는 안정적인 기본 URL 사용
            return {
                'urls': [
                    "https://xdworld.vworld.kr/2d/Base/service/{z}/{x}/{y}.png"
                ],
                'version': 'latest',
                'attribution': '<a target="_blank" href="https://www.vworld.kr/" title="VWorld로 이동">VWorld</a>',
                'status': 'success',
                'message': 'VWorld 기본 URL을 사용합니다.'
            }
            
        except Exception as e:
            return {
                'urls': [],
                'version': '',
                'attribution': '',
                'status': 'error',
                'message': f'VWorld URL 가져오기 실패: {str(e)}'
            }
    
    def update_all_services(self):
        """모든 서비스의 최신 URL을 가져옵니다"""
        results = {}
        
        # 카카오 지도
        results['kakao'] = self.get_kakao_latest_urls()
        
        # 네이버 지도
        results['naver'] = self.get_naver_latest_urls()
        
        # VWorld
        results['vworld'] = self.get_vworld_latest_urls()
        
        return results

    def _naver_refresh_version_in_template(self, template_url):
        """저장된 nrb 경로의 숫자 버전이 만료된 경우 styles JSON에서 최신 version으로 치환."""
        m = re.search(r"/nrb/styles/(basic|satellite|terrain)/(\d+)(/)", template_url, re.I)
        if not m:
            return None
        style_key = m.group(1).lower()
        old_ver = m.group(2)
        try:
            api_url = "http://nrb.map.naver.net/styles/%s.json?fmt=jpg" % style_key
            r = self._session_get(api_url, timeout=15)
            r.raise_for_status()
            data = r.json()
            ver = str(data.get("version", "")).strip()
            if not ver or ver == old_ver:
                return None
            return template_url[: m.start(2)] + ver + template_url[m.end(2) :]
        except Exception:
            return None

    def test_url_availability(self, urls, user_probe=None):
        """URL의 가용성을 테스트합니다 (타일 좌표·호스트 치환·응답 형식 보정).

        user_probe: (z, x, y) 정수 튜플이면 해당 타일을 첫 후보로 사용(이웃 x+1,y+1로 동일성 검사).
        """

        def _normalize_template(s):
            t = s.strip()
            t = t.replace("{0-3}", "0").replace("${0-3}", "0")
            for a, b in (("${z}", "{z}"), ("${x}", "{x}"), ("${y}", "{y}")):
                t = t.replace(a, b)
            return t

        def _probe_sets(template):
            """레이어와 동일한 타일 격자를 쓰도록 호스트별로 여러 (z,xa,ya,xb,yb) 후보."""
            low = template.lower()
            daum_native = (
                "mts.daumcdn.net" in low
                or "/api/v1/tile/" in low
                or "map_skyview" in low
                or ("daumcdn.net" in low and "pstatic" not in low)
            )
            if daum_native:
                return [
                    (8, 112, 52, 113, 53),
                    (10, 220, 100, 221, 101),
                    (6, 28, 13, 29, 14),
                ]
            return [
                (14, 27942, 12788, 27943, 12789),
                (12, 6985, 3197, 6986, 3198),
                (10, 1746, 799, 1747, 800),
            ]

        def _expand_placeholders(u, z, xa, ya):
            s = _normalize_template(u)
            return s.replace("{z}", str(z)).replace("{x}", str(xa)).replace("{y}", str(ya))

        def _second_tile_url(u, z, xb, yb):
            s = _normalize_template(u)
            return s.replace("{z}", str(z)).replace("{x}", str(xb)).replace("{y}", str(yb))

        def _referer(u):
            low = u.lower()
            if "pstatic.net" in low or "naver" in low or "nrb.map" in low:
                return "https://map.naver.com/"
            if "daum" in low or "kakao" in low:
                return "https://map.kakao.com/"
            if "vworld" in low:
                return "https://map.vworld.kr/"
            return "https://www.openstreetmap.org/"

        def _looks_like_image(body, content_type):
            ct = (content_type or "").lower()
            if "image" in ct:
                return True
            if not body or len(body) < 4:
                return False
            if body[:8] == b"\x89PNG\r\n\x1a\n":
                return True
            if body[:2] == b"\xff\xd8":
                return True
            if body[:4] in (b"GIF8", b"RIFF"):
                return True
            return False

        results = []

        for url in urls:
            try:
                work_url = url
                naver_retried = False
                last_fail = None

                while True:
                    hdr_base = {"Referer": _referer(work_url)}
                    probes = list(_probe_sets(work_url))
                    if user_probe is not None:
                        uz, ux, uy = user_probe
                        first = (int(uz), int(ux), int(uy), int(ux) + 1, int(uy) + 1)
                        if first not in probes:
                            probes.insert(0, first)
                    ok_row = None

                    for z, xa, ya, xb, yb in probes:
                        test_url_a = _expand_placeholders(work_url, z, xa, ya)
                        test_url_b = _second_tile_url(work_url, z, xb, yb)
                        hdr = dict(hdr_base)
                        hdr["Referer"] = _referer(test_url_a)

                        response_a = self._session_get_tile_test(test_url_a, timeout=12, headers=hdr)
                        content_type = response_a.headers.get("content-type") or ""
                        body_a = response_a.content or b""
                        status_ok = response_a.status_code == 200
                        looks_img = _looks_like_image(body_a, content_type)

                        if not status_ok or not looks_img:
                            last_fail = (
                                response_a.status_code,
                                "HTTP %s" % response_a.status_code
                                if not status_ok
                                else "이미지로 보이지 않음 (Content-Type: %s, %s bytes)"
                                % (content_type or "-", len(body_a)),
                            )
                            continue

                        response_b = self._session_get_tile_test(test_url_b, timeout=12, headers=hdr)
                        body_b = response_b.content or b""
                        same_hash = (
                            response_b.status_code == 200
                            and len(body_a) > 256
                            and len(body_b) > 256
                            and hashlib.sha1(body_a).hexdigest()
                            == hashlib.sha1(body_b).hexdigest()
                        )
                        note = "OK (z=%s, %s, %s bytes)" % (
                            z,
                            (content_type or "image").split(";")[0].strip(),
                            len(body_a),
                        )
                        if same_hash:
                            note += " — 참고: 다른 타일 좌표와 바이트 동일(빈 타일/플레이스홀더 가능)"
                        if work_url != url:
                            note += " — 참고: nrb styles JSON으로 버전 경로 갱신 후 통과"
                        ok_row = {
                            "url": url,
                            "available": True,
                            "status_code": response_a.status_code,
                            "detail": note,
                        }
                        break

                    if ok_row is not None:
                        results.append(ok_row)
                        break

                    low = work_url.lower()
                    can_refresh = (
                        "map.pstatic.net" in low
                        and "/nrb/styles/" in low
                        and not naver_retried
                        and last_fail
                        and last_fail[0] in (400, 404)
                    )
                    if can_refresh:
                        refreshed = self._naver_refresh_version_in_template(work_url)
                        if refreshed and refreshed != work_url:
                            work_url = refreshed
                            naver_retried = True
                            continue

                    detail = last_fail[1] if last_fail else "알 수 없음"
                    if last_fail and last_fail[0] in (400, 404) and "map.pstatic.net" in low:
                        detail += (
                            " — 저장된 URL의 버전 폴더가 만료됐을 수 있습니다. "
                            "'URL 최신화' 후 다시 테스트하세요."
                        )
                    results.append(
                        {
                            "url": url,
                            "available": False,
                            "status_code": last_fail[0] if last_fail else None,
                            "detail": detail,
                        }
                    )
                    break

            except Exception as e:
                results.append(
                    {
                        "url": url,
                        "available": False,
                        "status_code": None,
                        "detail": str(e),
                    }
                )

        return results 